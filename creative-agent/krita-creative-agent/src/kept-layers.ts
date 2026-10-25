// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Layer plan (openspec layer-plan, approved by the artist 2026-10-24). A New Moscow chat reached 146 layers and 10.1 GiB
// after three kept moves: Keep merged only runs of plain stroke layers, so Finish and accents groups, clipped and blended
// layers and the passes between them stayed. Now Keep (Met on a plan step) merges the move's group whole, in the plugin
// (merge_craft.py `whole`), into one layer named here; the kept underpainting is also locked (Krita's layer lock) so
// nothing paints on it. The painter reads a one-line summary of the stack before each move.
//
// - keptLayer: the merged layer's name and lock for a kept move: its plan step's layer name ("Underpainting" for the
//   underpainting step, else the step's title without its file), or "Move N · title" for a move outside the plan.
// - stackSummary: the observation's top-level layers, bottom to top (nearest the top when there are many), each group's
//   size, the locked ones, and the group this move paints in.
import { layerName } from './folder-notes.ts';
import { folderStepKind } from './project-folder.ts';

export type KeptLayer = { name: string; lock: boolean };
type StepLike = { title: string; scope?: string; kind?: string };
type MoveLike = { number: number; title?: string };

export function keptLayer(step: StepLike | undefined, move: MoveLike): KeptLayer {
  if (!step) return { name: 'Move ' + move.number + ' · ' + String(move.title ?? 'kept').slice(0, 80), lock: false };
  const underpainting = folderStepKind(step) === 'underpainting';
  return { name: underpainting ? 'Underpainting' : layerName(step.title), lock: underpainting };
}

/** One observed layer as the plugin lists it (creative_tools.py _creative_layer_list), bottom to top. */
export type ObservedLayer = { id?: string; name?: string; type?: string; depth?: number; visible?: boolean; editable_by_agent?: boolean };

const SHOWN = 12;                                  // top-level layers named; the rest are counted
const NAME = 40;                                   // characters of a layer name

export function stackSummary(layers: readonly ObservedLayer[] | undefined, { move }: { move?: number }): string | undefined {
  if (!Array.isArray(layers) || !layers.length) return undefined;
  const top: { layer: ObservedLayer; inside: number; hidden: number }[] = [];
  for (const layer of layers) {
    if (!layer.depth) top.push({ layer, inside: 0, hidden: 0 });
    else if (top.length) { const last = top[top.length - 1]; last.inside++; if (layer.visible === false) last.hidden++; }
  }
  const label = ({ layer, inside, hidden }: { layer: ObservedLayer; inside: number; hidden: number }) => {
    const notes = [layer.type === 'grouplayer' ? `group of ${inside}${hidden ? `, ${hidden} hidden` : ''}` : '',
      layer.editable_by_agent === false ? 'locked' : '', layer.visible === false ? 'hidden' : ''].filter(Boolean);
    return String(layer.name ?? '').slice(0, NAME) + (notes.length ? ` (${notes.join(', ')})` : '');
  };
  const shown = top.slice(-SHOWN).map(label);
  if (top.length > SHOWN) shown.unshift(`${top.length - SHOWN} more below`);
  let text = `${layers.length} layer${layers.length === 1 ? '' : 's'}. Top level, bottom to top: ${shown.join(' · ')}.`;
  if (Number.isInteger(move)) {
    const group = 'Creative Agent · move-' + move, made = top.some(t => t.layer.name === group);
    text += ` This move paints in ${made ? 'its own' : 'a new'} group "${group}" at the top; when the artist keeps it, it merges into one layer. Never paint on a locked layer.`;
  }
  return text;
}
