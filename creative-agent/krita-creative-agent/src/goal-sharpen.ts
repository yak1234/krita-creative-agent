// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Sharpen goal (the artist, 2026-10-24): a goal image much smaller than the canvas cannot give the painting detail it does
// not have (New Moscow: 1448 x 1086 on 6000 x 4500, 4.1x). When the project folder's goal would be enlarged more than
// ENLARGEMENT onto the canvas, the chat offers once per goal (by content hash) to sharpen it 4x on this computer with
// Real-ESRGAN x4plus (upscale/), nothing uploaded. The setting "Sharpen small goal images" (settings-schema.mjs
// sharpen_goal) decides: Ask (the default) offers a card, Always sharpens and uses it without asking, Never does neither.
//   offer card [Sharpen] [Use as is]  ->  progress on the Now card (Stop cancels)  ->  side by side [Use sharpened] [Keep original]
// - The result is cached in the chat folder (goal-sharpen/), never in the artist's folder. The goal reference becomes the
//   sharpened picture, whole when the reference tools read it (TRANSFER_PIXELS and TRANSFER_BYTES, reference-limits.ts),
//   else the largest copy they do: the same reference id and the same placement (it is the same picture, larger).
// - The artist's answer is remembered per goal content in the companion's data folder (goal-sharpen.json), so a new chat
//   of the same goal asks nothing: a "sharpened" answer sharpens again by itself, "original" never offers again.
// - A failure or a Stop keeps the original with a message; a Stop offers the card again.
// - The swap waits while a move paints (it changes what the painter reads): it happens when the run ends.
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { TRANSFER_BYTES, TRANSFER_PIXELS } from './closeups.ts';
import { downloadBytes, downloadModel, modelDirectory, modelReady, type ModelSpec } from './shapes/model.ts';
import { tilePlan } from './upscale/image.ts';
import { MAX_INPUT_PIXELS, TILE_PAD } from './upscale/core.ts';
import { SCALE, TILE, UPSCALE_MODEL } from './upscale/model.ts';
import { UpscaleError, upscaleService, type UpscaleReply, type UpscaleService } from './upscale/index.ts';

export type SharpenSetting = 'ask' | 'always' | 'never';
export const ENLARGEMENT = 2;                    // more than this x onto the canvas, and the goal is offered
/** A goal of more pixels than this is not offered: sharpened 4x and reduced to the reference tools' TRANSFER_PIXELS, it would
 * gain too little (at most this is half of them, so the painter reads it at least 1.4x larger). */
export const OFFER_PIXELS = Math.min(MAX_INPUT_PIXELS, TRANSFER_PIXELS / 2);
export const SHARPEN_ANSWERS = { offer: ['Sharpen', 'Use as is'], review: ['Use sharpened', 'Keep original'] } as const;
const CHOICES_FILE = 'goal-sharpen.json';

export type Sharpened = { from: { path: string; width: number; height: number; sha256: string; mimeType?: string }; model: string; revision: string;
  scale: number; full: string; at: string };
export type GoalReference = { id: string; path: string; width?: number; height?: number; mimeType?: string; source?: string; role?: string;
  part_kind?: string; name?: string; folder_name?: string; sharpened?: Sharpened; mass_map?: unknown };
type Result = { reference: { path: string; width: number; height: number; mimeType: string; bytes: number }; full: { path: string; width: number; height: number };
  compare: string; ms: number; peak_mb: number; provider: string; tiles: number };
export type SharpenRecord = { state: 'offered' | 'running' | 'review' | 'used' | 'kept' | 'failed' | 'cancelled'; id: string; name?: string; factor?: number;
  result?: Result; pending_use?: boolean; auto?: boolean; message?: string };
type Study = { id: string; directory: string; references: GoalReference[]; goal_sharpen?: Record<string, SharpenRecord> };
export type SharpenHost = {
  readonly study: Study | null | undefined;
  canvas(): { width?: unknown; height?: unknown } | null | undefined;
  setting(): SharpenSetting;
  busy(): boolean;
  dataDir(): string | undefined;
  emit(event: Record<string, unknown>): void;
  persist(): Promise<unknown>;
  publish(): void;
  callNative(operation: string, params: Record<string, unknown>): Promise<unknown>;
  /** The goal reference's pixels changed: the likeness grid, mass map and folder card follow. */
  goalChanged(): void;
  platform?: NodeJS.Platform;
};
type Download = (options: { directory: string; spec: ModelSpec; onProgress?: (done: number, total: number) => void; signal?: AbortSignal }) => Promise<void>;

/** How many times larger the goal is drawn onto the canvas: the whole goal over the whole canvas (trimmed to its proportions). */
export function enlargement(goal: { width?: number; height?: number }, canvas: { width?: unknown; height?: unknown } | null | undefined): number {
  const gw = Number(goal.width), gh = Number(goal.height), cw = Number(canvas?.width), ch = Number(canvas?.height);
  return gw > 0 && gh > 0 && cw > 0 && ch > 0 ? Math.max(cw / gw, ch / gh) : 0;
}

/** The project folder's goal reference (a whole picture, not a part), or null. */
export const folderGoal = (references: readonly GoalReference[] | undefined) =>
  references?.find(r => r.source === 'folder' && r.role === 'reference' && !r.part_kind) ?? null;

type Rect = [number, number, number, number];
const isRect = (v: unknown): v is Rect => Array.isArray(v) && v.length === 4 && v.every(n => typeof n === 'number' && Number.isFinite(n));

/** A source rect the painter wrote in the goal's pixels from before it was sharpened, in the sharpened pixels; null when it
 * is not one. Stale means: the old picture's whole rect, or a rect an earlier transfer of the old picture used (the painter
 * repeating it). Anything else is taken as written in the new pixels (the context says the size changed). */
export function staleGoalSource(source: unknown, reference: Pick<GoalReference, 'id' | 'width' | 'height' | 'sharpened'>,
  earlier: readonly { reference_hash?: string; recipe?: { reference_id?: string; source?: unknown } }[]): Rect | null {
  const was = reference.sharpened?.from;
  if (!was || !isRect(source) || !reference.width || !reference.height) return null;
  const same = (a: unknown) => isRect(a) && a.every((v, i) => v === source[i]);
  const stale = same([0, 0, was.width, was.height]) || earlier.some(job => job.reference_hash === was.sha256 && job.recipe?.reference_id === reference.id && same(job.recipe.source));
  if (!stale) return null;
  const k = reference.width / was.width, [x, y, w, h] = source.map(v => Math.round(v * k)) as Rect;
  return [Math.min(x, reference.width - 1), Math.min(y, reference.height - 1), Math.min(w, reference.width - x), Math.min(h, reference.height - y)];
}

/** The file a transfer job reads: one begun on the goal before it was sharpened resumes on that picture (its plan was
 * built from it), every other on the reference as it is now. */
export function goalSourceFile(reference: Pick<GoalReference, 'path' | 'sharpened'>, jobHash?: string): string {
  return jobHash && reference.sharpened && jobHash === reference.sharpened.from.sha256 ? reference.sharpened.from.path : reference.path;
}

/** What the painter is told of a sharpened goal: its pixels changed size, so rects in the old pixels scale by `scale`. */
export function sharpenedContext(reference: Pick<GoalReference, 'width' | 'height' | 'sharpened'>): Record<string, unknown> | undefined {
  const was = reference.sharpened?.from;
  if (!was) return undefined;
  const scale = Math.round((reference.width ?? 0) / was.width * 10000) / 10000;
  return { width: reference.width, height: reference.height, was: [was.width, was.height], scale,
    note: `The goal image was sharpened: its pixels are now ${reference.width} x ${reference.height} (they were ${was.width} x ${was.height}). Give its source rects in the new pixels: multiply any earlier rect by ${scale}.` };
}

/** About how long sharpening takes, in seconds rounded to 5: tiles at the last measured speed (else a cautious guess), the
 * model's load and the files. */
export function estimateSeconds(width: number, height: number, { msPerTile, platform = process.platform }: { msPerTile?: number; platform?: NodeJS.Platform } = {}): number {
  const tiles = tilePlan(width, height, { tile: TILE, pad: TILE_PAD }).length;
  const perTile = msPerTile ?? (platform === 'darwin' ? 80 : 1500);
  const seconds = tiles * perTile / 1000 + 4 + width * height * SCALE * SCALE / 8e6;
  return Math.max(5, Math.round(seconds / 5) * 5);
}

const sha256 = (data: Buffer) => createHash('sha256').update(data).digest('hex');
const exists = async (path: string) => !!(await stat(path).catch(() => null));

export function goalSharpener(host: SharpenHost, { spec = UPSCALE_MODEL, download = downloadModel as Download, service }: { spec?: ModelSpec; download?: Download; service?: UpscaleService } = {}) {
  const platform = host.platform ?? process.platform, where = platform === 'darwin' ? 'this Mac' : 'this computer';
  const size_mb = Math.round(downloadBytes(spec) / 1e6);
  const hashes = new Map<string, { stamp: string; sha: string }>();
  let running: { sha: string; controller: AbortController; done: Promise<void> } | null = null, shown = new Set<string>(), shownFor: Study | null = null;

  const dataDir = () => host.dataDir();
  const modelDir = () => { const dir = dataDir(); if (!dir) throw new UpscaleError('model', 'Sharpening needs the companion’s data folder, and none is set.'); return modelDirectory(dir, spec); };
  const sharpen = service ?? upscaleService({ modelDir: async () => modelDir() });

  async function choices(): Promise<{ choices: Record<string, { choice: 'sharpened' | 'original'; at: string }>; ms_per_tile?: number }> {
    const dir = dataDir();
    if (!dir) return { choices: {} };
    try { const saved = JSON.parse(await readFile(join(dir, CHOICES_FILE), 'utf8')); return { choices: saved.choices ?? {}, ...(Number(saved.ms_per_tile) > 0 ? { ms_per_tile: Number(saved.ms_per_tile) } : {}) }; }
    catch { return { choices: {} }; }
  }
  async function remember(change: { sha?: string; choice?: 'sharpened' | 'original'; ms_per_tile?: number }) {
    const dir = dataDir();
    if (!dir) return;
    const saved = await choices();
    if (change.sha && change.choice) saved.choices[change.sha] = { choice: change.choice, at: new Date().toISOString() };
    if (change.ms_per_tile) saved.ms_per_tile = change.ms_per_tile;
    await mkdir(dir, { recursive: true });
    const temporary = join(dir, CHOICES_FILE + '.' + process.pid);
    await writeFile(temporary, JSON.stringify({ version: 1, ...saved }, null, 2));
    await rename(temporary, join(dir, CHOICES_FILE));
  }
  async function hashOf(path: string): Promise<string> {
    const info = await stat(path), stamp = `${info.size}:${info.mtimeMs}`, known = hashes.get(path);
    if (known?.stamp === stamp) return known.sha;
    const sha = sha256(await readFile(path));
    hashes.set(path, { stamp, sha });
    return sha;
  }
  const records = (study: Study) => (study.goal_sharpen ??= {});
  const say = (message: string) => host.emit({ type: 'action', seconds: 0, message });
  /** A card once per chat and record (the panel keeps it); a reopened chat shows it again. */
  function show(study: Study, key: string, event: Record<string, unknown>) {
    if (shownFor !== study) { shown = new Set(); shownFor = study; }
    if (shown.has(key)) return;
    shown.add(key); host.emit(event);
  }
  const offerEvent = (record: SharpenRecord, goal: GoalReference, ready: boolean, msPerTile?: number) => ({
    type: 'goal_sharpen_offer', id: record.id, name: goal.name ?? 'the goal image', factor: record.factor,
    seconds: estimateSeconds(goal.width ?? 0, goal.height ?? 0, { platform, ...(msPerTile ? { msPerTile } : {}) }), download_mb: ready ? 0 : size_mb,
    model: 'Real-ESRGAN x4plus', licence: spec.licence, options: [...SHARPEN_ANSWERS.offer],
    message: `Your goal image is ${(record.factor ?? 0).toFixed(1)}x smaller than the canvas, so detail will blur. Sharpen it 4x on ${where} `
      + `(about ${estimateSeconds(goal.width ?? 0, goal.height ?? 0, { platform, ...(msPerTile ? { msPerTile } : {}) })} s, nothing uploaded)?`
      + (ready ? '' : ` The first time downloads the sharpening model, Real-ESRGAN x4plus (${spec.licence}, ${size_mb} MB).`) });
  const reviewEvent = (record: SharpenRecord) => {
    const r = record.result!;
    return { type: 'goal_sharpen_review', id: record.id, image_path: r.compare, options: [...SHARPEN_ANSWERS.review],
      width: r.full.width, height: r.full.height, reference: [r.reference.width, r.reference.height],
      question: `Sharpened 4x on ${where} in ${Math.max(1, Math.round(r.ms / 1000))} s (${r.full.width} x ${r.full.height}). Left: your goal image enlarged; `
        + `right: sharpened, on its most detailed part. ${r.reference.width === r.full.width ? 'The painter reads it at full size.' : `The painter reads it at ${r.reference.width} x ${r.reference.height}, the most its reference tools take.`} Use the sharpened goal?` };
  };

  /** The goal reference's state for the panel's folder card. */
  function status(): { state: string; factor?: number; sharpened?: { width: number; height: number; full: [number, number] } } | null {
    const study = host.study, goal = folderGoal(study?.references);
    if (!study || !goal) return null;
    if (goal.sharpened) return { state: 'used', sharpened: { width: goal.width ?? 0, height: goal.height ?? 0, full: [goal.sharpened.from.width * goal.sharpened.scale, goal.sharpened.from.height * goal.sharpened.scale] } };
    const record = Object.values(study.goal_sharpen ?? {}).find(r => r.name === goal.path);
    return record ? { state: record.state, ...(record.factor ? { factor: record.factor } : {}) } : null;
  }

  /** Offers, sharpens by itself, or does nothing, as the setting, the goal's size and earlier answers say. Never throws. */
  async function check(): Promise<void> {
    try {
      const study = host.study, goal = folderGoal(study?.references);
      if (!study || !goal || goal.sharpened || host.setting() === 'never') return;
      const factor = enlargement(goal, host.canvas());
      if (!(factor > ENLARGEMENT) || (goal.width ?? 0) * (goal.height ?? 0) > OFFER_PIXELS) return;
      const sha = await hashOf(goal.path), all = records(study), saved = await choices(), known = all[sha];
      if (known?.state === 'review' && known.result) { show(study, known.id + ':review', reviewEvent(known)); return; }
      if (known?.state === 'offered' || known?.state === 'cancelled') {
        show(study, known.id, offerEvent(known, goal, await modelReady(modelDir(), spec).catch(() => false), saved.ms_per_tile)); return;
      }
      if (known || running) return;                               // running, used, kept or failed: once per goal in a chat
      const choice = saved.choices[sha]?.choice;
      if (choice === 'original') return;
      const record: SharpenRecord = { state: 'offered', id: randomUUID(), name: goal.path, factor: Math.round(factor * 10) / 10 };
      all[sha] = record;
      if (choice === 'sharpened' || host.setting() === 'always') {
        record.auto = true; await host.persist();
        say(`Your goal image is ${record.factor!.toFixed(1)}x smaller than the canvas: sharpening it 4x on ${where} (${choice === 'sharpened' ? 'you chose this for this goal before' : 'Settings: Sharpen small goal images'}).`);
        void start(sha);
        return;
      }
      await host.persist();
      show(study, record.id, offerEvent(record, goal, await modelReady(modelDir(), spec).catch(() => false), saved.ms_per_tile));
    } catch { /* no offer: the goal is used as it is */ }
  }

  function start(sha: string): Promise<void> {
    const controller = new AbortController();
    const done = run(sha, controller.signal).finally(() => { if (running?.controller === controller) running = null; });
    running = { sha, controller, done };
    return done;
  }

  async function run(sha: string, signal: AbortSignal): Promise<void> {
    const study = host.study, goal = folderGoal(study?.references), record = study?.goal_sharpen?.[sha];
    if (!study || !goal || !record) return;
    record.state = 'running'; delete record.message; await host.persist();
    const progress = (done: number, total: number, message: string) => host.emit({ type: 'goal_sharpen_progress', id: record.id, done, total, message });
    try {
      if (record.result && await exists(record.result.reference.path) && await exists(record.result.compare)) return await finished(study, sha, record);
      const directory = modelDir();
      if (!(await modelReady(directory, spec))) {
        let percent = -1;
        progress(0, 1, `Downloading the sharpening model (${size_mb} MB)…`);
        try {
          await download({ directory, spec, signal, onProgress: (done, total) => {
            const now = Math.floor(done / total * 100);
            if (now >= percent + 5) { percent = now; progress(done, total, `Downloading the sharpening model: ${now}% of ${size_mb} MB…`); }
          } });
        } catch (error) {
          if (signal.aborted) throw new UpscaleError('cancelled', 'Sharpening was stopped; the model download resumes next time.');
          throw new UpscaleError('model', 'The sharpening model could not be downloaded: ' + (error as Error).message);
        }
      }
      signal.throwIfAborted();
      const data = await readFile(goal.path);
      if (sha256(data) !== sha) throw new UpscaleError('failed', 'The goal image changed while it was being sharpened.');
      const decoded = await host.callNative('decode_reference', { image_base64: data.toString('base64'), sha256: sha }) as { width: number; height: number; rgba_base64: string; sha256: string };
      if (decoded?.sha256 !== sha) throw new UpscaleError('failed', 'The goal image could not be read for sharpening.');
      const folder = join(study.directory, 'goal-sharpen'), stem = join(folder, sha.slice(0, 16));
      await mkdir(folder, { recursive: true });
      const outputs = { full: stem + '.x4.png', reference: stem + '.reference.png', compare: stem + '.compare.png' };
      progress(0, 1, 'Sharpening the goal image…');
      const reply: UpscaleReply = await sharpen.upscale({ rgba: new Uint8Array(Buffer.from(decoded.rgba_base64, 'base64')), width: decoded.width, height: decoded.height,
        outputs, max_pixels: TRANSFER_PIXELS, max_bytes: TRANSFER_BYTES }, { signal, onProgress: (done, total) => progress(done, total, `Sharpening the goal image: ${Math.floor(done / total * 100)}%…`) });
      const reference = { path: reply.reference.path, width: reply.reference.width, height: reply.reference.height, mimeType: 'image/png', bytes: reply.reference.bytes };
      record.result = { reference, full: { path: outputs.full, ...reply.full }, compare: outputs.compare, ms: reply.ms, peak_mb: reply.peak_mb, provider: reply.provider, tiles: reply.tiles };
      await remember({ ms_per_tile: reply.ms_per_tile });
      await finished(study, sha, record);
    } catch (error) {
      if (host.study !== study || study.goal_sharpen?.[sha] !== record) {   // the chat closed or the goal changed: nothing to say
        host.emit({ type: 'goal_sharpen_progress', id: record.id, done: 0, total: 0, finished: true, message: '' });
        return;
      }
      const stopped = signal.aborted || (error as UpscaleError).code === 'cancelled';
      record.state = stopped ? 'cancelled' : 'failed';
      record.message = (error as Error).message;
      if (stopped) record.id = randomUUID();                       // a fresh card to offer it again
      await host.persist();
      host.emit({ type: 'goal_sharpen_progress', id: record.id, done: 0, total: 0, finished: true, message: '' });
      if (stopped) {
        say('Sharpening stopped: the original goal image is used. You can sharpen it later from the card.');
        const saved = await choices().catch(() => ({ choices: {} }));
        show(study, record.id, offerEvent(record, goal, await modelReady(modelDir(), spec).catch(() => false), (saved as { ms_per_tile?: number }).ms_per_tile));
      } else say(`${(error as Error).message.replace(/\.?$/, '.')} The original goal image is used.`);
    }
  }

  async function finished(study: Study, sha: string, record: SharpenRecord) {
    if (host.study !== study || study.goal_sharpen?.[sha] !== record) return;   // the chat closed or the goal changed meanwhile
    host.emit({ type: 'goal_sharpen_progress', id: record.id, done: 1, total: 1, finished: true, message: '' });
    if (record.auto) { record.state = 'review'; await use(study, sha, record); return; }
    record.state = 'review'; await host.persist();
    show(study, record.id + ':review', reviewEvent(record));
  }

  /** The goal reference becomes the sharpened picture: same id and placement, its pixels and size changed. */
  async function use(study: Study, sha: string, record: SharpenRecord) {
    const goal = folderGoal(study.references), result = record.result;
    if (!goal || !result || goal.sharpened) return;
    // Only onto the picture it was made from: the goal may have changed since (the goal picker).
    if (goal.path !== record.name || await hashOf(goal.path).catch(() => '') !== sha) {
      record.state = 'kept'; delete record.pending_use; await host.persist();
      say('The goal image changed since it was sharpened, so the sharpened copy was not used.');
      return;
    }
    if (host.busy()) {
      record.pending_use = true; await host.persist();
      say('The sharpened goal is used as soon as this move ends.');
      return;
    }
    goal.sharpened = { from: { path: goal.path, width: goal.width ?? 0, height: goal.height ?? 0, sha256: sha, ...(goal.mimeType ? { mimeType: goal.mimeType } : {}) },
      model: spec.name, revision: spec.revision, scale: result.reference.width / (goal.width || 1), full: result.full.path, at: new Date().toISOString() };
    goal.path = result.reference.path; goal.width = result.reference.width; goal.height = result.reference.height; goal.mimeType = result.reference.mimeType;
    delete goal.mass_map;
    record.state = 'used'; delete record.pending_use;
    await remember({ sha, choice: 'sharpened' });
    await host.persist(); host.goalChanged(); host.publish();
    say(`The goal image is now the sharpened one (${result.full.width} x ${result.full.height}${result.reference.width === result.full.width ? '' : `; the painter reads it at ${result.reference.width} x ${result.reference.height}`}).`);
  }

  /** The panel's answer: Sharpen / Use as is on the offer, Use sharpened / Keep original on the side by side, or cancel. */
  async function answer({ id, action }: { id?: unknown; action?: unknown }): Promise<void> {
    const study = host.study;
    if (!study) return;
    if (action === 'cancel') { running?.controller.abort(); return; }
    const entry = Object.entries(study.goal_sharpen ?? {}).find(([, r]) => r.id === id);
    if (!entry) return;
    const [sha, record] = entry;
    if (action === 'sharpen' && ['offered', 'cancelled'].includes(record.state) && !running) { void start(sha); return; }
    if (action === 'original' && ['offered', 'cancelled'].includes(record.state)) {
      record.state = 'kept'; await remember({ sha, choice: 'original' }); await host.persist();
      say('The goal image is used as it is. You won’t be asked again for this goal.');
      return;
    }
    if (action === 'use' && record.state === 'review') { await use(study, sha, record); return; }
    if (action === 'keep' && record.state === 'review') {
      record.state = 'kept'; await remember({ sha, choice: 'original' }); await host.persist();
      say('Kept the original goal image. The sharpened copy stays in the chat folder.');
    }
  }

  /** After a run: a swap the artist approved while it painted happens now; then a goal the canvas now shows small is offered. */
  async function settle(): Promise<void> {
    const study = host.study;
    for (const [sha, record] of Object.entries(study?.goal_sharpen ?? {}))
      if (record.pending_use && study) await use(study, sha, record);
    await check();
  }

  /** The goal picker changed the goal: a sharpening in progress stops, and nothing offered or waiting for the old goal
   * is used (its answers stay remembered; a goal chosen again is offered again if it was never answered). */
  function goalChanged(): void {
    running?.controller.abort();
    const all = host.study?.goal_sharpen;
    for (const [sha, record] of Object.entries(all ?? {}))
      if (all && (['offered', 'running', 'review', 'cancelled'].includes(record.state) || record.pending_use)) delete all[sha];
  }

  return { check, answer, settle, status, goalChanged, stop() { running?.controller.abort(); }, running: () => running?.done ?? null };
}
export type GoalSharpener = ReturnType<typeof goalSharpener>;
