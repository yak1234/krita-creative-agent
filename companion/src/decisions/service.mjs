// Decision endpoints as the artist configured them: custom endpoints, saved keys and
// image-check results in decision-endpoints.json (0600); keys never leave this module
// except as Authorization headers. Model lists are fetched live and cached briefly.
import { readFile, rename, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { BUILT_IN_ENDPOINTS, customEndpoint, resolveEndpoint } from './endpoints.mjs';
import { DecisionClient, checkImages } from './client.mjs';
import { parseDotEnv } from '../langfuse-tracing.mjs';

const MODEL_CACHE_MS = 10 * 60 * 1000;
const ID = /^[a-z0-9][a-z0-9-]{0,39}$/;

export class DecisionService {
  constructor({ stateDirectory, envPath = null, painterKey = async () => null, secrets = [], fetch = globalThis.fetch, env = process.env }) {
    Object.assign(this, { path: join(stateDirectory, 'decision-endpoints.json'), envPath, painterKey, secrets, fetchImpl: fetch, env });
    this.store = { custom: {}, keys: {}, images: {} };
    this.verified = { 'openrouter:openai/gpt-6-luna-decisions': true };   // checked live; no check needed on first use
    this.modelCache = new Map();
  }
  async load() {
    let text = null;
    try { text = await readFile(this.path, 'utf8'); } catch (error) { if (error.code !== 'ENOENT') throw error; /* First use. */ }
    if (text !== null) {
      try { this.store = { custom: {}, keys: {}, images: {}, ...JSON.parse(text) }; }
      catch {
        // Unreadable store: keep it beside the new one so saved endpoints and keys can be recovered by hand.
        this.recoveredFrom = this.path + '.corrupt-' + Date.now();
        await rename(this.path, this.recoveredFrom);
      }
    }
    for (const key of Object.values(this.store.keys)) this.remember(key);
    return this;
  }
  async save() {
    const temporary = this.path + '.' + randomUUID() + '.tmp';
    await writeFile(temporary, JSON.stringify(this.store, null, 2) + '\n', { mode: 0o600 });
    await rename(temporary, this.path);
  }
  // Redacted from any error text. `secrets` is shared with the studio, so it is extended in place.
  remember(key) { if (key && !this.secrets.includes(key)) this.secrets.push(key); return key; }

  async key(endpointId) {
    if (endpointId === 'openrouter') {
      return this.remember((await this.painterKey()) || this.env.OPENROUTER_API_KEY || null);
    }
    if (this.store.keys[endpointId]) return this.store.keys[endpointId];
    const variable = BUILT_IN_ENDPOINTS[endpointId]?.envKey;
    if (!variable) return null;
    let fromFile = null;
    if (this.envPath) try { fromFile = parseDotEnv(await readFile(this.envPath, 'utf8'))[variable] || null; } catch { /* No .env. */ }
    return this.remember(fromFile || this.env[variable] || null);
  }
  endpoint(id) { return resolveEndpoint(id, this.store.custom); }
  async endpoints() {
    const all = [...Object.values(BUILT_IN_ENDPOINTS), ...Object.entries(this.store.custom).map(([id, value]) => customEndpoint({ id, ...value }))];
    return Promise.all(all.map(async e => ({ id: e.id, name: e.name, protocol: e.protocol, url: e.url, custom: !!e.custom,
      key_configured: !!(await this.key(e.id)), key_hint: e.keyHint })));
  }
  // Image support is what the two-image check measured. A declaration is not enough: on OpenRouter,
  // cloudflare/clef and clef-flash declare image input but answer identically for orange and green
  // (checked 2026-10-10). Declared-but-unchecked models report null until checked; text-only stays false.
  imagesFor(endpointId, model, declared) { const key = endpointId + ':' + model; return this.store.images[key] ?? this.verified[key] ?? (declared === false ? false : null); }
  async models(endpointId, { refresh = false } = {}) {
    const cached = this.modelCache.get(endpointId);
    if (cached && !refresh && Date.now() - cached.at < MODEL_CACHE_MS) return cached.models;
    const endpoint = this.endpoint(endpointId);
    const models = (await endpoint.listModels({ fetch: this.fetchImpl, key: await this.key(endpointId) }))
      .map(model => ({ ...model, images: this.imagesFor(endpointId, model.id, model.images) }));
    this.modelCache.set(endpointId, { at: Date.now(), models });
    return models;
  }
  async client({ endpoint: endpointId, model }, options = {}) {
    const endpoint = this.endpoint(endpointId);
    const listed = this.modelCache.get(endpointId)?.models ?? await this.models(endpointId).catch(() => []);
    const declared = listed.find(m => m.id === model)?.images;
    return new DecisionClient({ endpoint, model, apiKey: await this.key(endpointId), fetch: this.fetchImpl,
      images: this.imagesFor(endpointId, model, declared), ...options });
  }
  async checkImages(selection) {
    const result = await checkImages(await this.client(selection));
    if (result.images !== null) {
      this.store.images[selection.endpoint + ':' + selection.model] = result.images;
      this.modelCache.delete(selection.endpoint); await this.save();
    }
    return result;
  }
  async saveKey(endpointId, key) {
    this.endpoint(endpointId);
    if (endpointId === 'openrouter') throw new Error('OpenRouter decisions use the painter’s OpenRouter connection.');
    if (key) this.store.keys[endpointId] = this.remember(String(key).trim()); else delete this.store.keys[endpointId];
    this.modelCache.delete(endpointId); await this.save();
  }
  async addEndpoint({ id, name, url, key, default_model: defaultModel }) {
    if (!ID.test(id ?? '') || BUILT_IN_ENDPOINTS[id]) throw new Error('Use a short lowercase id (letters, digits, dashes) that is not a built-in endpoint.');
    customEndpoint({ id, name, url, defaultModel });            // validates the URL
    this.store.custom[id] = { name: name || id, url, ...(defaultModel ? { defaultModel } : {}) };
    if (key) this.store.keys[id] = this.remember(String(key).trim());
    await this.save();
  }
  async removeEndpoint(id) {
    delete this.store.custom[id]; delete this.store.keys[id];
    for (const k of Object.keys(this.store.images)) if (k.startsWith(id + ':')) delete this.store.images[k];
    this.modelCache.delete(id); await this.save();
  }
}
