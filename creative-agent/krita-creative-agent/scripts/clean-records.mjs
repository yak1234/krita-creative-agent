#!/usr/bin/env node
// Free disk space in a project's agent records: old canvas previews, stored reference stroke plans
// and reduced reference copies. Everything removed is rebuilt when needed. Chats, plans, history and
// attached references are kept. The companion runs the same cleanup at start.
//   node scripts/clean-records.mjs <project folder> [--dry-run]
import { pruneAllPreviews } from '../src/previews.mjs';
import { ProjectStore } from '../src/project-store.mjs';
import { installedDataDirectory } from '../src/storage-paths.mjs';

const [project, flag] = process.argv.slice(2);
if (!project) { console.error('Usage: clean-records.mjs <project folder> [--dry-run]'); process.exit(2); }
// A painting session reads its newest previews and job files: never clean underneath it.
try {
  const response = await fetch('http://127.0.0.1:5678', { method: 'POST', body: JSON.stringify({ action: 'creative', params: { operation: 'health', params: {} } }), signal: AbortSignal.timeout(5000) });
  const data = await response.json(), health = data.result ?? data;
  if (health?.session_active) { console.error('Krita is painting. Run this when no chat is painting.'); process.exit(1); }
} catch {}                                   // Krita not running: nothing can be painting
const store = new ProjectStore({ projectRoot: project, dataDirectory: await installedDataDirectory() });
await store.initialize();
const totals = await pruneAllPreviews(store.chatsDirectory, { dryRun: flag === '--dry-run', recordText: id => store.recordText(id), rebuildable: id => store.removableFiles(id) });
store.close();
console.log((flag === '--dry-run' ? 'Would remove ' : 'Removed ') + totals.removed + ' files (' + (totals.bytes / 1e9).toFixed(2) + ' GB) from ' + totals.studies + ' chats.');
