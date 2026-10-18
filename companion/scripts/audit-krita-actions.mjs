// @ts-check
/** Audit Krita's menu actions for the agent: each candidate runs on a throwaway document in the
 * installed Krita; only those that opened no dialog and were undone go into the plugin's vetted
 * list (plugin/kritamcp/krita_actions.json), under the audited Krita version.
 * Run with Krita idle: it refuses while a painting session is open. Rebuild and install after. */
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { PaintingBridge } from '../src/bridge.mjs';

export const CANDIDATES = [
  { id: 'mirrorNodeX', label: 'Mirror the layer horizontally', kind: 'pixels', needs: ['target'] },
  { id: 'mirrorNodeY', label: 'Mirror the layer vertically', kind: 'pixels', needs: ['target'] },
  { id: 'rotateLayer180', label: 'Rotate the layer 180°', kind: 'pixels', needs: ['target'] },
  { id: 'rotateLayerCW90', label: 'Rotate the layer 90° clockwise', kind: 'pixels', needs: ['target'] },
  { id: 'rotateLayerCCW90', label: 'Rotate the layer 90° counter-clockwise', kind: 'pixels', needs: ['target'] },
  { id: 'selectopaque', label: 'Select the opaque pixels of the layer', kind: 'selection', needs: ['target'] },
  { id: 'selectopaque_add', label: 'Add the opaque pixels of the layer to selection', kind: 'selection', needs: ['target', 'selection'] },
  { id: 'selectopaque_subtract', label: 'Subtract the opaque pixels of the layer from selection', kind: 'selection', needs: ['target', 'selection'] },
  { id: 'selectopaque_intersect', label: 'Keep only selection where the layer is opaque', kind: 'selection', needs: ['target', 'selection'] },
  { id: 'invert_selection', label: 'Invert selection', kind: 'selection', needs: ['target', 'selection'] },
  { id: 'clear', label: 'Clear the layer inside selection', kind: 'pixels', needs: ['target', 'selection'] },
  { id: 'split_alpha_into_mask', label: 'Move the layer’s transparency into a mask', kind: 'pixels', needs: ['target'] },
  { id: 'convert_to_paint_layer', label: 'Convert the layer to a paint layer', kind: 'pixels', needs: ['target'] },
];
export const ACTIONS_FILE = fileURLToPath(new URL('../../plugin/kritamcp/krita_actions.json', import.meta.url));

/** The vetted entries from an audit: no dialog, a visible change on the audit layer, and undone. An action that
 * changed nothing proves nothing (it may have acted elsewhere), so it is not vetted. */
export function vetted(results, candidates = CANDIDATES) {
  const passed = new Set(results.filter(r => r.status === 'ok' && r.changed && r.undone).map(r => r.id));
  return candidates.filter(c => passed.has(c.id));
}

async function main() {
  const bridge = new PaintingBridge(null, {});
  await bridge.connect();
  const health = await bridge.call('health');
  if (health.session_active) throw new Error('Krita is painting (a session is open). Run the audit when it is idle.');
  const audit = await bridge.call('krita_actions_audit', { candidates: CANDIDATES.map(c => c.id) });
  const entries = vetted(audit.results);
  const table = JSON.parse(await readFile(ACTIONS_FILE, 'utf8').catch(() => '{}'));
  table[audit.version] = entries;
  await writeFile(ACTIONS_FILE, JSON.stringify(table, null, 2) + '\n');
  console.log(JSON.stringify({ version: audit.version, vetted: entries.map(e => e.id),
    refused: audit.results.filter(r => !entries.some(e => e.id === r.id)) }, null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
