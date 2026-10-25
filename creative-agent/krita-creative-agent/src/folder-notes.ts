// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Project folder (project-folder B3): the only things the agent writes into the artist's folder. PLAN.md mirrors the
// agent's plan as a checklist (ticked as elements are kept), NOTES.md is a short log that only grows, and a Markdown
// file the agent did not write itself is copied to <name>.backup-<yyyy-mm-dd>.md before it is changed. Every write is a
// plain .md name directly in the folder, opened without following links (O_NOFOLLOW), the folder resolved first.
// Plan step controls: a step line may end in the artist's marks (" · skipped", " · met by the artist", " · good enough",
// " · redone 2 times"), keyed by the step's identity (stepKeys), so a resumed or new chat restores them.
import { constants } from 'node:fs';
import { copyFile, lstat, open, realpath } from 'node:fs/promises';
import { basename, dirname, extname, join } from 'node:path';

export type Step = { title: string; done_when: string; scope?: string; checks?: string[]; kind?: string; tool?: string; parts?: string[]; materials?: unknown[] };
export type Brief = { title: string; objective: string; requirements: string[]; freedom: string[]; completion: string[]; steps: Step[] };
/** The artist's marks on a step: skipped, met (by the Met button, or "good enough" while it painted), redone (count). */
export type StepMark = { skipped?: boolean; met?: 'artist' | 'good_enough'; redone?: number };
export type StepMarks = Record<string, StepMark>;
export type PlanStep = { title: string; file?: string; layer?: string; done: boolean; mark?: StepMark };
/** painting: the painting its ticks and met marks belong to, from the intent block ("Painting:", "Painting file:" when it is
 * saved, "Painting id:" its live id), null in an older file. A saved painting is known by its file across restarts; the
 * live id (per Krita process) only tells an unsaved canvas. */
export type PaintingIdentity = { id: string | null; name: string; path: string | null };
/** goal: the goal image the intent block names ("Goal image: …"), the artist's choice in the panel or a typed one. */
export type Plan = { title: string | null; text: string; lines: string[]; steps: PlanStep[]; ticked: number[]; marks: StepMarks;
  painting: PaintingIdentity | null; goal: string | null };
const PAINTING_FIELD = /^Painting( file| id)?: (.+?)\s*$/;
const GOAL_FIELD = /^Goal image: (.+?)(?: \(it decides the layout\)\.?)?\s*$/;
const goalLine = (goal: string) => `Goal image: ${oneLine(goal)} (it decides the layout).`;

export const PLAN_FILE = 'PLAN.md';
export const NOTES_FILE = 'NOTES.md';
const IMAGE = /\.(png|jpe?g|gif|webp)$/i;
const STEP_LINE = /^\s*[-*]\s+\[( |x|X)\]\s+(?:\d+\.\s+)?(.+?)\s*$/;
const FILE = /\s+\(([^()]+)\)$/;
// A mark or the layer, anywhere after the title (the artist may write them in any order): up to the next " · ", " (" or the end.
const MARK = /\s+·\s+(skipped|met by the artist|good enough|redone (\d{1,3}) times?)(?=\s+·|\s+\(|\s*$)/gi;
const LAYER_ANY = /\s+·\s+layer\s+"([^"]*)"(?=\s+·|\s+\(|\s*$)/;

const TEXT_CAP = 200_000;                           // as the folder scan's text cap: a larger file is the artist's, backed up unread
const MOVES = /^##\s+Moves\s*$/;

const day = () => new Date().toISOString().slice(0, 10);
/** One line, no control characters. */
const oneLine = (text: string) => text.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();
/** A line of intent that cannot read as a heading or a checklist item. */
const plainLine = (text: string) => oneLine(text).replace(/^([-*+#>\[]|\d+\.)/, '\\$1');
/** A step title as written: one line, double quotes made single (the layer name is quoted), no brackets at the start. */
const stepTitle = (text: string) => oneLine(text).replaceAll('"', "'").replace(/^[\[\]]+\s*/, '');

/** The image file a step paints from (its scope when that names an image), or undefined. */
export function stepFile(step: Pick<Step, 'scope'>): string | undefined {
  return step.scope && IMAGE.test(step.scope.trim()) ? step.scope.trim() : undefined;
}

/** A step's layer name: its title without a trailing "(file)". */
export function layerName(title: string): string {
  const line = stepTitle(title), file = FILE.exec(line)?.[1];
  return (file && IMAGE.test(file) ? line.replace(FILE, '') : line).slice(0, 60);
}

/** Each step's identity: its image file, else its title and how many earlier steps share that title. */
export function stepKeys(steps: readonly { title: string; scope?: string; file?: string }[]): string[] {
  const seen = new Map<string, number>();
  return steps.map(step => {
    const file = step.file ?? stepFile(step);
    if (file) return 'file:' + oneLine(file).toLowerCase();
    const title = layerName(step.title).toLowerCase(), n = seen.get(title) ?? 0;
    seen.set(title, n + 1);
    return `title:${title}#${n}`;
  });
}

/** A mark as written after the layer: ' · skipped', ' · met by the artist' or ' · good enough', ' · redone N time(s)'. */
function markText(mark: StepMark | undefined): string {
  if (!mark) return '';
  const redone = Number.isInteger(mark.redone) && (mark.redone ?? 0) > 0 ? Math.min(mark.redone ?? 0, 999) : 0;
  return (mark.skipped ? ' · skipped' : '') + (mark.met === 'artist' ? ' · met by the artist' : mark.met === 'good_enough' ? ' · good enough' : '')
    + (redone ? ` · redone ${redone} time${redone === 1 ? '' : 's'}` : '');
}

function stepLine(step: Step, index: number, done: boolean, mark?: StepMark): string {
  const scope = stepFile(step), file = scope ? oneLine(scope).replace(/[()]/g, '') : undefined, title = layerName(step.title);
  return `- [${done ? 'x' : ' '}] ${index + 1}. ${title}${file ? ` (${file})` : ''} · layer "${title}"${markText(mark)}`;
}

/** PLAN.md's text: a few lines of intent, then the checklist. */
export function planText(brief: Brief, ticked: readonly number[], { goal, marks = {}, painting }: { goal?: string | null; marks?: StepMarks;
  painting?: PaintingIdentity | null } = {}): string {
  const intent = [plainLine(brief.objective), ...(goal ? [goalLine(goal)] : []),
    ...(painting && (painting.id || painting.path) ? [`Painting: ${oneLine(painting.name || 'painting')}`,
      ...(painting.path ? [`Painting file: ${oneLine(painting.path)}`] : []), ...(painting.id ? [`Painting id: ${oneLine(painting.id)}`] : [])] : []),
    ...brief.requirements.map(r => `- ${plainLine(r)}`)];
  const keys = stepKeys(brief.steps);
  return [`# Plan · ${oneLine(brief.title)}`, '', ...intent, '', '## Moves', '',
    ...brief.steps.map((step, i) => stepLine(step, i, ticked.includes(i), Object.hasOwn(marks, keys[i]) ? marks[keys[i]] : undefined)), ''].join('\n');
}

/** A plain Markdown name directly in the folder, as an absolute path inside its real location. */
async function markdownPath(root: string, name: string): Promise<string> {
  if (typeof name !== 'string' || name !== basename(name) || name.startsWith('.') || extname(name).toLowerCase() !== '.md')
    throw new Error(`Only a Markdown file directly inside the project folder can be written (${name}).`);
  const base = await realpath(root);
  if (!(await lstat(base)).isDirectory()) throw new Error('The project folder is not a folder.');
  return join(base, name);
}

type Found = { size: number; text: string | null };       // text is null for a file over TEXT_CAP (not read)

/** The file as found, or null when there is none; a link or anything but a regular file is refused. */
async function existing(path: string): Promise<Found | null> {
  let info;
  try { info = await lstat(path); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
  if (info.isSymbolicLink()) throw new Error(`${basename(path)} is a link; links are never followed in the project folder.`);
  if (!info.isFile()) throw new Error(`${basename(path)} is not a regular file.`);
  if (info.nlink > 1) throw new Error(`${basename(path)} is a hard link to another file; links are never followed in the project folder.`);
  if (info.size > TEXT_CAP) return { size: info.size, text: null };
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try { return { size: info.size, text: await handle.readFile('utf8') }; } finally { await handle.close(); }
}

/** Open for writing without following a link, refuse a hard link, then truncate (when asked) and write. */
async function writeNoFollow(path: string, text: string, flags: number, truncate = false): Promise<void> {
  let handle;
  try { handle = await open(path, flags | constants.O_WRONLY | constants.O_NOFOLLOW, 0o644); }
  catch (error) {
    if (['ELOOP', 'EMLINK'].includes((error as NodeJS.ErrnoException).code ?? '')) throw new Error(`${basename(path)} is a link; links are never followed in the project folder.`);
    throw error;
  }
  try {
    const info = await handle.stat();
    if (!info.isFile()) throw new Error(`${basename(path)} is not a regular file.`);
    if (info.nlink > 1) throw new Error(`${basename(path)} is a hard link to another file; links are never followed in the project folder.`);
    if (truncate) await handle.truncate(0);
    await handle.write(text, null, 'utf8');
  } finally { await handle.close(); }
}

/** The last byte of a file (is there a final newline?), read without reading the rest. */
async function lastByte(path: string, size: number): Promise<string> {
  if (!size) return '';
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try { const buffer = Buffer.alloc(1); await handle.read(buffer, 0, 1, size - 1); return buffer.toString('latin1'); }
  finally { await handle.close(); }
}

/** <stem>.backup-<yyyy-mm-dd>.md beside the file (a byte copy), never over an earlier backup. Returns the backup's name. */
async function backup(path: string): Promise<string> {
  const stem = basename(path, extname(path)), folder = path.slice(0, path.length - basename(path).length);
  for (let n = 1; n < 100; n++) {
    const name = `${stem}.backup-${day()}${n > 1 ? '-' + n : ''}.md`;
    try { await copyFile(path, join(folder, name), constants.COPYFILE_EXCL); return name; }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; }
  }
  throw new Error('Too many backups of ' + basename(path) + ' today.');
}

/**
 * Write PLAN.md. `expected` is the text this chat last wrote: a file that differs from it (changed by hand, or written
 * by another session) is backed up first, unless it already says what is about to be written.
 */
export async function writePlan(root: string, brief: Brief, ticked: readonly number[],
  { expected, goal, marks, painting }: { expected?: string | null; goal?: string | null; marks?: StepMarks; painting?: PaintingIdentity | null } = {}): Promise<{ text: string; backup?: string }> {
  const path = await markdownPath(root, PLAN_FILE), text = planText(brief, ticked, { goal, marks, painting });
  const before = await existing(path);
  const saved = before !== null && (before.text === null || (before.text !== expected && before.text !== text)) ? await backup(path) : undefined;
  await writeNoFollow(path, text, constants.O_CREAT, true);
  return saved ? { text, backup: saved } : { text };
}

/**
 * Record the artist's goal image in PLAN.md when the chat has no plan to write (writePlan records it with the plan): the
 * intent block's "Goal image:" line is replaced or added, and nothing else changes. With no PLAN.md, one with no steps is
 * written. A file that differs from `expected` (what this chat last wrote) is backed up first, as writePlan does.
 */
export async function writePlanGoal(root: string, goal: string, { expected, title }: { expected?: string | null; title?: string } = {}): Promise<{ text: string; backup?: string }> {
  if (typeof goal !== 'string' || !goal.trim() || /[\u0000-\u001f\u007f]/.test(goal)) throw new Error('The goal image\u2019s name must be one line.');
  const path = await markdownPath(root, PLAN_FILE), before = await existing(path);
  let text: string;
  if (before?.text == null) text = [`# Plan · ${oneLine(title || basename(dirname(path)))}`, '', goalLine(goal), '', '## Moves', ''].join('\n');
  else {
    const lines = before.text.split('\n'), end = lines.findIndex(line => /^#{2}\s/.test(line)), stop = end < 0 ? lines.length : end;
    const at = lines.slice(0, stop).findIndex(line => GOAL_FIELD.test(line));
    if (at >= 0) lines[at] = goalLine(goal);
    else {
      const head = lines.findIndex(line => /^#\s/.test(line));
      lines.splice(head >= 0 && head < stop ? head + 1 : 0, 0, ...(head >= 0 && head < stop ? ['', goalLine(goal)] : [goalLine(goal), '']));
    }
    text = lines.join('\n');
    if (text === before.text) return { text };
  }
  const saved = before !== null && (before.text === null || before.text !== expected) ? await backup(path) : undefined;
  await writeNoFollow(path, text, constants.O_CREAT, true);
  return saved ? { text, backup: saved } : { text };
}

/** One dated line at the end of NOTES.md (created when missing); what is there is never changed. */
export async function appendNote(root: string, line: string): Promise<void> {
  const path = await markdownPath(root, NOTES_FILE);
  const before = await existing(path);
  const lead = before === null ? '# Notes\n\n' : before.size && await lastByte(path, before.size) !== '\n' ? '\n' : '';
  await writeNoFollow(path, `${lead}- ${day()} · ${oneLine(line).slice(0, 400)}\n`, constants.O_CREAT | constants.O_APPEND);
}

/** PLAN.md as the artist may have left it: its checklist lines in order, which are ticked, the title. Null without one. */
export async function readPlan(root: string): Promise<Plan | null> {
  const found = await existing(await markdownPath(root, PLAN_FILE));
  return found?.text == null ? null : parsePlan(found.text);
}

export function parsePlan(text: string): Plan {
  const lines = text.split('\n'), steps: PlanStep[] = [];
  let moves = false;
  for (const line of lines) {
    if (/^#{1,2}\s/.test(line)) { moves = MOVES.test(line); continue; }   // only the checklist under "## Moves" is the plan
    if (!moves) continue;
    const match = STEP_LINE.exec(line);
    if (!match) continue;
    let rest = match[2];
    const mark: StepMark = {};
    rest = rest.replace(MARK, (_all: string, found: string, count?: string) => {
      const word = found.toLowerCase();
      if (word === 'skipped') mark.skipped = true;
      else if (word === 'met by the artist') mark.met ??= 'artist';
      else if (word === 'good enough') mark.met ??= 'good_enough';
      else mark.redone = Number(count);
      return '';
    });
    const layer = LAYER_ANY.exec(rest)?.[1];
    rest = rest.replace(LAYER_ANY, '');
    const file = FILE.exec(rest)?.[1];
    if (file && IMAGE.test(file)) rest = rest.replace(FILE, '');
    steps.push({ title: oneLine(rest), ...(file && IMAGE.test(file) ? { file } : {}), ...(layer ? { layer } : {}), done: match[1] !== ' ',
      ...(Object.keys(mark).length ? { mark } : {}) });
  }
  const title = /^#\s+(?:Plan\s*·\s*)?(.+)$/m.exec(text)?.[1]?.trim() ?? null;
  const keys = stepKeys(steps), marks: StepMarks = {};
  steps.forEach((step, i) => { if (step.mark) marks[keys[i]] = step.mark; });
  // The painting's fields, from the intent block only (before "## Moves"): a step can never name it.
  const fields: Record<string, string> = {};
  let goal: string | null = null;
  for (const line of lines) {
    if (/^#{2}\s/.test(line)) break;
    const found = PAINTING_FIELD.exec(line);
    if (found) fields[(found[1] ?? '').trim() || 'name'] = found[2]!;
    goal ??= GOAL_FIELD.exec(line)?.[1] ?? null;
  }
  const painting = fields.file || fields.id ? { id: fields.id ?? null, name: fields.name ?? 'painting', path: fields.file ?? null } : null;
  return { title, text, lines, steps, ticked: steps.flatMap((s, i) => s.done ? [i] : []), marks, painting, goal };
}

/** What changed between the agent's plan (and its ticks) and PLAN.md's lines, in words for the artist. */
export function planDifference(brief: Brief, lines: readonly string[], ticked: readonly number[], marks: StepMarks = {}): string[] {
  const edited = parsePlan(lines.join('\n')).steps, ourKeyList = stepKeys(brief.steps), theirKeyList = stepKeys(edited);
  const ours = brief.steps.map((s, i) => ({ key: ourKeyList[i], title: layerName(s.title), done: ticked.includes(i) }));
  const theirs = edited.map((s, i) => ({ key: theirKeyList[i], title: layerName(s.title), done: s.done }));
  const out: string[] = [];
  const theirKeys = new Set(theirs.map(s => s.key)), ourKeys = new Set(ours.map(s => s.key));
  for (const step of ours) if (!theirKeys.has(step.key)) out.push(`Removed: ${step.title}`);
  for (const step of theirs) if (!ourKeys.has(step.key)) out.push(`Added: ${step.title}`);
  const common = (list: typeof ours) => list.filter(s => theirKeys.has(s.key) && ourKeys.has(s.key)).map(s => s.key);
  const a = common(ours), b = common(theirs);
  for (const [i, k] of a.entries()) {
    const j = b.indexOf(k);
    if (j !== i) out.push(`Moved: ${ours.find(s => s.key === k)?.title} from step ${ours.findIndex(s => s.key === k) + 1} to step ${theirs.findIndex(s => s.key === k) + 1}`);
  }
  for (const step of theirs) {
    const mine = ours.find(s => s.key === step.key);
    if (mine && mine.done !== step.done) out.push(`${step.done ? 'Ticked' : 'Unticked'}: ${step.title}`);
  }
  edited.forEach((step, i) => {                                          // skipped, restored, met or unmet by hand
    const key = theirKeyList[i], mine = Object.hasOwn(marks, key) ? marks[key] : undefined;
    if (!ourKeys.has(key)) return;
    if (!!mine?.skipped !== !!step.mark?.skipped) out.push(`${step.mark?.skipped ? 'Skipped' : 'Restored'}: ${layerName(step.title)}`);
    if (!!mine?.met !== !!step.mark?.met) out.push(`${step.mark?.met ? 'Marked met' : 'Unmarked met'}: ${layerName(step.title)}`);
  });
  return out;
}

/** The plan as PLAN.md lists it: steps in its order, each keeping its done_when and checks from `brief` when it matches. */
export function briefFromPlan(plan: Pick<Plan, 'title' | 'steps'>, brief?: Brief | null): Brief {
  const mineKeys = stepKeys(brief?.steps ?? []), theirKeys = stepKeys(plan.steps);
  const known = new Map((brief?.steps ?? []).map((s, i) => [mineKeys[i], s]));
  const steps: Step[] = plan.steps.slice(0, 16).map((s, i) => {
    const mine = known.get(theirKeys[i]);
    const scope = s.file ?? mine?.scope;
    return { title: s.title.slice(0, 200), done_when: mine?.done_when ?? `${s.title} is painted where the goal image places it.`,
      ...(scope ? { scope } : {}), ...(mine?.checks?.length ? { checks: mine.checks } : {}),
      // A step's kind, tool and refine parts (plan-from-request) follow it by its identity, as its done_when does.
      ...(mine?.kind ? { kind: mine.kind } : {}), ...(mine?.tool ? { tool: mine.tool } : {}), ...(mine?.parts?.length ? { parts: [...mine.parts] } : {}),
      ...(mine?.materials?.length ? { materials: structuredClone(mine.materials) } : {}) };
  });
  return { title: (brief?.title ?? plan.title ?? 'Project folder plan').slice(0, 200),
    objective: brief?.objective ?? 'Paint the folder’s plan one move per step, as PLAN.md lists it.',
    requirements: brief?.requirements ?? [], freedom: brief?.freedom ?? [],
    completion: brief?.completion?.length ? brief.completion : ['Every step of PLAN.md is painted and ticked.'], steps };
}

/** The ticked steps' new indices once the plan is revised: a tick follows its step by title. */
export function remapTicks(before: Pick<Brief, 'steps'> | null | undefined, after: Pick<Brief, 'steps'>, ticked: readonly number[]): number[] {
  const beforeKeys = stepKeys(before?.steps ?? []), afterKeys = stepKeys(after.steps);
  const done = new Set(ticked.filter(i => i >= 0 && i < beforeKeys.length).map(i => beforeKeys[i]));
  return afterKeys.flatMap((k, i) => done.has(k) ? [i] : []);
}

/**
 * Write a Markdown file of the folder. One the agent did not create (not in `created`) is copied to a dated backup
 * first, so the artist's own words are never lost. Returns whether it changed and the backup's name.
 */
export async function editMarkdown(root: string, name: string, text: string,
  { created = [] }: { created?: readonly string[] } = {}): Promise<{ changed: boolean; backup?: string }> {
  const path = await markdownPath(root, name);
  const before = await existing(path);
  if (before?.text === text) return { changed: false };
  const saved = before !== null && !created.includes(name) ? await backup(path) : undefined;
  await writeNoFollow(path, text, constants.O_CREAT, true);
  return saved ? { changed: true, backup: saved } : { changed: true };
}
