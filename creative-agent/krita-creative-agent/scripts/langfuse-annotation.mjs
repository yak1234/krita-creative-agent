// Sets up artist confirmation in Langfuse (openspec krita-decision-dataset):
//   - score config `artist-verdict` (BOOLEAN): "is this decision's statement true?";
//   - one annotation queue (the Hobby plan allows one) holding single-question decisions:
//     * sampled review checks, as `decide-review-check` traces (canvas, statement, reviewer verdict);
//     * every Luna hard-graphic flag (>= 0.7) plus as many unflagged passes, as
//       `decide-pass-failures` traces (BEFORE/AFTER images, Luna's probability),
//       so misses are measured as well as false alarms.
// Re-runnable: decisions and queue items already sent are skipped.
//   node scripts/langfuse-annotation.mjs [--checks 150] [--luna-since 2026-10-01] [--seed krita] [--dry-run]
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { projectDir } from './project-dir.mjs';
import { connectLangfuse } from '../src/langfuse-tracing.mjs';
import { hardGraphicDecision, reviewCheckDecision, sampleKey } from '../src/decision-records.mjs';
import { BUILD_INFO } from '../src/build-info.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => v.startsWith('--') ? [...a, [v.slice(2), all[i + 1]?.startsWith('--') || all[i + 1] === undefined ? true : all[i + 1]]] : a, []));
const CHECKS = Number(args.checks ?? 150), SEED = String(args.seed ?? 'krita'), DRY = !!args['dry-run'];
const LUNA_SINCE = args['luna-since'] ?? '2026-10-01T00:00:00Z', HARD = 0.7;
const project = projectDir();
const studies = join(project, '.creative-agent', 'studies');
const stateFile = projectId => join(project, '.creative-agent', `annotation-state-${projectId}.json`);

const CONFIGS = {
  'artist-verdict': 'Your verdict: is this decision\'s statement true in the image(s)? Overrides the reviewer and Luna.',
};
const RETIRED_CONFIGS = ['artist-hard-graphic'];
// The Hobby plan allows one queue; the first name is the one already created.
const QUEUE_NAMES = ['Krita · confirm review checks', 'Krita · confirm decisions'];
const QUEUE = { name: QUEUE_NAMES[1], config: 'artist-verdict',
  description: 'One decision per item; read the statement in the input. Review checks show the canvas and the reviewer\'s verdict (output). Hard-graphic items show BEFORE and AFTER and Luna\'s probability. Score artist-verdict True if the statement is true.' };

async function pages(fetchPage) { const out = []; let page = 1; for (;;) { const r = await fetchPage(page); out.push(...r.data); if (page >= (r.meta?.totalPages ?? 1)) return out; page++; } }
const loadJson = async (path, fallback) => { try { return JSON.parse(await readFile(path, 'utf8')); } catch { return fallback; } };

const tracing = await connectLangfuse({ release: BUILD_INFO.build_id, dotEnvPath: join(project, '.env') });
console.log('Langfuse: ' + tracing.describe());
const api = tracing.client.api;
// What was sent is tracked per Langfuse project: trace ids are the same in every project.
const statePath = stateFile(tracing.projectId);
const state = await loadJson(statePath, { decisions: {} });

// 1. Score configs and queues (created once, found by name afterwards).
const configs = await pages(page => api.scoreConfigs.get({ page, limit: 100 }));
const configId = {};
for (const [name, description] of Object.entries(CONFIGS)) {
  const found = configs.find(c => c.name === name && c.dataType === 'BOOLEAN' && !c.isArchived);
  configId[name] = found?.id ?? (DRY ? 'dry-run' : (await api.scoreConfigs.create({ name, dataType: 'BOOLEAN', description })).id);
}
for (const name of RETIRED_CONFIGS) {
  const old = configs.find(c => c.name === name && !c.isArchived);
  if (old && !DRY) await api.scoreConfigs.update(old.id, { isArchived: true });
}
const queues = await pages(page => api.annotationQueues.listQueues({ page, limit: 100 }));
const existing = queues.find(x => QUEUE_NAMES.includes(x.name));
const queueId = existing?.id ?? (DRY ? 'dry-run' : (await api.annotationQueues.createQueue({ name: QUEUE.name, description: QUEUE.description, scoreConfigIds: [configId[QUEUE.config]] })).id);
const inQueue = DRY || queueId === 'dry-run' ? new Set() :
  new Set((await pages(page => api.annotationQueues.listQueueItems(queueId, { page, limit: 100 }))).map(i => i.objectId));
const enqueue = async traceId => { if (DRY || inQueue.has(traceId)) return 0; await api.annotationQueues.createQueueItem(queueId, { objectId: traceId, objectType: 'TRACE' }); inQueue.add(traceId); return 1; };

// 2. Review checks: sample from saved reviews that store each check's text,
// balanced between met and not met, round-robin across paintings.
const candidates = [];
for (const id of await readdir(studies)) {
  const goal = await loadJson(join(studies, id, 'goal.json'), null);
  for (const [reviewIndex, review] of (goal?.reviews ?? []).entries()) {
    if (!review.criteria_text || !review.image) continue;
    for (const check of review.checks ?? []) {
      const statement = review.criteria_text[check.id];
      if (statement) candidates.push({ chatId: id, reviewIndex, review, check, statement, objective: goal.brief?.objective });
    }
  }
}
const byGroup = new Map();
for (const c of candidates.sort((a, b) => sampleKey(SEED, a.chatId + a.reviewIndex + a.check.id).localeCompare(sampleKey(SEED, b.chatId + b.reviewIndex + b.check.id)))) {
  const key = c.chatId + (c.check.met ? ':met' : ':unmet');
  byGroup.set(key, [...(byGroup.get(key) ?? []), c]);
}
// Checks already sent count toward the target: re-runs top up, they never re-sample.
const sentId = c => `${c.chatId}:review-check:${c.reviewIndex}:${c.check.id}`;
const chosen = candidates.filter(c => state.decisions[sentId(c)]);
for (let round = 0; chosen.length < CHECKS && [...byGroup.values()].some(g => g.length > round); round++)
  for (const group of [...byGroup.values()]) if (group[round] && chosen.length < CHECKS && !state.decisions[sentId(group[round])]) chosen.push(group[round]);

let sent = 0, skipped = 0;
for (const c of chosen) {
  const path = resolve(project, c.review.image);
  let image; try { image = 'data:image/png;base64,' + (await readFile(path)).toString('base64'); } catch { skipped++; continue; }
  const decision = reviewCheckDecision({ ...c, imageDataUrl: image });
  const traceId = state.decisions[decision.decision_id] ?? (DRY ? 'dry-run' : await tracing.recordDecision(decision, { sessionId: c.chatId, metadata: { source: 'annotation-sample' } }));
  state.decisions[decision.decision_id] = traceId;
  sent += await enqueue(traceId);
}
if (!DRY) { await tracing.flush(); await writeFile(statePath, JSON.stringify(state, null, 1)); }
const met = chosen.filter(c => c.check.met).length;
console.log(`Review checks: ${candidates.length} candidates from ${new Set(candidates.map(c => c.chatId)).size} paintings; chose ${chosen.length} (${met} met, ${chosen.length - met} not met) across ${new Set(chosen.map(c => c.chatId)).size} paintings; queued ${sent} new; ${skipped} skipped (image missing).`);

// 3. Luna hard-graphic: every flag, plus an equal number of unflagged passes.
const luna = [];
let cursor;
do {
  const r = await api.observations.getMany({ name: 'luna-detect-pass-failures', fromStartTime: LUNA_SINCE, fields: 'core,basic,io', limit: 200, ...(cursor ? { cursor } : {}) });
  luna.push(...r.data); cursor = r.meta?.cursor;
} while (cursor);
const parse = v => typeof v === 'string' ? JSON.parse(v) : v;
const scored = luna.map(o => ({ o, id: o.id, p: parse(o.output)?.hard_graphic?.noul })).filter(x => typeof x.p === 'number' && x.o.sessionId);
const flagged = scored.filter(x => x.p >= HARD);
const unflagged = scored.filter(x => x.p < HARD).sort((a, b) => sampleKey(SEED, a.id).localeCompare(sampleKey(SEED, b.id))).slice(0, flagged.length);
let lunaSent = 0;
for (const x of [...flagged, ...unflagged]) {
  const id = `${x.o.sessionId}:pass-failures:${x.id}:hard_graphic`;
  let traceId = state.decisions[id];
  if (!traceId && !DRY) {
    // Re-attach Luna's own BEFORE/AFTER images; identical bytes are stored once by Langfuse.
    const input = await tracing.client.resolveMediaReferences({ obj: parse(x.o.input), resolveWith: 'base64DataUri' });
    const images = (input.state ?? []).filter(p => p.type === 'image_url').map(p => p.image_url.url);
    if (images.length !== 2) continue;
    traceId = await tracing.recordDecision(hardGraphicDecision({ chatId: x.o.sessionId, observationId: x.id, probability: x.p, images, at: x.o.startTime }),
      { sessionId: x.o.sessionId, metadata: { source: 'annotation-sample', luna_observation_id: x.id } });
    state.decisions[id] = traceId;
  }
  if (traceId) lunaSent += await enqueue(traceId);
}
if (!DRY) { await tracing.flush(); await writeFile(statePath, JSON.stringify(state, null, 1)); }
console.log(`Luna hard-graphic: ${scored.length} pass checks since ${LUNA_SINCE.slice(0, 10)}; ${flagged.length} flagged + ${unflagged.length} unflagged; queued ${lunaSent} new.`);
console.log(DRY ? 'Dry run: nothing was written.' : `Open Langfuse → Annotation queues → "${existing?.name ?? QUEUE.name}": ${inQueue.size} items.`);
await tracing.shutdown();
