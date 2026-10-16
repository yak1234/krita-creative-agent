// Calibrate Luna's artifact check on real painting calls labelled by hand (luna-artifact-labels.json:
// Langfuse before/after pairs, the failure types each AFTER really introduced, and whether BEFORE was
// still a block-in or a flat graphic picture). Asks the shipped questions (src/visual-checks.mjs) live and reports, per type and
// threshold, how many flags were real (precision) and how many real artifacts were flagged (recall),
// plus the stage answer and the automatic-undo rule. About $0.001 per pair.
//   node scripts/calibrate-luna-artifacts.mjs             evaluate against the labels
//   node scripts/calibrate-luna-artifacts.mjs --upload    also upsert the labels as the Langfuse dataset
//   node scripts/calibrate-luna-artifacts.mjs --json      machine-readable report
// Keys: Langfuse from the project's .env; Luna through the painter's OpenRouter key (Pi) or OPENROUTER_API_KEY.
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { projectDir } from './project-dir.mjs';
import { langfuseCredentials } from '../src/langfuse-tracing.mjs';
import { QUESTIONS, artifactQuestions, artifactAnswers, artifactFindings } from '../src/visual-checks.mjs';
import { DecisionClient } from '../src/decisions/client.mjs';
import { BUILT_IN_ENDPOINTS } from '../src/decisions/endpoints.mjs';

export const DATASET = 'luna-pass-artifacts';
const THRESHOLDS = [0.5, 0.7, 0.9];
const SEVERE = Object.keys(QUESTIONS.pass.failures).filter(id => QUESTIONS.pass.failures[id].severe);

/** Precision/recall rows from per-pair predictions {probabilities, established} beside the labels. */
export function score(rows) {
  const pr = (pairs) => {
    const tp = pairs.filter(([p, t]) => p && t).length, fp = pairs.filter(([p, t]) => p && !t).length, fn = pairs.filter(([p, t]) => !p && t).length;
    return { flagged: tp + fp, real: tp + fn, precision: tp + fp ? +(tp / (tp + fp)).toFixed(2) : null, recall: tp + fn ? +(tp / (tp + fn)).toFixed(2) : null, false_flags: fp, missed: fn };
  };
  const types = {};
  for (const id of Object.keys(QUESTIONS.pass.failures))
    types[id] = Object.fromEntries(THRESHOLDS.map(t => [t, pr(rows.map(r => [r.answer.probabilities[id] >= t, r.label.artifacts[id]]))]));
  // Labelled block-in = not established; the question asks the opposite way round.
  const blockin = pr(rows.map(r => [r.answer.established < QUESTIONS.pass.established.threshold, r.label.blockin]));
  // Ordinary passes (no reference-only types) with the block-in rule, as the painter is told.
  const ordinary = r => artifactFindings({ ...r.answer, probabilities: Object.fromEntries(Object.entries(r.answer.probabilities).filter(([id]) => !QUESTIONS.pass.failures[id].reference_only)) });
  const reported = pr(rows.flatMap(r => { const found = new Set(ordinary(r).map(f => f.type)); return Object.keys(r.label.artifacts).filter(id => !QUESTIONS.pass.failures[id].reference_only).map(id => [found.has(id), r.label.artifacts[id]]); }));
  const undo = pr(rows.map(r => [ordinary(r).some(f => f.severe), r.label.undo]));
  const wrongUndos = rows.filter(r => ordinary(r).some(f => f.severe) && !r.label.undo).map(r => ({ observation_id: r.label.observation_id, note: r.label.note }));
  return { pairs: rows.length, types, blockin, reported, undo, wrong_undos: wrongUndos, severe_types: SEVERE };
}

async function langfuse() {
  const c = await langfuseCredentials(process.env, async () => null, join(projectDir(), '.env'));
  if (!c) throw new Error('No Langfuse keys in the project .env.');
  const base = (c.LANGFUSE_BASE_URL || 'https://cloud.langfuse.com').replace(/\/$/, '');
  const auth = 'Basic ' + Buffer.from(c.LANGFUSE_PUBLIC_KEY + ':' + c.LANGFUSE_SECRET_KEY).toString('base64');
  return async (path, init = {}) => {
    const response = await fetch(base + path, { ...init, headers: { Authorization: auth, 'Content-Type': 'application/json', ...init.headers } });
    if (!response.ok) throw new Error(`Langfuse ${init.method ?? 'GET'} ${path.split('?')[0]}: HTTP ${response.status}`);
    return response.json();
  };
}

async function upload(api, labels) {
  await api('/api/public/v2/datasets', { method: 'POST', body: JSON.stringify({ name: DATASET,
    description: 'Real painting calls (Luna detect-pass-failures inputs) labelled by eye: which failure types AFTER introduced, and whether BEFORE was a block-in.',
    metadata: { labels_version: labels.version, meaning: labels.meaning } }) });
  for (const item of labels.items)
    await api('/api/public/dataset-items', { method: 'POST', body: JSON.stringify({ datasetName: DATASET, id: 'luna-artifact-' + item.observation_id,
      sourceObservationId: item.observation_id,
      input: { before_media_id: item.before_media_id, after_media_id: item.after_media_id, session_id: item.session_id },
      expectedOutput: { artifacts: item.artifacts, blockin: item.blockin, undo: item.undo },
      metadata: { note: item.note, luna_flag_at_the_time: item.luna_flag, labelled_by: labels.labelled_by, labelled_at: labels.labelled_at } }) });
}

async function image(api, id) {
  const { url, contentType } = await api('/api/public/media/' + id);
  const response = await fetch(url);
  if (!response.ok) throw new Error('Media download: HTTP ' + response.status);
  return { type: 'image', mimeType: contentType || 'image/jpeg', data: Buffer.from(await response.arrayBuffer()).toString('base64') };
}

// The painter's OpenRouter key, as the app reads it (Pi's auth), else OPENROUTER_API_KEY.
async function lunaKey() {
  if (process.env.OPENROUTER_API_KEY) return process.env.OPENROUTER_API_KEY;
  const { ModelRuntime, getAgentDir } = await import('@earendil-works/pi-coding-agent');
  const { inheritPiCatalog } = await import('../src/model-catalog.mjs');
  const scratch = await mkdtemp(join(tmpdir(), 'luna-calibration-'));
  try {
    const pi = getAgentDir();
    const models = await ModelRuntime.create({ allowModelNetwork: false, authPath: join(pi, 'auth.json'), modelsPath: join(pi, 'models.json'),
      modelsStorePath: await inheritPiCatalog(pi, scratch), signal: AbortSignal.timeout(15000) });
    return (await models.getAuth('openrouter'))?.auth?.apiKey ?? null;
  } finally { await rm(scratch, { recursive: true, force: true }); }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const labels = JSON.parse(await readFile(new URL('./luna-artifact-labels.json', import.meta.url), 'utf8'));
  const api = await langfuse();
  if (process.argv.includes('--upload')) { await upload(api, labels); console.error(`Uploaded ${labels.items.length} items to the Langfuse dataset "${DATASET}".`); }
  const apiKey = await lunaKey();
  if (!apiKey) { console.error('No OpenRouter key: connect OpenRouter in the app or set OPENROUTER_API_KEY.'); process.exit(2); }
  const client = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, apiKey, images: true, timeout: 30000 });
  const rows = [], failed = [];
  let cost = 0;
  for (const label of labels.items) {
    const [before, after] = await Promise.all([label.before_media_id, label.after_media_id].map(id => image(api, id)));
    // Every type, so reference-only ones are measured too; ordinary passes drop them when scored.
    const result = await client.decide({ purpose: 'calibrate-artifacts', questions: artifactQuestions({ reference: true }),
      parts: ['BEFORE (canvas before this paint pass):', before, 'AFTER (canvas after this paint pass):', after] });
    const answer = result.fallback ? null : artifactAnswers(result.answers, { reference: true });
    if (!answer) { failed.push({ observation_id: label.observation_id, reason: result.fallback ?? 'malformed' }); continue; }
    cost += result.usage?.cost ?? 0;
    rows.push({ label, answer });
  }
  const report = { ...score(rows), failed, cost: +cost.toFixed(4), model: client.model };
  if (process.argv.includes('--json')) console.log(JSON.stringify(report, null, 1));
  else {
    const cell = r => `${r.precision ?? '-'}/${r.recall ?? '-'} (${r.flagged} flagged, ${r.real} real)`;
    console.log(`${report.pairs} pairs, ${failed.length} failed, $${report.cost}, ${report.model}\nprecision/recall per type at ${THRESHOLDS.join(' | ')}:`);
    for (const [id, byThreshold] of Object.entries(report.types)) console.log(`  ${id.padEnd(13)} ` + THRESHOLDS.map(t => cell(byThreshold[t])).join(' | '));
    console.log(`block-in (not established): ${cell(report.blockin)}\nreported to the painter (ordinary pass): ${cell(report.reported)}\nautomatic undo: ${cell(report.undo)}`);
    for (const w of report.wrong_undos) console.log(`  wrong undo ${w.observation_id}: ${w.note}`);
  }
}
