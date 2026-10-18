// A test companion: the installed companion run as a separate process with its own data folder, driven over
// stdin/stdout exactly as the panel drives it, so test chats never appear in the artist's chat list. It works on a
// copy of a painting (opened in Krita, closed unsaved and deleted at the end) or on a new painting. Development
// only: scripts/evaluate-tool-choice.ts and scripts/test-driver.ts (the MCP's creative_test_* tools) use it.
import { spawn as spawnProcess, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { copyFile, mkdir, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { toolCallsFromEntries, type Call } from './tool-choice.ts';

/** The installed companion's settings (the panel's creative-agent-config.json). */
export type Base = { node: string; companion: string; data_dir: string; project_root: string; bridge_url: string; build_id: string; [key: string]: unknown };
export type Bridge = (action: string, params?: Record<string, unknown>, timeoutSeconds?: number) => Promise<any>;
export type Spawn = (command: string, args: string[], options: { cwd: string; env: NodeJS.ProcessEnv }) => ChildProcessWithoutNullStreams;
export type StartOptions = { prompt: string; painting?: string; width?: number; height?: number; name?: string;
  provider?: string; model?: string; loopGuards?: boolean };
export type Move = { number: number; status: string; title?: string; actions?: number; strokes?: number; request_done?: boolean; [key: string]: unknown };
export type TestState = { folder: string; chat_id: string | null; ready: boolean; busy: boolean; activity: string | null;
  moves: Move[]; question: unknown; canvas: string | null; copy: string | null; errors: string[]; exited: boolean };

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
  private child: ChildProcessWithoutNullStreams | null = null;
  private buffer = '';
  private busyStarts = 0;
  private idleSince = Date.now();
  private readonly waiters = new Set<() => void>();
  private readonly status: TestState;

  constructor(base: Base, folder: string, { bridge, spawn = spawnProcess as unknown as Spawn, quietMs = 4000, startMs = 120000 }:
    { bridge: Bridge; spawn?: Spawn; quietMs?: number; startMs?: number }) {
    this.base = base; this.folder = folder; this.bridge = bridge; this.spawn = spawn; this.quietMs = quietMs; this.startMs = startMs;
    this.status = { folder, chat_id: null, ready: false, busy: false, activity: null, moves: [], question: null, canvas: null, copy: null, errors: [], exited: false };
  }

  /** Start a test chat in Agent mode. With `painting` (relative to the project root) a copy is opened in Krita;
   * without it the companion makes a new painting. Returns once the request is sent; waitIdle() waits for the move. */
  async start(options: StartOptions): Promise<{ copy: string | null; krita: string }> {
    const health = await this.bridge('creative', { operation: 'health', params: {} });
    if (health.session_active) throw new Error('Krita holds a painting session (the artist’s chat); end it before a test chat.');
    if (health.build?.build_id !== this.base.build_id) throw new Error(`Krita runs build ${health.build?.build_id}, the installed companion is ${this.base.build_id}.`);
    const data = join(this.folder, 'data');
    await mkdir(data, { recursive: true });
    for (const file of SETTINGS) {
      await mkdir(dirname(join(data, file)), { recursive: true });
      await copyFile(join(this.base.data_dir, file), join(data, file)).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'ENOENT') throw error; });
    }
    let krita = 'Krita: a new painting will be created by the test chat (nothing of yours is opened).';
    if (options.painting) {
      const copy = join(this.folder, basename(options.painting));
      await copyFile(join(this.base.project_root, options.painting), copy);
      this.status.copy = copy;                     // from here on, a failure closes and deletes the copy
      // Opening a large painting can take minutes while Krita is busy (an autosave): wait for it.
      const opened = await this.bridge('open_file', { path: copy }, 900).catch(error => ({ error: String(error) }));
      if (opened.error) { await this.discardCopy(); throw new Error('Could not open the copy: ' + opened.error); }
      krita = `Krita: opened a copy of ${options.painting} at ${copy}; the original is untouched. It is closed unsaved and deleted at the end.`;
    }
    try {
      return await this.launch(options, data, krita);
    } catch (error) {
      this.child?.kill();
      await this.discardCopy();
      throw error;
    }
  }

  private async launch(options: StartOptions, data: string, krita: string): Promise<{ copy: string | null; krita: string }> {
    const config = { ...this.base, paintings_dir: this.folder, data_dir: data, output: data, legacy_output: undefined, loopGuards: options.loopGuards !== false };
    await writeFile(join(this.folder, 'companion-config.json'), JSON.stringify(config, null, 2));
    this.child = this.spawn(this.base.node, [this.base.companion], { cwd: dirname(this.base.companion),
      env: { ...process.env, KRITA_CREATIVE_CONFIG: join(this.folder, 'companion-config.json') } });
    this.child.stdout.on('data', chunk => this.read(String(chunk)));
    this.child.stderr.on('data', chunk => { const text = String(chunk).trim(); if (text) this.status.errors.push(text.slice(0, 500)); });
    this.child.on('exit', () => { this.status.exited = true; this.notify(); });
    await this.until(() => this.status.ready, this.startMs, 'the companion to start');
    const started = this.busyStarts;
    this.send({ type: 'start', chat_mode: 'agent', prompt: options.prompt, provider: options.provider, model: options.model,
      mode: options.painting ? 'current' : 'new', width: options.width, height: options.height, name: options.name ?? 'Test chat',
      experiment: 'free', canvas: { selected: !!options.painting }, references: [], message_id: randomUUID() });
    await this.until(() => this.busyStarts > started || this.status.exited, this.startMs, 'the request to begin');
    return { copy: this.status.copy, krita };
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

  /** Wait until the companion has been idle for a moment (a move finished), or `ms` pass; returns the state either way. */
  async waitIdle(ms: number): Promise<TestState> {
    await this.until(() => this.status.exited || (!this.status.busy && Date.now() - this.idleSince >= this.quietMs), ms, 'the move').catch(() => {});
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
      this.send({ type: 'end' });
      await new Promise(resolve => setTimeout(resolve, Math.min(5000, this.quietMs * 2)));
      this.send({ type: 'shutdown' });
      await this.until(() => this.status.exited, 20000, 'the companion to exit').catch(() => this.child?.kill());
    }
    let krita = 'Krita: nothing to close (the test chat made its own painting).';
    if (this.status.copy) {
      const closed = await this.bridge('creative', { operation: 'close_benchmark_copy', params: { path: this.status.copy } }, 300);
      if (!closed.closed) throw new Error(`Krita did not close the copy ${this.status.copy}: ${closed.error ?? 'still open'}. Close it by hand.`);
      await rm(this.status.copy, { force: true }); await rm(this.status.copy + '~', { force: true });
      krita = `Krita: closed the copy ${this.status.copy} unsaved and deleted it.`;
      this.status.copy = null;
    }
    return { krita };
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
      if (event.type === 'goal') s.question = event.goal?.question ?? null;
      if (event.type === 'error') s.errors.push(String(event.message));
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
