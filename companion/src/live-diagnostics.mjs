import {createServer} from 'node:http';
import {mkdtemp, chmod, writeFile, appendFile, rename, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {BUILD_INFO} from './build-info.mjs';
import {sanitize, exportDiagnostics} from './diagnostics.mjs';

/** Observes the existing runtime. Never dispatches painting or model requests. */
export class LiveDiagnostics {
  constructor(runtime) {
    this.runtime=runtime; this.events=[]; this.sequence=0; this.pending=new Map();
    this.instance=randomUUID(); this.startedAt=new Date().toISOString(); this.writes=Promise.resolve();
  }
  attach() {
    const r=this.runtime,emit=r.emit,call=r.bridge.call.bind(r.bridge);
    r.diagnostics=this;
    r.emit=event=>{this.observe(event);emit(event);};
    r.bridge.call=async(operation,params,sessionId,operationId)=>{
      const request_id=randomUUID(),started=Date.now();
      const context={request_id,operation,operation_id:operationId ?? null,session_id:sessionId ?? null,
        model_request_id:r.diagnosticRequestId ?? null,
        tool_call_ids:[...(r.pendingTools?.keys() ?? [])],started_at:new Date(started).toISOString()};
      this.pending.set(request_id,context);this.record({type:'native_dispatch',...context});
      try {
        const result=await call(operation,params,sessionId,operationId);
        this.record({type:'native_result',...context,elapsed_ms:Date.now()-started,
          checkpoint:result?.checkpoint,replayed:result?.replayed,error_code:result?.error_code});
        if(result?.checkpoint)this.record({type:'save_receipt',...context,path:result.checkpoint,
          note:'Checkpoint returned by bridge; may be an existing checkpoint on observation or replay.'});
        return result;
      } catch(error) {
        this.record({type:'native_error',...context,elapsed_ms:Date.now()-started,error_code:error.code,message:error.message});
        throw error;
      } finally {this.pending.delete(request_id);}
    };
  }
  clean(value) {return sanitize(value,text=>this.runtime.redact(text));}
  record(event) {
    const row=this.clean({...event,sequence:++this.sequence,at:new Date().toISOString(),instance:this.instance,
      conversation_id:this.runtime.study?.id ?? null});
    this.events.push(row); if(this.events.length>500)this.events.shift();
    if(this.logPath) this.writes=this.writes.then(async()=>{
      if(row.sequence % 500===1) await rename(this.logPath,this.logPath+'.previous').catch(e=>{if(e.code!=='ENOENT')throw e;});
      await appendFile(this.logPath,JSON.stringify(row)+'\n',{mode:0o600});
    }).catch(error=>{this.logError=error.code ?? 'write_failed';});
  }
  observe(event) {
    if(event.type==='ready')this.connection={captured_at:new Date().toISOString(),build:event.build,bridge:event.bridge,compatible:event.compatible};
    if(event.type==='error')this.lastError=event;
    if(['status','error','busy','message_end','action','ready'].includes(event.type))
      this.record({type:event.type,phase:event.phase,message:event.message,error:event.error,busy:event.busy});
  }
  snapshot() {
    const r=this.runtime;
    return this.clean({captured_at:new Date().toISOString(),instance:this.instance,pid:process.pid,started_at:this.startedAt,
      companion_build:BUILD_INFO,connection:this.connection,ui:this.ui ?? null,
      ui_note:'Last panel-reported connection snapshot; not a fresh screenshot or widget inspection.',
      mode:r.mode,busy:r.busy,activity:r.activity,execution_phase:r.executionPhase,
      stop_requested:r.cancelRequested,faulted:r.faulted,error:r.runError ?? this.lastError ?? null,
      transition:r.transition,study:r.study,goal:r.goal,canvas:r.canvasContext,
      last_model_activity_at:r.lastModelActivityAt,pending_native:[...this.pending.values()],
      pending_tools:[...(r.pendingTools ?? [])].map(([id,tool])=>({id,name:tool.name,started_at:tool.at})),
      timeline_first_sequence:this.events[0]?.sequence ?? null,timeline_last_sequence:this.sequence,log_error:this.logError});
  }
  timeline(after=0,limit=100) {
    return {instance:this.instance,events:this.events.filter(e=>e.sequence>after).slice(0,limit),
      first_available_sequence:this.events[0]?.sequence ?? null,last_sequence:this.sequence,
      truncated:after>0 && after<(this.events[0]?.sequence ?? 1)-1};
  }
  async report() {
    await this.writes;
    return exportDiagnostics({stateDirectory:this.runtime.config.output,studyId:this.runtime.study?.id,
      record:this.runtime.study?.id ? this.runtime.store?.recordText?.(this.runtime.study.id) : undefined,
      sessions:this.runtime.study?.id && this.runtime.store?.sessions ? this.runtime.store.sessions.keys(this.runtime.study.id)
        .map(key=>({label:key,entries:this.runtime.store.sessions.stored({chat:this.runtime.study.id,key})})) : [],
      snapshot:{...this.snapshot(),timeline:this.timeline(0,500)},redact:text=>this.runtime.redact(text)});
  }
  async start() {
    this.directory=await mkdtemp('/tmp/krita-diagnostics-'); await chmod(this.directory,0o700);
    this.socket=join(this.directory,'socket');
    this.logPath=join(this.runtime.config.output,'diagnostic-events.jsonl');
    await rename(this.logPath,this.logPath+'.previous').catch(e=>{if(e.code!=='ENOENT')throw e;});
    this.descriptor=join(this.runtime.config.output,'diagnostics-endpoint.json');
    this.server=createServer(async(req,res)=>{
      res.setHeader('Content-Type','application/json');
      try {
        const url=new URL(req.url,'http://localhost'); let result;
        if(req.method==='GET' && url.pathname==='/state')result=this.snapshot();
        else if(req.method==='GET' && url.pathname==='/events') {
          const after=Number(url.searchParams.get('after') ?? 0),limit=Number(url.searchParams.get('limit') ?? 100);
          if(!Number.isSafeInteger(after)||after<0||!Number.isInteger(limit)||limit<1||limit>500) {
            res.statusCode=400;result={error:'after must be nonnegative; limit must be 1–500'};
          } else result=this.timeline(after,limit);
        } else if(req.method==='POST' && url.pathname==='/report') {
          this.reportPending ??= this.report().finally(()=>{this.reportPending=null;});
          result=await this.reportPending;
        } else {res.statusCode=404;result={error:'Unknown diagnostic operation'};}
        res.end(JSON.stringify(result));
      } catch(error) {res.statusCode=500;res.end(JSON.stringify(this.clean({error:error.message})));}
    });
    try {
      await new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(this.socket,resolve);});
      await chmod(this.socket,0o600);
      const temporary=this.descriptor+'.'+this.instance;
      await writeFile(temporary,JSON.stringify({socket:this.socket,pid:process.pid,instance:this.instance}),{mode:0o600});
      await rename(temporary,this.descriptor);
      this.record({type:'diagnostics_started'});
    } catch(error) {await this.close();throw error;}
  }
  async close() {
    if(this.server?.listening)await new Promise(resolve=>{this.server.close(resolve);this.server.closeIdleConnections();});
    await this.writes;
    if(this.descriptor)await rm(this.descriptor,{force:true});
    if(this.directory)await rm(this.directory,{recursive:true,force:true});
  }
}
