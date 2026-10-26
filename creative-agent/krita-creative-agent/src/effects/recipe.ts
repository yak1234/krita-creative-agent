// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Effect recipes (openspec custom-effects): an effect is a YAML recipe, never code. This module reads and checks one
// (TypeBox schemas, `additionalProperties: false`, the same keys and enums the plugin's effect_craft.py accepts, so a
// recipe that passes here is never refused there), evaluates its numbers and resolves its blocks for a call.
// - A number in a recipe is a number or arithmetic on the recipe's own options: numbers, option names, + - * /,
//   parentheses, min() and max(). A hand-written reader (tokenizer + recursive descent): no Function, no eval, no property
//   access, so nothing else can ever run.
// - The caps hold whatever a recipe says (particles 60 000 per call, 3 depth layers, opacity 1, 8 blocks): values beyond
//   are clamped and said in `notes`. The plugin clamps again; this keeps the numbers honest before they leave.
// - Names of parts (caps `part`, texture `area`, `within`) stay words; the studio finds them later.
import { Type, type TSchema } from 'typebox';
import Value from 'typebox/value';
import { parseDocument } from 'yaml';

export const MOST_BLOCKS = 8;            // the engine's cap on blocks per call
export const MOST_PARTICLES = 60000;     // per call
export const MOST_LAYERS = 3;
export const MOST_RAYS = 64;
export const CUE_MAX = 160;
export const LESSON_MAX = 300;
export const EVIDENCE_MAX = 300;
export const DEFAULT_KEEP_CLEAR = ['faces', 'hair'];
export const NAME_PATTERN = /^[a-z0-9-]{1,60}$/;
const OPTION_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const MOST_OPTIONS = 16;
const MOST_RECIPE_BLOCKS = 50;           // sanity only: resolveBlocks keeps MOST_BLOCKS and says so
const MOST_KEEP_CLEAR = 16;
const MOST_EXPRESSION = 200;
const MOST_DEPTH = 40;
export const HUGE = 1e12;               // the plugin refuses a number beyond this (creative_validation.numeric)

export type Expr = number | string;
export type BlockName = 'particles' | 'wash' | 'noise' | 'caps' | 'rays' | 'texture';
export type Band = { from: 'top' | 'bottom' | 'left' | 'right'; share: Expr };
export type BlockSpec = { block: BlockName; [key: string]: Expr | string | Expr[] | Band };
export type ResolvedValue = number | string | number[] | { from: string; share: number };
export type ResolvedBlock = { block: BlockName; [key: string]: ResolvedValue };
export type RecipeOption = { default: number; min: number; max: number; describe?: string };
export type Recipe = {
  name: string; cue: string; lesson?: string; evidence?: string; layer?: string; keep_clear: string[];
  options: Record<string, RecipeOption>; blocks: BlockSpec[]; auto_kept?: boolean;
};

// ---- schemas -------------------------------------------------------------------------------------------------------

const expr = Type.Union([Type.Number(), Type.String({ minLength: 1, maxLength: MOST_EXPRESSION })], { description: 'A number or arithmetic on the options.' });
// A part name holds a word: one only of spaces passes minLength but the plugin's text() refuses it.
const part = Type.String({ minLength: 1, maxLength: 120, pattern: '\\S' });
const side = Type.Union(['top', 'bottom', 'left', 'right'].map(s => Type.Literal(s)));
const common = { opacity: Type.Optional(expr), within: Type.Optional(part) };
const block = <N extends string>(kind: N, fields: Record<string, ReturnType<typeof Type.Optional> | ReturnType<typeof Type.String>>) =>
  Type.Object({ block: Type.Literal(kind), ...common, ...fields }, { additionalProperties: false });

export const BLOCK_SCHEMAS = {
  particles: block('particles', {
    layers: Type.Optional(expr), density: Type.Optional(expr), count: Type.Optional(expr), wind_deg: Type.Optional(expr),
    streak: Type.Optional(expr), colour: Type.Optional(Type.Union([Type.Literal('light'), Type.Literal('local')])) }),
  wash: block('wash', { from: Type.Optional(side), falloff: Type.Optional(expr), lower_contrast: Type.Optional(expr) }),
  // band: paint only in that strip of the canvas (share of its height or width), the inner edge softened.
  noise: block('noise', {
    scale: Type.Optional(Type.Union(['small', 'medium', 'large'].map(s => Type.Literal(s)))),
    band: Type.Optional(Type.Object({ from: side, share: expr }, { additionalProperties: false })) }),
  rays: block('rays', {
    from_point: Type.Optional(Type.Tuple([expr, expr])), from: Type.Optional(side), count: Type.Optional(expr), spread_deg: Type.Optional(expr) }),
  // image_path is optional here: the studio supplies the texture (the AI texture of the last resort) when it calls the plugin.
  texture: block('texture', {
    image_path: Type.Optional(Type.String({ minLength: 1, maxLength: 1000 })), area: part,
    blend: Type.Optional(Type.Union(['over', 'screen', 'multiply'].map(s => Type.Literal(s)))) }),
  caps: block('caps', { part, thickness: Type.Optional(expr) }),
} as const;

const optionSchema = Type.Object({
  default: Type.Number(), min: Type.Number(), max: Type.Number(), describe: Type.Optional(Type.String({ maxLength: 300 })),
}, { additionalProperties: false });

const recipeSchema = Type.Object({
  name: Type.String({ pattern: NAME_PATTERN.source }),
  cue: Type.String({ minLength: 1, maxLength: CUE_MAX }),
  lesson: Type.Optional(Type.String({ maxLength: LESSON_MAX })),
  evidence: Type.Optional(Type.String({ maxLength: EVIDENCE_MAX })),
  layer: Type.Optional(Type.String({ minLength: 1, maxLength: 100 })),
  keep_clear: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 60, pattern: '\\S' }), { maxItems: MOST_KEEP_CLEAR })),
  options: Type.Optional(Type.Record(Type.String(), optionSchema)),
  blocks: Type.Array(Type.Unknown(), { minItems: 1, maxItems: MOST_RECIPE_BLOCKS }),
  auto_kept: Type.Optional(Type.Boolean()),
}, { additionalProperties: false });

/** The first real schema error as "field.path: message". */
function firstError(schema: TSchema, value: unknown, root: string): string | null {
  for (const e of Value.Errors(schema, value)) {
    if (e.keyword === 'boolean') continue;                 // the per-property echo of additionalProperties
    let path = root + e.instancePath.split('/').filter(Boolean).map(p => (/^\d+$/.test(p) ? `[${p}]` : `.${p}`)).join('');
    const params = e.params as { additionalProperties?: string[]; requiredProperties?: string[]; pattern?: string };
    if (params.additionalProperties) path += `.${params.additionalProperties[0]}`;
    if (params.requiredProperties) path += `.${params.requiredProperties[0]}`;
    const message = params.additionalProperties ? 'is not a parameter of this block' : params.requiredProperties ? 'is required'
      : params.pattern === '\\S' ? 'is a name, not only spaces' : e.message;
    return `${path.replace(/^\./, '')}: ${message}`;
  }
  return null;
}

// ---- expressions ---------------------------------------------------------------------------------------------------

type Token = { kind: 'num'; value: number } | { kind: 'name'; value: string } | { kind: 'op'; value: string };

function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === ' ' || c === '\t') { i++; continue; }
    const number = /^(\d+(\.\d+)?|\.\d+)/.exec(text.slice(i));
    if (number) {
      const after = text[i + number[0].length];
      if (after !== undefined && /[A-Za-z0-9_.]/.test(after)) throw new Error(`"${number[0]}${after}" is not a number`);
      tokens.push({ kind: 'num', value: Number(number[0]) });
      i += number[0].length;
    } else if (/[A-Za-z_]/.test(c)) {
      const name = /^[A-Za-z_][A-Za-z0-9_]*/.exec(text.slice(i))![0];
      tokens.push({ kind: 'name', value: name });
      i += name.length;
    } else if ('+-*/(),'.includes(c)) {
      tokens.push({ kind: 'op', value: c });
      i++;
    } else {
      throw new Error(`"${c}" is not allowed`);
    }
  }
  return tokens;
}

/** The value of one number-or-arithmetic. Throws on any name that is not an option, any token that is not allowed. */
export function evaluate(expression: number | string, options: Record<string, number>): number {
  if (typeof expression === 'number') {
    if (!Number.isFinite(expression)) throw new Error('a number is finite');
    return expression;
  }
  if (typeof expression !== 'string' || expression.length > MOST_EXPRESSION) throw new Error('an expression is a short text');
  const tokens = tokenize(expression);
  let at = 0;
  const next = () => tokens[at];
  const take = (op: string) => { const t = next(); if (t && t.kind === 'op' && t.value === op) { at++; return true; } return false; };
  const sum = (depth: number): number => {
    if (depth > MOST_DEPTH) throw new Error('too deeply nested');
    let value = product(depth);
    for (;;) {
      if (take('+')) value += product(depth); else if (take('-')) value -= product(depth); else return value;
    }
  };
  const product = (depth: number): number => {
    let value = unary(depth);
    for (;;) {
      if (take('*')) value *= unary(depth);
      else if (take('/')) {
        const divisor = unary(depth);
        if (divisor === 0) throw new Error('division by zero');
        value /= divisor;
      } else return value;
    }
  };
  const unary = (depth: number): number => {
    if (take('-')) return -unary(depth + 1);
    if (take('+')) return unary(depth + 1);
    return primary(depth + 1);
  };
  const primary = (depth: number): number => {
    const t = next();
    if (!t) throw new Error('the expression ends too soon');
    at++;
    if (t.kind === 'num') return t.value;
    if (t.kind === 'name') {
      if (t.value === 'min' || t.value === 'max') {
        if (!take('(')) throw new Error(`${t.value} needs ( )`);
        const args = [sum(depth + 1)];
        while (take(',')) args.push(sum(depth + 1));
        if (!take(')')) throw new Error('a ")" is missing');
        return t.value === 'min' ? Math.min(...args) : Math.max(...args);
      }
      if (!Object.hasOwn(options, t.value)) throw new Error(`"${t.value}" is not one of the options`);
      return options[t.value];
    }
    if (t.value === '(') {
      const value = sum(depth + 1);
      if (!take(')')) throw new Error('a ")" is missing');
      return value;
    }
    throw new Error(`"${t.value}" is not expected here`);
  };
  const value = sum(0);
  if (at < tokens.length) {
    const t = tokens[at];
    throw new Error(`"${t.value}" is not expected here`);
  }
  if (!Number.isFinite(value)) throw new Error('the result is not a finite number');
  return value;
}

// ---- parsing -------------------------------------------------------------------------------------------------------

const NUMERIC_KEYS = new Set(['opacity', 'layers', 'density', 'count', 'wind_deg', 'streak', 'falloff', 'lower_contrast', 'spread_deg', 'thickness']);

/** The recipe in `text` (YAML), or {error} naming the file and the field. */
export function parseRecipe(text: string, file: string): { recipe: Recipe } | { error: string } {
  const fail = (field: string, message: string) => ({ error: `${file}: ${field ? field + ': ' : ''}${message}` });
  let data: unknown;
  const doc = parseDocument(text, { logLevel: 'silent' });   // a tag the schema does not know is a warning, refused below
  const trouble = doc.errors[0] ?? doc.warnings[0];
  if (trouble) return fail('', `not valid YAML (${trouble.message.split('\n')[0]})`);
  try {
    data = doc.toJS({ maxAliasCount: 0 });                      // no aliases: nothing to expand
  } catch (e) {
    return fail('', `not valid YAML (${(e as Error).message.split('\n')[0]})`);
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return fail('', 'a recipe is a mapping of name, cue, blocks ...');
  const problem = firstError(recipeSchema, data, '');
  if (problem) { const [field, ...rest] = problem.split(': '); return fail(field, rest.join(': ')); }
  const raw = data as Omit<Recipe, 'keep_clear' | 'options'> & { keep_clear?: string[]; options?: Record<string, RecipeOption> };
  const options = raw.options ?? {};
  const names = Object.keys(options);
  if (names.length > MOST_OPTIONS) return fail('options', `at most ${MOST_OPTIONS} options`);
  for (const name of names) {
    const o = options[name];
    if (!OPTION_NAME.test(name) || name === 'min' || name === 'max') return fail(`options.${name}`, 'an option name is letters, digits and _, and not min or max');
    if (o.min > o.max) return fail(`options.${name}.min`, `min ${o.min} is above max ${o.max}`);
    if (o.default < o.min || o.default > o.max) return fail(`options.${name}.default`, `default ${o.default} is outside ${o.min}..${o.max}`);
  }
  const defaults = Object.fromEntries(names.map(n => [n, options[n].default]));
  const blocks: BlockSpec[] = [];
  const list = raw.blocks as unknown[];
  for (let i = 0; i < list.length; i++) {
    const spec = list[i];
    if (spec === null || typeof spec !== 'object' || Array.isArray(spec)) return fail(`blocks[${i}]`, 'a block is a mapping with a "block" name');
    const kind = (spec as { block?: unknown }).block;
    if (typeof kind !== 'string' || !Object.hasOwn(BLOCK_SCHEMAS, kind)) {
      return fail(`blocks[${i}].block`, `${JSON.stringify(kind ?? null)} is not a block (${Object.keys(BLOCK_SCHEMAS).join(', ')})`);
    }
    const bad = firstError(BLOCK_SCHEMAS[kind as BlockName], spec, `blocks[${i}]`);
    if (bad) { const [field, ...rest] = bad.split(': '); return fail(field, rest.join(': ')); }
    for (const [key, value] of Object.entries(spec as Record<string, unknown>)) {
      const items = key === 'from_point' ? (value as Expr[]) : NUMERIC_KEYS.has(key) ? [value as Expr] : [];
      for (const item of items) {
        try { evaluate(item, defaults); } catch (e) { return fail(`blocks[${i}].${key}`, (e as Error).message); }
      }
    }
    const band = (spec as { band?: Band }).band;
    if (band) {
      try { evaluate(band.share, defaults); } catch (e) { return fail(`blocks[${i}].band.share`, (e as Error).message); }
    }
    if (kind === 'texture' || kind === 'caps') {                      // the part a block names stays a word
      const named = kind === 'caps' ? 'part' : 'area';
      if (typeof (spec as Record<string, unknown>)[named] !== 'string') return fail(`blocks[${i}].${named}`, 'a part name is required');
    }
    blocks.push(spec as BlockSpec);
  }
  const recipe: Recipe = { ...raw, keep_clear: raw.keep_clear ?? [...DEFAULT_KEEP_CLEAR], options, blocks };
  return { recipe };
}

// ---- resolving -----------------------------------------------------------------------------------------------------

/** The recipe's blocks as plain numbers for one call. `given` are the painter's option values (clamped to each option's range). */
export function resolveBlocks(recipe: Recipe, given: Record<string, unknown>): { blocks: ResolvedBlock[]; notes: string[] } {
  const notes: string[] = [];
  const values: Record<string, number> = {};
  for (const [name, o] of Object.entries(recipe.options)) {
    let value = o.default;
    if (Object.hasOwn(given, name)) {
      const asked = given[name];
      if (typeof asked === 'number' && Number.isFinite(asked)) {
        value = Math.min(o.max, Math.max(o.min, asked));
        if (value !== asked) notes.push(`${name}: ${asked} asked, ${value} used (allowed ${o.min} to ${o.max})`);
      } else {
        notes.push(`${name}: ${JSON.stringify(asked)} is not a number, the default ${o.default} used`);
      }
    }
    values[name] = value;
  }
  for (const name of Object.keys(given)) {
    if (!Object.hasOwn(recipe.options, name)) notes.push(`${name}: not an option of this effect, ignored`);
  }
  const defaults = Object.fromEntries(Object.entries(recipe.options).map(([n, o]) => [n, o.default]));
  let specs = recipe.blocks;
  if (specs.length > MOST_BLOCKS) {
    notes.push(`blocks: ${specs.length} asked, the first ${MOST_BLOCKS} used`);
    specs = specs.slice(0, MOST_BLOCKS);
  }
  const clamp = (label: string, value: number, lo: number, hi: number): number => {
    const used = Math.min(hi, Math.max(lo, value));
    if (used !== value) notes.push(`${label}: ${value} asked, ${used} used`);
    return used;
  };
  const blocks = specs.map((spec, i): ResolvedBlock => {
    const label = (key: string) => `block ${i + 1} (${spec.block}) ${key}`;
    // An expression that fails at the painter's option values (1/density at 0) falls back to its value at the defaults, and says so.
    const number = (key: string, value: Expr): number => {
      try {
        return clamp(label(key), evaluate(value, values), -HUGE, HUGE);
      } catch (e) {
        const used = clamp(label(key), evaluate(value, defaults), -HUGE, HUGE);
        notes.push(`${label(key)}: ${(e as Error).message} with these options, the value at the defaults (${used}) used`);
        return used;
      }
    };
    const out: ResolvedBlock = { block: spec.block };
    for (const [key, value] of Object.entries(spec)) {
      if (key === 'block') continue;
      if (key === 'band') {
        const band = value as Band;
        out[key] = { from: band.from, share: clamp(label('band share'), number('band share', band.share), 0, 1) };
      } else if (key === 'from_point') {
        out[key] = (value as Expr[]).map(v => number(key, v));
      } else if (NUMERIC_KEYS.has(key)) {
        let n = number(key, value as Expr);
        if (key === 'opacity') n = clamp(label(key), n, 0, 1);
        else if (key === 'layers') n = clamp(label(key), Math.round(n), 2, MOST_LAYERS);
        else if (key === 'count' && spec.block === 'particles') n = clamp(label(key), Math.round(n), 0, MOST_PARTICLES);
        else if (key === 'count') n = clamp(label(key), Math.round(n), 1, MOST_RAYS);
        out[key] = n;
      } else {
        out[key] = value as string;
      }
    }
    return out;
  });
  return { blocks, notes };
}
