// @ts-check
// GPT-6 Luna Decisions on OpenRouter: the default decision model. Kept as a thin
// default over the endpoint-agnostic DecisionClient (src/decisions/).
import { DecisionClient } from './decisions/client.mjs';
import { BUILT_IN_ENDPOINTS } from './decisions/endpoints.mjs';
export { imagePart } from './decisions/protocols.mjs';

export const LUNA_URL = BUILT_IN_ENDPOINTS.openrouter.url;
export const LUNA_MODEL = BUILT_IN_ENDPOINTS.openrouter.defaultModel;

export class LunaClient extends DecisionClient {
  constructor({ apiKey, fetch, timeout = 4000, model = LUNA_MODEL, url = LUNA_URL, tracing = null, context } = /** @type {{apiKey?: string, fetch?: typeof globalThis.fetch, timeout?: number, model?: string, url?: string, tracing?: any, context?: any}} */ ({})) {
    super({ endpoint: { ...BUILT_IN_ENDPOINTS.openrouter, url }, model, apiKey, fetch, timeout, images: true, tracing, context });
  }
}
