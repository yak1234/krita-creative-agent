// @ts-check
// Langfuse tracing for Agent Pi sessions and Luna decisions.
// One trace per agent run (session.prompt → agent_end): an `agent` root with a
// `generation` per model call and a `tool` per tool execution, as siblings.
// Tracing is optional: with Langfuse keys every chat is traced; without them chats run untraced.
// Every trace of a Krita chat carries that chat's id as its Langfuse session,
// from the chat's start until New chat (endSession).
import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { promisify } from 'node:util';

const run = promisify(execFile);
export const KEYCHAIN_SERVICE = 'creative-agent-langfuse';
const KEYS = ['LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL'];
const SECRET_PATTERNS = [/sk-or-v1-[A-Za-z0-9]+/g, /sk-lf-[A-Za-z0-9-]+/g, /sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}/g, /Bearer\s+[A-Za-z0-9._-]{12,}/g];

// Minimal dotenv: KEY=value lines, optional `export`, single or double quotes,
// `#` comments (inline only after unquoted values), CRLF. No variable expansion.
export function parseDotEnv(text) {
  const values = {};
  for (const line of String(text).split(/\r?\n/)) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let value = m[2].trim();
    const quote = value[0];
    if ((quote === '"' || quote === "'") && value.indexOf(quote, 1) > 0) value = value.slice(1, value.indexOf(quote, 1));
    else value = value.replace(/\s+#.*$/, '').trim();
    values[m[1]] = value;
  }
  return values;
}
async function readDotEnv(path) {
  if (!path) return {};
  try { return parseDotEnv(await readFile(path, 'utf8')); } catch { return {}; }
}

// Sources in order: the project's .env, the process environment, the macOS Keychain
// (Krita does not inherit the login shell; see scripts/langfuse-credentials.mjs).
// A key pair always comes whole from one source, never mixed across sources.
export async function langfuseCredentials(env = process.env, keychain = readKeychain, dotEnvPath = null) {
  const fromKeychain = async () => Object.fromEntries(await Promise.all(KEYS.map(async key => [key, await keychain(key)])));
  /** @type {[string, () => Promise<any>][]} */
  const sources = [['.env', async () => readDotEnv(dotEnvPath)], ['environment', async () => env], ['Keychain', fromKeychain]];
  for (const [source, load] of sources) {
    const values = await load();
    if (!values.LANGFUSE_PUBLIC_KEY || !values.LANGFUSE_SECRET_KEY) continue;
    return { LANGFUSE_PUBLIC_KEY: values.LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY: values.LANGFUSE_SECRET_KEY,
      LANGFUSE_BASE_URL: values.LANGFUSE_BASE_URL || values.LANGFUSE_HOST || null, source };
  }
  return null;
}
async function readKeychain(account) {
  if (process.platform !== 'darwin') return null;
  try { return (await run('security', ['find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', account, '-w'], { timeout: 5000 })).stdout.trim() || null; }
  catch { return null; }
}

export function maskSecrets(value, secrets = []) {
  if (typeof value !== 'string') return value;
  let text = value;
  for (const secret of secrets) if (secret && secret.length >= 8) text = text.split(secret).join('[redacted]');
  for (const pattern of SECRET_PATTERNS) text = text.replace(pattern, '[redacted]');
  return text;
}

// Pi message → OpenAI chat format, which Langfuse renders as a conversation
// (tool calls as cards, images as media).
export function chatMessage(message) {
  const parts = content => typeof content === 'string' ? content : content.map(part =>
    part.type === 'image' ? { type: 'image_url', image_url: { url: `data:${part.mimeType};base64,${part.data}` } }
      : { type: 'text', text: part.text ?? '' });
  if (message.role === 'user') return { role: 'user', content: parts(message.content) };
  if (message.role === 'toolResult') return { role: 'tool', tool_call_id: message.toolCallId, name: message.toolName, content: parts(message.content) };
  if (message.role === 'assistant') {
    const text = message.content.filter(p => p.type === 'text').map(p => p.text).join('\n');
    const thinking = message.content.filter(p => p.type === 'thinking' && !p.redacted).map(p => p.thinking).join('\n');
    const calls = message.content.filter(p => p.type === 'toolCall').map(p => ({ id: p.id, type: 'function', function: { name: p.name, arguments: JSON.stringify(p.arguments ?? {}) } }));
    return { role: 'assistant', content: text, ...(thinking ? { thinking } : {}), ...(calls.length ? { tool_calls: calls } : {}) };
  }
  return { role: message.role ?? 'custom', content: JSON.stringify(message) };
}
const toolOutput = result => {
  const content = result?.content;
  return Array.isArray(content) ? parts(content) : result;
  function parts(list) { return list.map(p => p.type === 'image' ? { type: 'image_url', image_url: { url: `data:${p.mimeType};base64,${p.data}` } } : p.type === 'text' ? p.text : p); }
};
const usageDetails = u => u && { input: u.input ?? 0, output: u.output ?? 0, cache_read_input_tokens: u.cacheRead ?? 0, cache_creation_input_tokens: u.cacheWrite ?? 0, ...(u.reasoning != null ? { reasoning_tokens: u.reasoning } : {}) };
const costDetails = u => u?.cost && { input: u.cost.input, output: u.cost.output, cache_read_input_tokens: u.cost.cacheRead, cache_creation_input_tokens: u.cost.cacheWrite, total: u.cost.total };

export class LangfuseTracing {
  /** @param {{tracing?: any, propagateAttributes?: any, provider?: any, processor?: any, client?: any, projectId?: string, projectName?: string, organizationName?: string, credentialSource?: string, baseUrl?: string, environment?: string, release?: string}} options */
  constructor({ tracing, propagateAttributes, provider, processor, client, projectId, projectName, organizationName, credentialSource, baseUrl, environment, release }) {
    this.tracing = tracing; this.propagateAttributes = propagateAttributes; this.provider = provider; this.processor = processor; this.client = client;
    this.projectId = projectId; this.projectName = projectName; this.organizationName = organizationName; this.credentialSource = credentialSource;
    this.baseUrl = baseUrl; this.environment = environment; this.release = release;
  }
  describe() { return [this.organizationName, this.projectName].filter(Boolean).join(' / ') + ' · ' + this.environment + (this.credentialSource ? ', keys from ' + this.credentialSource : ''); }
  sessionUrl(sessionId) { return `${this.baseUrl}/project/${this.projectId}/sessions/${encodeURIComponent(sessionId)}`; }
  // Scores (e.g. the reviewer's verdict) make traces filterable as training data.
  // Langfuse takes exactly one target: a trace (already in its chat session) or a session.
  score(/** @type {{traceId?: string, sessionId?: string, [key: string]: any}} */ { traceId, sessionId, ...body }) {
    try { this.client.score.create({ environment: this.environment, ...body, ...(traceId ? { traceId } : { sessionId }) }); }
    catch { /* Tracing never interrupts painting. */ }
  }
  // New chat closes the session: a final `end-chat` event, then everything is sent.
  async endSession(sessionId, { reason = 'new_chat', metadata } = /** @type {{reason?: string, metadata?: object}} */ ({})) {
    if (!sessionId) return;
    try { this.start(null, 'end-chat', { metadata: { reason, ...metadata } }, { asType: 'event' }, { traceName: 'end-chat', sessionId, version: this.release }); }
    catch { /* Tracing never interrupts painting. */ }
    await this.flush();
  }
  // Trace attributes go on every observation (propagated), as the docs advise.
  start(parent, name, attributes, options, trace) {
    // The observation's own startObservation() drops startTime, so pass the parent context.
    const create = () => this.tracing.startObservation(name, attributes, parent ? { ...options, parentSpanContext: parent.otelSpan.spanContext() } : options);
    return trace ? this.propagateAttributes(trace, create) : create();
  }
  // Follows one Pi session. `describe()` is read per run so the study and plan
  // step are current. Returns an unsubscribe function.
  // onRun({traceId, observationId}) fires when a run starts, for scores.
  watchSession(session, { traceName, generationName, describe = /** @type {() => any} */ (() => ({})), onRun }) {
    let run = null;
    const tools = new Map();
    const begin = () => {
      const info = describe();
      // Propagated metadata must be short strings; rich context stays on the root.
      const name = info.traceName ?? traceName;
      const trace = { traceName: name, sessionId: info.sessionId, tags: info.tags, version: this.release,
        metadata: Object.fromEntries(Object.entries(info.ids ?? {}).filter(([, v]) => v != null).map(([k, v]) => [k, String(v).slice(0, 200)])) };
      const root = this.start(null, name, { metadata: { ...info.ids, ...info.metadata, pi_session_id: session.sessionId, system_prompt: session.agent?.state?.systemPrompt } }, { asType: 'agent' }, trace);
      // A run may name its own generations (the studio's plan turns on the Planner model: plan-steps).
      run = { root, trace, pending: [], turnStart: new Date(), firstToken: null, lastText: '', generationName: info.generationName ?? generationName };
      onRun?.({ traceId: root.traceId, observationId: root.id });
    };
    const handler = event => {
      try {
        if (event.type === 'agent_start') begin();
        if (!run) return;
        if (event.type === 'turn_start') { run.turnStart = new Date(); run.firstToken = null; }
        else if (event.type === 'message_start' && event.message?.role === 'assistant') run.firstToken = new Date();
        else if (event.type === 'message_end' && event.message?.role !== 'assistant') {
          const message = chatMessage(event.message);
          if (event.message.role === 'user' && !run.input) {
            // The trace input reads as the artist's message; images stay as media parts.
            const content = Array.isArray(message.content) && message.content.every(p => p.type === 'text') ? message.content.map(p => p.text).join('\n') : message.content;
            run.input = content; run.root.update({ input: content });
          }
          run.pending.push(message);
        } else if (event.type === 'message_end') {
          const m = event.message, output = chatMessage(m);
          const generation = this.start(run.root, run.generationName, {
            model: m.responseModel ?? m.model, input: run.pending, output,
            usageDetails: usageDetails(m.usage), costDetails: costDetails(m.usage),
            completionStartTime: run.firstToken ?? undefined,
            metadata: { provider: m.provider, api: m.api, stop_reason: m.stopReason, response_id: m.responseId },
            ...(m.stopReason === 'error' || m.stopReason === 'aborted' ? { level: 'ERROR', statusMessage: m.errorMessage ?? m.stopReason } : {}),
          }, { asType: 'generation', startTime: run.turnStart }, run.trace);
          generation.end();
          run.pending = [output]; run.lastText = output.content || run.lastText;
          run.turnStart = new Date();
        } else if (event.type === 'tool_execution_start') {
          tools.set(event.toolCallId, this.start(run.root, event.toolName, { input: event.args }, { asType: 'tool' }, run.trace));
        } else if (event.type === 'tool_execution_end') {
          const tool = tools.get(event.toolCallId); tools.delete(event.toolCallId);
          tool?.update({ output: toolOutput(event.result), ...(event.isError ? { level: 'ERROR', statusMessage: 'Tool returned an error' } : {}) }).end();
        } else if (event.type === 'agent_end') {
          for (const tool of tools.values()) tool.update({ level: 'WARNING', statusMessage: 'Run ended before the tool finished' }).end();
          tools.clear();
          run.root.update({ output: run.lastText }).end();
          run = null;
        }
      } catch { /* Tracing never interrupts painting. */ }
    };
    const unsubscribe = session.subscribe(handler);
    return () => { handler({ type: 'agent_end' }); unsubscribe?.(); };
  }
  // A single non-Pi model call (Luna decisions), as its own trace in the study session.
  // `finish(result)` returns the observation update (output, usage, level).
  async observeGeneration(name, { model, input, sessionId, tags, metadata }, call, finish) {
    const generation = this.start(null, name, { model, input, metadata }, { asType: 'generation' }, { traceName: name, sessionId, tags, version: this.release });
    try {
      const result = await call();
      try { generation.update(finish(result)); } catch { /* Tracing never interrupts painting. */ }
      return result;
    } catch (error) {
      generation.update({ level: 'ERROR', statusMessage: error.message }); throw error;
    } finally { generation.end(); }
  }
  // A typed decision as its own trace (one `decide-<kind>` event) in its chat session.
  // The trace id derives from the decision id, so later evidence can find it without a lookup.
  async decisionTraceId(decisionId) { return this.tracing.createTraceId(decisionId); }
  async recordDecision(decision, { sessionId, metadata } = /** @type {{sessionId?: string, metadata?: object}} */ ({})) {
    const traceId = await this.decisionTraceId(decision.decision_id);
    const spanId = (await this.tracing.createTraceId(decision.decision_id + ':span')).slice(0, 16);
    const name = 'decide-' + decision.kind;
    this.propagateAttributes({ traceName: name, sessionId, tags: ['decision', decision.kind], version: this.release,
      metadata: { decision_id: decision.decision_id.slice(0, 200), kind: decision.kind, answered_by: decision.answered_by ?? 'none' } }, () =>
      this.tracing.startObservation(name, {
        input: { state: decision.state, questions: decision.questions, images: decision.images.map(url => ({ type: 'image_url', image_url: { url } })) },
        output: { answers: decision.answers ?? null, answered_by: decision.answered_by ?? null },
        metadata: { decision_id: decision.decision_id, kind: decision.kind, ...metadata },
      }, { asType: 'event', parentSpanContext: { traceId, spanId, traceFlags: 1, isRemote: true }, ...(decision.recorded_at ? { startTime: new Date(decision.recorded_at) } : {}) }));
    return traceId;
  }
  // The artist's verdict on a decision: `artist-verdict` for single-question decisions,
  // `artist-<question>` otherwise.
  async scoreDecision(decisionId, { name = 'artist-verdict', value, comment, source = 'artist' }) {
    this.score({ traceId: await this.decisionTraceId(decisionId), name, value: value ? 1 : 0, dataType: 'BOOLEAN', comment, metadata: { decision_id: decisionId, source } });
  }
  async flush() { await Promise.allSettled([this.processor.forceFlush(), this.client.flush()]); }
  async shutdown() { await this.flush(); await Promise.allSettled([this.provider.shutdown(), this.client.shutdown()]); }
}

export class LangfuseConnectionError extends Error {}

// Connects to Langfuse or throws LangfuseConnectionError. The credentials are
// checked against the project (LangfuseClient) before any chat can start.
export async function connectLangfuse({ secrets = () => [], release, env = process.env, keychain = readKeychain, dotEnvPath = null, timeout = 10000 } = /** @type {{secrets?: () => any[], release?: string, env?: NodeJS.ProcessEnv, keychain?: (account: string) => Promise<string>, dotEnvPath?: string | null, timeout?: number}} */ ({})) {
  const credentials = await langfuseCredentials(env, keychain, dotEnvPath);
  if (!credentials) throw new LangfuseConnectionError('No Langfuse keys. Add LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL to ' + (dotEnvPath ?? 'the project .env') + '.');
  const baseUrl = (credentials.LANGFUSE_BASE_URL || 'https://cloud.langfuse.com').replace(/\/+$/, '');
  const [{ NodeTracerProvider }, { LangfuseSpanProcessor }, tracing, { LangfuseClient }, { context }, { AsyncLocalStorageContextManager }, { resourceFromAttributes }] = await Promise.all([
    import('@opentelemetry/sdk-trace-node'), import('@langfuse/otel'), import('@langfuse/tracing'), import('@langfuse/client'), import('@opentelemetry/api'),
    import('@opentelemetry/context-async-hooks'), import('@opentelemetry/resources')]);
  const client = new LangfuseClient({ publicKey: credentials.LANGFUSE_PUBLIC_KEY, secretKey: credentials.LANGFUSE_SECRET_KEY, baseUrl, timeout: Math.ceil(timeout / 1000) });
  let projectId, projectName, organizationName;
  try {
    const projects = await Promise.race([client.api.projects.get(), new Promise((_, reject) => setTimeout(() => reject(new Error('timed out')), timeout))]);
    ({ id: projectId, name: projectName, organization: { name: organizationName } = /** @type {{name?: string}} */ ({}) } = /** @type {any} */ (projects?.data?.[0] ?? {}));
  } catch (error) {
    await client.shutdown().catch(() => {});
    const status = error?.statusCode ?? error?.status;
    throw new LangfuseConnectionError(baseUrl + (status === 401 || status === 403 ? ' rejected the credentials from ' + credentials.source + '.' : ' could not be reached (' + maskSecrets(String(error?.message ?? error), [credentials.LANGFUSE_SECRET_KEY]).slice(0, 160) + ').'));
  }
  if (!projectId) { await client.shutdown().catch(() => {}); throw new LangfuseConnectionError('These Langfuse keys have no project.'); }
  // propagateAttributes (session, tags, ids on every observation) needs a context manager.
  context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
  const environment = env.LANGFUSE_TRACING_ENVIRONMENT || 'development';
  const processor = new LangfuseSpanProcessor({
    publicKey: credentials.LANGFUSE_PUBLIC_KEY, secretKey: credentials.LANGFUSE_SECRET_KEY, baseUrl, environment, release,
    mask: ({ data }) => maskSecrets(data, [credentials.LANGFUSE_SECRET_KEY, ...secrets()]),
  });
  const provider = new NodeTracerProvider({ spanProcessors: [processor], resource: resourceFromAttributes({ 'service.name': 'krita-creative-agent', 'service.version': release ?? 'unknown' }) });
  // Langfuse's own tracer provider, so nothing else in the process is affected.
  tracing.setLangfuseTracerProvider(provider);
  return new LangfuseTracing({ tracing, propagateAttributes: tracing.propagateAttributes, provider, processor, client, projectId, projectName, organizationName,
    credentialSource: credentials.source, baseUrl, environment, release });
}
