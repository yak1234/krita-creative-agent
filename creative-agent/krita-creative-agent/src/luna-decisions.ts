// GPT-6 Luna Decisions on OpenRouter: the default decision model. Kept as a thin
// default over the endpoint-agnostic DecisionClient (src/decisions/).
import { DecisionClient } from './decisions/client.ts';
import { BUILT_IN_ENDPOINTS } from './decisions/endpoints.ts';
import type { DecisionTracing, TraceInfo } from './decisions/types.ts';
export { imagePart } from './decisions/protocols.ts';

export const LUNA_URL = BUILT_IN_ENDPOINTS.openrouter.url;
export const LUNA_MODEL = BUILT_IN_ENDPOINTS.openrouter.defaultModel;

export type LunaClientOptions = { apiKey?: string | null; fetch?: typeof globalThis.fetch; timeout?: number; model?: string; url?: string;
  tracing?: DecisionTracing | null; context?: () => TraceInfo };

export class LunaClient extends DecisionClient {
  constructor({ apiKey, fetch, timeout = 4000, model = LUNA_MODEL, url = LUNA_URL, tracing = null, context }: LunaClientOptions = {}) {
    super({ endpoint: { ...BUILT_IN_ENDPOINTS.openrouter, url }, model, apiKey, fetch, timeout, images: true, tracing, context });
  }
}
