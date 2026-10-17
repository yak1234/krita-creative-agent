// @ts-check
// What each installed Krita preset actually paints, measured by one probe stroke per preset
// (brush-catalog.json). Without it the painter chose presets by name: a traced run guessed "Wet
// Paint" for a reference transfer and got a washed-out, grainy canvas.
import { readFileSync } from 'node:fs';

export const CATALOG = JSON.parse(readFileSync(new URL('./brush-catalog.json', import.meta.url), 'utf8'));

/** The measured card for each name, or null for a preset that was never probed. */
export const brushCards = names => names.map(name => ({ name, card: CATALOG.cards[name] ?? null }));

/** Prompt section: the presets to reach for, by job, and the ones to avoid. */
export function brushGuide(catalog = CATALOG) {
  const jobs = Object.entries(catalog.jobs).map(([job, presets]) => `- ${job}: ${presets.join(', ')}`);
  const avoid = Object.entries(catalog.avoid).map(([why, presets]) => `- ${why}: ${presets.join(', ')}`);
  return `Brushes by job (measured with one probe stroke each; list_brushes returns a card for every probed preset, so check that a preset is installed there):
${jobs.join('\n')}
Avoid for painting:
${avoid.join('\n')}
Size is in canvas pixels: on a large canvas, details need small sizes and masses large ones. Blender presets lay no colour; they only move paint already on the layer they touch.`;
}
