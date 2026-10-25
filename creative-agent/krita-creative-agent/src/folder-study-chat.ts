// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Folder study in a chat (openspec folder-study goals 1-5): when the study runs, on which images, and what the panel and
// the painter's context read of it. The study itself (notes, 4 at a time, timeouts, Stop) is folder-study.ts; the studio
// gives a host (studio.mjs folderStudyHost) and calls attached() when a folder is attached to the chat, planChanged()
// when its plan changes, viewed() when the agent opens a folder image, command() for the panel's menu and choice card.
//
// Policy, from the approved description:
//   - the setting "Study folder images" (study_folder) Off: nothing is studied and no note is given (file names only);
//   - at most SMALL_FOLDER images: every image not excluded, as soon as the folder is attached;
//   - more: the choice card (the choice, the picked images and the exclusions are kept with the chat's folder,
//     study.folder.study): only what the plan uses (the goal, then the images the plan's steps name), all, the picked
//     ones, or none; an image opened by the agent is studied then (lazy) whatever the choice, unless excluded;
//   - an excluded image is never sent to any model: it is not attached to the chat (no painter, planner or Luna image)
//     and never studied. The goal image cannot be excluded (it decides the layout): choose another goal first.
// The candidates are the goal and the element images (the images attached to the chat); other images are never attached.
import { FolderStudy, modelImageCost, studyEstimate, studyTargets, STUDY_DEFAULTS, type Picture, type StudyChoice, type StudyImage, type StudyReader, type StudyStatus,
  type VisionModel } from './folder-study.ts';
import { createHash } from 'node:crypto';
import { reduceRgba } from './bounded-image.ts';
import { decodeRgba, pngSize } from './png-rgba.ts';
import { encodeRgba } from './shapes/png.ts';

const CHOICES: readonly StudyChoice[] = ['plan', 'all', 'pick', 'none'];
/** How long a folder's planning turn waits for a study in progress before planning with the notes it has. */
export const PLAN_WAIT_MS = 120_000;

export type FolderImageRef = { name: string; path: string; guess: string; prompt?: string };
/** Kept on the chat's folder record: what to study (a big folder), the excluded images, and whether the artist stopped the
 * study (a run starts again only when they ask: a choice, Study, or the setting turned On again). */
export type FolderStudyChoices = { choice?: StudyChoice; picked?: string[]; excluded?: string[]; stopped?: boolean };
export type ChatStudyHost = {
  enabled(): boolean;
  /** The chat's data folder; null before the chat starts (a folder opened first is studied when the chat starts). */
  directory(): string | null;
  index(): { root: string; goal: FolderImageRef | null; elements: FolderImageRef[] } | null;
  /** The model that would study (its cost per token gives the estimate), or null when none reads images. */
  model(): (VisionModel & { cost?: { input?: number; output?: number } }) | null;
  /** The chat's folder record (study.folder, or the folder waiting for the chat); the choices are kept on it. */
  folder(): { study?: FolderStudyChoices } | null;
  /** The folder-relative images the plan's steps name (a step's scope, a refine step's parts). */
  planFiles(): string[];
  readImage(path: string): Promise<Buffer>;
  /** An image the companion cannot reduce (a JPEG, a PNG with a colour profile) reduced by Krita, or null when Krita is away. */
  reduce?(data: Buffer, side: number): Promise<Picture | null>;
  reader(): Promise<StudyReader | null>;
  detach(name: string): Promise<void>;
  attach(name: string): Promise<void>;
  persist(): Promise<void>;
  changed(): void;
  record(event: Record<string, unknown>): void;
};
export type ChatStudyStatus = Omit<StudyStatus, 'state'> & { state: StudyStatus['state'] | 'waiting'; enabled: boolean; count: number;
  needs_choice: boolean; big: boolean; stopped: boolean; choice: StudyChoice | null; picked: string[]; excluded: string[]; model: string | null;
  estimate: { plan: { images: number; cost: number; seconds: number }; all: { images: number; cost: number; seconds: number } } };

const mime = (data: Buffer) => data[0] === 0x89 && data[1] === 0x50 ? 'image/png' : data[0] === 0xff && data[1] === 0xd8 ? 'image/jpeg'
  : data.subarray(0, 3).toString('latin1') === 'GIF' ? 'image/gif' : 'image/png';

/** The picture at most `side` px on its long side: a plain PNG reduced here (area averaging, bounded-image.ts), else the
 * file as it is (`reduce`, Krita, may reduce it first). Nothing is written. */
export async function boundedPicture(data: Buffer, side: number, reduce?: (data: Buffer, side: number) => Promise<Picture | null>): Promise<Picture> {
  const size = pngSize(data);
  const long = size ? Math.max(size.width, size.height) : 0;
  if (size && long <= side) return { data: data.toString('base64'), mimeType: 'image/png' };
  if (size) {
    const decoded = decodeRgba(data, size.width * size.height);
    if (decoded) {
      const k = side / long, pixels = reduceRgba(decoded, Math.floor(size.width * k) * Math.floor(size.height * k));
      return { data: encodeRgba(pixels).toString('base64'), mimeType: 'image/png' };
    }
  }
  const reduced = reduce ? await reduce(data, side).catch(() => null) : null;
  return reduced ?? { data: data.toString('base64'), mimeType: mime(data) };
}

/** The messages with the images of `withheld` (excluded since they were sent) replaced by a line: from the moment an image
 * is excluded no request carries it, even from the chat's earlier messages. The input is not changed. */
export function withholdImages<M extends { content?: unknown }>(messages: M[], withheld: readonly { sha: string; length: number }[]): M[] {
  if (!withheld.length) return messages;
  const lengths = new Set(withheld.map(w => w.length)), shas = new Set(withheld.map(w => w.sha));
  const hit = (part: unknown) => {
    const p = part as { type?: string; data?: unknown };
    return p?.type === 'image' && typeof p.data === 'string' && lengths.has(p.data.length) && shas.has(createHash('sha256').update(p.data).digest('hex'));
  };
  return messages.map(m => Array.isArray(m.content) && m.content.some(hit)
    ? { ...m, content: m.content.map(part => hit(part) ? { type: 'text', text: '[An image the artist excluded from this chat was removed.]' } : part) } : m);
}
/** What to record of an image sent to a model, so withholdImages can find it later. */
export const sentImage = (data: string): { sha: string; length: number } => ({ sha: createHash('sha256').update(data).digest('hex'), length: data.length });

export class ChatFolderStudy {
  private readonly host: ChatStudyHost;
  private study: FolderStudy | null = null;
  private directory: string | null = null;
  private readonly lazy = new Set<Promise<unknown>>();

  constructor(host: ChatStudyHost) { this.host = host; }

  /** The FolderStudy of this chat (a new one when the chat changes). */
  private current(): FolderStudy {
    const directory = this.host.directory();
    if (!this.study || directory !== this.directory) {
      this.study?.stop();
      this.directory = directory;
      this.study = new FolderStudy({ directory: () => directory, readImage: path => this.host.readImage(path),
        picture: (_path, data, side) => boundedPicture(data, side, this.host.reduce?.bind(this.host)), reader: () => this.host.reader(),
        changed: () => this.host.changed(), record: event => this.host.record(event) });
    }
    return this.study;
  }

  private images(): StudyImage[] {
    const index = this.host.index();
    if (!index) return [];
    return [...(index.goal ? [{ ...index.goal, role: 'goal' as const }] : []), ...index.elements.map(e => ({ ...e, role: 'element' as const }))];
  }
  private goal(): StudyImage | null { return this.images().find(i => i.role === 'goal') ?? null; }
  private choices(): FolderStudyChoices { return this.host.folder()?.study ?? {}; }

  /** The excluded images; never the goal (an excluded element made the goal is the goal, excluded again if it stops being it). */
  private excludedNames(): string[] { const goal = this.goal()?.name; return (this.choices().excluded ?? []).filter(n => n !== goal); }
  private async setExcluded(names: string[]): Promise<void> { await this.setChoices({ excluded: names }); }
  excluded(name: string): boolean { return this.excludedNames().includes(name); }

  private async setChoices(change: FolderStudyChoices): Promise<void> {
    const folder = this.host.folder();
    if (!folder) throw new Error('Open a project folder first.');
    folder.study = { ...folder.study, ...change };
    await this.host.persist();
  }

  /** The images to study now under the setting and the choice, or null when the card asks. */
  private targets(): StudyImage[] | null {
    const images = this.images(), { choice, picked } = this.choices(), excluded = this.excludedNames();
    const names = studyTargets(images.map(i => i.name), { choice, picked, excluded, planFiles: this.host.planFiles(), goal: this.goal()?.name ?? null });
    return names && images.filter(i => names.includes(i.name));
  }

  /** Study what the policy says now, in the background; nothing after the artist's Stop until they ask again. */
  private start(): Promise<unknown> {
    if (!this.host.enabled() || !this.host.directory() || this.choices().stopped) { this.host.changed(); return Promise.resolve(); }
    const targets = this.targets();
    if (!targets?.length) { this.host.changed(); return Promise.resolve(); }
    return this.current().run(targets, { goal: this.goal(), allowed: name => this.host.enabled() && !this.excluded(name) }).catch(() => {});
  }

  /** The folder is attached to the chat (opened, resumed, its goal changed): notes of changed images or of another goal are
   * dropped (no image is read again unless its file changed), then the policy's images not studied and not failed are
   * studied, unless the artist stopped the study. */
  async attached(): Promise<void> {
    if (!this.host.enabled() || !this.host.directory()) { this.host.changed(); return; }
    await this.current().refresh(this.images(), { goal: this.goal() }).catch(() => {});
    void this.start();
  }

  /** The setting was turned On again: a Stop no longer holds, the folder is studied. */
  async enabledAgain(): Promise<void> {
    if (this.host.folder()?.study?.stopped) await this.setChoices({ stopped: false });
    await this.attached();
  }

  /** The plan changed: with "only what the plan uses", the images its steps name are studied. */
  async planChanged(): Promise<void> {
    if (this.choices().choice === 'plan') void this.start();
  }

  private studyNow(image: StudyImage): void {
    const work = this.current().studyOne(image, { goal: this.goal() }).catch(() => null);
    this.lazy.add(work); void work.finally(() => this.lazy.delete(work));
  }

  /** The agent opened a folder image (view_reference): studied now if it has no note (lazy; a failure is tried again). */
  viewed(name: string): void {
    if (!this.host.enabled() || !this.host.directory() || this.excluded(name)) return;
    const image = this.images().find(i => i.name === name);
    if (image && !this.current().noteOf(name)) this.studyNow(image);
  }

  /** The run in progress, if any. */
  running(): Promise<unknown> | null { return this.study?.running() ?? null; }
  /** Every study of this chat settled (the run and the lazy ones). */
  async idle(): Promise<void> { await Promise.all([this.running(), ...this.lazy].map(p => p?.catch(() => {}))); }

  /** Before a folder's planning turn: a study in progress is waited for, at most `waitMs`, and no longer than the chat is
   * not stopped (`cancelled`); `progress` tells the artist ("Reading the folder's images… k/N"). */
  async beforePlanning({ waitMs = PLAN_WAIT_MS, cancelled = () => false, progress = () => {} }:
    { waitMs?: number; cancelled?: () => boolean; progress?: (text: string) => void } = {}): Promise<void> {
    const run = this.running();
    if (!run) return;
    let settled = false;
    void run.catch(() => {}).finally(() => { settled = true; });
    const until = Date.now() + waitMs;
    while (!settled && !cancelled() && Date.now() < until) {
      const status = this.status();
      progress(`Reading the folder's images before planning…${status.total ? ` ${status.done}/${status.total}` : ''}`);
      await new Promise(resolve => setTimeout(resolve, 150));
    }
  }

  /** The image's note for the painter's context, or undefined (Off, not studied, excluded). */
  noteOf(name: string): string | undefined {
    if (!this.host.enabled() || this.excluded(name) || !this.study || this.host.directory() !== this.directory) return undefined;
    return this.study.noteOf(name) ?? undefined;
  }

  /** The panel's menu and choice card: choose, study one image, exclude, include, stop. */
  async command(command: { action?: unknown; choice?: unknown; picked?: unknown; name?: unknown }): Promise<void> {
    const images = this.images(), names = images.map(i => i.name);
    const named = () => {
      if (typeof command.name !== 'string' || !names.includes(command.name)) throw new Error('That is not an image of the project folder.');
      return command.name;
    };
    switch (command.action) {
      case 'stop': if (this.host.folder()) await this.setChoices({ stopped: true }); this.study?.stop(); this.host.changed(); return;
      case 'choose': {
        if (!CHOICES.includes(command.choice as StudyChoice)) throw new Error('Choose what to study: only what the plan uses, all, the images you pick, or none.');
        const picked = command.choice === 'pick' ? (Array.isArray(command.picked) ? command.picked.filter((n): n is string => typeof n === 'string' && names.includes(n)) : []) : undefined;
        await this.setChoices({ choice: command.choice as StudyChoice, stopped: false, ...(picked ? { picked } : {}) });
        if (command.choice === 'none') this.study?.stop();
        void this.start(); return;
      }
      case 'study': {
        const name = named();
        if (this.excluded(name)) throw new Error(`${name} is excluded: include it first.`);
        if (!this.host.enabled()) throw new Error('Turn on Study folder images in Settings first.');
        if (!this.host.directory()) throw new Error('Start the chat first: the notes are kept with it.');
        this.studyNow(images.find(i => i.name === name)!);
        return;
      }
      case 'exclude': {
        const name = named();
        if (images.find(i => i.name === name)?.role === 'goal') throw new Error('The goal image cannot be excluded: it decides the layout. Choose another goal image first.');
        if (!this.excluded(name)) await this.setExcluded([...(this.choices().excluded ?? []), name]);
        await this.host.detach(name); this.host.changed(); return;
      }
      case 'include': {
        const name = named();
        await this.setExcluded((this.choices().excluded ?? []).filter(n => n !== name));
        await this.host.attach(name);
        void this.start(); return;
      }
      default: throw new Error('Unknown folder study action.');
    }
  }

  /** What the folder card shows. */
  status(): ChatStudyStatus {
    const images = this.images(), names = images.map(i => i.name), { choice, picked = [], stopped = false } = this.choices(), excluded = this.excludedNames();
    const inner = this.study && this.host.directory() === this.directory ? this.study.status(names, { excluded })
      : { state: 'idle' as const, total: 0, done: 0, failed: 0, images: Object.fromEntries(names.map(n => [n, excluded.includes(n) ? 'excluded' as const : 'not_studied' as const])) };
    // The estimate: this chat's measured averages, else the study model's own price per token (modelImageCost).
    const model = this.host.model(), priced = model ? modelImageCost(model) : null;
    const per = this.study?.measured() ?? (priced !== null ? { cost: priced, seconds: STUDY_DEFAULTS.seconds } : null);
    const open = (list: string[]) => list.filter(n => inner.images[n] === 'not_studied').length;
    const planNames = studyTargets(names, { choice: 'plan', excluded, planFiles: this.host.planFiles(), goal: this.goal()?.name ?? null }) ?? [];
    const enabled = this.host.enabled();
    return { ...inner, state: enabled && !this.host.directory() ? 'waiting' : inner.state, enabled, count: names.length,
      needs_choice: enabled && !!this.host.directory() && names.length > 0 && studyTargets(names, { choice, excluded }) === null,
      big: studyTargets(names, {}) === null, stopped, choice: choice ?? null, picked: [...picked], excluded: [...excluded],
      model: model ? `${model.provider}/${model.id}` : null,
      estimate: { plan: studyEstimate(open(planNames), per), all: studyEstimate(open(names.filter(n => !excluded.includes(n))), per) } };
  }

  /** The chat ends or the setting goes Off: the study stops. */
  async close(): Promise<void> { this.study?.stop(); await this.idle(); }
}
