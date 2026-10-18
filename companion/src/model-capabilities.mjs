// @ts-check
/** Verify a model route with disposable visual/tool work, never artist content. */
import { createHash, randomBytes, randomInt } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { deflateSync } from 'node:zlib';
import { setTimeout as wait } from 'node:timers/promises';
import { createAgentSession, defineTool, DefaultResourceLoader, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { stopAfterTurn } from './turn-control.mjs';
import { Type } from 'typebox';

const MAX_AGE = 24 * 60 * 60 * 1000;
/** @type {[string, number[]][]} */
const PALETTE = [ ['red', [235, 35, 45]], ['green', [25, 175, 70]], ['blue', [30, 65, 230]],
  ['yellow', [250, 220, 30]], ['black', [15, 15, 15]], ['white', [245, 245, 245]] ];
const MESSAGES = {
  batch_only: 'Choose an interactive model. Batch routes cannot run a painting conversation.',
  unsupported_image: 'This model is declared text-only. Choose a model that can receive canvas images.',
  authentication: 'The model connection could not authenticate. Reconnect the provider and retry.',
  image_unverified: 'The model did not correctly read the test image. Choose another vision route or retry the connection test.',
  tools_unverified: 'The model did not complete the test tool call. Choose a route that supports interactive tools.',
  tool_roundtrip: 'The model did not confirm the tool result. This route is not ready for Agent mode.',
  endpoint: 'The configured model endpoint is unavailable or incompatible. Check the connection settings.',
  rate_limit: 'The provider is temporarily limiting requests. Retry the connection test later.',
  timeout: 'The model connection test timed out. Retry or choose another route.',
  cancelled: 'Model connection test stopped. No artwork was changed.',
  provider_error: 'The model connection test failed. Check the provider connection or try another model.',
};

export class CapabilityError extends Error {
  constructor(code) {
    super(MESSAGES[code] ?? MESSAGES.provider_error); this.name = 'CapabilityError'; this.code = code;
    /** @type {Record<string, number> | undefined} */ this.usage = undefined;   // tokens spent before the failure
    /** @type {{expected: string[], reported: string[]} | undefined} */ this.diagnostic = undefined;
  }
}
export const isInteractiveModel = model => !!model && !/\bbatch\b/i.test((model.id ?? '') + ' ' + (model.name ?? ''));
export function modelRouteKey(model, configVersion = 2) {
  let endpoint = model.baseUrl ?? '';
  try {
    const url = new URL(endpoint); url.hash = '';
    url.pathname = url.pathname.replace(/\/+$/, '') || '/';
    endpoint = url.toString().replace(/\/$/, '');
  } catch { /* A missing endpoint still has a stable provider/API key. */ }
  return createHash('sha256').update(JSON.stringify({ provider: model.provider, model: model.id,
    api: model.api, endpoint, headers: model.headers ?? {}, compat: model.compat ?? {}, configVersion })).digest('hex');
}

function classify(error) {
  if (error instanceof CapabilityError) return error;
  const message = String(error?.message ?? error).toLowerCase();
  if (/401|403|unauthori|forbidden|invalid.{0,20}(key|token)|api.?key/.test(message)) return new CapabilityError('authentication');
  if (/429|rate.limit|too many request/.test(message)) return new CapabilityError('rate_limit');
  if (/image.{0,40}(unsupported|not support|invalid)|not support.{0,20}image/.test(message)) return new CapabilityError('image_unverified');
  if (/(tool|function).{0,40}(unsupported|not support|invalid)/.test(message)) return new CapabilityError('tools_unverified');
  if (/404|not.found|endpoint|econnrefused|enotfound/.test(message)) return new CapabilityError('endpoint');
  return new CapabilityError('provider_error');
}

export class ModelCapabilities {
  constructor({ models, cacheDirectory, configVersion = 2, timeoutMs = 30000, ttlMs = MAX_AGE, retryDelayMs = 1000, onStatus = /** @type {(status: any) => void} */ (() => {}) }) {
    if (!models || !cacheDirectory) throw new Error('Model runtime and capability cache directory are required.');
    this.models = models; this.cacheDirectory = cacheDirectory; this.configVersion = configVersion;
    this.timeoutMs = timeoutMs; this.retryDelayMs = retryDelayMs; this.onStatus = onStatus;
    this.ttlMs = Math.max(1, Math.min(MAX_AGE, ttlMs));
    this.entries = {}; this.pending = new Map(); this.writeQueue = Promise.resolve();
  }
  async initialize() {
    await mkdir(this.cacheDirectory, { recursive: true });
    try {
      const saved = JSON.parse(await readFile(join(this.cacheDirectory, 'model-capabilities.json'), 'utf8'));
      if (saved.version === 1) for (const [key, entry] of Object.entries(saved.entries ?? {})) {
        if (/^[a-f0-9]{64}$/.test(key) && entry.status === 'verified' && Number.isFinite(entry.verified_at) && Number.isFinite(entry.expires_at)
          && entry.expires_at > Date.now() && entry.expires_at - entry.verified_at <= MAX_AGE && entry.verified_at <= Date.now())
          this.entries[key] = { status: 'verified', verified_at: entry.verified_at, expires_at: entry.expires_at };
      }
    } catch (error) { if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error; }
    return this;
  }
  status(model) {
    if (!isInteractiveModel(model)) return this.result({ status: 'failed', code: 'batch_only' });
    if (!model.input?.includes('image')) return this.result({ status: 'failed', code: 'unsupported_image' });
    const key = modelRouteKey(model, this.configVersion);
    if (this.pending.has(key)) return this.result({ status: 'verifying' });
    const entry = this.entries[key];
    if (entry?.status === 'verified' && entry.expires_at > Date.now()) return this.result(entry);
    if (entry?.status === 'failed') return this.result(entry);
    return this.result({ status: 'unverified' });
  }
  result(entry, extra = {}) {
    const verified = entry.status === 'verified';
    return { ...entry, route_verified: verified, images_supported: verified, tools_supported: verified,
      message: entry.code ? MESSAGES[entry.code] : verified ? 'Image input and tool round trip verified.'
        : entry.status === 'verifying' ? 'Testing image input and tools with a disposable sample…' : 'This model route has not been tested yet.', ...extra };
  }
  async persist() {
    const entries = Object.fromEntries(Object.entries(this.entries).filter(([, entry]) => entry.status === 'verified')
      .map(([key, entry]) => [key, { status: 'verified', verified_at: entry.verified_at, expires_at: entry.expires_at }]));
    const text = JSON.stringify({ version: 1, entries }, null, 2) + '\n';
    const task = this.writeQueue.catch(() => {}).then(async () => {
      await mkdir(this.cacheDirectory, { recursive: true });
      const file = join(this.cacheDirectory, 'model-capabilities.json'), temporary = file + '.' + randomBytes(8).toString('hex') + '.tmp';
      try { await writeFile(temporary, text, { mode: 0o600 }); await rename(temporary, file); }
      finally { await rm(temporary, { force: true }); }
    });
    this.writeQueue = task; await task;
  }
  async invalidate(model) { delete this.entries[modelRouteKey(model, this.configVersion)]; await this.persist(); }
  async verify(model, { signal, force = false } = /** @type {{signal?: AbortSignal, force?: boolean}} */ ({})) {
    if (signal?.aborted) throw new CapabilityError('cancelled');
    if (!isInteractiveModel(model)) throw new CapabilityError('batch_only');
    if (!model.input?.includes('image')) throw new CapabilityError('unsupported_image');
    const key = modelRouteKey(model, this.configVersion);
    if (!force && this.status(model).route_verified) return this.result(this.entries[key], { cached: true });
    if (this.pending.has(key)) return this.pending.get(key);
    const task = Promise.resolve().then(async () => {
      this.onStatus({ ...this.result({ status: 'verifying' }), provider: model.provider, model: model.id });
      try {
        let usage = {}, completed = false;
        for (let attempt = 1; attempt <= 2 && !completed; attempt++) {
          try {
            const current = await this.probe(model, signal);
            for (const [key,value] of Object.entries(current ?? {})) if (typeof value === 'number') usage[key]=(usage[key] ?? 0)+value;
            completed = true;
          } catch (error) {
            for (const [key,value] of Object.entries(error.usage ?? {})) if (typeof value === 'number') usage[key]=(usage[key] ?? 0)+value;
            error.usage = usage;
            if (signal?.aborted || error.code === 'cancelled') throw new CapabilityError('cancelled');
            if (attempt === 2 || !['rate_limit','timeout','provider_error','image_unverified','tools_unverified','tool_roundtrip'].includes(error.code)) throw error;
            this.onStatus({...this.result({status:'verifying'}),provider:model.provider,model:model.id,
              message:'Checking the model connection again automatically (2/2)…'});
            try {await wait(this.retryDelayMs,undefined,{signal});}
            catch {throw new CapabilityError('cancelled');}
          }
        }
        const now = Date.now();
        this.entries[key] = { status: 'verified', verified_at: now, expires_at: now + this.ttlMs };
        await this.persist();
        const result = this.result(this.entries[key], { cached: false, usage });
        this.pending.delete(key);
        this.onStatus({ ...result, provider: model.provider, model: model.id }); return result;
      } catch (error) {
        const safe = classify(error);
        this.entries[key] = { status: safe.code === 'cancelled' ? 'unverified' : 'failed', code: safe.code };
        // Failure details stay in memory. Neither raw provider errors nor
        // failed test transcripts are written into the persistent cache.
        await this.persist();
        this.pending.delete(key);
        const result = this.result(this.entries[key], { usage: safe.usage });
        this.onStatus({ ...result, provider: model.provider, model: model.id }); throw safe;
      } finally { this.pending.delete(key); }
    });
    this.pending.set(key, task); return task;
  }
  async probe(model, signal) {
    const directory = await mkdtemp(join(tmpdir(), 'creative-model-probe-'));
    const testImage = visionSample();
    const confirmation = randomBytes(12).toString('hex');
    /** @type {import('@earendil-works/pi-coding-agent').AgentSession | undefined} */
    let session;
    let reportReceived = false, failure = null, lastProviderError, timer, cancelled;
    const onAbort = () => { failure = new CapabilityError('cancelled'); session?.agent.abort(); cancelled?.(failure); };
    const deadline = new Promise((_, reject) => {
      cancelled = reject;
      timer = setTimeout(() => { failure = new CapabilityError('timeout'); session?.agent.abort(); reject(failure); }, this.timeoutMs);
    });
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) onAbort();
    const run = async () => {
      const settings = SettingsManager.inMemory({ compaction: { enabled: false },
        retry: { enabled: false, provider: { timeoutMs: this.timeoutMs, maxRetries: 0 } },
        packages: [], extensions: [], skills: [], enableAnalytics: false, enableInstallTelemetry: false });
      const loader = new DefaultResourceLoader({ cwd: directory, agentDir: join(directory, 'agent'), settingsManager: settings,
        noExtensions: true, noSkills: true, noContextFiles: true, noPromptTemplates: true, noThemes: true,
        systemPromptOverride: () => 'You are testing an image-and-tool connection. Read the supplied image, report its four quadrant colors through the provided tool, then reply READY followed by the confirmation_code returned by that tool. Do no other work.' });
      await loader.reload();
      if (failure) throw failure;
      const tool = defineTool({ name: 'report_visual_readiness', label: 'Report test image', executionMode: 'sequential',
        description: 'Report the colors actually visible in the test image: top-left, top-right, bottom-left, bottom-right.',
        parameters: Type.Object({ colors: Type.Array(Type.Union(PALETTE.map(([name]) => Type.Literal(name))), { minItems: 4, maxItems: 4 }) }, { additionalProperties: false }),
        execute: async (_id, args) => {
          if (reportReceived) { failure = new CapabilityError('tool_roundtrip'); throw failure; }
          if (JSON.stringify(args.colors) !== JSON.stringify(testImage.colors)) {
            failure = new CapabilityError('image_unverified'); failure.diagnostic = {expected:testImage.colors,reported:args.colors}; throw failure;
          }
          reportReceived = true;
          return { content: [{ type: 'text', text: JSON.stringify({ confirmation_code: confirmation }) }], details: { reported: true } };
        } });
      ({ session } = await createAgentSession({ cwd: directory, agentDir: join(directory, 'agent'), modelRuntime: this.models,
        model, thinkingLevel: 'off', settingsManager: settings, resourceLoader: loader,
        sessionManager: SessionManager.inMemory(directory), customTools: [tool], tools: [tool.name] }));
      if (failure) { session.dispose(); throw failure; }
      let turns = 0;
      stopAfterTurn(session.agent, () => turns, done => !!failure || done >= 3);
      session.subscribe(event => {
        if (event.type === 'turn_end') turns++;
        if (event.type === 'message_end' && event.message.role === 'assistant' && event.message.stopReason === 'error')
          lastProviderError = event.message.errorMessage;
      });
      await session.prompt('Read the four solid-color quadrants in the attached image. Use report_visual_readiness to report their colors in top-left, top-right, bottom-left, bottom-right order. After receiving the tool result, reply READY and its confirmation_code.',
        { images: [{ type: 'image', data: testImage.png.toString('base64'), mimeType: 'image/png' }], expandPromptTemplates: false });
      if (failure) throw failure;
      if (lastProviderError) throw new Error(lastProviderError);
      if (!reportReceived) throw new CapabilityError('tools_unverified');
      const final = session.messages.filter(message => message.role === 'assistant').at(-1);
      const finalText = (final?.content ?? []).filter(item => item.type === 'text').map(item => item.text).join('\n');
      if (!finalText.includes(confirmation)) throw new CapabilityError('tool_roundtrip');
      return session.getSessionStats().tokens;
    };
    try { return await Promise.race([run(), deadline]); }
    catch (error) {
      const safe = classify(error);
      safe.usage = session?.getSessionStats().tokens;
      throw safe;
    }
    finally {
      clearTimeout(timer); signal?.removeEventListener('abort', onAbort);
      session?.agent.abort(); session?.dispose();
      await rm(directory, { recursive: true, force: true });
    }
  }
}

// A tiny lossless PNG fixture is generated locally. The answer is randomized
// and appears only in image pixels, never in the model's text instructions.
export function visionSample() {
  const colors = [...PALETTE];
  for (let i = colors.length - 1; i > 0; i--) { const j = randomInt(i + 1); [colors[i], colors[j]] = [colors[j], colors[i]]; }
  const selected = colors.slice(0, 4), width = 512, height = 512;
  const pixels = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const rgb = selected[(y >= height / 2 ? 2 : 0) + (x >= width / 2 ? 1 : 0)][1];
    const at = y * (width * 3 + 1) + 1 + x * 3;
    pixels[at] = rgb[0]; pixels[at + 1] = rgb[1]; pixels[at + 2] = rgb[2];
  }
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  return { colors: selected.map(([name]) => name), png: Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), pngChunk('IHDR', header), pngChunk('IDAT', deflateSync(pixels)), pngChunk('IEND', Buffer.alloc(0))]) };
}
function pngChunk(name, data) {
  const type = Buffer.from(name), length = Buffer.alloc(4); length.writeUInt32BE(data.length);
  let crc = 0xffffffff;
  for (const byte of Buffer.concat([type, data])) { crc ^= byte; for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0); }
  const checksum = Buffer.alloc(4); checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([length, type, data, checksum]);
}
