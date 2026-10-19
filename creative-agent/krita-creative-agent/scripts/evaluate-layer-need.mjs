// Luna's layer-need choices beside what the painter then did, from every chat's goal.json.
// Agreement is not accuracy (the painter is often wrong, which is the point), but rows where
// they differ are the cases to label before switching routing from Evaluate to Guide.
//   node scripts/evaluate-layer-need.mjs [--json]
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { projectDir } from './project-dir.mjs';

// Accents are plain strokes, so that pair agrees.
const agrees = e => e.painted === e.need || (e.need === 'accents' && e.painted === 'strokes');

export function summarize(entries) {
  const asked = entries.filter(e => e.need);
  const compared = asked.filter(e => e.painted);
  const byNeed = {};
  for (const e of compared) {
    const row = byNeed[e.need] ??= { asked: 0, painter_agreed: 0, painter_did: {} };
    row.asked++; if (agrees(e)) row.painter_agreed++;
    row.painter_did[e.painted] = (row.painter_did[e.painted] ?? 0) + 1;
  }
  return { decisions: entries.length, fallbacks: entries.length - asked.length, compared: compared.length,
    agreement: compared.length ? +(Object.values(byNeed).reduce((s, r) => s + r.painter_agreed, 0) / compared.length).toFixed(2) : null, by_need: byNeed,
    to_label: compared.filter(e => !agrees(e)).slice(-30).map(({ at, area, need, painted, confidence }) => ({ at, area, need, painted, confidence })) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { ProjectStore } = await import('../src/project-store.mjs');
  const { installedDataDirectory } = await import('../src/storage-paths.mjs');
  const store = new ProjectStore({ projectRoot: projectDir(), dataDirectory: await installedDataDirectory() });
  const entries = [];
  for (const { id } of await store.list()) {
    try { entries.push(...(JSON.parse(store.recordText(id)).goal?.layer_needs ?? []).map(e => ({ ...e, study: id }))); }
    catch { /* no goal yet */ }
  }
  store.close();
  const report = summarize(entries);
  console.log(process.argv.includes('--json') ? JSON.stringify(report, null, 2)
    : `${report.decisions} decisions, ${report.fallbacks} fallbacks, ${report.compared} compared, painter agreed ${report.agreement ?? '-'}\n` +
      Object.entries(report.by_need).map(([need, r]) => `  ${need.padEnd(8)} asked ${r.asked}, painter agreed ${r.painter_agreed}, painter did ${JSON.stringify(r.painter_did)}`).join('\n'));
}
