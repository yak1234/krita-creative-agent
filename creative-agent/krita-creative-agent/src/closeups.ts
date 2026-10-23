// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Close-up references for detail (after-the-underpainting goal 1). The goal image of a 1448 px reference on a 6000 px
// canvas is spent by the underpainting; later transfers from it only enlarge the same pixels. A close-up (a reference or
// a project-folder element that shows part of the goal more sharply) is aligned to its place in the goal by the plugin
// (align_closeup, kritamcp/closeup_align.py) once per content of both images, shown to the artist for a yes before its
// first use (a question beside the chat that never holds the run: until the yes, transfers sample the goal; with the
// place drawn on the goal), and from then on a detail transfer whose source
// rect on the goal lies inside it samples the close-up instead: the rect is mapped through the alignment into
// close-up pixels, so the enlargement drops by the close-up's sharpness. The painter's context lists which areas have one.
// Mechanism only: the studio gives the chat, the native call and the question (CloseupHost); this module imports no .mjs.
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { basename, join } from 'node:path';

export type Rect = [number, number, number, number];
export type Ref = { id: string; path: string; role?: string; name?: string; width?: number; height?: number; source?: string;
  folder_name?: string; part_kind?: string; notes?: string };
export type CloseupRecord = {
  key: string; closeup_id: string; goal_id: string; name: string; area: string; aligned: boolean; reason?: string;
  matrix?: number[]; quad?: number[][]; box?: Rect; scale?: number; rotation?: number;
  matches?: number; inliers?: number; similarity?: number; score?: number; ms?: number;
  goal_size?: [number, number]; closeup_size?: [number, number]; preview?: string; confirmed?: 'yes' | 'no';
  bytes?: number;
};
export type CloseupQuestion = { question: string; options: string[]; image_path?: string; closeup_id: string };
export type CloseupHost = {
  study?: { id?: string; directory: string; references: Ref[]; closeups?: Record<string, CloseupRecord> } | undefined;
  /** The open painting's size, to tell the whole picture from a part when there is no project folder. */
  canvas?: { width: number; height: number } | null | undefined;
  callNative(operation: string, params: Record<string, unknown>): Promise<unknown>;
  readReference(ref: Ref): Promise<Buffer>;
  /** Size and modification time: an unchanged file is not read or hashed again. */
  statReference?(ref: Ref): Promise<{ size: number; mtimeMs: number }>;
  persist(): Promise<unknown>;
  emit(event: Record<string, unknown>): void;
  /** Show the question beside the chat without holding the run; the answer comes back through answer(). */
  ask(question: CloseupQuestion): void;
  diagnostics?: { record(event: Record<string, unknown>): void } | undefined;
};
export type Route = { recipe: Record<string, unknown> & { source: Rect }; note: string; closeup_id: string };
export type CloseupContext = { aligned: { reference_id: string; name: string; area: string; goal_box: Rect; sharper: number; status: string }[];
  could_not_align: string[]; note: string };

export const CLOSEUP_ANSWERS = ['Use the close-up there', 'Not this close-up'];
export const MIN_SHARPER = 1.25;           // a close-up less sharper than this where it sits is not worth a transfer
export const MAX_ROTATION = 5;             // degrees: a turned close-up would paint its content turned
const ASPECT_TOLERANCE = 0.03;             // as the reference tools: the canvas's proportions make the whole picture
const EDGE = 1;                            // close-up pixels a mapped corner may fall outside it
const STRETCH = 0.03;                      // the mapped source's proportions may differ from the target's this much
// What the transfer path reads (reference-tool.mjs): a reference of at most 5 MB, decoded at most four million pixels
// (the plugin's decode_reference), rects of at most 8192 a side (the schemas). A close-up past these is not used.
export const TRANSFER_BYTES = 5 * 1024 * 1024, TRANSFER_PIXELS = 4_000_000, TRANSFER_SIDE = 8192;
// Recipe sizes in source pixels, with their schema ranges: they follow the source into the close-up.
const SOURCE_SIZES: Record<string, [number, number]> = { spacing: [0.75, 16], length: [2, 200] };
const SURFACE_SPACING: [number, number] = [1, 32];

const aspect = (w = 0, h = 1) => w / h;
const sameShape = (a: { width?: number; height?: number }, b: { width: number; height: number }) =>
  !!a.width && !!a.height && Math.abs(aspect(a.width, a.height) / aspect(b.width, b.height) - 1) <= ASPECT_TOLERANCE;
const isPart = (ref: Ref) => !!ref.part_kind;
const isElement = (ref: Ref) => ref.source === 'folder' && ref.role === 'asset';

/** The picture close-ups are placed in: the project folder's goal image, else the one reference with the canvas's proportions. */
export function goalReference(refs: Ref[], canvas?: { width: number; height: number } | null): Ref | null {
  const folderGoal = refs.find(r => r.source === 'folder' && r.role === 'reference' && !isPart(r));
  if (folderGoal) return folderGoal;
  if (!canvas?.width || !canvas.height) return null;
  return refs.find(r => r.role === 'reference' && !isPart(r) && r.source !== 'folder' && sameShape(r, canvas)) ?? null;
}

/** References that may show part of the goal: a project folder's numbered elements, and the artist's references of other
 * proportions. Parts and crops (already placed by the artist), generated assets and construction maps are not. */
export function closeupCandidates(refs: Ref[], goal: Ref): Ref[] {
  const whole = { width: goal.width ?? 0, height: goal.height ?? 1 };
  return refs.filter(r => r.id !== goal.id && !isPart(r) && (isElement(r) || (r.role === 'reference' && !sameShape(r, whole))));
}

const sha = (data: Buffer) => createHash('sha256').update(data).digest('hex');
const round = (value: number, places = 1) => Math.round(value * 10 ** places) / 10 ** places;

function invert(m: number[]): number[] | null {
  const [a, b, c, d, e, f, g, h, i] = m as [number, number, number, number, number, number, number, number, number];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return null;
  return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det,
    C / det, -(a * h - b * g) / det, (a * e - b * d) / det];
}
function apply(m: number[], x: number, y: number): [number, number] {
  const [a, b, c, d, e, f, g, h, i] = m as [number, number, number, number, number, number, number, number, number];
  const s = g * x + h * y + i;
  return [(a * x + b * y + c) / s, (d * x + e * y + f) / s];
}
function polygonArea(points: [number, number][]): number {
  let sum = 0;
  for (let k = 0; k < points.length; k++) {
    const [x0, y0] = points[k]!, [x1, y1] = points[(k + 1) % points.length]!;
    sum += x0 * y1 - x1 * y0;
  }
  return Math.abs(sum) / 2;
}
const sameAspect = (sw: number, sh: number, tw: number, th: number) => Math.abs(sh * tw / sw - th) <= 1;   // reference-generator's rule

/** A goal rect [x, y, w, h] in close-up pixels, the target's proportions kept; null when it is not wholly inside the
 * close-up, the alignment stretches it (its proportions differ from the target's by more than STRETCH), or no whole-pixel
 * rect keeps the proportions without moving more than a pixel. */
export function mapSource(record: Pick<CloseupRecord, 'matrix' | 'closeup_size'>, source: Rect, target: Rect): Rect | null {
  const inverse = record.matrix && invert(record.matrix), size = record.closeup_size;
  if (!inverse || !size) return null;
  const [sx, sy, sw, sh] = source, [, , tw, th] = target, [W, H] = size;
  const corners = ([[sx, sy], [sx + sw, sy], [sx + sw, sy + sh], [sx, sy + sh]] as [number, number][]).map(([x, y]) => apply(inverse, x, y));
  if (corners.some(([x, y]) => !(x >= -EDGE && y >= -EDGE && x <= W + EDGE && y <= H + EDGE))) return null;
  const length = (a: [number, number], b: [number, number]) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const [c0, c1, c2, c3] = corners as [[number, number], [number, number], [number, number], [number, number]];
  const qw = (length(c0, c1) + length(c3, c2)) / 2, qh = (length(c0, c3) + length(c1, c2)) / 2;
  if (!(qh > 0) || Math.abs((qw / qh) / (tw / th) - 1) > STRETCH) return null;
  const k = Math.sqrt(polygonArea(corners) / (sw * sh));
  const [cx, cy] = apply(inverse, sx + sw / 2, sy + sh / 2);
  const start = Math.round(sw * k);
  for (const step of [0, 1, -1, 2, -2, 3, -3]) {
    const w = start + step, h = Math.round(w * th / tw);
    if (w < 1 || h < 1 || w > W || h > H || !sameAspect(w, h, tw, th)) continue;
    const ix = Math.round(cx - w / 2), iy = Math.round(cy - h / 2);
    const x = Math.min(W - w, Math.max(0, ix)), y = Math.min(H - h, Math.max(0, iy));
    if (Math.abs(x - ix) > 1 || Math.abs(y - iy) > 1) return null;
    return [x, y, w, h];
  }
  return null;
}

/** A recipe moved from the goal's source rect to the close-up's: focal regions mapped by the same transform and clamped
 * inside the mapped rect, source-pixel sizes scaled to keep their size on the canvas. Null when a focal region or a size
 * cannot follow. */
function moveRecipe<T extends Record<string, unknown>>(recipe: T, source: Rect, mapped: Rect): (T & { source: Rect }) | null {
  const [sx, sy, sw, sh] = source, [mx, my, mw, mh] = mapped, kx = mw / sw, ky = mh / sh, k = (kx + ky) / 2;
  const out: Record<string, unknown> = { ...recipe, source: mapped };
  if (Array.isArray(recipe.focal_regions)) {
    const regions: Rect[] = [];
    for (const [x, y, w, h] of recipe.focal_regions as Rect[]) {
      const left = Math.max(mx, Math.round(mx + (x - sx) * kx)), top = Math.max(my, Math.round(my + (y - sy) * ky));
      const right = Math.min(mx + mw, Math.round(mx + (x + w - sx) * kx)), bottom = Math.min(my + mh, Math.round(my + (y + h - sy) * ky));
      if (right - left < 1 || bottom - top < 1) return null;
      regions.push([left, top, right - left, bottom - top]);
    }
    out.focal_regions = regions;
  }
  if (Array.isArray(recipe.steps)) {
    const steps = (recipe.steps as number[]).map(v => round(v * k, 2));
    if (steps.some(v => v > 64) || !(steps[0]! > steps[1]! && steps[1]! > steps[2]!)) return null;
    out.steps = steps;
  }
  for (const [name, [low, high]] of Object.entries({ ...SOURCE_SIZES, ...(recipe.mode === 'surface' ? { spacing: SURFACE_SPACING } : {}) })) {
    if (typeof recipe[name] !== 'number') continue;
    const value = round((recipe[name] as number) * k, 2);
    if (value < low || value > high) return null;
    out[name] = value;
  }
  return out as T & { source: Rect };
}

/** The studio's close-ups for the open chat: refresh (align what is new), route (a transfer's source), answer, context. */
export function chatCloseups(host: CloseupHost) {
  const memory = new Map<string, Record<string, unknown>>();   // the plugin's answers by content of both images, across chats
  const hashes = new Map<string, { size: number; mtimeMs: number; sha: string }>();   // by file path
  const failed = new Set<string>();                  // chat directory + content key: a transient failure, tried once a chat
  let asked = new Set<string>();                     // close-ups asked about this run
  let refreshing: Promise<void> | null = null, unsupported = false;
  const attached = () => new Set((host.study?.references ?? []).map(r => r.id));
  const records = () => host.study ? (host.study.closeups ??= {}) : {};
  /** The records of close-ups still attached: a removed one is never used, listed or answered. */
  const current = () => { const ids = attached(); return Object.values(records()).filter(r => ids.has(r.closeup_id)); };
  /** A file's content hash, read again only when its size or modification time changed. */
  async function fileSha(ref: Ref): Promise<{ sha: string; size: number; data?: Buffer }> {
    const seen = await host.statReference?.(ref).catch(() => undefined), known = hashes.get(ref.path);
    if (seen && known && known.size === seen.size && known.mtimeMs === seen.mtimeMs) return { sha: known.sha, size: known.size };
    const data = await host.readReference(ref), value = sha(data);
    if (seen) hashes.set(ref.path, { ...seen, sha: value });
    return { sha: value, size: data.length, data };
  }
  const goal = () => host.study ? goalReference(host.study.references, host.canvas) : null;
  const usable = (r: CloseupRecord) => r.aligned && (r.scale ?? 0) >= MIN_SHARPER && Math.abs(r.rotation ?? 0) <= MAX_ROTATION;
  const areaOf = (ref: Ref) => (/^Element:\s*(.+)$/.exec(ref.notes ?? '')?.[1]?.trim()) || basename(ref.name ?? ref.id);

  async function alignAll(): Promise<void> {
    const study = host.study, target = goal();
    if (!study || !target || unsupported) return;
    const candidates = closeupCandidates(study.references, target);
    if (!candidates.length) return;
    const goalFile = await fileSha(target);
    let goalData = goalFile.data, changed = false;
    for (const ref of candidates) {
      let file: { sha: string; size: number; data?: Buffer };
      try { file = await fileSha(ref); } catch { continue; }
      const key = goalFile.sha + ':' + file.sha, known = records()[ref.id];
      if (known?.key === key || failed.has(study.directory + ':' + key)) continue;
      let reply = memory.get(key);
      const fresh = !reply;
      if (!reply) {
        try {
          goalData ??= await host.readReference(target);
          const data = file.data ?? await host.readReference(ref);
          reply = await host.callNative('align_closeup', { goal: { image_base64: goalData.toString('base64'), sha256: goalFile.sha },
            closeup: { image_base64: data.toString('base64'), sha256: file.sha }, preview: true }) as Record<string, unknown>;
        } catch (error) {
          const { message, code } = error as Error & { code?: string };
          host.diagnostics?.record({ type: 'closeup_error', name: ref.name ?? ref.id, error: message });
          // A plugin without the operation is not asked again; one that refuses the image (a ValueError: not a PNG or
          // JPEG, too large, undecodable) gives a lasting answer, kept by content; anything else is tried once a chat.
          if (/Unsupported creative operation/.test(message)) { unsupported = true; break; }
          if (code !== 'validation_rejected') { failed.add(study.directory + ':' + key); continue; }
          reply = { aligned: false, reason: message.replace(/^ValueError:\s*/, '') };
        }
        memory.set(key, reply);
      }
      let preview: string | undefined;
      if (reply.aligned === true && typeof reply.preview_jpeg_base64 === 'string') {
        preview = join('closeups', ref.id.replace(/[^\w-]/g, '_') + '.jpg');
        await mkdir(join(study.directory, 'closeups'), { recursive: true });
        await writeFile(join(study.directory, preview), Buffer.from(reply.preview_jpeg_base64, 'base64'));
      }
      const answer = reply, pick = <T>(name: string) => answer[name] as T | undefined;
      const found: CloseupRecord = { key, closeup_id: ref.id, goal_id: target.id, name: basename(ref.name ?? ref.id), area: areaOf(ref), aligned: reply.aligned === true,
        ...(reply.aligned === true ? { matrix: pick<number[]>('matrix'), quad: pick<number[][]>('quad'), box: pick<Rect>('box'),
          scale: pick<number>('scale'), rotation: pick<number>('rotation'), score: pick<number>('score'), similarity: pick<number>('similarity') }
          : { reason: String(reply.reason ?? 'Could not align.') }),
        matches: pick<number>('matches'), inliers: pick<number>('inliers'), ms: pick<number>('ms'), bytes: file.size,
        goal_size: pick<[number, number]>('goal_size'), closeup_size: pick<[number, number]>('closeup_size'), ...(preview ? { preview } : {}) };
      const timing = { type: 'closeup_aligned', name: found.name, aligned: found.aligned, ms: found.ms, inliers: found.inliers,
        ...(found.aligned ? { box: found.box, sharper: round(found.scale ?? 0), score: found.score } : { reason: found.reason }) };
      if (fresh) { host.diagnostics?.record(timing); host.emit(timing); }
      // A new alignment (the content changed) is confirmed afresh.
      records()[ref.id] = found;
      changed = true;
    }
    if (changed) await host.persist();
  }

  function question(record: CloseupRecord): CloseupQuestion {
    const [x, y, w, h] = record.box ?? [0, 0, 0, 0];
    return { closeup_id: record.closeup_id,
      question: `${record.name} matches part of the goal image (${record.area}): the box at ${x}, ${y}, ${w} x ${h} goal pixels, `
        + `about ${round(record.scale ?? 0)}x sharper there. Use it for detail in that area instead of enlarging the goal?`,
      options: [...CLOSEUP_ANSWERS], ...(record.preview && host.study ? { image_path: join(host.study.directory, record.preview) } : {}) };
  }

  /** Align the chat's close-ups that are new or changed (once per content of both images). Never throws for one image. */
  // A close-up is never a reason to stop painting: a failure is recorded and the transfers sample the goal.
  const refresh = (): Promise<void> => (refreshing ??= alignAll()
    .catch(error => { host.diagnostics?.record({ type: 'closeup_error', error: (error as Error).message }); })
    .finally(() => { refreshing = null; }));

  return {
    refresh,
    /** A new run: a close-up still unanswered may be shown again (once a run). */
    startRun() { asked = new Set(); },
    /** A transfer's recipe, sampled from a confirmed close-up when its source on the goal lies inside one; else null, to
     * sample the goal as asked. A close-up not yet confirmed is shown to the artist (once a run) and never waited for. */
    async route(recipe: Record<string, unknown> & { reference_id?: unknown; source?: unknown; target?: unknown }): Promise<Route | null> {
      const target = goal();
      if (!target || recipe.reference_id !== target.id || !Array.isArray(recipe.source) || !Array.isArray(recipe.target)) return null;
      await refresh();
      const source = recipe.source as Rect, area = recipe.target as Rect;
      const readable = (r: CloseupRecord) => (r.bytes ?? 0) <= TRANSFER_BYTES && !!r.closeup_size && r.closeup_size[0] * r.closeup_size[1] <= TRANSFER_PIXELS;
      const fits = current()
        .filter(r => r.goal_id === target.id && usable(r) && r.confirmed !== 'no' && readable(r))
        .map(r => ({ record: r, mapped: mapSource(r, source, area) }))
        .filter((f): f is { record: CloseupRecord; mapped: Rect } => !!f.mapped && f.mapped[2] <= TRANSFER_SIDE && f.mapped[3] <= TRANSFER_SIDE
          && f.mapped[2] / source[2] >= MIN_SHARPER)                // sharper where this source is, not only at the centre
        .sort((a, b) => b.mapped[2] - a.mapped[2]);
      const best = fits[0];
      if (!best) return null;
      if (best.record.confirmed !== 'yes') {
        if (!asked.has(best.record.closeup_id)) { asked.add(best.record.closeup_id); host.ask(question(best.record)); }
        return null;
      }
      const moved = moveRecipe(recipe, source, best.mapped);
      if (!moved) return null;
      const local = best.mapped[2] / source[2], before = area[2] / source[2], after = area[2] / best.mapped[2];
      return { closeup_id: best.record.closeup_id, recipe: { ...moved, reference_id: best.record.closeup_id },
        note: `Sampled ${best.record.name} (${best.record.area}), about ${round(local)}x sharper here, instead of the goal: `
          + `source [${best.mapped.join(',')}] in its pixels; the transfer enlarges ${round(after)}x, not ${round(before)}x.` };
    },
    /** A removed reference's record goes with it. */
    forget(closeupId: string) {
      const all = records();
      if (!(closeupId in all)) return;
      delete all[closeupId]; asked.delete(closeupId);
      void host.persist();
    },
    /** The artist's answer to a close-up question: the first answer is yes, anything else is no. False when it changed nothing. */
    answer(closeupId: string, text: string): boolean {
      const record = records()[closeupId];
      if (!record?.aligned || !attached().has(closeupId)) return false;
      record.confirmed = text.trim() === CLOSEUP_ANSWERS[0] || /^(yes|y|ok|use it)\b/i.test(text.trim()) ? 'yes' : 'no';
      void host.persist();
      host.emit({ type: 'closeup_confirmed', closeup_id: closeupId, confirmed: record.confirmed });
      return true;
    },
    /** What the painter is told: the areas with a close-up, and the close-ups that could not be placed. */
    context(): CloseupContext | undefined {
      const all = current();
      if (!Object.keys(records()).length) return undefined;
      const status = (r: CloseupRecord) => !usable(r) ? ((r.scale ?? 0) < MIN_SHARPER ? 'aligned, not sharper than the goal there: not used' : 'aligned but turned: not used')
        : r.confirmed === 'yes' ? 'confirmed by the artist' : r.confirmed === 'no' ? 'declined by the artist: not used'
          : 'aligned; the artist is asked before its first use';
      const aligned = all.filter(r => r.aligned).map(r => ({ reference_id: r.closeup_id, name: r.name, area: r.area, goal_box: r.box as Rect,
        sharper: round(r.scale ?? 0), status: status(r) }));
      const lines = aligned.filter(a => !/not used/.test(a.status)).map(a => `${a.area}: ${a.name}, about ${a.sharper}x sharper (goal box [${a.goal_box.join(',')}])`);
      return { aligned, could_not_align: all.filter(r => !r.aligned).map(r => r.name),
        note: (lines.length ? 'Close-ups for detail: ' + lines.join('; ') + '. A detail transfer (paint_from_reference, paint_reference_edges, paint_reference_surface) from the goal whose source lies inside one samples the close-up instead; give the source in goal pixels as usual.'
          : 'No close-up can be used for detail yet.') + (all.some(r => !r.aligned) ? ' The others could not be placed in the goal: they are looks to follow, not sharper sources.' : '') };
    },
  };
}
export type ChatCloseups = ReturnType<typeof chatCloseups>;
