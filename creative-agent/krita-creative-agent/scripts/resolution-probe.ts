// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The resolution probe, run for real (openspec luna-goal-reviewer goal 3; src/resolution-probe.ts draws and scores). For
// each model: one request a probed size (the whole picture at 1024, 1536, 2048 and 2560 px on the long side) and one with
// the five boxes as 1:1 crops, ten known answers each, so five requests a model. Prints accuracy, latency, tokens and cost
// per request and the sides recommendSides gives; with --record-to, merges {view_side, crop_side, ...} by model into that
// JSON (the shipped src/model-resolutions.json, or the artist's data folder resolution-probe.json, view-size.ts).
//   node scripts/resolution-probe.ts --luna                                   the decision model (Decision checks' choice)
//   node scripts/resolution-probe.ts --painter deepseek/deepseek-flash        a painter model, through Pi's own connection
//   node scripts/resolution-probe.ts --luna --record-to src/model-resolutions.json
// Keys: Luna through OPENROUTER_API_KEY or the painter's OpenRouter key in Pi; a painter through Pi's auth, as the app.
// Keys are never printed; a failed request reports its fallback reason or a classified error only.
import { parseArgs } from 'node:util';
import { mkdtemp, readFile, rm, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { probeImage, probeCrops, probeQuestions, scoreProbe, recommendSides, PROBE_SIZES, type ProbeQuestion, type Score } from '../src/resolution-probe.ts';
import { encodeRgba } from '../src/shapes/png.ts';
import { DecisionClient } from '../src/decisions/client.ts';
import { BUILT_IN_ENDPOINTS } from '../src/decisions/endpoints.ts';
import { modelKey } from '../src/view-size.ts';
import type { DecisionPart, Questions } from '../src/decisions/types.ts';

type Image = { label: string; png: Buffer };
type Asked = { answers: Record<string, string | null>; ms: number; cost: number; input_tokens: number; error?: string };
type Reader = { key: string; ask(images: Image[], questions: ProbeQuestion[]): Promise<Asked> };

const { values } = parseArgs({ options: { luna: { type: 'boolean' }, 'luna-model': { type: 'string' }, painter: { type: 'string' },
  seed: { type: 'string' }, 'record-to': { type: 'string' }, timeout: { type: 'string' } } });
const TIMEOUT = Number(values.timeout ?? 90000);

/** Luna (the decision model): one choice question an answer, all in one decision. */
function lunaReader(apiKey: string, model: string): Reader {
  const client = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, model, apiKey, images: true, timeout: TIMEOUT });
  return {
    key: modelKey('openrouter', model),
    async ask(images, questions) {
      const parts: DecisionPart[] = images.flatMap(i => [i.label, { data: i.png.toString('base64'), mimeType: 'image/png' }]);
      const asked: Questions = Object.fromEntries(questions.map(q => [q.id, { type: 'choice' as const, instructions: q.text,
        criteria: Object.fromEntries(q.options.map(o => [o, q.id.endsWith('_digit') ? `The digit ${o}.` : `${o} dots.`])) }]));
      const result = await client.decide({ purpose: 'resolution-probe', parts, questions: asked });
      if (result.fallback) return { answers: {}, ms: result.elapsed_ms, cost: 0, input_tokens: 0, error: result.fallback };
      const answers = Object.fromEntries(questions.map(q => { const a = result.answers[q.id]; return [q.id, a?.type === 'choice' ? String(a.choice) : null]; }));
      return { answers, ms: result.elapsed_ms, cost: result.usage.cost, input_tokens: result.usage.input_tokens };
    },
  };
}

/** A painter model through Pi, as the app connects it: the questions in text, a JSON object back. */
async function painterReader(route: string, scratch: string): Promise<Reader> {
  const slash = route.indexOf('/');
  if (slash < 1) throw new Error('Give the painter as provider/model, e.g. deepseek/deepseek-flash.');
  const provider = route.slice(0, slash), id = route.slice(slash + 1);
  const { ModelRuntime, getAgentDir } = await import('@earendil-works/pi-coding-agent');
  // @ts-ignore: an .mjs module (allowJs is off in the strict project)
  const { inheritPiCatalog } = await import('../src/model-catalog.mjs');
  const pi = getAgentDir();
  const models = await ModelRuntime.create({ allowModelNetwork: false, authPath: join(pi, 'auth.json'), modelsPath: join(pi, 'models.json'),
    modelsStorePath: await inheritPiCatalog(pi, scratch), signal: AbortSignal.timeout(15000) });
  const model = models.getModel(provider, id);
  if (!model) throw new Error(`Pi has no model ${route}.`);
  if (!model.input.includes('image')) throw new Error(`${route} does not read images.`);
  return {
    key: modelKey(provider, id),
    async ask(images, questions) {
      const started = Date.now();
      const text = 'Answer each question about the image(s) by reading them closely. Reply with only a JSON object mapping each id to its answer as a string.\n'
        + questions.map(q => `${q.id}: ${q.text} (one of ${q.options.join(', ')})`).join('\n');
      try {
        const reply = await models.completeSimple(model, { messages: [{ role: 'user', timestamp: Date.now(), content: [
          ...images.flatMap(i => [{ type: 'text' as const, text: i.label }, { type: 'image' as const, data: i.png.toString('base64'), mimeType: 'image/png' }]),
          { type: 'text' as const, text }] }] }, { signal: AbortSignal.timeout(TIMEOUT) });
        const said = reply.content.filter(c => c.type === 'text').map(c => (c as { text: string }).text).join('');
        const json = said.match(/\{[\s\S]*\}/)?.[0];
        const parsed = json ? JSON.parse(json) as Record<string, unknown> : {};
        const answers = Object.fromEntries(questions.map(q => [q.id, parsed[q.id] === undefined || parsed[q.id] === null ? null : String(parsed[q.id]).trim()]));
        return { answers, ms: Date.now() - started, cost: reply.usage?.cost?.total ?? 0, input_tokens: reply.usage?.input ?? 0,
          ...(reply.stopReason === 'error' ? { error: 'provider_error' } : {}) };
      } catch (error) {
        return { answers: {}, ms: Date.now() - started, cost: 0, input_tokens: 0, error: (error as Error)?.name === 'TimeoutError' ? 'timeout' : 'request_failed' };
      }
    },
  };
}

async function probe(reader: Reader, seed: number) {
  const sizes: Record<number, Score & { ms: number; cost: number; input_tokens: number; error?: string }> = {};
  for (const size of PROBE_SIZES) {
    const p = probeImage({ width: size, height: Math.round(size * 3 / 4), seed: seed + size });
    const questions = probeQuestions(p.boxes);
    const asked = await reader.ask([{ label: `IMAGE (${size} x ${Math.round(size * 3 / 4)} px):`, png: encodeRgba(p.image) }], questions);
    sizes[size] = { ...scoreProbe(questions, asked.answers), ms: asked.ms, cost: asked.cost, input_tokens: asked.input_tokens, ...(asked.error ? { error: asked.error } : {}) };
    process.stderr.write(`${reader.key} ${size}px: ${sizes[size].correct}/${sizes[size].total} in ${asked.ms} ms, $${asked.cost.toFixed(5)}, ${asked.input_tokens} input tokens${asked.error ? ' (' + asked.error + ')' : ''}\n`);
  }
  const p = probeImage({ width: 2560, height: 1920, seed: seed + 1 }), crops = probeCrops(p), questions = probeQuestions(p.boxes, { crops: true });
  const asked = await reader.ask(crops.map((c, i) => ({ label: `CROP ${i + 1}:`, png: encodeRgba(c.image) })), questions);
  const cropScore = { ...scoreProbe(questions, asked.answers), ms: asked.ms, cost: asked.cost, input_tokens: asked.input_tokens, ...(asked.error ? { error: asked.error } : {}) };
  process.stderr.write(`${reader.key} 1:1 crops: ${cropScore.correct}/${cropScore.total} in ${asked.ms} ms, $${asked.cost.toFixed(5)}${asked.error ? ' (' + asked.error + ')' : ''}\n`);
  const sides = recommendSides({ crops: cropScore, sizes });
  return { key: reader.key, measured_at: new Date().toISOString(), seed, sizes, crops: cropScore, ...(sides ?? { unreadable: true }) };
}

async function openRouterKey(scratch: string): Promise<string | null> {
  if (process.env.OPENROUTER_API_KEY) return process.env.OPENROUTER_API_KEY;
  const { ModelRuntime, getAgentDir } = await import('@earendil-works/pi-coding-agent');
  // @ts-ignore: an .mjs module
  const { inheritPiCatalog } = await import('../src/model-catalog.mjs');
  const pi = getAgentDir();
  const models = await ModelRuntime.create({ allowModelNetwork: false, authPath: join(pi, 'auth.json'), modelsPath: join(pi, 'models.json'),
    modelsStorePath: await inheritPiCatalog(pi, scratch), signal: AbortSignal.timeout(15000) });
  const auth = await models.getAuth('openrouter') as { auth?: { apiKey?: string } } | undefined;
  return auth?.auth?.apiKey ?? null;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  if (!values.luna && !values.painter) { process.stderr.write('Give --luna and/or --painter provider/model.\n'); process.exit(2); }
  const scratch = await mkdtemp(join(tmpdir(), 'resolution-probe-'));
  try {
    const seed = Number(values.seed ?? 20261024), results = [];
    if (values.luna) {
      const key = await openRouterKey(scratch);
      if (!key) { process.stderr.write('No OpenRouter key: connect OpenRouter in the app or set OPENROUTER_API_KEY.\n'); process.exit(2); }
      results.push(await probe(lunaReader(key, values['luna-model'] ?? BUILT_IN_ENDPOINTS.openrouter.defaultModel), seed));
    }
    if (values.painter) results.push(await probe(await painterReader(values.painter, scratch), seed));
    process.stdout.write(JSON.stringify(results, null, 2) + '\n');
    if (values['record-to']) {
      const path = values['record-to'];
      let records: Record<string, unknown> = {};
      try { records = JSON.parse(await readFile(path, 'utf8')); } catch { /* a new file */ }
      for (const r of results) if (!('unreadable' in r)) records[r.key] = { view_side: r.view_side, crop_side: r.crop_side, reads: r.reads, measured_at: r.measured_at };
      await writeFile(path + '.tmp', JSON.stringify(records, null, 2) + '\n'); await rename(path + '.tmp', path);
      process.stderr.write(`Recorded in ${path}.\n`);
    }
  } finally { await rm(scratch, { recursive: true, force: true }); }
}
