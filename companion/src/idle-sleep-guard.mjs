import { spawn } from 'node:child_process';

/** Hold macOS awake while an Agent direction is running, never while paused. */
export class IdleSleepGuard {
  constructor({enabled=process.platform==='darwin',spawnProcess=spawn,pid=process.pid,onError=()=>{}}={}) {
    Object.assign(this,{enabled,spawnProcess,pid,onError});
    this.child=null;
  }
  start() {
    if (!this.enabled || this.child) return;
    try {
      const child=this.spawnProcess('/usr/bin/caffeinate',['-i','-w',String(this.pid)],{stdio:'ignore'});
      this.child=child;
      child.on('error',error=>{
        if (this.child===child) this.child=null;
        this.onError(error);
      });
      child.on('exit',()=>{if (this.child===child)this.child=null;});
    } catch(error) {this.onError(error);}
  }
  stop() {
    const child=this.child;
    this.child=null;
    if (child && child.exitCode===null && !child.killed) child.kill();
  }
}
