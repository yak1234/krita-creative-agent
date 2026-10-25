// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Argument repair: tool-call arguments the host can safely put right before they are validated. The artist's chats of
// 2026-10-23/24 had about 70 calls refused for their shape alone, each costing a model round trip and often the batch:
// - malformed JSON in big paint_batch calls (one brace too many or too few, 15 calls) -> repairJsonText, by the parser's
//   own error position: a missing closer is inserted, a stray one dropped;
// - a 2- or 4-number stroke segment (11) -> a straight line or a quadratic curve, as the cubic [c1x,c1y,c2x,c2y,x,y];
// - a pen list (pressure, tilt, rotation, speed, time_ms) with a value count that fits neither the points nor the
//   segments (11) -> resampled along the stroke to one value per point;
// - a field the tool does not have (9): count -> stroke_count, a note or summary the model added to an action -> dropped,
//   opacity on a stroke tool -> told (a stroke's opacity is not the layer's);
// - a text field over its limit (finish_move's summary, 6) -> shortened;
// - an object or list sent as a JSON string (paint_accents' area, 2) -> parsed.
// Each repair is named in `notes`, so the caller can record it. Anything else is left for validation to report.
// Repairs never invent painting: a dropped field is a note to nobody, and a converted segment paints the same line.
// Pure: no I/O; imports only types.
import type { TSchema } from 'typebox';

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type JsonObject = { [key: string]: Json };
type Schema = TSchema & { type?: string | string[]; properties?: Record<string, Schema>; additionalProperties?: boolean | Schema;
  anyOf?: Schema[]; oneOf?: Schema[]; maxLength?: number; items?: Schema };

const isObject = (value: unknown): value is JsonObject => !!value && typeof value === 'object' && !Array.isArray(value);
const MATCH: Record<string, string> = { '{': '}', '[': ']' };

/** Where the parser stood at `end`: the open containers, and whether it was inside a string. */
function scan(text: string, end: number): { stack: string[]; inString: boolean } {
  const stack: string[] = [];
  let inString = false;
  for (let i = 0; i < end; i++) {
    const c = text[i];
    if (inString) { if (c === '\\') i++; else if (c === '"') inString = false; continue; }
    if (c === '"') inString = true;
    else if (c === '{' || c === '[') stack.push(c);
    else if (c === '}' || c === ']') stack.pop();
  }
  return { stack, inString };
}
const lastNonSpace = (text: string, before: number): number => { let k = before - 1; while (k >= 0 && /\s/.test(text[k])) k--; return k; };
const insert = (text: string, at: number, what: string): string => text.slice(0, at) + what + text.slice(at);

/** For each key of the text in order, whether it lies inside a list of the root object (a paint_batch's actions). Read
 * leniently, as the model wrote it: a closer also closes what was left open inside it, one without an opener is
 * skipped, and the root never closes early. */
function keysInLists(text: string): boolean[] {
  const stack: string[] = [], flags: boolean[] = [];
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inString) {
      if (c === '\\') i++;
      else if (c === '"') { inString = false; const k = text.slice(i + 1).search(/\S/); if (k >= 0 && text[i + 1 + k] === ':') flags.push(stack.length >= 2 && stack[1] === '['); }
      continue;
    }
    if (c === '"') inString = true;
    else if (c === '{' || c === '[') stack.push(c);
    else if (c === '}' || c === ']') {                  // closes its own opener and whatever was left open inside it
      const at = stack.map(open => MATCH[open]).lastIndexOf(c);
      if (at >= 1) stack.length = at;
    }
  }
  return flags;
}

/** JSON object text with unbalanced brackets put right, or null when it cannot be done safely. At most `tries` fixes,
 * each at the position JSON.parse reports; only brackets (and a missing comma between properties) are changed. A repair
 * that would move a key into or out of the root's list (an action's field to the top, or back) changes what the call
 * means: null. Text cut short inside an element of that list drops the element (named in `notes`), never runs half of it. */
export function repairJsonText(raw: string, tries = 16, notes: string[] = []): JsonObject | null {
  let text = String(raw ?? '').trim(), reference = text;
  for (let attempt = 0; attempt <= tries; attempt++) {
    let message: string;
    try {
      const value = JSON.parse(text) as Json;
      if (!(attempt > 0 && isObject(value))) return null;        // nothing to repair, or not an object: not ours
      return JSON.stringify(keysInLists(reference)) === JSON.stringify(keysInLists(text)) ? value : null;
    } catch (error) { message = error instanceof Error ? error.message : String(error); }
    if (attempt === tries) break;
    const found = /position (\d+)/.exec(message);
    const pos = found ? Number(found[1]) : /end of JSON input/i.test(message) ? text.length : -1;
    if (pos < 0) return null;
    const { stack, inString } = scan(text, Math.min(pos, text.length));
    if (pos >= text.length) {                                    // cut short: close what is open
      if (!stack.length && !inString) return null;
      if (stack.length > 2 && stack[1] === '[') {                // inside an element of the root's list: drop that element
        let cut = -1, open = -1, elements = 1, inStr = false;
        const depth: string[] = [];
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (inStr) { if (ch === '\\') i++; else if (ch === '"') inStr = false; continue; }
          if (ch === '"') inStr = true;
          else if (ch === '{' || ch === '[') { depth.push(ch); if (depth.length === 2 && ch === '[') { open = i; cut = -1; elements = 1; } }
          else if (ch === '}' || ch === ']') depth.pop();
          else if (ch === ',' && depth.length === 2 && depth[1] === '[') { cut = i; elements++; }
        }
        if (open < 0) return null;
        text = text.slice(0, cut >= 0 ? cut : open + 1);
        reference = text;
        notes.push(`action ${elements} was cut off and dropped`);
        text += ']}';
        continue;
      }
      text += (inString ? '"' : '') + stack.reverse().map(open => MATCH[open]).join('');
      continue;
    }
    if (inString) return null;
    const c = text[pos];
    if (!stack.length) {                                         // the root closed before the text ended
      const rest = text.slice(pos);
      if (/^[\s\]}]*$/.test(rest)) { text = text.slice(0, pos); continue; }       // stray closers at the end
      const k = lastNonSpace(text, pos);
      if (text[k] !== '}' && text[k] !== ']') return null;
      text = text.slice(0, k) + text.slice(k + 1);              // one closer too many: the rest still belongs inside
      continue;
    }
    const top = stack[stack.length - 1];
    if (c === '}' || c === ']') {
      if (MATCH[top] === c) return null;
      text = insert(text, pos, MATCH[top]);                      // an object or list left open before this closer
      continue;
    }
    if (top === '{' && (c === '{' || c === '[')) {               // a key was expected: the object before was not closed
      const k = lastNonSpace(text, pos);
      text = insert(text, text[k] === ',' ? k : pos, '}');
      continue;
    }
    if (top === '[' && c === ':') {                              // a key inside a list: the list was not closed before it
      const close = lastNonSpace(text, pos);
      if (text[close] !== '"') return null;
      let open = close - 1;
      while (open >= 0 && !(text[open] === '"' && text[open - 1] !== '\\')) open--;
      const k = lastNonSpace(text, open);
      if (open < 0 || text[k] !== ',') return null;
      text = insert(text, k, ']');
      continue;
    }
    if (top === '{' && c === '"' && /after property value/.test(message)) { text = insert(text, pos, ','); continue; }
    return null;
  }
  return null;
}

/** Where a missing JSON text is kept by Pi when the model's arguments did not parse (pi-ai json-parse.ts). */
export const RECEIVED = 'Received arguments:\n';

// ----- strokes -----------------------------------------------------------------------------------------------------------
const PEN_LISTS = ['pressure', 'rotation', 'speed', 'time_ms', 'tilt'];
const isPoint = (value: unknown): value is [number, number] => Array.isArray(value) && value.length === 2 && value.every(v => typeof v === 'number' && Number.isFinite(v));
const round = (v: number): number => Math.round(v * 100) / 100;

/** A segment as the cubic [c1x,c1y,c2x,c2y,x,y] from p: 2 numbers are a straight line to (x, y), 4 a quadratic through
 * the control (cx, cy). Null when it is neither. */
function cubic(p: [number, number], segment: number[]): number[] | null {
  if (segment.length === 2) {
    const [x, y] = segment;
    return [p[0] + (x - p[0]) / 3, p[1] + (y - p[1]) / 3, p[0] + 2 * (x - p[0]) / 3, p[1] + 2 * (y - p[1]) / 3, x, y].map(round);
  }
  if (segment.length === 4) {
    const [cx, cy, x, y] = segment;
    return [p[0] + 2 * (cx - p[0]) / 3, p[1] + 2 * (cy - p[1]) / 3, x + 2 * (cx - x) / 3, y + 2 * (cy - y) / 3, x, y].map(round);
  }
  return null;
}
/** values resampled to `count`, linearly along the list (a pair list componentwise). */
function resample(values: Json[], count: number): Json[] {
  const at = (t: number): Json => {
    const i = Math.min(values.length - 1, Math.floor(t)), j = Math.min(values.length - 1, i + 1), f = t - i;
    const a = values[i], b = values[j];
    if (typeof a === 'number' && typeof b === 'number') return round(a + (b - a) * f);
    if (Array.isArray(a) && Array.isArray(b)) return a.map((v, k) => typeof v === 'number' && typeof b[k] === 'number' ? round(v + ((b[k] as number) - v) * f) : v);
    return a;
  };
  return Array.from({ length: count }, (_, n) => at(count === 1 ? 0 : n * (values.length - 1) / (count - 1)));
}
function repairStroke(stroke: JsonObject, where: string, notes: string[]): void {
  if (!isPoint(stroke.start) || !Array.isArray(stroke.segments)) return;
  let point: [number, number] = stroke.start;
  let converted = 0;
  stroke.segments = stroke.segments.map(segment => {
    if (!Array.isArray(segment) || !segment.every(v => typeof v === 'number' && Number.isFinite(v))) return segment;
    const numbers = segment as number[];
    const made = numbers.length === 6 ? numbers : cubic(point, numbers);
    if (!made) return segment;
    if (made !== numbers) converted++;
    point = [made[4], made[5]];
    return made;
  });
  if (converted) notes.push(`${where}: ${converted} segment${converted === 1 ? '' : 's'} of 2 or 4 numbers made cubic`);
  const segments = stroke.segments.length;
  for (const name of PEN_LISTS) {
    const list = stroke[name];
    if (!Array.isArray(list) || !list.length || list.length === segments || list.length === segments + 1) continue;
    stroke[name] = resample(list, segments + 1);
    notes.push(`${where}: ${name} resampled from ${list.length} values to ${segments + 1} (one per point)`);
  }
}
/** Strokes anywhere in value (objects with start and segments) repaired in place. */
export function repairStrokes(value: unknown, notes: string[], where = 'strokes'): void {
  if (Array.isArray(value)) value.forEach((item, i) => repairStrokes(item, notes, `${where}[${i}]`));
  else if (isObject(value)) {
    repairStroke(value, where, notes);
    for (const [key, item] of Object.entries(value)) if (item && typeof item === 'object' && key !== 'start' && key !== 'segments') repairStrokes(item, notes, key);
  }
}

// ----- fields ------------------------------------------------------------------------------------------------------------
/** A field the tool lacks, read as the one it has (the model's word, the tool's word). Only where the meaning is the same:
 * opacity on a stroke tool is not layer_opacity (each stroke has its own), so it is told (fieldHint), not guessed. */
export const ALIASES: Record<string, string> = { count: 'stroke_count' };
/** What to say about a field a tool does not have, when the painter likely meant another: '' when nothing is known. */
export function fieldHint(tool: string, schema: TSchema, field: string): string {
  const properties = (schema as Schema).properties ?? {};
  if (field === 'opacity' && properties.layer_opacity && properties.strokes) return ` ${tool} has no opacity: give each stroke its opacity, or layer_opacity for the whole layer.`;
  return '';
}
/** Fields models add that carry no painting: dropped when the tool has no such field. */
export const NOTE_FIELDS = ['summary', 'strokes_note', 'note', 'notes', 'comment', 'comments', 'description', 'reason', 'rationale', 'intent', 'tool'];
/** Free text that may be shortened to its limit (a name, a summary). */
const TEXT_FIELDS = ['summary', 'name', 'title', 'note', 'label', 'element'];

const variants = (schema: Schema): Schema[] => schema.anyOf ?? schema.oneOf ?? [schema];
const takesString = (schema: Schema): boolean => variants(schema).some(v => v.type === 'string' || (Array.isArray(v.type) && v.type.includes('string')) || (!v.type && !v.anyOf && !v.properties && !v.items));
const shorten = (text: string, max: number): string => {
  const cut = text.slice(0, Math.max(1, max - 1)), space = cut.lastIndexOf(' ');
  return (space >= max * 0.5 ? cut.slice(0, space) : cut).replace(/[\s,;:.\-–—]+$/, '') + '…';
};

/** args fitted to an object schema's own fields (one level): aliases, note fields dropped, JSON strings parsed, long text
 * shortened. Returns a copy when anything changed, else args itself. */
export function repairToSchema(schema: TSchema, args: unknown, notes: string[], where = 'arguments'): unknown {
  const s = schema as Schema;
  if (!isObject(args) || !s.properties) return args;
  const properties = s.properties, closed = s.additionalProperties === false;
  let out: JsonObject | null = null;
  const edit = (): JsonObject => (out ??= { ...args });
  for (const [key, value] of Object.entries(args)) {
    const field = properties[key];
    if (!field) {
      if (!closed) continue;
      const alias = ALIASES[key];
      if (alias && properties[alias] && !(alias in args)) { const o = edit(); o[alias] = value; delete o[key]; notes.push(`${where}: ${key} read as ${alias}`); }
      else if (NOTE_FIELDS.includes(key) || /_notes?$/.test(key)) { delete edit()[key]; notes.push(`${where}: ${key} dropped (the tool has no such field)`); }
      continue;
    }
    if (typeof value === 'string' && !takesString(field) && /^\s*[[{]/.test(value)) {
      try { const parsed = JSON.parse(value) as Json; edit()[key] = parsed; notes.push(`${where}: ${key} parsed from a JSON string`); } catch { /* left for validation */ }
      continue;
    }
    const max = variants(field).find(v => typeof v.maxLength === 'number')?.maxLength;
    if (typeof value === 'string' && max !== undefined && value.length > max && TEXT_FIELDS.includes(key)) {
      edit()[key] = shorten(value, max); notes.push(`${where}: ${key} shortened from ${value.length} to ${max} characters`);
    }
  }
  return out ?? args;
}

/** A tool's arguments repaired before validation: strokes, then the schema's own fields. Returns the (possibly new)
 * arguments; `notes` gets one line per repair. */
export function repairArguments(tool: { name: string; parameters: TSchema }, args: unknown, notes: string[]): unknown {
  if (!isObject(args)) return args;
  const copy = JSON.parse(JSON.stringify(args)) as JsonObject;
  const before = notes.length;
  repairStrokes(copy, notes);
  const fitted = repairToSchema(tool.parameters, copy, notes, tool.name);
  return notes.length > before ? fitted : args;
}

/** paint_batch actions put in their shape: a tool name left inside arguments comes out, the action's other fields go into
 * its arguments, and arguments.tool naming the action's own tool is dropped. */
export function repairBatchActions(args: unknown, notes: string[]): unknown {
  if (!isObject(args) || !Array.isArray(args.actions)) return args;
  let changed = false;
  const actions = args.actions.map((action, i) => {
    if (!isObject(action)) return action;
    const out: JsonObject = { ...action }, inner: JsonObject = isObject(out.arguments) ? { ...out.arguments } : {};
    const had = isObject(out.arguments);
    if (typeof out.tool !== 'string' && typeof inner.tool === 'string') { out.tool = inner.tool; delete inner.tool; notes.push(`action ${i + 1}: its tool name came out of its arguments`); }
    else if (typeof out.tool === 'string' && inner.tool === out.tool) { delete inner.tool; notes.push(`action ${i + 1}: arguments.tool dropped`); }
    const extra = Object.keys(out).filter(k => k !== 'tool' && k !== 'arguments');
    for (const key of extra) { if (!(key in inner)) inner[key] = out[key]; delete out[key]; }
    if (extra.length) notes.push(`action ${i + 1}: ${extra.join(', ')} moved into its arguments`);
    if (!had && !extra.length && JSON.stringify(inner) === '{}' ) return action;
    const changedHere = JSON.stringify({ ...out, arguments: inner }) !== JSON.stringify(action);
    if (!changedHere) return action;
    changed = true;
    return { ...out, arguments: inner };
  });
  return changed ? { ...args, actions } : args;
}

/** Tools whose arguments are repaired before Pi validates them: each gets a prepareArguments (its own, if it has one, runs
 * after the repair). record gets one argument_repair event per repaired call. Mutates and returns tools. */
export function withArgumentRepair<T extends { name: string; parameters: TSchema; prepareArguments?: (args: unknown, quiet?: boolean) => unknown;
  preparedArguments?: (args: unknown) => unknown }>(
  tools: T[], record: (event: { type: 'argument_repair'; tool: string; repairs: string[] }) => void = () => {}): T[] {
  for (const tool of tools) {
    const own = tool.prepareArguments;
    tool.prepareArguments = (args: unknown) => {
      const notes: string[] = [];
      const repaired = repairArguments(tool, args, notes);
      if (notes.length) record({ type: 'argument_repair', tool: tool.name, repairs: notes });
      return own ? own(repaired) : repaired;
    };
    // The same repair, unrecorded and never throwing: what the host reads of a call as it starts (the move's area, the
    // pending tools) is what will run.
    tool.preparedArguments = (args: unknown) => {
      try { const repaired = repairArguments(tool, args, []); return own ? own(repaired, true) : repaired; } catch { return args; }
    };
  }
  return tools;
}
