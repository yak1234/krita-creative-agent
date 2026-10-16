import { thinkingLevel } from './execution-settings.mjs';
import { createAgentSession, DefaultResourceLoader, getAgentDir, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { copyFile, mkdir, open, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { basename, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { containedFile, imageContent, imageInfo } from './files.mjs';
import { paintingTools, resultContent, keepRecentImages } from './tools.mjs';
import { PAINTING_INSTRUCTIONS, studyContext } from './prompt.mjs';
import { COMIC_OPERATIONS, CRAFT_OPERATIONS } from './craft.mjs';
import { BUILD_INFO, PROTOCOL_VERSION } from './build-info.mjs';
import { inheritPiCatalog } from './model-catalog.mjs';
import { SKILLS_DIR } from './skills.mjs';

const SIGN_IN_NAMES = { 'openai-codex': 'ChatGPT (Codex)', 'anthropic': 'Claude', 'google-gemini-cli': 'Gemini CLI', 'google-antigravity': 'Google Antigravity' };
/** How to restore a lapsed or missing OAuth sign-in. The chat keeps its model. */
export function signInMessage(provider, lapsed = false) {
  const name = SIGN_IN_NAMES[provider] ?? provider;
  return (lapsed ? `Your ${name} sign-in has lapsed, so the run is paused. ` : `${name} is not signed in. `)
    + 'Sign in again in Pi (run pi in a terminal, then /login), then send a message or press Resume to continue on the same model.';
}

export class PaintingRuntime {
  constructor({ root, config, bridge, emit, models }) {
    Object.assign(this, { root, config, bridge, emit });
    this.busy = false;
    this.faulted = false;
    this.cancelRequested = false;
    this.secrets = [];
    this.models = models;
    this.activity = 'idle';
    this.pendingTools = new Map();
    this.modelIdleTimeoutMs = config?.model_idle_timeout_ms ?? 90000;
  }
  async initialize() {
    await mkdir(this.config.output, { recursive: true });
    await this.acquireLock();
    if(!this.models) {
      const piDirectory=this.config.pi_agent_dir ?? getAgentDir();
      const catalog=await inheritPiCatalog(piDirectory,this.config.output);
      this.models=await ModelRuntime.create({allowModelNetwork:false,authPath:join(piDirectory,'auth.json'),
        modelsPath:join(piDirectory,'models.json'),modelsStorePath:catalog,signal:AbortSignal.timeout(15000)});
      const connectionsPath=join(this.config.output,'model-connections.json');
      try {this.modelConnections=JSON.parse(await readFile(connectionsPath,'utf8'));}
      catch(error){if(error.code!=='ENOENT')throw new Error('Saved model connections need repair before reconnecting.');}
      for(const [provider,connection] of Object.entries(this.modelConnections ?? {}))this.models.registerProvider(provider,connection);
      if(this.modelConnections)await this.models.refresh({allowNetwork:false,signal:AbortSignal.timeout(15000)});
      // Pi's persisted catalog can lag newly released routes. Refresh only the
      // connected OpenRouter provider; a network failure leaves cached models usable.
      if (this.models.hasConfiguredAuth('openrouter') && process.env.PI_OFFLINE === undefined)
        await this.refreshModels('openrouter',{silent:true}).catch(()=>{});
    }
    await this.refreshKeyProviders();
    await this.bridge.connect();
    let bridgeStatus;
    try { bridgeStatus = await this.bridge.call('health'); }
    catch { bridgeStatus = { error: 'The creative commands are not loaded in Krita yet.' }; }
    // Release an orphaned companion's ownership, preserving all documents/files.
    try {
      const stale = JSON.parse(await readFile(join(this.config.output, 'active-session.json'), 'utf8'));
      await this.bridge.call('end', {}, stale.id);
      await rm(join(this.config.output, 'active-session.json'), { force: true });
    } catch { /* No orphan, or the bridge restarted and no longer owns it. */ }
    this.acceptBridgeHealth(bridgeStatus);
  }
  acceptBridgeHealth(bridgeStatus) {
    this.routingCapabilities=bridgeStatus.capabilities ?? {};
    this.bridgeCompatible = bridgeStatus.protocol_version === PROTOCOL_VERSION &&
      (BUILD_INFO.build_id === 'development-unverified' || bridgeStatus.build?.build_id === BUILD_INFO.build_id);
    this.emit({ type: 'ready', models: this.listModels(),providers:this.listProviders(), bridge: bridgeStatus, build:BUILD_INFO, compatible:this.bridgeCompatible });
    if (!this.bridgeCompatible) this.emit({type:'error',code:'version_mismatch',message:'The running Krita bridge needs the matching Creative Agent build. Reload the plugin before painting.'});
  }
  async acquireLock() {
    const path = join(this.config.output, 'companion.lock');
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const file = await open(path, 'wx', 0o600);
        await file.writeFile(JSON.stringify({ pid: process.pid }));
        await file.close();
        this.lockPath = path;
        return;
      } catch (error) {
        if (error.code !== 'EEXIST') throw error;
        let pid;
        try { pid = JSON.parse(await readFile(path, 'utf8')).pid; }
        catch { throw new Error('A companion is starting or its lock needs inspection: ' + path); }
        try { process.kill(pid, 0); }
        catch (probe) {
          if (probe.code === 'ESRCH') { await rm(path); continue; }
          throw probe;
        }
        throw new Error('The creative assistant is already running in another panel.');
      }
    }
    throw new Error('Could not acquire the painting session.');
  }
  async releaseLock() {
    if (this.lockPath) await rm(this.lockPath, { force: true });
    this.lockPath = undefined;
  }
  // Providers Pi signs into with OAuth (e.g. ChatGPT Codex). They are offered like key providers,
  // but a sign-in can lapse mid-run, so a lapse pauses the run with "sign in again" (signInLapsed)
  // and key-connected models stay first, so they are the default.
  // A provider configured only through its environment variable has no stored credential: a key.
  async refreshKeyProviders() {
    try { this.oauthProviders = new Set((await this.models.listCredentials?.() ?? []).filter(c => c.type !== 'api_key').map(c => c.providerId)); }
    catch { this.oauthProviders = new Set(); }
  }
  // After the artist signs in again in Pi: re-read that provider's credential (local, no network).
  async recheckSignIn(provider) {
    if (!provider || (this.models.hasConfiguredAuth(provider) && !this.oauthProviders?.has(provider))) return;
    try { await this.models.refresh?.({ providers: [provider], allowNetwork: false, signal: AbortSignal.timeout(6000) }); } catch { /* keep the last snapshot */ }
    await this.refreshKeyProviders();
  }
  authKind(provider) { return this.oauthProviders?.has(provider) ? 'oauth' : 'api_key'; }
  assertConnected(provider) {
    if (this.models.hasConfiguredAuth(provider)) return;
    throw new Error(this.oauthProviders?.has(provider) ? signInMessage(provider) : 'Connect this provider with an API key before selecting it.');
  }
  // A model request refused because the OAuth sign-in lapsed: pause with how to sign in again.
  signInLapsed(provider, message) {
    return this.oauthProviders?.has(provider) && /\b(401|403)\b|unauthori[sz]ed|expired|invalid[_ ]?(grant|token)|re-?auth|log ?in again|sign ?in again|refresh token|not authenticated|authentication/i.test(String(message ?? ''));
  }
  listModels() {
    return this.models.getModels().map(m => ({
      provider: m.provider, id: m.id, name: m.name, auth: this.authKind(m.provider),
      configured: this.models.hasConfiguredAuth(m.provider), reasoning: m.reasoning,
      declared_images_supported:m.input.includes('image'),images_supported:m.input.includes('image'),route_verified:false,
      interactive:!/\bbatch\b/i.test(m.id+' '+m.name),painting_eligible:m.input.includes('image')&&!/\bbatch\b/i.test(m.id+' '+m.name),
    })).sort((a, b) => Number(b.configured) - Number(a.configured) || Number(a.auth === 'oauth') - Number(b.auth === 'oauth') || a.provider.localeCompare(b.provider) || a.name.localeCompare(b.name));
  }
  listProviders() {
    return (this.models.getProviders?.() ?? []).map(provider=>({id:provider.id,name:provider.name ?? provider.id,auth:this.authKind(provider.id),
      configured:this.models.hasConfiguredAuth(provider.id),model_count:this.models.getModels(provider.id).length}));
  }
  emitModels(selected) {this.emit({type:'models',models:this.listModels(),providers:this.listProviders(),...(selected?{selected}:{})});}
  async refreshModels(provider='openrouter',{silent=false}={}) {
    if (!this.models.getProvider(provider)) throw new Error('Choose a registered model provider.');
    const result=await this.models.refresh({providers:[provider],allowNetwork:true,force:true,signal:AbortSignal.timeout(6000)});
    if (!silent) this.emitModels(this.study ? {provider:this.study.provider,id:this.study.model}:undefined);
    const failure=result.errors?.get(provider);
    if ((failure || result.aborted) && !silent) this.emit({type:'status',message:'Could not refresh '+provider+' models. Cached models remain available.'});
    else if (!silent) this.emit({type:'status',message:'Model catalog refreshed for '+provider+'.'});
    return result;
  }
  async configureProvider(p) {
    if (this.busy && this.transition?.kind!=='configure_provider') throw new Error('Pause before changing model connections.');
    if (/\bbatch\b/i.test(p.model ?? '')) throw new Error('Choose an interactive model instead of a batch route.');
    if (!p.provider || !p.model || !p.base_url || !p.api_key) throw new Error('Provider, model ID, endpoint and API key are required.');
    const endpoint = new URL(p.base_url);
    if(endpoint.username || endpoint.password)throw new Error('Put credentials in the API key field, not the endpoint.');
    if (endpoint.protocol !== 'https:' && !(endpoint.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname)))
      throw new Error('Use an HTTPS endpoint, or a local model server.');
    this.secrets.push(p.api_key);
    this.modelConnections ??= {};
    const previous=this.modelConnections[p.provider] ?? this.models.getRegisteredProviderConfig?.(p.provider);
    const connection={baseUrl: endpoint.toString(), api: 'openai-completions', models: [...(previous?.models ?? []).filter(model=>model.id!==p.model),{
      id: p.model, name: p.model, reasoning: false, input: ['text', 'image'],
      contextWindow: 64000, maxTokens: 8192, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    }]};
    this.models.registerProvider(p.provider,connection);
    await this.models.login(p.provider,'api_key',{signal:AbortSignal.timeout(15000),notify(){},prompt:async request=>{
      if(request.type!=='secret')throw new Error('This provider requires additional connection steps. Connect it in Pi, then reconnect the assistant.');
      return p.api_key;
    }});
    this.modelConnections[p.provider]=connection;
    await this.refreshKeyProviders();
    await writeFile(join(this.config.output,'model-connections.json'),JSON.stringify(this.modelConnections,null,2)+'\n',{mode:0o600});
    this.emitModels(this.study ? {provider:this.study.provider,id:this.study.model}:{provider:p.provider,id:p.model});
  }
  async start(p) {
    if (this.busy) throw new Error('A study is already running.');
    if (this.study) throw new Error('End the current study before starting another.');
    const model = this.models.getModel(p.provider, p.model);
    if (!model?.input.includes('image')) throw new Error('Select a registered model that accepts images.');
    if (!this.models.hasConfiguredAuth(p.provider)) throw new Error('Connect this provider in Pi, or add its API key in the panel.');
    if (!['free', 'guided', 'independent'].includes(p.experiment ?? 'free')) throw new Error('Unknown study mode.');
    if (!p.prompt?.trim()) throw new Error('Describe what you would like to paint.');
    this.busy = true;
    this.cancelRequested = false;
    this.emit({ type: 'busy', busy: true });
    let began = false;
    try {
      const id = randomUUID();
      const directory = join(this.config.output, id);
      await mkdir(directory);
      const references = [];
      for (const [index, item] of (p.references ?? []).entries()) {
        if (index >= 4) throw new Error('Attach up to four reference images.');
        if (p.experiment === 'independent' && item.role === 'construction-map') continue;
        const data = await readFile(item.path);
        if (data.length > 12 * 1024 * 1024) throw new Error('Use references smaller than 12 MB.');
        const info = imageInfo(data);
        const path = join(directory, `reference-${index + 1}` + ({ 'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif' }[info.mimeType]));
        await copyFile(item.path, path);
        references.push({ id: `reference-${index + 1}`, role: item.role === 'construction-map' ? item.role : 'reference',
          name: basename(item.path), path, width: info.width, height: info.height });
      }
      if (p.experiment === 'guided' && !references.some(r => r.role === 'construction-map')) throw new Error('Attach a construction map for a guided study.');
      if (p.experiment === 'independent' && !references.some(r => r.role === 'reference')) throw new Error('Attach a reference for an independent study.');
      this.study = { id, directory, references, name: p.name ?? 'Creative study', experiment: p.experiment ?? 'free', provider: p.provider, model: p.model };
      await writeFile(join(directory, 'study.json'), JSON.stringify({ ...this.study, prompt: p.prompt, started_at: new Date().toISOString() }, null, 2));
      await writeFile(join(this.config.output, 'active-session.json'), JSON.stringify({ id }), { mode: 0o600 });
      if (this.cancelRequested) throw new Error('Stopped before creating a study.');
      this.setActivity('preparing', 'Preparing your painting…');
      // Mark before dispatch: even a lost begin response can leave a new document.
      began = true;
      const observation = await this.callNative('begin', { mode: p.mode ?? 'new', name: p.name ?? 'Creative study',
        width: p.width ?? 768, height: p.height ?? 1024, background: p.background ?? '#ece3d4', output_dir: directory });
      await resultContent(this, observation);
      await this.openSession(model);
      const first = await imageContent(directory, observation.image_path);
      await this.runPrompt(studyContext(this.study, observation) + '\n\nUser request:\n' + p.prompt, [first.content]);
    } catch (error) {
      if (began && this.study) await this.bridge.call('end', {}, this.study.id).catch(() => {});
      this.untrace?.(); this.untrace = undefined; this.session?.dispose();
      this.session = undefined;
      this.study = undefined;
      await rm(join(this.config.output, 'active-session.json'), { force: true });
      this.emit({ type: 'ended' });
      throw error;
    } finally {
      this.busy = false;
      this.emit({ type: 'busy', busy: false });
    }
  }
  // OpenRouter key for image assets: the painter's OpenRouter connection, else OPENROUTER_API_KEY.
  async imageKey() {
    try { return (await this.models?.getAuth?.('openrouter'))?.auth?.apiKey ?? process.env.OPENROUTER_API_KEY ?? null; }
    catch { return process.env.OPENROUTER_API_KEY ?? null; }
  }
  // The artist's ChatGPT (Codex) sign-in, for Codex image assets; Pi refreshes it.
  async codexKey() {
    try { return (await this.models?.getAuth?.('openai-codex'))?.auth?.apiKey ?? null; } catch { return null; }
  }
  async openSession(model, sessionFile) {
      const { directory, id } = this.study;
      const settings = SettingsManager.inMemory({
        compaction: { enabled: true, reserveTokens: Math.max(16384, (model.contextWindow ?? 131072) - 65536), keepRecentTokens: 12000 }, retry: { enabled: true, maxRetries: 2, baseDelayMs: 1000, provider: { timeoutMs: 90000, maxRetries: 0 } },
        packages: [], extensions: [], skills: [], enableAnalytics: false, enableInstallTelemetry: false,
        images: { autoResize: true, blockImages: false },
      });
      const loader = new DefaultResourceLoader({ cwd: directory, agentDir: join(directory, 'agent'), settingsManager: settings,
        // Only the bundled skills: Pi lists them while the painter's skill-only `read` tool is active.
        noExtensions: true, noSkills: true, additionalSkillPaths: [SKILLS_DIR], noContextFiles: true, noPromptTemplates: true, noThemes: true,
        systemPromptOverride: () => this.systemInstructions ?? PAINTING_INSTRUCTIONS,
      });
      await loader.reload();
      const tools = this.buildTools ? this.buildTools() : paintingTools(this);
      const result = await createAgentSession({ cwd: directory, agentDir: join(directory, 'agent'),
        modelRuntime: this.models, model, thinkingLevel: thinkingLevel(this.executionSettings,model),
        resourceLoader: loader, settingsManager: settings, customTools: tools, tools: tools.map(t => t.name),
        sessionManager: (managers => sessionFile ? managers.open(sessionFile, join(directory, 'sessions'), directory) : managers.create(directory, join(directory, 'sessions')))(this.sessionManagers ?? SessionManager) });
      this.session = result.session;
      this.session.agent.toolExecution = 'sequential';
      // Send only the newest canvas images to the model; Pi's own transform runs first.
      const transform = this.session.agent.transformContext;
      this.session.agent.transformContext = async (messages, signal) => keepRecentImages(transform ? await transform(messages, signal) : messages);
      this.session.agent.shouldStopAfterTurn = () => this.cancelRequested || this.faulted || this.turns >= 24;
      this.session.subscribe(event => this.onEvent(event));
      this.untrace?.(); this.untrace = this.traceSession?.(this.session, 'painter');
      this.emit({ type: 'study', id, directory, session_file: this.session.sessionFile, model: { provider: model.provider, id: model.id } });
      this.study.session_file = this.session.sessionFile;
      this.applyExecutionSettings?.();
      await writeFile(join(directory, 'resume.json'), JSON.stringify(this.study, null, 2));
  }
  async resume(id) {
    if (this.busy || this.study) throw new Error('Finish the current conversation before opening another.');
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid saved painting.');
    const directory = join(this.config.output, id);
    const info = JSON.parse(await readFile(await containedFile(directory, join(directory, 'study.json')), 'utf8'));
    const files = (await readdir(join(directory, 'sessions'))).filter(f => f.endsWith('.jsonl')).sort();
    if (!files.length) throw new Error('No saved conversation was found.');
    const sessionFile = await containedFile(directory, join(directory, 'sessions', files.at(-1)));
    const entries = (await readFile(sessionFile, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
    let layers = [];
    for (const entry of entries) {
      const message = entry.message;
      if (message?.role !== 'toolResult') continue;
      for (const part of message.content ?? []) {
        if (part.type !== 'text') continue;
        try { const value = JSON.parse(part.text); if (value.layers) layers = value.layers; } catch { /* Non-canvas result. */ }
      }
    }
    const model = this.models.getModel(info.provider, info.model);
    if (!model?.input.includes('image')) throw new Error('The saved painting model is unavailable.');
    this.busy = true; this.cancelRequested = false; this.faulted = false;
    this.emit({ type: 'busy', busy: true });
    this.study = { ...info, id, directory };
    try {
      this.setActivity('preparing', 'Reopening your conversation…');
      const observation = await this.callNative('begin', { mode: 'resume', name: info.name ?? 'Creative study', output_dir: directory,
        ...(info.painting_file ? { painting_path: resolve(this.paintingsDirectory ?? directory, info.painting_file) } : {}),
        editable_layers: layers.filter(layer => layer.editable_by_agent).map(layer => layer.id) });
      await writeFile(join(this.config.output, 'active-session.json'), JSON.stringify({ id }), { mode: 0o600 });
      await this.openSession(model, sessionFile);
      const messages = this.session.messages.filter(m => ['user', 'assistant'].includes(m.role)).map(m => ({
        role: m.role, text: typeof m.content === 'string' ? m.content : m.content.filter(c => c.type === 'text').map(c => c.text).join('\n'),
      })).filter(m => m.text.trim()).map(m => ({ ...m, text: m.role === 'user' && m.text.includes('\n\nUser request:\n') ? m.text.split('\n\nUser request:\n').slice(1).join('\n\nUser request:\n') : m.text }));
      for (const message of messages) {
        if (message.role === 'user' && message.text.startsWith('The conversation was reopened on the attached current canvas.'))
          message.text = message.text.slice(message.text.indexOf('\n\n') + 2);
      }
      this.emit({ type: 'history', messages });
      await resultContent(this, observation);
      this.resumeImage = (await imageContent(directory, observation.image_path)).content;
      this.setActivity('idle', 'Conversation restored. What would you like to change?');
    } catch (error) {
      await this.bridge.call('end', {}, id).catch(() => {});
      this.untrace?.(); this.untrace = undefined; this.session?.dispose(); this.session = undefined; this.study = undefined;
      this.emit({ type: 'ended' });
      throw error;
    } finally { this.busy = false; this.emit({ type: 'busy', busy: false }); }
  }
  setActivity(phase, message) {
    this.activity = phase;
    this.emit({ type: 'status', phase, message });
  }
  async callNative(operation, params = {}, operationId) {
    const expected = operation === 'begin' ? 'begin' : operationId;
    let last;
    let polling = false;
    let closed = false;
    const timer = setInterval(async () => {
      if (polling || !this.study) return;
      polling = true;
      try {
        const progress = JSON.parse(await readFile(join(this.study.directory, '.progress.json'), 'utf8'));
        if (!closed && progress.operation_id === expected && progress.at !== last) {
          last = progress.at;
          this.diagnostics?.record({type:'native_progress',operation_id:expected,phase:progress.phase,message:progress.message});
          if (!this.cancelRequested) this.setActivity(progress.phase, progress.message);
        }
      } catch { /* A progress file is optional on older bridges. */ }
      finally { polling = false; }
    }, 200);
    try { return await this.bridge.call(operation, params, this.study.id, operationId); }
    finally { closed = true; clearInterval(timer); }
  }
  checkModelWait(now = Date.now()) {
    if (!this.busy || this.cancelRequested || !['waiting', 'thinking', 'replying', 'planning'].includes(this.activity)) return;
    if (now - this.lastModelActivityAt >= this.modelIdleTimeoutMs) {
      this.runError = 'The model stopped responding for ' + Math.round(this.modelIdleTimeoutMs / 1000) + ' seconds. The run is paused. Send a message to try again.';
      this.stop();
    }
  }
  onEvent(event) {
    if(event.type==='turn_start')this.diagnosticRequestId=randomUUID();
    if (['turn_start','turn_end','message_start','message_end','tool_execution_start','tool_execution_end','auto_retry_start','auto_retry_end'].includes(event.type))
      this.diagnostics?.record({type:'model_'+event.type,tool_call_id:event.toolCallId,tool:event.toolName,
        model_request_id:this.diagnosticRequestId,role:event.message?.role,error:!!event.isError,stop_reason:event.message?.stopReason});
    if (event.type === 'auto_retry_start') {
      this.runError = undefined;
      this.setActivity('retrying','Temporary model connection problem. Retrying automatically ('+event.attempt+'/'+event.maxAttempts+')…');
    }
    if (event.type === 'auto_retry_end' && event.success) this.runError = undefined;
    if (event.type === 'turn_start' || (event.type === 'message_start' && event.message.role === 'assistant')) {
      this.lastModelActivityAt = Date.now();
      if (!this.cancelRequested) this.setActivity('waiting', 'Waiting for the model…');
    }
    if (event.type === 'message_update') {
      this.lastModelActivityAt = Date.now();
      const kind = event.assistantMessageEvent.type;
      const phase = kind.startsWith('thinking') ? 'thinking' : kind.startsWith('toolcall') ? 'planning' : kind.startsWith('text') ? 'replying' : null;
      if (phase && this.activity !== phase && !this.cancelRequested) this.setActivity(phase, ({thinking:'Thinking about the painting…', planning:'Preparing the next painting action…', replying:'Writing a reply…'})[phase]);
    }
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta')
      this.emit({ type: 'text', text: event.assistantMessageEvent.delta });
    if (event.type === 'message_end' && event.message.role === 'assistant') {
      this.emit({ type: 'message_end' });
      if (event.message.stopReason === 'error') {
        const provider = this.study?.provider, message = event.message.errorMessage ?? 'The model request failed.';
        this.runError = this.signInLapsed(provider, message) ? signInMessage(provider, true) : this.redact(message);
      }
    }
    if (event.type === 'tool_execution_start') {
      this.pendingTools.set(event.toolCallId, { name: event.toolName, args: event.args, at: Date.now() });
      this.setActivity('tool', ({observe_canvas:'Looking at the canvas…',list_brushes:'Choosing a brush…',paint_pass:'Painting: ' + (event.args?.name ?? 'next pass'),adjust_layer:'Adjusting a layer…',create_layer:'Creating a layer: ' + (event.args?.name ?? 'new layer'),set_layer:'Setting a layer…',select:'Selecting: ' + (event.args?.name ?? 'a region'),fill_region:'Filling a region: ' + (event.args?.name ?? 'a layer'),apply_filter:'Applying a filter: ' + (event.args?.filter ?? 'filter'),colorize_flats:'Colorizing flats: ' + (event.args?.name ?? 'Flats'),transform_layer:'Transforming a layer…',letter:'Lettering: ' + (event.args?.kind ?? 'text') + ' in ' + (event.args?.panel ?? 'a panel'),view_reference:'Studying the reference…'})[event.toolName] ?? 'Working…');
    }
    if (event.type === 'tool_execution_end') {
      const tool = this.pendingTools.get(event.toolCallId);
      this.pendingTools.delete(event.toolCallId);
      if (tool && ['paint_pass','adjust_layer',...CRAFT_OPERATIONS,...COMIC_OPERATIONS,'painting_toolbox','paint_recipe','paint_contours','paint_from_reference','continue_reference_painting','paint_reference_edges','paint_reference_surface'].includes(tool.name)) this.emit({ type: 'action', error: !!event.isError,
        message: event.isError ? 'Painting action needs attention' : ['paint_pass','painting_toolbox','create_layer','fill_region','paint_recipe','paint_contours','paint_from_reference','continue_reference_painting','paint_reference_edges','paint_reference_surface'].includes(tool.name) ? 'Painted: ' + (tool.args?.name ?? 'new layer') : 'Adjusted a layer',
        seconds: (Date.now() - tool.at) / 1000 });
      this.lastModelActivityAt = Date.now();
      if (!this.cancelRequested) this.setActivity('waiting', 'Waiting for the model…');
    }
    if (event.type === 'turn_end') this.turns++;
  }
  runDeadlineMs() { return 10 * 60 * 1000; }
  async runPrompt(prompt, images = []) {
    this.turns = 0;
    this.runError = undefined;
    this.lastModelActivityAt = Date.now();
    this.setActivity('waiting', 'Waiting for the model…');
    if (this.cancelRequested) { this.emit({ type: 'status', message: 'Paused before the next model request.' }); return; }
    // A chat turn may not run forever; autonomous painting runs are bounded by the artist's time and
    // pass allowances and by the model-idle watch instead (runDeadlineMs() returns null for them).
    const limit = this.runDeadlineMs();
    const deadline = limit && setTimeout(() => {
      this.runError = 'Time limit reached. The run is paused. You can continue with another message.';
      this.stop();
    }, limit);
    const modelWatch = setInterval(() => this.checkModelWait(), 1000);
    try {
      await this.session.prompt(prompt, { images, expandPromptTemplates: false });
      if (this.runError) { this.emit({ type: 'error', message: this.runError }); this.setActivity('error', this.runError); }
      else this.setActivity('idle', this.faulted ? 'Paused for inspection.' : this.cancelRequested ? 'Paused. No further painting will start.' : this.turns >= 24 ? 'Run limit reached. Review the painting before continuing.' : 'Ready for your next message.');
    } finally { if (deadline) clearTimeout(deadline); clearInterval(modelWatch); }
  }
  async prompt(text) {
    if (!this.session) throw new Error('Start a study first.');
    if (!text?.trim()) throw new Error('Enter a painting direction.');
    if (this.busy) { await this.session.steer(text); this.emit({ type: 'status', message: 'Your direction is queued after the current pass.' }); return; }
    this.busy = true; this.cancelRequested = false;
    this.emit({ type: 'busy', busy: true });
    try {
      const images = this.resumeImage ? [this.resumeImage] : [];
      this.resumeImage = undefined;
      await this.runPrompt(text, images);
    }
    finally { this.busy = false; this.emit({ type: 'busy', busy: false }); }
  }
  stop() {
    this.cancelRequested = true;
    this.session?.agent.clearAllQueues();
    this.session?.agent.abort();
    this.setActivity('stopping', 'Stopping… Any brush action in progress will finish and save.');
  }
  async observe() {
    if (!this.study) throw new Error('Start a study first.');
    if (this.busy) throw new Error('A fresh preview arrives after the current pass.');
    return resultContent(this, await this.bridge.call('observe', {}, this.study.id));
  }
  async end() {
    if (this.busy) throw new Error('Stop the agent and wait for the current pass to finish first.');
    if (this.study) await this.bridge.call('end', {}, this.study.id);
    await rm(join(this.config.output, 'active-session.json'), { force: true });
    this.untrace?.(); this.untrace = undefined; this.session?.dispose(); this.session = undefined; this.study = undefined; this.faulted = false;
    this.emit({ type: 'ended' });
  }
  redact(value) {
    let text = String(value);
    for (const secret of this.secrets) if (secret) text = text.replaceAll(secret, '[redacted]');
    return text.replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[redacted]');
  }
}
