// Canvas previews: the plugin writes a 1024-px view (JPEG, PNG for crops) to <chat>/.previews for every
// observation, so each painting action leaves a before and an after picture. They are scratch: the
// picture the model saw is already in the chat database (phase B), and pass review needs them only
// while the chat is open. Once a chat is closed, only what its record points to (the chat-list
// thumbnail, review images) and the two newest views (a replayed result's image) are kept; pass
// review then shows "No snapshot" for its passes. Storage-layout phase D.
import { readFile, readdir, rm, stat, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { readRows } from './db.mjs';

const VIEW = /view-[0-9a-f]{32}\.(?:png|jpg)/g;
const RECORDS = ['study.json', 'goal.json', 'record.json', 'resume.json'];
const FOLDERS = ['reviews', 'recipes', 'reference-paintings'];

const text = path => readFile(path, 'utf8').catch(() => '');
const names = value => new Set(value.match(VIEW) ?? []);

/** Delete previews nothing still needs. Returns {kept, removed, bytes}; dryRun only counts. */
export async function prunePreviews(directory, { keepPasses = 0, keepRecent = 2, dryRun = false, extraText = '' } = {}) {
  const folder = join(directory, '.previews');
  let files;
  try { files = (await readdir(folder)).filter(name => /^view-[0-9a-f]{32}\.(?:png|jpg)$/.test(name)); }
  catch { return { kept: 0, removed: 0, bytes: 0 }; }
  const keep = new Set(names(extraText));            // the chat's record, which now lives in SQLite
  for (const name of RECORDS) for (const view of names(await text(join(directory, name)))) keep.add(view);
  for (const sub of FOLDERS) {
    const entries = await readdir(join(directory, sub)).catch(() => []);
    for (const entry of entries) if (!entry.endsWith('.plan.json'))
      for (const view of names(await text(join(directory, sub, entry)))) keep.add(view);
  }
  // The plugin's pass history: its journal database (phase C), or .passes.json in older chats.
  let passes = readRows(join(directory, 'journal.sqlite'), 'SELECT entry FROM passes ORDER BY seq').map(row => JSON.parse(row.entry));
  if (!passes.length) try { passes = JSON.parse(await text(join(directory, '.passes.json')) || '[]'); } catch {}
  for (const entry of keepPasses > 0 ? passes.slice(-keepPasses) : [])      // slice(-0) would keep them all
    for (const view of names(JSON.stringify([entry.before_path, entry.after_path]))) keep.add(view);
  const sized = await Promise.all(files.map(async name => {
    try { const info = await stat(join(folder, name)); return { name, size: info.size, time: info.mtimeMs }; }
    catch { return null; }
  }));
  const present = sized.filter(Boolean).sort((a, b) => b.time - a.time);
  for (const file of present.slice(0, keepRecent)) keep.add(file.name);
  let removed = 0, bytes = 0;
  for (const file of present) {
    if (keep.has(file.name)) continue;
    if (!dryRun) { try { await unlink(join(folder, file.name)); } catch { continue; } }
    removed++; bytes += file.size;
  }
  return { kept: present.length - removed, removed, bytes };
}

/** Delete what a chat can rebuild: stored reference stroke plans (rebuilt and hash-checked on
 *  resume since 2026-10-12; 25-37 MB a job) and the reduced reference copies sent to models. */
export async function removeRebuildable(directory, { dryRun = false, files = [] } = {}) {
  let removed = 0, bytes = 0;
  // Files the records database recreates when the chat opens (its stored references).
  for (const path of files) {
    try { const { size } = await stat(path); if (!dryRun) await unlink(path); removed++; bytes += size; } catch {}
  }
  const plans = join(directory, 'reference-paintings');
  for (const name of await readdir(plans).catch(() => [])) {
    if (!name.endsWith('.plan.json')) continue;
    try { const { size } = await stat(join(plans, name)); if (!dryRun) await unlink(join(plans, name)); removed++; bytes += size; } catch {}
  }
  const reduced = join(directory, '.model-references');
  for (const name of await readdir(reduced).catch(() => [])) {
    try { bytes += (await stat(join(reduced, name))).size; removed++; } catch {}
  }
  if (!dryRun) await rm(reduced, { recursive: true, force: true });
  return { removed, bytes };
}

/** Prune every study under studiesDirectory except `active`; recordText(id) returns a chat's stored record. */
export async function pruneAllPreviews(studiesDirectory, { active, recordText, rebuildable, ...options } = {}) {
  const totals = { studies: 0, kept: 0, removed: 0, bytes: 0 };
  for (const id of await readdir(studiesDirectory).catch(() => [])) {
    if (id === active) continue;
    const extra = await removeRebuildable(join(studiesDirectory, id), { ...options, files: (await rebuildable?.(id)) ?? [] });
    const result = await prunePreviews(join(studiesDirectory, id), { ...options, extraText: recordText?.(id) ?? '' });
    result.removed += extra.removed; result.bytes += extra.bytes;
    if (!result.kept && !result.removed) continue;
    totals.studies++; totals.kept += result.kept; totals.removed += result.removed; totals.bytes += result.bytes;
  }
  return totals;
}
