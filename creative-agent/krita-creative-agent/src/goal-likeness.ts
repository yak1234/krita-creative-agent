// Goal likeness (crisp-accents goal 8, the artist's fix 2): how close the canvas is to the goal reference, before and
// after each painting batch, at a scale where brushwork does not count. In chat 34deca0e Luna reported "no regressions"
// for every batch of hand strokes that pulled a clean underpainting away from the goal: it judges how strokes look, not
// whether the painting moved away from the picture the artist asked for. This measures that.
//
// The plugin (goal_likeness.py likeness_grid) reduces the goal's crop and the same canvas area of each view to one grid
// of GRID_SIDE cells on the long side (about 94 canvas px a cell on a 6000 px canvas), blurred by a cell and in CIE Lab;
// here the cells are compared with CIE76 delta E. A batch's area is the cells it changed at that scale (MOVED_DE).
// Thresholds, from measurements on the New Moscow goal and the views of chat 34deca0e (the builder's report). The mean
// alone missed the real case: move 2's strokes over the underpainting moved their cells +1.1 on average (some got
// better) while the coat and the car got much worse (90th percentile +7). So the tail decides too: the cells made
// clearly worse (>= CELL_CLEARLY) net of those made clearly better. Real move 2: 73 - 26 = 47 cells of 3072. Brushwork
// in the goal's colours, texture in the canvas's own and small detail over the same view: at most 12. Flat blocks,
// wrong-colour strokes, greying and broad scrubbing: 100 to 700. Smears hardly register: those are Luna's.
// Pure functions: the studio fetches grids (studio.mjs likenessHost), extensions/goal-likeness.ts decides.


export const GRID_SIDE = 64;
/** A cell the batch changed: delta E between before and after at this scale (texture-only noise is about 1-2). */
export const MOVED_DE = 1.5;
/** Clearly worse: the changed area's mean distance to the goal rose by this much (about two just-noticeable differences)... */
export const AREA_WORSE = 4;
/** ...over at least this many cells (16 of 3072: about 0.5% of the canvas, a 375 px square on 6000 px)... */
export const MIN_CELLS = 16;
/** ...or the whole frame's mean rose by this much (a broad shift; normal batches moved it by 0.12 at most)... */
export const WHOLE_WORSE = 1;
/** ...or this share of the grid got clearly worse (CELL_CLEARLY) more than it got clearly better: 20 cells of 3072, about
 * a 480 px passage on a 6000 px canvas (the real case 47, normal brushwork at most 12). */
export const NET_WORSE_SHARE = 0.0065;
/** A cell made clearly worse or better: about two and a half just-noticeable differences at this scale. */
export const CELL_CLEARLY = 6;
/** A cell that got worse by this much counts toward where and what got worse when none got clearly worse. */
const CELL_WORSE = 3;

export type Rect = [number, number, number, number];
export type Grid = { width: number; height: number; lab: Float32Array };
export type Mapping = { reference_id: string; source: Rect; target: Rect; from: 'transfer' | 'proportions' };
export type Worse = { rect: Rect; where: string; what: string[] };
export type Measure = {
  whole: { before: number; after: number; change: number };
  area: { before: number; after: number; change: number; cells: number; share: number; p90: number; worse_cells: number; better_cells: number };
  grid_cells: number;
  worse: Worse | null;
  /** Where the batch changed anything at this scale (the moved cells' bounds, canvas px); null when nothing moved. */
  changed: Rect | null;
};
export type Exemption = 'accents' | 'finish' | 'transfer' | 'departure' | 'layer_settings';

const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

/** Cells of a grid over `target`: GRID_SIDE on the long side, the other in proportion. */
export function gridSize([, , w, h]: Rect | number[], side = GRID_SIDE): [number, number] {
  return w >= h ? [side, Math.max(4, Math.round(side * h / w))] : [Math.max(4, Math.round(side * w / h)), side];
}

/** The plugin's answer as a grid: little-endian float32 L, a, b per cell, row by row. */
export function decodeGrid({ grid, lab_base64 }: { grid: number[]; lab_base64: string }): Grid {
  const bytes = Buffer.from(lab_base64, 'base64');
  const lab = new Float32Array(bytes.length / 4);
  for (let i = 0; i < lab.length; i++) lab[i] = bytes.readFloatLE(i * 4);
  if (lab.length !== grid[0] * grid[1] * 3) throw new Error('The likeness grid has the wrong size.');
  return { width: grid[0], height: grid[1], lab };
}

const de = (p: Float32Array, q: Float32Array, i: number) => Math.hypot(p[i] - q[i], p[i + 1] - q[i + 1], p[i + 2] - q[i + 2]);
const thirds = (centre: number, size: number) => Math.min(2, Math.max(0, Math.floor(centre / size * 3)));
const WHERE = [['upper left', 'top', 'upper right'], ['left', 'centre', 'right'], ['lower left', 'bottom', 'lower right']];
const hueAngle = (a: number, b: number) => (Math.atan2(b, a) * 180 / Math.PI + 360) % 360;
const warmth = (hue: number) => -Math.min(Math.abs(hue - 60), 360 - Math.abs(hue - 60));   // closer to orange-yellow is warmer

/** How the cells that got worse differ from the goal now, against before: lighter/darker, greyer/more saturated, warmer/cooler. */
function whatChanged(goal: Grid, before: Grid, after: Grid, cells: number[]): string[] {
  const mean = (grid: Grid, k: number) => cells.reduce((s, c) => s + grid.lab[c * 3 + k], 0) / cells.length;
  const [gl, ga, gb] = [0, 1, 2].map(k => mean(goal, k)), [bl, ba, bb] = [0, 1, 2].map(k => mean(before, k)), [al, aa, ab] = [0, 1, 2].map(k => mean(after, k));
  const what: string[] = [];
  if (Math.abs(al - gl) - Math.abs(bl - gl) >= 2) what.push(al < gl ? 'darker' : 'lighter');
  const [gc, bc, ac] = [Math.hypot(ga, gb), Math.hypot(ba, bb), Math.hypot(aa, ab)];
  if (Math.abs(ac - gc) - Math.abs(bc - gc) >= 2) what.push(ac < gc ? 'greyer' : 'more saturated');
  if (Math.min(gc, ac) >= 8) {
    const turn = (x: number, y: number) => { const d = Math.abs(hueAngle(x, y) - hueAngle(ga, gb)); return Math.min(d, 360 - d); };
    if (turn(aa, ab) - turn(ba, bb) >= 15) what.push(warmth(hueAngle(aa, ab)) > warmth(hueAngle(ga, gb)) ? 'warmer' : 'cooler');
  }
  return what.length ? what : ['different in colour'];
}

/** The likeness of before and after to the goal, over the whole frame (`target`, canvas px) and the cells the batch changed. */
export function measure(goal: Grid, before: Grid, after: Grid, target: Rect | number[]): Measure {
  const n = goal.width * goal.height;
  if (before.width !== goal.width || after.width !== goal.width || before.lab.length !== goal.lab.length || after.lab.length !== goal.lab.length)
    throw new Error('Likeness grids of different sizes.');
  let wholeBefore = 0, wholeAfter = 0, areaBefore = 0, areaAfter = 0, cells = 0, better = 0;
  const worse: number[] = [], clearly: number[] = [], changes: number[] = [], moved: number[] = [];
  for (let c = 0; c < n; c++) {
    const i = c * 3, db = de(before.lab, goal.lab, i), da = de(after.lab, goal.lab, i);
    wholeBefore += db; wholeAfter += da;
    if (de(before.lab, after.lab, i) < MOVED_DE) continue;
    cells++; moved.push(c); areaBefore += db; areaAfter += da; changes.push(da - db);
    if (da - db >= CELL_WORSE) worse.push(c);
    if (da - db >= CELL_CLEARLY) clearly.push(c);
    if (da - db <= -CELL_CLEARLY) better++;
  }
  changes.sort((p, q) => p - q);
  const p90 = changes.length ? changes[Math.min(changes.length - 1, Math.floor(changes.length * 0.9))] : 0;
  const [x0, y0, w, h] = target, cw = w / goal.width, ch = h / goal.height;
  let where: Worse | null = null;
  if (clearly.length) worse.splice(0, worse.length, ...clearly);     // where it got clearly worse, not a light pass around it
  if (worse.length) {
    const xs = worse.map(c => c % goal.width), ys = worse.map(c => Math.floor(c / goal.width));
    const [left, top, right, bottom] = [Math.min(...xs), Math.min(...ys), Math.max(...xs) + 1, Math.max(...ys) + 1];
    const rect: Rect = [Math.round(x0 + left * cw), Math.round(y0 + top * ch), Math.round((right - left) * cw), Math.round((bottom - top) * ch)];
    const cx = xs.reduce((s, v) => s + v + 0.5, 0) / xs.length, cy = ys.reduce((s, v) => s + v + 0.5, 0) / ys.length;
    where = { rect, where: WHERE[thirds(cy, goal.height)][thirds(cx, goal.width)], what: whatChanged(goal, before, after, worse) };
  }
  const bounds = (list: number[]): Rect => {
    const xs = list.map(c => c % goal.width), ys = list.map(c => Math.floor(c / goal.width));
    const [left, top, right, bottom] = [Math.min(...xs), Math.min(...ys), Math.max(...xs) + 1, Math.max(...ys) + 1];
    return [Math.round(x0 + left * cw), Math.round(y0 + top * ch), Math.round((right - left) * cw), Math.round((bottom - top) * ch)];
  };
  return {
    whole: { before: round(wholeBefore / n), after: round(wholeAfter / n), change: round((wholeAfter - wholeBefore) / n) },
    area: cells ? { before: round(areaBefore / cells), after: round(areaAfter / cells), change: round((areaAfter - areaBefore) / cells), cells, share: round(cells / n, 4),
      p90: round(p90), worse_cells: clearly.length, better_cells: better }
      : { before: 0, after: 0, change: 0, cells: 0, share: 0, p90: 0, worse_cells: 0, better_cells: 0 },
    grid_cells: n,
    worse: where,
    changed: moved.length ? bounds(moved) : null,
  };
}

/** A batch that made the canvas clearly less like the goal (thresholds above). */
export function clearlyWorse(m: Measure): boolean {
  return (m.area.cells >= MIN_CELLS && m.area.change >= AREA_WORSE) || m.whole.change >= WHOLE_WORSE
    || m.area.worse_cells - m.area.better_cells >= Math.ceil(NET_WORSE_SHARE * m.grid_cells);
}

/** What got worse and where, for the painter and the artist. */
export function describeWorse(m: Measure): string {
  const what = m.worse ? m.worse.what.join(' and ') + ' than the goal' : 'further from the goal';
  const where = m.worse ? `${m.worse.where} [${m.worse.rect.join(',')}]` : 'across the canvas';
  const share = (cells: number) => Math.round(cells / m.grid_cells * 1000) / 10;
  return `${where}: ${what}. The changed area (${share(m.area.cells)}% of the canvas) went from ΔE ${m.area.before.toFixed(1)} → ${m.area.after.toFixed(1)}`
    + ` from the goal; ${share(m.area.worse_cells)}% got clearly worse and ${share(m.area.better_cells)}% clearly better;`
    + ` the whole canvas ΔE ${m.whole.before.toFixed(1)} → ${m.whole.after.toFixed(1)}`;
}

// A message that asks for something the reference does not show: compared with it, an addition, a recolouring, "make it
// ...", an atmosphere, a grade or a style. Deliberately broad: a false match only keeps a worse batch (measured and
// reported), never undoes one. A departure holds (studio.mjs) until a later message points back to the reference.
const AGAINST_REFERENCE = /\b(?:than|unlike|instead of|differ(?:ent|ently)? from|depart\w* from|deviat\w* from|not (?:like|as in)|ignor\w*|away from|regardless of|rather than)\b[^.!?\n]{0,40}?\b(?:the )?(?:reference|goal|original|photo|source|picture)\b/i;
const COLOURS = 'red|orange|yellow|green|blue|teal|cyan|purple|violet|pink|magenta|white|black|grey|gray|gold|golden|silver|brown|crimson|scarlet';
const CHANGE_WORDS = new RegExp('\\b(?:warmer|cooler|colder|brighter|darker|lighter|redder|bluer|greener|more (?:saturated|vivid|muted|contrast\\w*|dramatic)|less (?:saturated|vivid|muted|contrast\\w*)'
  + '|desaturat\\w*|recolou?r\\w*|change (?:the |its |their )?colou?rs?|stylis\\w*|styliz\\w*|my own colou?rs?|sunset|sunrise|daytime|at night'
  + '|add(?:s|ing)?\\b|make (?:it|them|this|that)\\b|moodier|mood\\w*|atmospher\\w*|fog\\w*|mist\\w*|haz[ey]\\w*|rain\\w*|glow\\w*|colou?r[- ]?grad\\w*|grade|grading|tint\\w*'
  + '|(?:in the |in a |another )?style of|style|paint (?:the |a |an |its |their )?[\\w -]{0,30}?\\b(?:' + COLOURS + ')\\b)', 'i');
const BACK_TO_REFERENCE = /\b(?:closer to|back to|like|as in|match(?:es|ing)?|follow(?:s|ing)?|faithful(?:ly)? to|true to|stick to|return to)\b[^.!?\n]{0,30}?\b(?:the )?(?:reference|goal|original)\b/i;

/** The phrase of the artist's message that asks to depart from the reference, or null. */
export function departureRequested(text: string): string | null {
  const said = String(text ?? '');
  const against = said.match(AGAINST_REFERENCE);
  if (against) return against[0];
  if (BACK_TO_REFERENCE.test(said)) return null;
  return said.match(CHANGE_WORDS)?.[0] ?? null;
}

/** The phrase of the artist's message that points back to the reference (ending a departure), or null. */
export function returnToReference(text: string): string | null {
  const said = String(text ?? '');
  return AGAINST_REFERENCE.test(said) ? null : said.match(BACK_TO_REFERENCE)?.[0] ?? null;
}

// Luna's reading of a message the phrases do not decide (any language) is message-reading.ts's, one decision a message
// (luna-goal-reviewer goal 2); these phrases are its offline fallback.

type Args = Record<string, unknown> & { actions?: { tool?: string }[] };
/** Why a batch is measured but never undone: accents are small by design; the finish repaints the whole underpainting from
 * the goal by design (finish-stage, its look approved by the artist 2026-10-24); a colour transfer paints a reference the artist
 * attached; a layer setting (opacity, blend mode) changes how existing paint shows, not the paint; a departure the artist
 * asked for. Null: the batch may be undone. */
const LAYER_SETTINGS = ['adjust_layer', 'set_layer'];
export function exemption(tool: string, args: Args = {}, { departure = null }: { departure?: string | null } = {}): Exemption | null {
  const actions = tool === 'paint_batch' && Array.isArray(args.actions) ? args.actions : null;
  if (tool === 'paint_accents' || (actions?.length && actions.every(a => a?.tool === 'paint_accents'))) return 'accents';
  if (tool === 'paint_finish' || tool === 'refine_to_goal') return 'finish';   // refine_to_goal: fine finishes and accents (goal 8)
  if (tool === 'paint_from_reference' || tool === 'continue_reference_painting') return 'transfer';
  if (LAYER_SETTINGS.includes(tool) || actions?.some(a => LAYER_SETTINGS.includes(String(a?.tool)))) return 'layer_settings';
  return departure ? 'departure' : null;
}

/** sharpened: the goal reference became a sharpened copy of itself (goal-sharpen.ts); `from` is the picture it was. */
export type Reference = { id: string; role?: string; purpose?: string; part_kind?: string; source?: string; width?: number; height?: number;
  sharpened?: { from: { sha256: string; width: number; height: number } } };
export type Transfer = { reference_hash?: string; recipe?: { reference_id?: string; source?: number[]; target?: number[] } };
const ASPECT_TOLERANCE = 0.03;      // as reference-tool.mjs: a reference with the canvas's proportions is the picture
const goalLike = (r: Reference) => (r.role ?? 'reference') === 'reference' && !r.part_kind && ['general', 'composition'].includes(r.purpose ?? 'general');
const rect = (v: unknown): v is Rect => Array.isArray(v) && v.length === 4 && v.every(Number.isFinite);

/** Where the goal sits on the canvas: as the chat's whole-picture transfer of a goal reference mapped it, else a goal
 * reference (the project folder's first) of the canvas's proportions over the whole canvas, trimmed as the transfer
 * trims it. Null when there is no goal to compare with. */
export function goalMapping({ references, transfers, canvas }: { references: Reference[]; transfers: Transfer[]; canvas: { width: number; height: number } }): Mapping | null {
  const goals = (references ?? []).filter(goalLike);
  for (const job of transfers ?? []) {
    const r = job.recipe, goal = goals.find(g => g.id === r?.reference_id);
    if (!r || !goal || !rect(r.source) || !rect(r.target)) continue;
    // A transfer of the picture the goal was before it was sharpened: its source in the sharpened goal's pixels.
    const was = goal.sharpened?.from, k = was && job.reference_hash === was.sha256 && goal.width ? goal.width / was.width : 1;
    const source = (k === 1 ? r.source : r.source.map(v => Math.round(v * k))) as Rect;
    return { reference_id: goal.id, source, target: r.target, from: 'transfer' };
  }
  const goal = [...goals].sort((a, b) => Number(b.source === 'folder') - Number(a.source === 'folder'))
    .find(g => g.width && g.height && Math.abs(g.width / g.height / (canvas.width / canvas.height) - 1) <= ASPECT_TOLERANCE);
  if (!goal?.width || !goal.height) return null;
  const source: Rect = goal.width / goal.height > canvas.width / canvas.height
    ? (w => [Math.floor((goal.width! - w) / 2), 0, w, goal.height!] as Rect)(Math.round(goal.height * canvas.width / canvas.height))
    : (h => [0, Math.floor((goal.height! - h) / 2), goal.width!, h] as Rect)(Math.round(goal.width * canvas.height / canvas.width));
  return { reference_id: goal.id, source, target: [0, 0, canvas.width, canvas.height], from: 'proportions' };
}

/** An area measured at full size before and after a batch (area_compare.py area_likeness; finish-stage goal 7). */
export type AreaFull = { rect: number[]; before: { colour: number; edges: number }; after: { colour: number; edges: number } };
/** Luna's goal comparisons in a move (luna-goal-reviewer goal 1): batches compared, found further (of which undone), closer. */
export type MoveComparisons = { compared: number; further: number; closer: number; undone: number; cost?: number; ms?: number };
export type MoveLikeness = { batches: number; before: number; after: number; undone: number; kept_worse: number; last_undone?: string; luna?: MoveComparisons;
  area?: { before: number; after: number } };
/** The move card's line: the whole canvas's distance to the goal before the move's first batch and after its last. */
export function likenessLine({ batches, before, after, undone, kept_worse, last_undone, luna, area }: MoveLikeness): string {
  const compared = luna?.compared ? `; Luna compared ${luna.compared} with the goal: ` + (luna.further || luna.closer
    ? [luna.further ? `${luna.further} further${luna.undone ? luna.undone === luna.further ? ' (undone)' : ` (${luna.undone} undone)` : ''}` : '', luna.closer ? `${luna.closer} closer` : ''].filter(Boolean).join(', ')
    : 'none further') : '';
  return `Goal likeness: ΔE ${before.toFixed(1)} → ${after.toFixed(1)} over ${batches} batch${batches === 1 ? '' : 'es'}`
    + (undone ? `; undid ${undone}${last_undone ? ` (${last_undone})` : ''}` : '')
    + (kept_worse ? `; ${kept_worse} less like the goal kept (accents, an asked-for change or free colours)` : '') + compared
    + (area ? `; the area at full size ΔE ${area.before.toFixed(1)} → ${area.after.toFixed(1)}` : '');
}
