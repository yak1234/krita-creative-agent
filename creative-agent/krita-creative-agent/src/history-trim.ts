// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Shorter history (openspec eyes-and-history 5). Every observe_canvas result carries the whole layer list and every
// painting result its details, so a long move fills the model's window and Pi compacts the history, slowly and often
// (a slow compaction aborted moves, goal 4). In the context sent to the model, tool results older than the last
// KEEP_TURNS assistant turns become one line when they are an observation or long: status, revision, layer count, error.
// The session keeps them whole (this runs in the agent's transformContext, like keepRecentImages); images are left to
// keepRecentImages. observe_canvas results are always shortened; lookups (LOOKUP_TOOLS) never are.

export const KEEP_TURNS = 3;
/** A result's text longer than this, older than the last turns, is shortened (observe_canvas always is). */
export const LONG_RESULT = 1500;
/** Lookups the painter reads once and uses later (brush names, the toolbox manual, Krita's capabilities, a skill): kept. */
export const LOOKUP_TOOLS = ['list_brushes', 'painting_tool_help', 'krita_capabilities', 'read'];

type Part = { type: string; text?: string };
type Message = { role?: string; toolName?: string; content?: unknown };

/** One line for an older result: what the painter may still need from it. */
function summary(name: string, text: string): string {
  let parsed: Record<string, unknown> | null = null;
  try { const value: unknown = JSON.parse(text); if (value && typeof value === 'object' && !Array.isArray(value)) parsed = value as Record<string, unknown>; }
  catch { /* not JSON: no details */ }
  const facts: string[] = [];
  if (typeof parsed?.status === 'string') facts.push('status ' + parsed.status);
  if (typeof parsed?.revision === 'string') facts.push('revision ' + parsed.revision);
  for (const key of ['layer_id', 'job_id']) if (typeof parsed?.[key] === 'string') facts.push(key + ' ' + parsed[key]);
  const layers = Array.isArray(parsed?.layers) ? parsed.layers.length : typeof parsed?.layer_count === 'number' ? parsed.layer_count : null;
  if (layers !== null) facts.push(layers + ' layers');
  if (typeof parsed?.error === 'string') facts.push('error: ' + parsed.error.slice(0, 120));
  const said = facts.length ? ': ' + facts.join(', ') : '';
  return `[Older ${name} result shortened${said}. ${name === 'observe_canvas' ? 'Observe again for the current canvas.' : 'Its details are in the painting now.'}]`;
}

/** The messages with tool results older than the last `keepTurns` assistant turns shortened; the input is not changed. */
export function trimOldToolResults<M extends Message>(messages: M[], { keepTurns = KEEP_TURNS, longResult = LONG_RESULT }: { keepTurns?: number; longResult?: number } = {}): M[] {
  let turns = 0, cut = -1;
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i]?.role === 'assistant' && ++turns === keepTurns) { cut = i; break; }
  if (cut <= 0) return messages;
  return messages.map((message, i) => {
    if (i >= cut || message.role !== 'toolResult' || !Array.isArray(message.content)) return message;
    const name = message.toolName ?? 'tool';
    if (LOOKUP_TOOLS.includes(name)) return message;
    const parts = message.content as Part[];
    const long = parts.some(p => p.type === 'text' && (p.text?.length ?? 0) > longResult);
    if (name !== 'observe_canvas' && !long) return message;
    return { ...message, content: parts.map(p => p.type === 'text' && typeof p.text === 'string' && !p.text.startsWith('[Older ') ? { ...p, text: summary(name, p.text) } : p) };
  });
}
