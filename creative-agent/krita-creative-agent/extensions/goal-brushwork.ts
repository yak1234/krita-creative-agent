// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Goal brushwork patterns (openspec architecture-texture goal 8; the artist 2026-10-25: "isn't krita patterns from image
// exactly what we need"). Before the form strokes of an architectural "Refine: <parts>" step (refine_to_goal, paint_finish)
// the host has the plugin (brushwork_pattern.py, operation brushwork_patterns) cut each architectural part's found area
// from the placed goal (its Sharpen-ed copy when the chat has one), high-pass it, make it seamless and register it with
// Krita.createPattern as "Goal brushwork: <part>". A part too flat or too small gets none: the library material alone.
// Once per step and goal; a failure is recorded and never fails the painting call.
//
// The record (BrushworkRecord, kept by the studio per step: goal.step_brushwork[key]) says per part which pattern it got,
// for the textured brushes (goal 6): brushworkPattern(record, part) -> {name, energy, scale} | null. `scale` is canvas px
// per pattern px (the goal's enlargement), for the brush texture's scale.
// A shipped Pi extension registered inline (src/extensions.mjs). It knows the studio only through BrushworkHost.
import type { ExtensionAPI, ToolCallEvent, ToolCallEventResult } from '@earendil-works/pi-coding-agent';
import { architecturalParts, type TextureStep } from './architecture-texture.ts';
import type { GoalSpec } from '../src/goal-spec.ts';

/** What the plugin reports for one part: the pattern resource's name, or null with its reason (flat, tiny, refused). */
export type BrushworkPart = { part: string; pattern: string | null; energy: number; size: number; scale: number; reason?: string; ms?: number };
/** A step's goal brushwork: per architectural part, which pattern it got; `goal` is the goal file's sha256. */
export type BrushworkRecord = { step: string; goal: string; parts: BrushworkPart[]; ms: number; error?: string };
export type BrushworkRequest = { goal: GoalSpec; parts: { name: string; inside_shape: { mask_path: string; bounds: number[] } }[] };
/** What the studio provides (studio.mjs brushworkHost). */
export interface BrushworkHost {
  step(): TextureStep | null;                      // the refine step painted now; null outside one
  goal(): Promise<GoalSpec | null>;                // the placed goal (sharpened when it is), or null
  recorded(key: string): BrushworkRecord | null;   // the step's record, if any
  record(entry: BrushworkRecord): void;
  native(params: BrushworkRequest, signal?: AbortSignal): Promise<{ brushwork?: BrushworkPart[] }>;   // brushwork_patterns
  status?(message: string): void;
}

/** The painting calls that paint form strokes: the patterns are made before the first of them in a step. */
export const BRUSHWORK_TOOLS = ['refine_to_goal', 'paint_finish'];

/** The plugin call for a step: its architectural parts with their found areas; null when it has none. */
export function brushworkRequest(step: TextureStep | null, goal: GoalSpec): BrushworkRequest | null {
  const parts = architecturalParts(step);
  return parts.length ? { goal, parts: parts.map(p => ({ name: p.name, inside_shape: { mask_path: p.area.mask_path, bounds: p.area.bounds } })) } : null;
}

const key = (name: string) => name.trim().split(/\s+/).join(' ').toLowerCase();
/** The goal brushwork pattern a part got (for its brush texture), or null: none made, flat, tiny, refused. */
export function brushworkPattern(record: BrushworkRecord | null | undefined, part: string): { name: string; energy: number; scale: number } | null {
  const found = record?.parts.find(p => key(p.part) === key(part));
  return found?.pattern ? { name: found.pattern, energy: found.energy, scale: found.scale } : null;
}

export default function goalBrushwork(host: BrushworkHost): (pi: ExtensionAPI) => void {
  async function ensure(signal?: AbortSignal): Promise<void> {
    const step = host.step();
    if (!step || !architecturalParts(step).length) return;
    const goal = await host.goal().catch(() => null);
    if (!goal || host.recorded(step.key)?.goal === goal.sha256) return;
    const request = brushworkRequest(step, goal)!, started = Date.now();
    host.status?.(`Goal brushwork: cutting patterns from the goal for ${step.label}…`);
    try {
      const result = await host.native(request, signal);
      host.record({ step: step.key, goal: goal.sha256, parts: result.brushwork ?? [], ms: Date.now() - started });
    } catch (error) {
      host.record({ step: step.key, goal: goal.sha256, parts: [], ms: Date.now() - started, error: String((error as Error)?.message ?? error).slice(0, 300) });
    }
  }

  return pi => {
    pi.on('tool_call', async (event: ToolCallEvent): Promise<ToolCallEventResult | undefined> => {
      if (!BRUSHWORK_TOOLS.includes((event as { toolName: string }).toolName)) return undefined;
      await ensure();
      return undefined;                              // never blocks: the brush falls back to the library material
    });
  };
}
