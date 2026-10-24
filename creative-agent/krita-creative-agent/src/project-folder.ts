// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Project folder (project-folder B1): a read-only scan of the artist's folder of references. The folder and one level of
// subfolders are listed; images (PNG, JPEG, GIF) are read for their size only, text files for their length, a
// *prompts*.json for what each image shows. Nothing is run, no link is followed (a symlink, file or folder, is skipped),
// nothing is written. Caps keep a big folder from stalling the panel.
// Ruling (builder): numbered images (`04-kremlin-towers.png`, in the folder or one subfolder) are the elements, in number
// order; loose unnumbered images are "other images" (listed, never attached), so review leftovers such as
// finished_review.png never become elements; .kra documents, `~` backups, scripts and archives are skipped with a reason.
// This module imports no .mjs (strict TypeScript); the image header reader mirrors imageInfo in files.mjs.
import { lstat, open, readdir, readFile, realpath } from 'node:fs/promises';
import { basename, extname, isAbsolute, join, relative, sep } from 'node:path';

export type FolderLimits = { images: number; imageBytes: number; textBytes: number; files: number };
export const FOLDER_LIMITS: Readonly<FolderLimits> = Object.freeze({ images: 40, imageBytes: 12_000_000, textBytes: 200_000, files: 400 });

export type FolderImage = { name: string; path: string; width: number; height: number; mimeType: string;
  role: 'goal' | 'element' | 'other'; guess: string; number?: number; prompt?: string };
export type FolderText = { name: string; path: string; kind: 'brief' | 'readme' | 'plan' | 'notes' | 'other'; chars: number };
/** goal_source: 'chosen' when the goal is the image the artist picked (the panel's Goal image list, a typed request, or
 * PLAN.md's "Goal image:" line), 'name' when it is found by its name (final_goal.png, goal.jpg), none without a goal. */
export type FolderIndex = { root: string; goal: FolderImage | null; goal_source?: 'chosen' | 'name'; elements: FolderImage[]; others: FolderImage[];
  texts: FolderText[]; prompts: Record<string, string>; skipped: { name: string; reason: string }[] };
/** goal: the folder-relative name of the image the artist chose as the goal. One that is not an image of the folder (gone,
 * renamed, or outside it) is ignored, and the goal is found by its name as before. */
export type ScanOptions = { goal?: string | null };

const IMAGE_TYPES = new Set(['.png', '.jpg', '.jpeg', '.gif']);
const TEXT_TYPES = new Set(['.md', '.txt']);
const ARCHIVES = new Set(['.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.dmg', '.pkg']);
const PROGRAMS = new Set(['.py', '.sh', '.zsh', '.bash', '.command', '.js', '.mjs', '.cjs', '.ts', '.rb', '.pl', '.php', '.bat', '.cmd',
  '.ps1', '.exe', '.app', '.jar', '.scpt', '.applescript', '.workflow', '.so', '.dylib', '.dll']);
const KRITA = new Set(['.kra', '.krz', '.ora', '.psd', '.xcf', '.blend']);
const HEADER_BYTES = 512 * 1024;                     // enough for a JPEG's size marker after its metadata
const NUMBERED = /^(\d{1,3})(?:[-_ .]|$)/;
const GOAL = /^(?:final[-_ ]?)?(?:goal|target)(?:[-_ ].*)?$/i;
const BACKUP = /\.backup-\d{4}-\d{2}-\d{2}(?:-\d+)?\.md$/i;

/** "04-kremlin-towers.png" → "Kremlin towers": the number and extension go, separators become spaces. */
export function elementGuess(name: string): string {
  const stem = basename(name, extname(name)).replace(NUMBERED, '').replace(/[-_.]+/g, ' ').replace(/\s+/g, ' ').trim();
  return stem ? stem[0].toUpperCase() + stem.slice(1) : basename(name);
}

/** A PNG, GIF or JPEG's type and size from its first bytes (as imageInfo in files.mjs), or null. */
export function imageHeader(data: Buffer): { mimeType: string; width: number; height: number } | null {
  if (data.length >= 24 && data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])))
    return { mimeType: 'image/png', width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
  if (data.length >= 10 && data.subarray(0, 3).toString('latin1') === 'GIF')
    return { mimeType: 'image/gif', width: data.readUInt16LE(6), height: data.readUInt16LE(8) };
  if (data[0] === 255 && data[1] === 216) {
    let at = 2;
    while (at + 9 < data.length && data[at] === 255) {
      const marker = data[at + 1];
      if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(marker))
        return { mimeType: 'image/jpeg', width: data.readUInt16BE(at + 7), height: data.readUInt16BE(at + 5) };
      if (marker === 218 || marker === 217) break;
      const length = data.readUInt16BE(at + 2);
      if (length < 2) break;
      at += 2 + length;
    }
  }
  return null;
}

function textKind(name: string): FolderText['kind'] {
  const base = basename(name).toLowerCase();
  if (base === 'plan.md') return 'plan';
  if (base === 'notes.md') return 'notes';
  if (base.startsWith('readme')) return 'readme';
  if (base.includes('brief')) return 'brief';
  return 'other';
}

/** Why a file that is not an image or text is passed over, in the artist's words. */
function skipReason(name: string): string {
  const ext = extname(name).toLowerCase();
  if (name.endsWith('~')) return 'a backup copy';
  if (ext === '.webp') return 'WebP is not supported yet';
  if (KRITA.has(ext)) return 'a Krita document or other painting file (not read)';
  if (ARCHIVES.has(ext)) return 'an archive (not opened)';
  if (PROGRAMS.has(ext)) return 'a script or program (not run)';
  return 'not an image or text file';
}

function inside(root: string, path: string): boolean {
  const part = relative(root, path);
  return part !== '' && part !== '..' && !part.startsWith('..' + sep) && !isAbsolute(part);
}

async function readHead(path: string, bytes: number): Promise<Buffer> {
  const handle = await open(path, 'r');
  try {
    const buffer = Buffer.alloc(bytes);
    const { bytesRead } = await handle.read(buffer, 0, bytes, 0);
    return buffer.subarray(0, bytesRead);
  } finally { await handle.close(); }
}

/** Text from a prompts file: {assets:[{name, prompt}]}, [{name|file, prompt}] or {name: prompt}; keyed by file stem. */
// A Map, not an object: a file named constructor.png or __proto__.png must not find an inherited property.
function promptEntries(value: unknown): Map<string, string> {
  const out = new Map<string, string>();
  const add = (name: unknown, prompt: unknown) => {
    if (typeof name === 'string' && typeof prompt === 'string' && name.trim() && prompt.trim())
      out.set(basename(name.trim(), extname(name.trim())), prompt.trim().slice(0, 4000));
  };
  const list = Array.isArray(value) ? value : value && typeof value === 'object' && Array.isArray((value as { assets?: unknown }).assets)
    ? (value as { assets: unknown[] }).assets : null;
  if (list) for (const item of list) {
    if (item && typeof item === 'object') {
      const entry = item as Record<string, unknown>;
      add(entry.name ?? entry.file ?? entry.filename, entry.prompt ?? entry.description);
    }
  }
  else if (value && typeof value === 'object') for (const [name, prompt] of Object.entries(value)) add(name, prompt);
  return out;
}

/** The part of a generation prompt that names the subject ("Subject: Only the moonlit sky…"), else the start of it. */
function promptSubject(prompt: string): string {
  const subject = /\bSubject:\s*([\s\S]+)$/i.exec(prompt)?.[1] ?? prompt;
  return subject.replace(/\s+/g, ' ').trim().slice(0, 300);
}

type Candidate = { name: string; path: string; size: number };

/**
 * Read a folder of references: the goal image, the numbered element images, other images, briefs and notes, the prompts
 * file. Only regular files in `dir` and its direct subfolders are considered, and each must resolve inside `dir`.
 * Names are relative to the folder ('moscow-painting-assets/01-moonlit-sky.png'); paths are absolute and real.
 */
export async function scanFolder(dir: string, limits: FolderLimits = FOLDER_LIMITS, { goal: chosen }: ScanOptions = {}): Promise<FolderIndex> {
  let root: string;
  try {
    root = await realpath(dir);
    if (!(await lstat(root)).isDirectory()) throw new Error('not a folder');
  } catch { throw new Error('Choose a folder that exists: ' + basename(dir) + ' is not a readable folder.'); }
  const skipped: { name: string; reason: string }[] = [];
  const images: Candidate[] = [], texts: Candidate[] = [], prompts: Candidate[] = [];
  let seen = 0, over = 0;
  const visit = async (folder: string, depth: number) => {
    let entries;
    try { entries = (await readdir(folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name)); }
    catch (error) {
      if (depth === 0) throw error;
      skipped.push({ name: relative(root, folder).split(sep).join('/'), reason: 'a folder that could not be read (' + ((error as NodeJS.ErrnoException).code ?? 'error') + ')' });
      return;
    }
    const later: string[] = [];
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;                              // .DS_Store and other hidden files
      const path = join(folder, entry.name), name = relative(root, path).split(sep).join('/');
      if (seen >= limits.files) { over++; continue; }
      if (/[\u0000-\u001f\u007f]/.test(entry.name)) { seen++; skipped.push({ name: name.replace(/[\u0000-\u001f\u007f]/g, '?'), reason: 'a name with control characters (not read)' }); continue; }
      seen++;
      if (entry.isSymbolicLink()) { skipped.push({ name, reason: 'a link (links are never followed)' }); continue; }
      if (entry.isDirectory()) {
        if (depth === 0) later.push(path);
        else skipped.push({ name, reason: 'a folder deeper than one level (not read)' });
        continue;
      }
      if (!entry.isFile()) { skipped.push({ name, reason: 'not a regular file' }); continue; }
      let real: string, size: number;
      try { real = await realpath(path); size = (await lstat(real)).size; }
      catch { skipped.push({ name, reason: 'could not be read' }); continue; }
      if (!inside(root, real)) { skipped.push({ name, reason: 'outside the folder (not read)' }); continue; }
      const ext = extname(entry.name).toLowerCase();
      if (entry.name.endsWith('~')) skipped.push({ name, reason: skipReason(entry.name) });
      else if (IMAGE_TYPES.has(ext)) {
        if (size > limits.imageBytes) skipped.push({ name, reason: `too large (over ${Math.round(limits.imageBytes / 1_000_000)} MB)` });
        else images.push({ name, path: real, size });
      }
      else if (TEXT_TYPES.has(ext) || ext === '.json') {
        if (BACKUP.test(entry.name)) { skipped.push({ name, reason: 'a backup copy' }); continue; }
        if (size > limits.textBytes) { skipped.push({ name, reason: `too large for a text file (over ${Math.round(limits.textBytes / 1000)} KB)` }); continue; }
        (ext === '.json' && /prompt/i.test(entry.name) ? prompts : texts).push({ name, path: real, size });
      }
      else skipped.push({ name, reason: skipReason(entry.name) });
    }
    for (const sub of later) await visit(sub, depth + 1);
  };
  await visit(root, 0);
  if (over) skipped.push({ name: `${over} more`, reason: `too many files (the first ${limits.files} were read)` });

  const promptText = new Map<string, string>();
  for (const file of prompts) {
    try { for (const [stem, prompt] of promptEntries(JSON.parse(await readFile(file.path, 'utf8')))) promptText.set(stem, prompt); }
    catch { skipped.push({ name: file.name, reason: 'a prompts file that is not valid JSON' }); }
  }
  const number = (name: string) => { const match = NUMBERED.exec(basename(name)); return match ? Number(match[1]) : null; };
  const picked = typeof chosen === 'string' && images.some(c => c.name === chosen) ? chosen : null;
  const isGoal = (name: string) => picked ? name === picked : GOAL.test(basename(name, extname(name)));
  // Read order decides what the image cap keeps: the goal, then elements by number, then other images.
  const rank = (c: Candidate) => isGoal(c.name) ? -1 : number(c.name) ?? Number.MAX_SAFE_INTEGER;
  images.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  let goal: FolderImage | null = null;
  const elements: FolderImage[] = [], others: FolderImage[] = [];
  let read = 0;
  for (const image of images) {
    if (read >= limits.images) { skipped.push({ name: image.name, reason: `too many images (the first ${limits.images} were read)` }); continue; }
    let info: ReturnType<typeof imageHeader>;
    try { info = imageHeader(await readHead(image.path, Math.min(HEADER_BYTES, Math.max(image.size, 1)))); }
    catch { info = null; }
    if (!info) { skipped.push({ name: image.name, reason: 'an image whose size could not be read' }); continue; }
    read++;
    const stem = basename(image.name, extname(image.name)), n = number(image.name);
    const prompt = promptText.get(stem);
    const item: FolderImage = { name: image.name, path: image.path, ...info, role: 'other', guess: elementGuess(image.name),
      ...(n !== null ? { number: n } : {}), ...(prompt ? { prompt: promptSubject(prompt) } : {}) };
    if (!goal && isGoal(image.name)) goal = { ...item, role: 'goal', guess: 'Goal image' };
    else if (n !== null) elements.push({ ...item, role: 'element' });
    else others.push(item);
  }
  const folderTexts: FolderText[] = [];
  for (const text of texts) {
    let chars = 0;
    try { chars = (await readFile(text.path, 'utf8')).length; }
    catch { skipped.push({ name: text.name, reason: 'could not be read' }); continue; }
    folderTexts.push({ name: text.name, path: text.path, kind: textKind(text.name), chars });
  }
  const promptsByName: Record<string, string> = Object.fromEntries([...promptText].map(([stem, prompt]) => [stem, promptSubject(prompt)]));
  return { root, goal, ...(goal ? { goal_source: picked ? 'chosen' as const : 'name' as const } : {}), elements, others, texts: folderTexts, prompts: promptsByName, skipped };
}

/** The images the artist may choose as the goal, by folder-relative name: the goal, the elements in order, the others. */
export function goalChoices(index: Pick<FolderIndex, 'goal' | 'elements' | 'others'>): string[] {
  return [...(index.goal ? [index.goal.name] : []), ...index.elements.map(e => e.name), ...index.others.map(o => o.name)];
}

/** "use 05-modern-skyline.png as the goal", "make skies.png the goal image", "set the goal to …": the one folder image (by
 * its name, file name or stem) a typed message makes the goal, or null. It needs a verb that chooses (use, choose, pick,
 * take, make; set, switch, change … to) and the goal words closing the clause, so a painting instruction that only
 * mentions the goal ("paint 03-tower.png as the goal shows it") chooses nothing; so does a negated request, or a slot that
 * names no image or two. */
export function goalNamed(text: string, images: readonly string[]): string | null {
  const said = fold(String(text ?? ''));
  const goal = '(?:the\\s+|my\\s+|our\\s+)?(?:new\\s+)?(?:goal|target)(?:\\s+(?:image|picture))?';
  const end = '\\s*(?=[!?;,]|\\.(?:\\s|$)|$)';             // the clause ends there (a full stop inside a file name does not end it)
  const forms = [
    new RegExp(`\\b(?:use|choose|pick|take)\\s+(.+?)\\s+as\\s+${goal}${end}`, 'u'),
    new RegExp(`\\bmake\\s+(.+?)\\s+(?:as\\s+)?${goal}${end}`, 'u'),
    new RegExp(`\\b(?:set|switch|change)\\s+${goal}\\s+to\\s+(.+?)${end}`, 'u'),
  ];
  for (const form of forms) {
    const found = form.exec(said);
    if (!found) continue;
    const before = said.slice(0, found.index), clause = before.slice(Math.max(-1, ...[...before.matchAll(/[.!?;,](?=\s|$)|\n/g)].map(m => m.index)) + 1);
    if (NEGATED.test(clause)) return null;
    const slot = found[1] ?? '';
    const named = images.filter(name => [fold(name), fold(basename(name)), fold(basename(name, extname(name)))].filter(f => f.length >= 3)
      .some(f => new RegExp(`(?<![\\p{L}\\p{N}._/-])${escape(f)}(?![\\p{L}\\p{N}_-]|\\.[\\p{L}])`, 'u').test(slot)));
    return named.length === 1 ? named[0]! : null;
  }
  return null;
}

/** A text file of the folder (a brief, PLAN.md), read only if it resolves inside the folder; at most `max` characters. */
export async function readFolderText(root: string, name: string, max = 4000): Promise<string> {
  const base = await realpath(root), path = await realpath(join(base, name));
  if (!inside(base, path) || !(await lstat(path)).isFile()) throw new Error('That file is not inside the project folder.');
  const text = (await readHead(path, Math.min(FOLDER_LIMITS.textBytes, max * 4))).toString('utf8');
  return text.slice(0, max);
}

// Plan shape (the artist, 2026-10-23, after a live New Moscow chat): after an excellent underpainting, one step per
// element made the painter repaint each element by hand (typed strokes, stamps), which read as blobs, "hard graphic" and
// "mechanical stripes" and moved the canvas away from the goal. So a folder plan is the whole-picture underpainting,
// then the finish (finish-stage, approved 2026-10-24: soft areas blended, forms restroked from the goal), then accents on
// the whole picture, and then the artist says what to refine. Refine to the goal between the finish and the accents
// (finish-stage goal 8, the artist 2026-10-24: "i want the end result where our accents and finishes make it move eventually
// to the final"): the host's loop of fine finishes and accents on the regions still furthest from the goal (refine-goal.ts). An element's step is added only when the artist asks for it
// (by name, or by adding the step); the element images stay attached as references.
export type FolderStep = { title: string; done_when: string; scope: string };
export type FolderStepKind = 'underpainting' | 'finish' | 'refine' | 'accents' | 'element' | 'whole';
export const UNDERPAINTING_STEP = 'Underpainting from the goal image';
export const FINISH_STEP = 'Finish';
export const REFINE_STEP = 'Refine to the goal';
export const ACCENTS_STEP = 'Accents';
const WHOLE = 'whole composition';

/** The plan a folder starts with: the underpainting from the goal image, the finish, refine to the goal, then accents on the whole picture. */
export function defaultFolderSteps(): FolderStep[] {
  return [
    { title: UNDERPAINTING_STEP, done_when: 'The goal image’s colours and light are laid over the whole canvas, every element where the goal image has it.', scope: WHOLE },
    { title: FINISH_STEP, done_when: 'The soft areas (sky, mist, water) are blended smooth and the forms are painted in strokes that follow them, from the goal image, on the whole picture.', scope: WHOLE },
    { title: REFINE_STEP, done_when: 'Every part of the picture is close to the goal image at full size: its forms, windows and edges as crisp as the goal shows them.', scope: WHOLE },
    { title: ACCENTS_STEP, done_when: 'The lights, darks and fine detail the goal image shows are crisp on the whole picture, in the underpainting’s own paint.', scope: WHOLE },
  ];
}

/** An element's step, added when the artist asks for that element: its scope is the element's file. */
export function elementStep(name: string, guess: string): FolderStep {
  return { title: guess.slice(0, 200), done_when: `${guess} is refined in its place as the goal image shows it, its look from ${basename(name)}.`, scope: name };
}

/** What a folder plan step paints: an element (its scope is an image), accents, the finish (the default step's own title,
 * exactly: an older PLAN.md's "Finishing touches" or "Finish the underpainting" keep their kinds), the underpainting, or
 * another whole step. */
export function folderStepKind(step: { title: string; scope?: string }): FolderStepKind {
  if (step.scope && IMAGE_TYPES.has(extname(step.scope.trim()).toLowerCase())) return 'element';
  if (/\baccents?\b/i.test(step.title)) return 'accents';
  if (step.title.trim().toLowerCase() === FINISH_STEP.toLowerCase()) return 'finish';
  if (step.title.trim().toLowerCase() === REFINE_STEP.toLowerCase()) return 'refine';
  if (/\bunderpaint|\bblock[- ]?in\b/i.test(step.title)) return 'underpainting';
  return 'whole';
}

const fold = (text: string) => text.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[‘’]/g, "'");
const words = (text: string) => fold(text).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** Last words too general to name an element alone ("the light is too harsh" is not "Street light"). */
const GENERIC = new Set(['light', 'lights', 'left', 'right', 'top', 'bottom', 'side', 'sides', 'area', 'areas', 'part', 'parts', 'thing', 'things',
  'front', 'back', 'middle', 'centre', 'center', 'background', 'foreground', 'detail', 'details', 'colour', 'color', 'shadow', 'shadows']);
/** A mention whose clause says not to work on it: "don't paint the sky", "leave the towers alone", "not the moon". */
const NEGATED = /\b(?:no|not|don'?t|do not|never|without|stop|avoid|leave|skip|except|apart from|ignore)\b/;
/** The elements a message names, in the folder's order: its name (the artist's or the guess), its file or file stem, or
 * the name's last word (singular or plural, three letters or more, not a general word like "light" or "left": "the
 * towers" names "Kremlin towers"). A mention counts only when its clause does not negate it (review B1). */
export function elementsNamed(text: string, elements: readonly { name: string; guess: string }[]): string[] {
  const said = fold(String(text ?? ''));
  const asked = (phrase: string) => {
    const pattern = new RegExp(`(?<![\\p{L}\\p{N}])${phrase}(?![\\p{L}\\p{N}])`, 'gu');
    for (const match of said.matchAll(pattern)) {
      const before = said.slice(0, match.index), clause = before.slice(Math.max(...[...'.!?;,\n'].map(c => before.lastIndexOf(c))) + 1);
      if (!NEGATED.test(clause)) return true;
    }
    return false;
  };
  return elements.filter(({ name, guess }) => {
    const phrase = words(guess), head = phrase.at(-1);
    const phrases = [phrase.map(escape).join('[^\\p{L}\\p{N}]+'), escape(fold(basename(name))), escape(fold(basename(name, extname(name))))];
    if (head && head.length >= 3 && !/^\d+$/.test(head) && !GENERIC.has(head)) phrases.push(escape(head.replace(/s$/, '')) + 's?');
    return phrases.some(p => p && asked(p));
  }).map(e => e.name);
}
