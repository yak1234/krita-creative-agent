// One client for every decision endpoint. decide() returns
//   {answers, model, elapsed_ms, usage}  or  {fallback: reason, elapsed_ms}
// with answers keyed by question name in System One form, whatever the protocol.
// Response bodies are never returned or logged: upstream errors can echo key fragments.
import { PROTOCOLS, hasImages } from './protocols.mjs';
import { BUILT_IN_ENDPOINTS } from './endpoints.mjs';
import { deflateSync } from 'node:zlib';

export class DecisionClient {
  constructor({ endpoint = BUILT_IN_ENDPOINTS.openrouter, model, apiKey, fetch = globalThis.fetch, timeout = 4000,
    images = undefined, tracing = null, context = () => ({}) } = {}) {
    const protocol = PROTOCOLS[endpoint.protocol];
    if (!protocol) throw new Error('Unknown decision protocol: ' + endpoint.protocol);
    Object.assign(this, { endpoint, protocol, model: model ?? endpoint.defaultModel, apiKey, fetchImpl: fetch, timeout, tracing, context,
      // Whether the selected model reads images: declared by the endpoint, or proven by checkImages().
      images: images ?? null });
  }
  get connected() { return !!this.apiKey || !!this.endpoint.custom; }
  get url() { return this.endpoint.url; }
  async decide(request) {
    if (!this.tracing || !this.connected) return this.request(request);
    const { parts = [], questions, purpose = 'decide' } = request, info = this.context();
    const model = this.endpoint.id + ':' + this.model;
    return this.tracing.observeGeneration('decision-' + purpose, { model, sessionId: info.sessionId, tags: ['decision', this.endpoint.id, ...(info.tags ?? [])],
      input: { state: parts.map(p => typeof p === 'string' && !p.startsWith('data:') ? p : { type: 'image_url', image_url: { url: typeof p === 'string' ? p : `data:${p.mimeType};base64,${p.data}` } }), questions },
      metadata: { purpose, endpoint: this.endpoint.id, question_ids: Object.keys(questions ?? {}) } },
      () => this.request(request),
      result => ({ output: result.answers ?? { fallback: result.fallback },
        usageDetails: result.usage && { input: result.usage.input_tokens, output: result.usage.output_tokens },
        costDetails: result.usage && { total: result.usage.cost }, metadata: { elapsed_ms: result.elapsed_ms },
        ...(result.fallback ? { level: 'WARNING', statusMessage: result.fallback } : {}) }));
  }
  async request({ parts, questions, signal }) {
    const started = Date.now(), elapsed = () => Date.now() - started;
    if (!this.connected) return { fallback: 'not_connected', elapsed_ms: 0 };
    // Visual decisions go only to a model known to read images (the image check itself excepted).
    if (hasImages(parts) && this.images !== true && !this.checkingImages)
      return { fallback: this.images === false ? 'text_only_model' : 'images_unverified', elapsed_ms: 0 };
    const deadline = AbortSignal.timeout(this.timeout), combined = signal ? AbortSignal.any([signal, deadline]) : deadline;
    try {
      combined.throwIfAborted();
      const response = await this.fetchImpl(this.endpoint.url, { method: 'POST', signal: combined,
        headers: { ...(this.apiKey ? { Authorization: 'Bearer ' + this.apiKey } : {}), 'Content-Type': 'application/json' },
        body: JSON.stringify(this.protocol.body({ model: this.model, parts, questions })) });
      const text = await response.text();
      combined.throwIfAborted();
      if (response.status === 502 && /refused to answer question/i.test(text)) return { fallback: 'refused', status: 502, elapsed_ms: elapsed() };
      if (!response.ok) return { fallback: 'service_or_response_error', status: response.status, elapsed_ms: elapsed() };
      const body = JSON.parse(text);
      const answers = this.protocol.answers(body);
      if (!answers) return { fallback: 'service_or_response_error', elapsed_ms: elapsed() };
      if (Object.values(answers).some(answer => answer?.type === 'refusal')) return { fallback: 'refused', elapsed_ms: elapsed() };
      const usage = body.usage ?? {};
      return { answers, model: String(body.model ?? body.metadata?.model ?? this.model), elapsed_ms: elapsed(),
        usage: { input_tokens: Number(usage.input_tokens) || 0, output_tokens: Number(usage.output_tokens) || 0, cost: Number(usage.cost) || 0 } };
    } catch {
      return { fallback: signal?.aborted ? 'cancelled' : deadline.aborted ? 'timeout' : 'service_or_response_error', elapsed_ms: elapsed() };
    }
  }
}

// Does this model actually read images? Two images differing only in colour must change the answer.
export function solidPng([r, g, b], size = 64) {
  const crc = buffer => { let c = ~0; for (const byte of buffer) { c ^= byte; for (let k = 0; k < 8; k++) c = c >>> 1 ^ (0xEDB88320 & -(c & 1)); } return ~c >>> 0; };
  const chunk = (type, data) => { const length = Buffer.alloc(4); length.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body)); return Buffer.concat([length, body, sum]); };
  const header = Buffer.alloc(13); header.writeUInt32BE(size, 0); header.writeUInt32BE(size, 4); header[8] = 8; header[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(size * 3).map((_, i) => [r, g, b][i % 3])]);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header),
    chunk('IDAT', deflateSync(Buffer.concat(Array(size).fill(row)))), chunk('IEND', Buffer.alloc(0))]).toString('base64');
}
const SOLID = { orange: solidPng([245, 130, 20]), green: solidPng([30, 160, 60]) };
export async function checkImages(client) {
  const question = { orange: { type: 'noul', instructions: 'Is this image filled with an orange colour?', criteria: { true: 'The image is orange.', false: 'The image is not orange.' } } };
  const ask = data => client.request({ parts: ['IMAGE:', { data, mimeType: 'image/png' }], questions: question });
  client.checkingImages = true;   // the check itself must send the images
  try {
    const [orange, green] = await Promise.all([ask(SOLID.orange), ask(SOLID.green)]);
    if (orange.fallback || green.fallback) return { images: null, reason: orange.fallback ?? green.fallback };
    const delta = (orange.answers.orange?.noul ?? 0) - (green.answers.orange?.noul ?? 0);
    return { images: delta > 0.5, delta };
  } finally { client.checkingImages = false; }
}
