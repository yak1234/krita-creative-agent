// A test companion: the installed companion run as a separate process with its own data folder, driven over
// stdin/stdout exactly as the panel drives it, so test chats never appear in the artist's chat list. It works on a
// copy of a painting (opened in Krita, closed unsaved and deleted at the end) or on a new painting, and on copies of a
// project folder and of reference images (test-fixtures.ts: the test chat never sees the artist's files). Panel
// commands (test-commands.ts) drive what the panel's buttons do. Development
// only: scripts/evaluate-tool-choice.ts and scripts/test-driver.ts (the MCP's creative_test_* tools) use it.
import { spawn as spawnProcess, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { access, copyFile, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { basename, dirname, join, sep } from 'node:path';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { toolCallsFromEntries, type Call } from './tool-choice.ts';
import { copyProjectFolder, copyReferences } from './test-fixtures.ts';
import { panelCommand, type AreaCommand, type FoundEvent, type Question, type SharpenCard } from './test-commands.ts';
import type { StepView } from './plan-steps.ts';

/** The installed companion's settings (the panel's creative-agent-config.json). */
export type Base = { node: string; companion: string; data_dir: string; project_root: string; bridge_url: string; build_id: string; [key: string]: unknown };
export type Bridge = (action: string, params?: Record<string, unknown>, timeoutSeconds?: number) => Promise<any>;
export type Spawn = (command: string, args: string[], options: { cwd: string; env: NodeJS.ProcessEnv }) => ChildProcessWithoutNullStreams;
/** folder: an absolute project folder and references: absolute image paths, each copied into the test chat's folder first. */
export type StartOptions = { prompt: string; painting?: string; width?: number; height?: number; name?: string;
  provider?: string; model?: string; loopGuards?: boolean; luna?: 'off' | 'evaluate' | 'guide'; folder?: string; references?: string[] };
export type Started = { copy: string | null; krita: string; project_folder?: string; references?: string[] };
export type Move = { number: number; status: string; title?: string; actions?: number; strokes?: number; request_done?: boolean; [key: string]: unknown };
/** One element-shapes timing (src/shapes/chat.ts's shape_timing event): a study or a shape, its time, peak memory and provider. */
export type ShapeTiming = { kind: string; ms: number; peak_mb: number; provider: string; [key: string]: unknown };
/** The project folder card (the companion's folder event): the copy's root, its goal and elements with their names. */
export type FolderCard = { root: string; name: string; goal: string | null; elements: { name: string; guess: string }[] };
/** The panel's Now painting card: the step that paints (or finished, waiting for Met or Redo), else the next open one. */
export type NowCard = StepView & { caption: string };
export type AreaView = { name: string | null; bounds: number[]; share?: number; mask_path: string; set_at?: string; auto?: unknown };
export type TestState = { folder: string; chat_id: string | null; ready: boolean; busy: boolean; activity: string | null;
  moves: Move[]; question: Question | null; canvas: string | null; copy: string | null; errors: string[]; exited: boolean;
  shape_timings: ShapeTiming[]; shapes_model_needed: string | null; mode: string | null;
  project_folder: FolderCard | null; references: string[]; plan: { title: string | null; status: string | null; steps: string[] } | null;
  plan_steps: StepView[]; now: NowCard | null; closeup_question: Question | null; paint_only_here: AreaView | null; found_areas: FoundEvent[];
  /** The part a find_it sent is looking for until its found_area arrives (the companion is not busy meanwhile). */
  finding: string | null; sharpen: SharpenCard | null;
  painting_target: { document_id?: string | null; filename?: string | null } | null };
const CAPTIONS: Record<string, string> = { painting: 'Now painting', finishing: 'Finishing', finished: 'Finished · keep it?', open: 'Up next' };
const FOUND_KEPT = 10;

const SETTINGS = ['execution-settings.json', 'model-connections.json', 'model-catalog.json', 'decision-endpoints.json', 'capabilities/model-capabilities.json'];

/** The bridge over HTTP, as the panel config names it. */
export function httpBridge(url: string): Bridge {
  return async (action, params = {}, timeoutSeconds = 120) => {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, params, timeout: timeoutSeconds }), signal: AbortSignal.timeout((timeoutSeconds + 20) * 1000) });
    return response.json();
  };
}

export class TestCompanion {
  readonly base: Base;
  readonly folder: string;
  private readonly bridge: Bridge;
  private readonly spawn: Spawn;
  private readonly quietMs: number;
  private readonly startMs: number;
  private readonly closeRetryMs: number;
  private child: ChildProcessWithoutNullStreams | null = null;
  private buffer = '';
  private busyStarts = 0;
  private idleSince = Date.now();
  private readonly waiters = new Set<() => void>();
  private readonly status: TestState;
  private findRequest: string | null = null;

  constructor(base: Base, folder: string, { bridge, spawn = spawnProcess as unknown as Spawn, quietMs = 4000, startMs = 120000, closeRetryMs = 5000 }:
    { bridge: Bridge; spawn?: Spawn; quietMs?: number; startMs?: number; closeRetryMs?: number }) {
    this.base = base; this.folder = folder; this.bridge = bridge; this.spawn = spawn; this.quietMs = quietMs; this.startMs = startMs;
    this.closeRetryMs = closeRetryMs;
    this.status = { folder, chat_id: null, ready: false, busy: false, activity: null, moves: [], question: null, canvas: null, copy: null, errors: [], exited: false,
      shape_timings: [], shapes_model_needed: null, mode: null, project_folder: null, references: [], plan: null, plan_steps: [], now: null,
      closeup_question: null, paint_only_here: null, found_areas: [], finding: null, sharpen: null, painting_target: null };
  }

  /** Start a test chat in Agent mode. With `painting` (relative to the project root) a copy is opened in Krita;
   * without it the companion makes a new painting. Returns once the request is sent; waitIdle() waits for the move. */
  async start(options: StartOptions): Promise<Started> {
    const health = await this.bridge('creative', { operation: 'health', params: {} });
    if (health.session_active) throw new Error('Krita holds a painting session (the artist’s chat); end it before a test chat.');
    if (health.build?.build_id !== this.base.build_id) throw new Error(`Krita runs build ${health.build?.build_id}, the installed companion is ${this.base.build_id}.`);
    const data = join(this.folder, 'data');
    await mkdir(data, { recursive: true });
    for (const file of SETTINGS) {
      await mkdir(dirname(join(data, file)), { recursive: true });
      await copyFile(join(this.base.data_dir, file), join(data, file)).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'ENOENT') throw error; });
    }
    // The element-shapes model (~330 MB, src/shapes/model.ts) is the artist's: linked, never copied or downloaded per test chat.
    const models = join(this.base.data_dir, 'models');
    if (await access(models).then(() => true, () => false)) await symlink(models, join(data, 'models')).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'EEXIST') throw error; });
    if (options.luna) {                            // Luna's setting for this test chat only; the artist's copy is untouched
      const path = join(data, 'execution-settings.json');
      const settings = JSON.parse(await readFile(path, 'utf8').catch(() => '{}'));
      await writeFile(path, JSON.stringify({ ...settings, routing: options.luna }));
    }
    // The project folder and references: copies in this test chat's folder, deleted at the end (or on a failed start).
    const copies: { folder?: string; references: { path: string; name: string }[] } = { references: [] };
    try {
      if (options.folder) copies.folder = await copyProjectFolder(options.folder, join(this.folder, 'project'));
      if (options.references?.length) copies.references = (await copyReferences(options.references, join(this.folder, 'references')))
        .map((path, index) => ({ path, name: basename(options.references![index]!) }));
    } catch (error) { await this.discardFolders(); throw error; }
    let krita = 'Krita: a new painting will be created by the test chat (nothing of yours is opened).';
    if (options.painting) {
      const copy = join(this.folder, basename(options.painting));
      await copyFile(join(this.base.project_root, options.painting), copy);
      this.status.copy = copy;                     // from here on, a failure closes and deletes the copy
      // Opening a large painting can take minutes while Krita is busy (an autosave): wait for it.
      const opened = await this.bridge('open_file', { path: copy }, 900).catch(error => ({ error: String(error) }));
      if (opened.error) { await this.discardCopy(); await this.discardFolders(); throw new Error('Could not open the copy: ' + opened.error); }
      krita = `Krita: opened a copy of ${options.painting} at ${copy}; the original is untouched. It is closed unsaved and deleted at the end.`;
    }
    if (copies.folder) krita += ` The test chat works on a copy of the project folder at ${copies.folder}; the original is never opened or written. The copy is deleted at the end.`;
    if (copies.references.length) krita += ` ${copies.references.length} reference image${copies.references.length === 1 ? '' : 's'} copied into ${join(this.folder, 'references')}.`;
    try {
      return await this.launch(options, data, krita, copies);
    } catch (error) {
      this.child?.kill();
      await this.discardCopy();
      await this.discardFolders();
      throw error;
    }
  }

  /** Delete the project folder and reference copies. */
  private async discardFolders(): Promise<void> {
    for (const name of ['project', 'references']) await rm(join(this.folder, name), { recursive: true, force: true });
    this.status.references = [];
  }

  private async launch(options: StartOptions, data: string, krita: string,
    copies: { folder?: string; references: { path: string; name: string }[] } = { references: [] }): Promise<Started> {
    const config = { ...this.base, paintings_dir: this.folder, data_dir: data, output: data, legacy_output: undefined, loopGuards: options.loopGuards !== false };
    await writeFile(join(this.folder, 'companion-config.json'), JSON.stringify(config, null, 2));
    this.child = this.spawn(this.base.node, [this.base.companion], { cwd: dirname(this.base.companion),
      env: { ...process.env, KRITA_CREATIVE_CONFIG: join(this.folder, 'companion-config.json') } });
    this.child.stdout.on('data', chunk => this.read(String(chunk)));
    this.child.stderr.on('data', chunk => { const text = String(chunk).trim(); if (text) this.status.errors.push(text.slice(0, 500)); });
    this.child.on('exit', () => { this.status.exited = true; this.notify(); });
    await this.until(() => this.status.ready, this.startMs, 'the companion to start');
    if (copies.folder) {                           // the panel's Open project folder before the first message: the chat attaches it
      const errors = this.status.errors.length;
      this.send({ type: 'open_folder', path: copies.folder });
      await this.until(() => this.status.project_folder?.root === copies.folder || this.status.errors.length > errors || this.status.exited, this.startMs, 'the project folder to open');
      if (this.status.project_folder?.root !== copies.folder) throw new Error('The project folder copy did not open: ' + (this.status.errors.at(-1) ?? 'the companion exited'));
    }
    this.status.references = copies.references.map(r => r.path);
    const started = this.busyStarts;
    this.send({ type: 'start', chat_mode: 'agent', prompt: options.prompt, provider: options.provider, model: options.model,
      mode: options.painting ? 'current' : 'new', width: options.width, height: options.height, name: options.name ?? 'Test chat',
      experiment: 'free', canvas: { selected: !!options.painting }, message_id: randomUUID(),
      references: copies.references.map(({ path, name }) => ({ path, role: 'reference', name, purpose: 'general', notes: '' })) });
    await this.until(() => this.busyStarts > started || this.status.exited, this.startMs, 'the request to begin');
    return { copy: this.status.copy, krita, ...(copies.folder ? { project_folder: copies.folder } : {}),
      ...(copies.references.length ? { references: this.status.references } : {}) };
  }

  /** Close the copy in Krita unsaved (whether or not it finished opening) and delete it. */
  private async discardCopy(): Promise<void> {
    const copy = this.status.copy;
    if (!copy) return;
    await this.bridge('creative', { operation: 'close_benchmark_copy', params: { path: copy } }, 300).catch(() => null);
    await rm(copy, { force: true }); await rm(copy + '~', { force: true });
    this.status.copy = null;
  }

  /** A follow-up message, as the artist would type it in the panel. */
  prompt(text: string): void {
    this.send({ type: 'prompt', text, chat_mode: 'agent', message_id: randomUUID() });
  }

  /** The panel's Keep or Undo on the latest move; both start the next move. */
  move(action: 'keep' | 'undo'): void {
    const last = this.status.moves.at(-1);
    if (!last) throw new Error('There is no move to keep or undo yet.');
    this.send({ type: 'move', action, move: last.number });
  }

  /** Keep the painter's proposed protected area `name`, as the artist's panel click would (the plugin allows it on test copies only). */
  async protect(name: string): Promise<Record<string, unknown>> {
    const result = await this.bridge('creative', { operation: 'test_keep_protection', params: { name } });
    if (result?.error) throw new Error(String(result.error));
    return result;
  }

  /** Wait until the companion has been idle for a moment (a move finished), or `ms` pass; returns the state either way. */
  async waitIdle(ms: number): Promise<TestState> {
    // A find runs while the companion is not busy (Find it for me): its outline is waited for like a move.
    await this.until(() => this.status.exited || (!this.status.busy && !this.findRequest && Date.now() - this.idleSince >= this.quietMs), ms, 'the move').catch(() => {});
    return this.state();
  }

  state(): TestState {
    return structuredClone(this.status);
  }

  /** The painter's tool calls so far, from the test chat's own records. */
  toolCalls(): Call[] {
    if (!this.status.chat_id) return [];
    try {
      // A short lock wait: a state poll must never hang behind the companion's own writes (a 375 s wait was seen live).
      const db = new DatabaseSync(join(this.folder, 'data', 'records.sqlite'), { readOnly: true, timeout: 500 });
      try {
        const rows = db.prepare('SELECT entry FROM session_entries WHERE chat_id = ? ORDER BY key, seq').all(this.status.chat_id) as { entry: string }[];
        return toolCallsFromEntries(rows.map(row => JSON.parse(row.entry)));
      } finally { db.close(); }
    } catch { return []; }
  }

  /** End the chat and the process; close the copy unsaved and delete it. */
  async end(): Promise<{ krita: string }> {
    if (this.child && !this.status.exited) {
      if (this.status.busy) {                      // mid-move, End is refused: stop the move first, as the panel's Stop does
        this.send({ type: 'stop' });
        await this.until(() => !this.status.busy || this.status.exited, 180000, 'the move to stop').catch(() => {});
      }
      this.send({ type: 'end' });
      await new Promise(resolve => setTimeout(resolve, Math.min(5000, this.quietMs * 2)));
      this.send({ type: 'shutdown' });
      await this.until(() => this.status.exited, 20000, 'the companion to exit').catch(() => this.child?.kill());
    }
    // What Krita has open from the run folder: the copy, the .kra the session saved it as (an image copy is saved as one), or
    // the test chat's own new painting (the rehearsal, 2026-10-24: Test chat.kra was left open). Never anything else.
    const open = await this.bridge('creative', { operation: 'context', params: {} }, 30).then(c => (c?.documents ?? []).map((d: { filename?: string }) => d.filename)
      .filter((f: unknown): f is string => typeof f === 'string' && f.startsWith(this.folder + sep))).catch(() => [] as string[]);
    const copy = this.status.copy;
    const targets: string[] = open.length ? open : copy ? [copy] : [];
    for (const target of targets) {
      // The session may take a moment to let go of the painting after End: retry while Krita says it is still open.
      let closed = await this.bridge('creative', { operation: 'close_benchmark_copy', params: { path: target } }, 300);
      for (let attempt = 0; attempt < 12 && /painting session is open/.test(String(closed.error ?? '')); attempt++) {
        await new Promise(resolve => setTimeout(resolve, this.closeRetryMs));
        closed = await this.bridge('creative', { operation: 'close_benchmark_copy', params: { path: target } }, 300);
      }
      if (!closed.closed) throw new Error(`Krita did not close ${copy ? 'the copy ' : 'the test chat’s painting '}${target}: ${closed.error ?? 'still open'}. Close it by hand.`);
    }
    let krita = 'Krita: nothing to close (the test chat made its own painting and Krita no longer has it open).';
    if (copy) {
      for (const file of new Set([copy, ...targets])) { await rm(file, { force: true }); await rm(file + '~', { force: true }); }
      krita = targets.length === 1 && targets[0] === copy ? `Krita: closed the copy ${copy} unsaved and deleted it.`
        : `Krita: closed ${targets.join(', ')} (the session's save of the copy ${copy}) unsaved and deleted them.`;
      this.status.copy = null;
    } else if (targets.length) {
      // The test chat's own painting is its record: closed unsaved, its saved file stays in the test folder.
      krita = `Krita: closed the test chat’s painting ${targets.join(', ')} unsaved (its saved file stays in the test folder).`;
    }
    const folders = !!this.status.project_folder || this.status.references.length > 0;
    await this.discardFolders();
    if (folders) krita += ' The project folder and reference copies are deleted.';
    return { krita };
  }

  /** A panel command (test-commands.ts allowlists and checks it against this state). An area is sent first, taken by
   * the companion, then protected in Krita on the test chat's own document, as the panel's Paint only here does. */
  async command(type: unknown, params: unknown): Promise<Record<string, unknown>> {
    const s = this.status;
    const planned = panelCommand(type, params, { testFolder: this.folder, mode: s.mode, planSteps: s.plan_steps, question: s.question,
      closeupQuestion: s.closeup_question, foundAreas: s.found_areas, folderElements: (s.project_folder?.elements ?? []).map(e => e.name), sharpen: s.sharpen });
    const result: Record<string, unknown> = { status: 'ok', type };
    if (planned.area) result.krita = await this.applyArea(planned.area);
    if (planned.command) {
      this.send(planned.command);
      if (planned.command.request_id) result.request_id = planned.command.request_id;
      if (planned.command.type === 'find_it') { this.findRequest = String(planned.command.request_id); s.finding = String(planned.command.part); }
      // Answered: the panel's card goes; Sharpen keeps it, with the progress, until the side by side replaces it.
      if (planned.command.type === 'goal_sharpen' && ['original', 'use', 'keep'].includes(String(planned.command.action))) s.sharpen = null;
    }
    return result;
  }

  private async applyArea(area: AreaCommand): Promise<string> {
    const s = this.status;
    if (area.action === 'clear' && !s.paint_only_here) return 'Krita: no area to clear.';
    const before = s.paint_only_here?.set_at ?? null, errors = s.errors.length;
    this.send({ type: 'paint_only_here', ...area });
    await this.until(() => s.errors.length > errors || s.exited
      || (area.action === 'set' ? !!s.paint_only_here && s.paint_only_here.set_at !== before : !s.paint_only_here), 30000, 'the companion to take the area');
    if (s.errors.length > errors) throw new Error('Paint only here: ' + s.errors.at(-1));
    const document = await this.testDocument();
    if (!document) return 'Krita: the area is the chat’s but not protected in Krita: no document from the test chat’s folder is open.';
    const params = area.action === 'set' && s.paint_only_here
      ? { action: 'set', bounds: s.paint_only_here.bounds, mask_path: s.paint_only_here.mask_path, name: s.paint_only_here.name, document_id: document }
      : { action: 'clear', document_id: document };
    const done = await this.bridge('creative', { operation: 'paint_only_here', params }).catch(error => ({ error: String(error) }));
    if (done?.error) return `Krita: the area was not ${area.action === 'set' ? 'protected' : 'cleared'} on the test document: ${done.error}`;
    return area.action === 'set' ? `Krita: the rest of the test document is protected (${s.paint_only_here?.name ?? 'the selection'}).` : 'Krita: the test document paints everywhere again.';
  }

  /** The test chat's document in Krita: one whose file lies in this test chat's folder (its painting target first); never another. */
  private async testDocument(): Promise<string | null> {
    const context = await this.bridge('creative', { operation: 'context', params: {} }, 30).catch(() => null);
    const ours = ((context?.documents ?? []) as { document_id?: string; filename?: string }[])
      .filter(d => typeof d.document_id === 'string' && typeof d.filename === 'string' && d.filename.startsWith(this.folder + sep));
    const target = this.status.painting_target?.document_id;
    return (ours.find(d => d.document_id === target) ?? ours[0])?.document_id ?? null;
  }

  private send(command: Record<string, unknown>): void {
    if (!this.child || this.status.exited) throw new Error('The test companion is not running.');
    this.child.stdin.write(JSON.stringify(command) + '\n');
  }

  private read(chunk: string): void {
    this.buffer += chunk;
    const lines = this.buffer.split('\n'); this.buffer = lines.pop() ?? '';
    for (const line of lines) {
      let event: any; try { event = JSON.parse(line); } catch { continue; }
      const s = this.status;
      if (event.type === 'ready') s.ready = true;
      if (event.type === 'study') s.chat_id = event.id;
      if (event.type === 'busy') {
        if (event.busy && !s.busy) this.busyStarts++;
        if (!event.busy && s.busy) this.idleSince = Date.now();
        s.busy = !!event.busy;
      }
      if (event.type === 'status') s.activity = event.message ?? null;
      if (event.type === 'canvas' && event.path) s.canvas = event.path;
      if (event.type === 'folder' && event.index) s.project_folder = { root: String(event.index.root), name: String(event.index.name ?? ''),
        goal: event.index.goal?.name ?? null, elements: (event.index.elements ?? []).map((e: { name: string; guess?: string }) => ({ name: e.name, guess: e.guess ?? '' })) };
      if (event.type === 'found_area') {
        s.found_areas.push(event); s.found_areas.splice(0, Math.max(0, s.found_areas.length - FOUND_KEPT));
        if (event.message || event.error) s.activity = String(event.message ?? event.error);   // the panel's status line after a find
        if (!this.findRequest || event.request_id === this.findRequest) { this.findRequest = null; s.finding = null; this.idleSince = Date.now(); }
      }
      if (event.type === 'goal_sharpen_offer' || event.type === 'goal_sharpen_review')
        s.sharpen = { kind: event.type === 'goal_sharpen_offer' ? 'offer' : 'review', id: String(event.id), options: (event.options ?? []).map(String),
          text: String(event.message ?? event.question ?? ''), ...(event.image_path ? { image_path: String(event.image_path) } : {}) };
      const card = s.sharpen;
      if (event.type === 'goal_sharpen_progress' && card && card.id === event.id && !event.finished) card.progress = String(event.message ?? '');
      if (event.type === 'goal') {
        s.question = event.goal?.question ?? null;
        s.closeup_question = event.goal?.closeup_question ?? null;
        if ('paint_only_here' in (event.goal ?? {})) s.paint_only_here = event.goal.paint_only_here ?? null;
        if (event.mode) s.mode = event.mode;
        if (event.painting_target !== undefined) s.painting_target = event.painting_target;
        const brief = event.goal?.brief;
        s.plan = brief ? { title: brief.title ?? null, status: event.goal.status ?? null, steps: (brief.steps ?? []).map((step: { title: string }) => step.title) } : null;
        if (Array.isArray(event.plan_steps)) s.plan_steps = event.plan_steps;
        const steps = s.plan_steps;
        const now = steps.find(step => ['painting', 'finishing', 'finished'].includes(step.state)) ?? steps.find(step => step.state === 'open');
        s.now = now ? { caption: CAPTIONS[now.state] ?? now.state, ...now } : null;
        // The goal carries every move with its status (an undo, a retry), as the panel reads them.
        for (const move of Array.isArray(event.goal?.moves) ? event.goal.moves : []) {
          const at = s.moves.findIndex(m => m.number === move.number);
          if (at >= 0) s.moves[at] = { ...s.moves[at], ...move }; else s.moves.push(move);
        }
        s.moves.sort((a, b) => a.number - b.number);
      }
      if (event.type === 'error') s.errors.push(String(event.message));
      if (event.type === 'shape_timing') { const { type: _type, ...timing } = event; s.shape_timings.push(timing); }
      if (event.type === 'shapes_model_needed') s.shapes_model_needed = String(event.message ?? 'The shape model needs a download.');
      if (event.type === 'shapes_model_ready') s.shapes_model_needed = null;
      if (event.type === 'move' && event.move) {
        const at = s.moves.findIndex(m => m.number === event.move.number);
        if (at >= 0) s.moves[at] = event.move; else s.moves.push(event.move);
      }
    }
    this.notify();
  }

  private notify(): void { for (const waiter of [...this.waiters]) waiter(); }

  private until(test: () => boolean, ms: number, label: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (test()) return resolve();
      const check = () => { if (test()) { cleanup(); resolve(); } };
      const tick = setInterval(check, Math.min(1000, Math.max(10, this.quietMs)));
      const timer = setTimeout(() => { cleanup(); reject(new Error('Timed out waiting for ' + label)); }, ms);
      const cleanup = () => { clearInterval(tick); clearTimeout(timer); this.waiters.delete(check); };
      this.waiters.add(check);
    });
  }
}
