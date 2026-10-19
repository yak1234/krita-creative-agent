#!/usr/bin/env node
// Re-encode the chat images stored as PNG (canvas views from before 2026-10-12) as JPEG, as new
// views are saved, then delete the PNGs and shrink the records database. Images with any
// transparency stay PNG; a JPEG that is not smaller is not used. Krita does the encoding, so it
// must be running and idle (no chat painting).
//   node scripts/recode-images.mjs <project folder> [--dry-run]
import { stat } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { ProjectStore } from '../src/project-store.mjs';
import { installedDataDirectory } from '../src/storage-paths.mjs';

const [project, flag] = process.argv.slice(2);
if (!project) { console.error('Usage: recode-images.mjs <project folder> [--dry-run]'); process.exit(2); }
const bridge = async (operation, params) => {
  const response = await fetch('http://127.0.0.1:5678', { method: 'POST', body: JSON.stringify({ action: 'creative', params: { operation, params }, timeout: 60 }) });
  const data = await response.json(), result = data.result ?? data;
  if (result.error) throw new Error(result.error);
  return result;
};
try { if ((await bridge('health', {})).session_active) { console.error('Krita is painting. Run this when no chat is painting.'); process.exit(1); } }
catch (error) { console.error('Krita must be running to encode the images: ' + error.message); process.exit(1); }

const data = process.env.CREATIVE_AGENT_DATA || await installedDataDirectory();   // the env var points it at a copy
const store = new ProjectStore({ projectRoot: project, dataDirectory: data });
await store.initialize();
const file = join(store.stateDirectory, 'records.sqlite');
const size = async () => ((await stat(file)).size + (await stat(file + '-wal').catch(() => ({ size: 0 }))).size) / 1e9;
const candidates = store.sessions.pngImages();
console.log(`${candidates.length} PNG images (${(candidates.reduce((s, c) => s + c.size, 0) / 1e9).toFixed(2)} GB); database ${(await size()).toFixed(2)} GB`);
if (flag === '--dry-run') { store.close(); process.exit(0); }
let done = 0, kept = 0, larger = 0, saved = 0;
const failed = [];
for (const { sha256 } of candidates) {
  try {
    const bytes = store.sessions.imageBytes(sha256);
    if (createHash('sha256').update(bytes).digest('hex') !== sha256) throw new Error('stored bytes do not match their hash');
    const copy = await bridge('jpeg_copy', { image_base64: bytes.toString('base64'), sha256, quality: 90 });
    if (copy.kept) kept++;
    else {
      const jpeg = Buffer.from(copy.image_base64, 'base64');
      if (jpeg.length >= bytes.length) larger++;
      else saved += store.sessions.replaceImage(sha256, jpeg, 'image/jpeg');
    }
  } catch (error) { failed.push({ sha256, error: error.message }); }
  if (++done % 100 === 0 || done === candidates.length) console.log(`${done}/${candidates.length} · ${(saved / 1e9).toFixed(2)} GB saved`);
}
console.log('Freeing the space…');
store.db.exec('PRAGMA wal_checkpoint(TRUNCATE)'); store.db.exec('VACUUM'); store.db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
console.log(`Re-encoded ${done - kept - larger - failed.length}; kept ${kept} with transparency and ${larger} whose JPEG was not smaller; ${failed.length} failed.` +
  ` Database now ${(await size()).toFixed(2)} GB.` + (failed.length ? ' ' + JSON.stringify(failed.slice(0, 5)) : ''));
store.close();
process.exit(failed.length ? 1 : 0);
