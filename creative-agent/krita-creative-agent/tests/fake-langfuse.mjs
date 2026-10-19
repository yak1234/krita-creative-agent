// In-memory Langfuse for tests: the real LangfuseTracing over a recorder, so no
// test sends data to Langfuse.
import { LangfuseTracing } from '../src/langfuse-tracing.mjs';

export function fakeLangfuse() {
  const observations = [], scores = [];
  let current;
  const make = (name, attributes, options) => {
    const parent = observations.find(p => p.context === options?.parentSpanContext) ?? null;
    const context = { id: observations.length };
    const o = { name, attributes: { ...attributes }, options, parent, context, ended: false, trace: current,
      traceId: parent?.traceId ?? 'trace-' + observations.length, id: 'obs-' + observations.length,
      otelSpan: { spanContext: () => context },
      update(a) { Object.assign(this.attributes, a); return this; }, end() { this.ended = true; } };
    observations.push(o); return o;
  };
  return { observations, scores, tracing: { startObservation: make },
    propagateAttributes: (trace, fn) => { current = trace; try { return fn(); } finally { current = undefined; } },
    client: { score: { create: body => scores.push(body) }, flush: async () => {}, shutdown: async () => {} } };
}

export function recordingTracing() {
  const fake = fakeLangfuse();
  const tracing = new LangfuseTracing({ ...fake, processor: { forceFlush: async () => {} }, provider: { shutdown: async () => {} },
    projectId: 'project-test', baseUrl: 'https://langfuse.test', environment: 'test', release: 'test-build' });
  return Object.assign(tracing, { recorded: fake });
}
