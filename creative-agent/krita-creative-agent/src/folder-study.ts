// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Folder study (openspec folder-study, approved by the artist 2026-10-24): a vision model reads each image of a project
// folder once and writes a short note (what it shows; where it sits in the goal image when it is part of it; its key
// colours, shapes and details; about 60-120 words), so the planner and painter know every image as text and open one
// only when they need it (view_reference). Luna keeps its yes/no judging; this does not replace it.
//
//   const study = new FolderStudy(host);                  // host: the chat folder, file reading, bounding, the reader
//   await study.run(images, { goal });                    // 4 at a time; a timeout and a failure per image
//   study.noteOf('04-kremlin-towers.png');                // the note, or null (not studied, or the image changed)
//   await study.studyOne(image, { goal });                // lazy: when the agent opens an image with no note
//
// Notes are kept in the chat's own data folder (folder-study.json; never in the artist's folder), keyed by the image's
// content hash, so an image is studied again only when it changes and a copy under another name costs nothing. A failed
// image is just not studied: it is retried when it is opened or studied again. Cost and latency go to the diagnostics
// (folder_study_image per image, folder_study per run), with a classified reason only (never a provider's message).
// Mechanism only: which images to study (studyTargets) and which model reads them (studyModelRoute) are the caller's
// policy. No .mjs imports (strict TypeScript).
import { createHash } from 'node:crypto';
import { readFile, rename, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

/** A folder of at most this many images is studied when it opens; a bigger one asks first (the choice card). */
export const SMALL_FOLDER = 20;
export const STUDY_CONCURRENCY = 4;
/** The long side an image is read at: the Pi resize cap. */
export const STUDY_SIDE = 2000;
/** The goal image sent beside an element, to place it: smaller, it only needs the layout. */
export const GOAL_CONTEXT_SIDE = 1024;
export const STUDY_TIMEOUT_MS = 90_000;
export const STUDY_FILE = 'folder-study.json';
/** The recommended vision model when neither the painter nor the planner reads images (measured 2026-10-24 by the
 * resolution probe: reads up to 2560 px, 10/10 at 2048 and 2560; about $0.0008 a 2048 px image). */
export const STUDY_MODEL = 'openrouter/qwen/qwen3-vl-235b-a22b-instruct';
/** Per image, before this chat has measured its own: qwen3-vl on the New Moscow fixture (13 images of 1448 x 1086 px,
 * 2026-10-24, scripts/folder-study-run.ts): $0.0078 and 36 s for all 13, 4 at a time; 4.6-12.6 s an image. */
export const STUDY_DEFAULTS: Readonly<{ cost: number; seconds: number }> = Object.freeze({ cost: 0.0006, seconds: 9 });
const MIN_WORDS = 12, MAX_WORDS = 160;

export type StudyChoice = 'plan' | 'all' | 'pick' | 'none';
export type StudyImage = { name: string; path: string; role: 'goal' | 'element' | 'other'; guess: string; prompt?: string };
export type Picture = { data: string; mimeType: string };
export type ReadRequest = { prompt: string; images: { label: string; picture: Picture }[]; signal: AbortSignal };
export type ReadReply = { text: string; cost: number; model: string };
export type StudyReader = (request: ReadRequest) => Promise<ReadReply>;
export type StudyNote = { note: string; model: string; at: string; ms: number; cost: number };
export type ImageState = 'studied' | 'not_studied' | 'studying' | 'excluded';
export type StudyState = 'idle' | 'running' | 'done' | 'stopped' | 'unavailable';
export type StudyStatus = { state: StudyState; total: number; done: number; failed: number; images: Record<string, ImageState> };
export type RunResult = { studied: number; failed: number; stopped: boolean; unavailable?: boolean };
export type StudyHost = {
  /** The chat's data folder (null: notes stay in memory). */
  directory(): string | null;
  readImage(path: string): Promise<Buffer>;
  /** The picture at most `side` px on its long side (the file itself when it is within that, or cannot be reduced). */
  picture(path: string, data: Buffer, side: number): Promise<Picture>;
  /** The model that reads the images, or null when none is connected that reads images. */
  reader(): Promise<StudyReader | null>;
  /** Something the panel shows changed (progress, a note). */
  changed(): void;
  record(event: Record<string, unknown>): void;
};
/** notes by key (an element's: its hash @ the goal's hash, since its note places it in that goal; the goal's: hash:goal);
 * names: each image's current key; failed: an image's failure for that key (retried only on demand); hashes: by path, with
 * the size and time they were read at, so a resumed chat reads no image again. */
type Saved = { notes: Record<string, StudyNote>; names: Record<string, string>; failed: Record<string, { key: string; reason: string }>;
  hashes: Record<string, { size: number; mtimeMs: number; hash: string }> };

/** Which images to study now (folder-relative names, in the folder's order), or null when a big folder must ask first.
 * At most SMALL_FOLDER images: all of them. More: the artist's choice: the goal and the images the plan's steps use
 * ('plan'), all, the ones picked, or none. Excluded images are never studied. */
export function studyTargets(names: readonly string[], { choice, picked = [], excluded = [], planFiles = [], goal = null }: {
  choice?: StudyChoice | null; picked?: readonly string[]; excluded?: readonly string[]; planFiles?: readonly string[]; goal?: string | null } = {}): string[] | null {
  const out = new Set(excluded), keep = (wanted: Iterable<string>) => { const w = new Set(wanted); return names.filter(n => w.has(n) && !out.has(n)); };
  if (names.length <= SMALL_FOLDER) return keep(names);
  if (!choice) return null;
  if (choice === 'all') return keep(names);
  if (choice === 'pick') return keep(picked);
  if (choice === 'plan') return keep([...(goal ? [goal] : []), ...planFiles]);
  return [];
}

/** One image's study cost with this model's price per million tokens (Pi's catalogue): the element (at most STUDY_SIDE,
 * about 1.6 MP here) and the goal beside it (GOAL_CONTEXT_SIDE), about 1400 px a token as qwen3-vl was measured (the New
 * Moscow run: $0.0006 an image at $0.21/M in, $1.9/M out), the request's words, and about 140 tokens of note. Null when
 * the model has no price (a local model, or one Pi does not price). */
export function modelImageCost(model: { cost?: { input?: number; output?: number } }, pixels = 1448 * 1086 + 1024 * 768): number | null {
  const input = model.cost?.input, output = model.cost?.output;
  if (typeof input !== 'number' || typeof output !== 'number' || (!input && !output)) return null;
  return Math.round(((pixels / 1400 + 300) * input + 140 * output) / 1e6 * 1e6) / 1e6;
}

/** What studying `images` costs and takes, 4 at a time: per image this chat's measured averages, else STUDY_DEFAULTS. */
export function studyEstimate(images: number, measured?: { cost: number; seconds: number } | null): { images: number; cost: number; seconds: number } {
  const per = measured ?? STUDY_DEFAULTS;
  return { images, cost: Math.round(images * per.cost * 1e6) / 1e6, seconds: Math.ceil(images / STUDY_CONCURRENCY) * Math.round(per.seconds) };
}

/** The reply as one paragraph of plain prose: markup and a "Note:" preamble go; a note over MAX_WORDS ends at its last
 * full sentence within them; one under MIN_WORDS is no note (null). */
export function cleanNote(text: string): string | null {
  let said = String(text ?? '').replace(/\r/g, '').split('\n').map(line => line.replace(/^\s*(?:[-*+>#]+|\d+[.)])\s*/, '')).join(' ');
  said = said.replace(/\*\*|__|`/g, '').replace(/^\s*(?:note|description|summary)\s*:\s*/i, '').replace(/\s+/g, ' ').trim();
  const words = said.split(' ').filter(Boolean);
  if (words.length < MIN_WORDS) return null;
  if (words.length <= MAX_WORDS) return said;
  const cut = words.slice(0, MAX_WORDS).join(' '), end = Math.max(cut.lastIndexOf('. '), cut.endsWith('.') ? cut.length - 1 : -1);
  return end > 0 ? cut.slice(0, end + 1) : cut + '…';
}

/** The request for one image's note. An element sent with the goal image is placed in it. */
export function studyPrompt(image: Pick<StudyImage, 'name' | 'role' | 'guess' | 'prompt'>, { goal }: { goal: boolean }): string {
  const plain = 'Write plain prose, one paragraph of 60-120 words, no lists, no headings, no preamble. Name colours as a painter would (deep ultramarine, warm amber), and say where things are (top left, lower third, centre).';
  const hint = image.prompt ? ` The folder's generation prompt for it said: "${image.prompt.slice(0, 300)}" (a hint; describe what the image shows).` : '';
  if (image.role === 'goal')
    return `IMAGE is the goal image of a painting project (${image.name}): the finished picture the painting follows. Write a note for a painter who cannot see it: what it shows, its layout (what is where), the light, the key colours and shapes.${hint} ${plain}`;
  const place = goal ? ' GOAL is the goal image of the project, smaller. Say where the element sits in the goal image (its rough position and size) if it is part of it, or that it is not in the goal.' : '';
  return `IMAGE is an element image of a painting project, ${image.name} (the artist calls it "${image.guess}").${place} Write a note for a painter who cannot see the image: what it shows${goal ? ', where it sits in the goal' : ''}, its key colours, shapes and details (edges, textures, lights).${hint} ${plain}`;
}

/** The first model that reads images: the painter's, the planner's, else the recommended vision model (when connected). */
export function studyModelRoute<M extends { input: readonly string[] }>({ painter, planner, fallback }: { painter?: M | null; planner?: M | null; fallback?: M | null }): M | null {
  return [painter, planner, fallback].find(m => m?.input?.includes('image')) ?? null;
}

export type VisionModel = { provider: string; id: string; input: readonly string[] };
type ReplyMessage = { content: ReadonlyArray<{ type: string; text?: string }>; usage?: { cost?: { total?: number } }; stopReason?: string };
type StudyContext = { messages: { role: 'user'; timestamp: number; content: ({ type: 'text'; text: string } | { type: 'image'; data: string; mimeType: string })[] }[] };
/** Pi's model runtime as the study uses it (ModelRuntime.completeSimple, as scripts/resolution-probe.ts calls models). */
export type StudyModels = { completeSimple(model: VisionModel, context: StudyContext, options: { signal: AbortSignal; maxTokens?: number }): Promise<ReplyMessage> };

/** A reader for one model through Pi: the labelled images, then the request; the reply's text and cost. A provider error
 * is thrown as 'provider_error' (its message may hold details that are not for the record). */
export function piReader(models: StudyModels, model: VisionModel): StudyReader {
  return async ({ prompt, images, signal }) => {
    const reply = await models.completeSimple(model, { messages: [{ role: 'user', timestamp: Date.now(), content: [
      ...images.flatMap(i => [{ type: 'text' as const, text: i.label }, { type: 'image' as const, data: i.picture.data, mimeType: i.picture.mimeType }]),
      { type: 'text' as const, text: prompt }] }] }, { signal, maxTokens: 600 });
    if (reply.stopReason === 'error' || reply.stopReason === 'aborted') throw new Error('provider_error');
    const text = reply.content.filter(c => c.type === 'text').map(c => c.text ?? '').join('').trim();
    if (!text) throw new Error('empty_reply');
    return { text, cost: reply.usage?.cost?.total ?? 0, model: `${model.provider}/${model.id}` };
  };
}

const sha256 = (data: Buffer) => createHash('sha256').update(data).digest('hex');
const timeoutError = () => Object.assign(new Error('timeout'), { name: 'TimeoutError' });
/** A promise that rejects when `signal` aborts, whether or not the work listens to it. */
function abortable<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener('abort', abort, { once: true });
    work.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

export class FolderStudy {
  private readonly host: StudyHost;
  private readonly timeoutMs: number;
  private saved: Saved = { notes: {}, names: {}, failed: {}, hashes: {} };
  private loaded: Promise<void> | null = null;
  private saving: Promise<void> = Promise.resolve();
  private readonly studying = new Map<string, Promise<string | null>>();
  private readonly controllers = new Set<AbortController>();
  private state: StudyState = 'idle';
  private total = 0;
  private done = 0;
  private current: Promise<RunResult> | null = null;
  private epoch = 0;                                  // Stop's count: a run queued before a Stop never starts
  private slots = STUDY_CONCURRENCY;                  // one cap for the runs and the lazy studies
  private readonly waiting: (() => void)[] = [];
  private goalPicture: { key: string; picture: Promise<Picture> } | null = null;

  constructor(host: StudyHost, { timeoutMs = STUDY_TIMEOUT_MS }: { timeoutMs?: number } = {}) { this.host = host; this.timeoutMs = timeoutMs; }

  /** The notes kept in the chat folder, read once. */
  load(): Promise<void> {
    this.loaded ??= (async () => {
      const directory = this.host.directory();
      if (!directory) return;
      try {
        const saved = JSON.parse(await readFile(join(directory, STUDY_FILE), 'utf8')) as Partial<Saved>;
        if (saved && typeof saved.notes === 'object' && typeof saved.names === 'object')
          this.saved = { notes: { ...saved.notes }, names: { ...saved.names }, failed: { ...(saved.failed ?? {}) }, hashes: { ...(saved.hashes ?? {}) } };
      } catch { /* none yet, or unreadable: studied again */ }
    })();
    return this.loaded;
  }

  private save(): Promise<void> {
    const directory = this.host.directory();
    if (!directory) return Promise.resolve();
    const text = JSON.stringify(this.saved), path = join(directory, STUDY_FILE);
    this.saving = this.saving.then(async () => {
      const temporary = `${path}.${process.pid}.tmp`;
      await writeFile(temporary, text); await rename(temporary, path);
    }).catch(() => {});
    return this.saving;
  }

  private async acquire(): Promise<void> {
    if (this.slots > 0) { this.slots--; return; }
    await new Promise<void>(resolve => this.waiting.push(resolve));
  }
  private release(): void { const next = this.waiting.shift(); if (next) next(); else this.slots++; }

  /** The file's content hash: the kept one while its size and time are unchanged, else read (and `data` kept for the caller). */
  private async hashOf(path: string): Promise<{ hash: string; data?: Buffer }> {
    const info = await stat(path), known = Object.hasOwn(this.saved.hashes, path) ? this.saved.hashes[path] : undefined;
    if (known && known.size === info.size && known.mtimeMs === info.mtimeMs) return { hash: known.hash };
    const data = await this.host.readImage(path), hash = sha256(data);
    this.saved.hashes[path] = { size: info.size, mtimeMs: info.mtimeMs, hash };
    return { hash, data };
  }
  /** The key of an image's note: the goal by its own hash; an element by its hash and the goal's (where it sits). */
  private static key(hash: string, image: StudyImage, goalHash: string | null): string {
    return image.role === 'goal' ? `${hash}:goal` : goalHash ? `${hash}@${goalHash}` : hash;
  }
  private async keys(images: readonly StudyImage[], goal: StudyImage | null): Promise<Map<string, string>> {
    const goalHash = goal ? await this.hashOf(goal.path).then(h => h.hash, () => null) : null, out = new Map<string, string>();
    for (const image of images) {
      try { out.set(image.name, FolderStudy.key((await this.hashOf(image.path)).hash, image, goalHash)); } catch { /* unreadable: not studied */ }
    }
    return out;
  }

  /** The note of the image with this name, or null. */
  noteOf(name: string): string | null {
    const key = Object.hasOwn(this.saved.names, name) ? this.saved.names[name] : undefined;
    return key && Object.hasOwn(this.saved.notes, key) ? this.saved.notes[key]!.note : null;
  }

  /** This chat's averages per image (cost, seconds), or null before any note. */
  measured(): { cost: number; seconds: number } | null {
    const notes = Object.values(this.saved.notes);
    if (!notes.length) return null;
    return { cost: notes.reduce((s, n) => s + n.cost, 0) / notes.length, seconds: notes.reduce((s, n) => s + n.ms, 0) / notes.length / 1000 };
  }

  /** Each name's state for the panel; `excluded` names show as excluded. The run's counts are its own. */
  status(names: readonly string[], { excluded = [] }: { excluded?: readonly string[] } = {}): StudyStatus {
    const out = new Set(excluded);
    const images = Object.fromEntries(names.map(n => [n, out.has(n) ? 'excluded' as const : this.studying.has(n) ? 'studying' as const
      : this.noteOf(n) ? 'studied' as const : 'not_studied' as const]));
    return { state: this.state, total: this.total, done: this.done,
      failed: names.filter(n => Object.hasOwn(this.saved.failed, n) && !this.noteOf(n) && !out.has(n)).length, images };
  }

  /** The images' content and the goal checked again (by size and time, read only when changed): a note for another picture
   * or another goal is no longer the image's (it stays kept for them); a failure for another picture is forgotten. */
  async refresh(images: readonly StudyImage[], { goal }: { goal?: StudyImage | null } = {}): Promise<void> {
    await this.load();
    const keys = await this.keys(images, goal === undefined ? images.find(i => i.role === 'goal') ?? null : goal);
    let changed = false;
    for (const image of images) {
      const key = keys.get(image.name), known = Object.hasOwn(this.saved.names, image.name) ? this.saved.names[image.name] : undefined;
      const failed = Object.hasOwn(this.saved.failed, image.name) ? this.saved.failed[image.name] : undefined;
      if (failed && failed.key !== key) { delete this.saved.failed[image.name]; changed = true; }
      if (!key || known === key) continue;
      if (Object.hasOwn(this.saved.notes, key)) this.saved.names[image.name] = key; else delete this.saved.names[image.name];
      changed = true;
    }
    await this.save();
    if (changed) this.host.changed();
  }

  /** The run in progress, if any. */
  running(): Promise<RunResult> | null { return this.current; }

  /** Study the images that have no note yet, STUDY_CONCURRENCY at a time (with any lazy study); `allowed` is asked again
   * before each image (one excluded meanwhile is skipped). An image that failed is left for an explicit ask (`retry`, or
   * studyOne). A second call while one runs studies its images after it, unless Stop comes first. */
  async run(images: readonly StudyImage[], { goal = null, allowed, retry = false }: { goal?: StudyImage | null; allowed?: (name: string) => boolean; retry?: boolean } = {}): Promise<RunResult> {
    const epoch = this.epoch;
    if (!this.current) this.state = 'running';
    while (this.current) await this.current.catch(() => {});
    if (epoch !== this.epoch) return { studied: 0, failed: 0, stopped: true };
    const work = this.runNow(images, goal, allowed, retry);
    this.current = work;
    try { return await work; } finally { if (this.current === work) this.current = null; }
  }

  private async runNow(images: readonly StudyImage[], goal: StudyImage | null, allowed: ((name: string) => boolean) | undefined, retry: boolean): Promise<RunResult> {
    await this.load();
    const reader = await this.host.reader();
    if (!reader) { this.state = 'unavailable'; this.host.changed(); return { studied: 0, failed: 0, stopped: false, unavailable: true }; }
    await this.refresh(images, { goal });
    const queue = images.filter(i => !this.noteOf(i.name) && (retry || !Object.hasOwn(this.saved.failed, i.name))), controller = new AbortController();
    this.controllers.add(controller);
    this.state = 'running'; this.total = queue.length; this.done = 0; this.host.changed();
    const started = Date.now();
    let studied = 0, failed = 0, cost = 0;
    const models = new Set<string>();
    const worker = async () => {
      for (let next = queue.shift(); next && !controller.signal.aborted; next = queue.shift()) {
        if (allowed && !allowed(next.name)) { this.done++; this.host.changed(); continue; }   // excluded since the run began
        const outcome = await this.studyImage(next, goal, reader, controller.signal);
        if (outcome.note) { studied++; cost += outcome.cost; if (outcome.model) models.add(outcome.model); } else if (outcome.reason !== 'stopped') failed++;
        this.done++; this.host.changed();
      }
    };
    try { await Promise.all(Array.from({ length: Math.min(STUDY_CONCURRENCY, queue.length) }, worker)); }
    finally { this.controllers.delete(controller); }
    const stopped = controller.signal.aborted;
    this.state = stopped ? 'stopped' : 'done'; this.host.changed();
    if (this.total) this.host.record({ type: 'folder_study', images: this.total, studied, failed, stopped, ms: Date.now() - started,
      cost: Math.round(cost * 1e6) / 1e6, models: [...models] });
    return { studied, failed, stopped };
  }

  /** Stop the study: requests in flight are abandoned, a run waiting its turn never starts; what is studied stays. */
  stop(): void {
    this.epoch++;
    for (const controller of this.controllers) controller.abort(Object.assign(new Error('stopped'), { name: 'AbortError' }));
  }

  /** The note of one image, studied now when it has none (the lazy study, when the agent opens an image; a failure is
   * retried). Joins a study of it already under way. Null when it cannot be studied (no reader, a failure). */
  async studyOne(image: StudyImage, { goal = null }: { goal?: StudyImage | null } = {}): Promise<string | null> {
    await this.load();
    await this.refresh([image], { goal });
    const known = this.noteOf(image.name);
    if (known) return known;
    const pending = this.studying.get(image.name);
    if (pending) return pending;
    const reader = await this.host.reader();
    if (!reader) return null;
    const controller = new AbortController();
    this.controllers.add(controller);
    try { return (await this.studyImage(image, goal, reader, controller.signal)).note; }
    finally { this.controllers.delete(controller); this.host.changed(); }
  }

  /** The goal sent beside the elements, made once for the goal as it is. */
  private contextPicture(goal: StudyImage, hash: string): Promise<Picture> {
    if (this.goalPicture?.key !== hash) {
      const picture = this.host.readImage(goal.path).then(data => this.host.picture(goal.path, data, GOAL_CONTEXT_SIDE));
      picture.catch(() => { if (this.goalPicture?.picture === picture) this.goalPicture = null; });
      this.goalPicture = { key: hash, picture };
    }
    return this.goalPicture.picture;
  }

  private async studyImage(image: StudyImage, goal: StudyImage | null, reader: StudyReader, stop: AbortSignal):
    Promise<{ note: string | null; cost: number; model?: string; reason?: string }> {
    const pending = this.studying.get(image.name);
    if (pending) return { note: await pending, cost: 0 };
    let outcome: { note: string | null; cost: number; model?: string; reason?: string } = { note: null, cost: 0 };
    const work = (async () => {
      await this.acquire();
      const started = Date.now(), timer = new AbortController(), clock = setTimeout(() => timer.abort(timeoutError()), this.timeoutMs);
      const signal = AbortSignal.any([stop, timer.signal]);
      let key: string | undefined;
      try {
        if (stop.aborted) throw stop.reason;
        const withGoal = image.role !== 'goal' && !!goal && goal.path !== image.path;
        const goalHash = withGoal ? (await this.hashOf(goal!.path)).hash : null;
        const own = await this.hashOf(image.path), data = own.data ?? await this.host.readImage(image.path);
        key = FolderStudy.key(own.hash, image, goalHash);
        if (Object.hasOwn(this.saved.notes, key)) {                // the same picture under another name, or studied before
          this.saved.names[image.name] = key; delete this.saved.failed[image.name]; await this.save();
          outcome = { note: this.saved.notes[key]!.note, cost: 0 };
          return outcome.note;
        }
        const pictures = [{ label: 'IMAGE:', picture: await this.host.picture(image.path, data, STUDY_SIDE) }];
        if (withGoal) pictures.push({ label: 'GOAL:', picture: await this.contextPicture(goal!, goalHash!) });
        const reply = await abortable(reader({ prompt: studyPrompt(image, { goal: withGoal }), images: pictures, signal }), signal);
        const note = cleanNote(reply.text), ms = Date.now() - started;
        if (!note) {
          this.saved.failed[image.name] = { key, reason: 'unusable_note' }; await this.save();
          this.host.record({ type: 'folder_study_image', name: image.name, ok: false, reason: 'unusable_note', ms, cost: reply.cost, model: reply.model });
          outcome = { note: null, cost: reply.cost, model: reply.model, reason: 'unusable_note' };
          return null;
        }
        this.saved.notes[key] = { note, model: reply.model, at: new Date().toISOString(), ms, cost: reply.cost };
        this.saved.names[image.name] = key; delete this.saved.failed[image.name];
        await this.save();
        this.host.record({ type: 'folder_study_image', name: image.name, ok: true, ms, cost: reply.cost, model: reply.model, words: note.split(' ').length });
        outcome = { note, cost: reply.cost, model: reply.model };
        return note;
      } catch (error) {
        const reason = stop.aborted ? 'stopped' : timer.signal.aborted ? 'timeout' : ['provider_error', 'empty_reply'].includes((error as Error)?.message) ? (error as Error).message : 'request_failed';
        if (reason !== 'stopped') { this.saved.failed[image.name] = { key: key ?? '', reason }; await this.save(); }
        this.host.record({ type: 'folder_study_image', name: image.name, ok: false, reason, ms: Date.now() - started, cost: 0 });
        outcome = { note: null, cost: 0, reason };
        return null;
      } finally { clearTimeout(clock); this.release(); }
    })();
    this.studying.set(image.name, work);
    this.host.changed();
    try { await work; } finally { this.studying.delete(image.name); }
    return outcome;
  }
}
