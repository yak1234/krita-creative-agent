// @ts-check
/** Local, serialized HTTP transport to Krita. No Python helper is required. */
import { COMIC_OPERATIONS, CRAFT_OPERATIONS, LONG_OPERATIONS } from './craft.mjs';

export class PaintingBridge {
  constructor(root, config) { this.root = root; this.config = config; }
  async connect() {
    this.url = new URL(this.config.bridge_url || 'http://127.0.0.1:5678');
    if (this.url.protocol !== 'http:' || !['127.0.0.1','localhost','[::1]'].includes(this.url.hostname) || this.url.username || this.url.password)
      throw new Error('The painting bridge must run locally on this Mac.');
  }
  async call(operation, params = {}, sessionId, operationId) {
    if (!this.url) await this.connect();
    const request = { operation, params };
    if (sessionId) request.session_id = sessionId;
    if (operationId) request.operation_id = operationId;
    const mutating = ['begin','paint_pass','adjust_layer','painting_toolbox','review_pass','merge_passes','finish',...CRAFT_OPERATIONS,...COMIC_OPERATIONS].includes(operation);
    // Filters can run long on a large canvas; past this the outcome is uncertain, never retried.
    const timeout = LONG_OPERATIONS.includes(operation) ? 300 : 120;
    let result;
    try {
      const token = process.env.KRITA_MCP_TOKEN;
      const response = await fetch(this.url, { method:'POST', redirect:'error',
        headers:{'Content-Type':'application/json', ...(token ? {Authorization:'Bearer '+token}: {})},
        body:JSON.stringify({action:'creative', params:request, timeout}), signal:AbortSignal.timeout((timeout+20)*1000) });
      result = await response.json();
      if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid painting bridge response.');
      // Krita returns its structured command errors with HTTP 500. Those are
      // delivered results, not a transport loss. Preserve their recovery code.
      if (!response.ok && !result.error) throw new Error('Painting bridge returned HTTP '+response.status);
    } catch (cause) {
      const error = /** @type {Error & {code?: string, result?: any}} */ (new Error(mutating ? 'Lost the painting operation result. Inspect the canvas before continuing; the operation will not be repeated.' : 'Could not reach Krita. Open Krita and reconnect the assistant.', { cause }));
      error.code = mutating ? 'outcome_unknown' : 'unavailable';
      throw error;
    }
    if (result.error) {
      const error = /** @type {Error & {code?: string, result?: any}} */ (new Error(result.error));
      error.code = result.error_code || (String(result.error).includes('Timeout waiting for command') ? (mutating ? 'outcome_unknown':'capture_failed') : undefined);
      if (error.code === 'internal' && String(result.error).startsWith('ValueError:')) error.code = 'validation_rejected';
      else if (mutating && ['internal','timeout'].includes(error.code)) error.code = 'outcome_unknown';
      error.result = result; throw error;
    }
    return result;
  }
  async close() {}
}
