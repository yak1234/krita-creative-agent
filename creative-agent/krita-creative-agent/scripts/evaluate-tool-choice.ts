// Development only: the tool-choice test set, live. Each scenario of scripts/tool-choice-scenarios.json runs
// --runs times (default 3) through the installed companion, in Agent mode, on a fresh copy of its painting; the
// chat's tool calls are scored (src/tool-choice.ts) and the report counts methods across runs, never one run.
//   node scripts/evaluate-tool-choice.ts [--runs 3] [--only moscow-sky,wave-sky] [--max-moves 3]
//     [--provider deepseek --model deepseek-flash] [--companion <release>/companion/src/main.mjs]
//     [--no-guards] [--compare <earlier report.json>] [--root ~/Documents/digital_art/benchmark-runs]
// Krita must be idle with no other painting open. Copies live in <root>/<stamp>-tool-choice/ and are closed
// unsaved and deleted after each run; the originals are never opened. Not published (curate-public-repo.py).
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { compareReports, scoreToolChoice, summarizeRuns, toolCallsFromEntries, type Report, type Run, type Scenario } from '../src/tool-choice.ts';

type Event = { type: string; [key: string]: any };
const NOT_PAINTING = new Set(['look', 'seed', 'select', 'split', 'sample_canvas_colors', 'list_brushes', 'krita_capabilities', 'read',
  'view_reference', 'painting_tool_help', 'composition_guides', 'finish_move', 'record_progress']);

const argv = process.argv.slice(2);
const args: Record<string, string> = Object.fromEntries(argv.flatMap((a, i) => a.startsWith('--') ? [[a.slice(2), argv[i + 1]?.startsWith('--') || argv[i + 1] === undefined ? 'yes' : argv[i + 1]]] : []));
const runs = Number(args.runs ?? 3), maxMoves = Number(args['max-moves'] ?? 3);
const provider = args.provider ?? 'deepseek', model = args.model ?? 'deepseek-flash';
const set = JSON.parse(await readFile(new URL('./tool-choice-scenarios.json', import.meta.url), 'utf8')) as
  { paintings: Record<string, string>; scenarios: Scenario[] };
const only = args.only?.split(',');
const scenarios = set.scenarios.filter(s => !only || only.includes(s.id));
const panelConfig = process.env.KRITA_CREATIVE_CONFIG || join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json');
const installed = JSON.parse(await readFile(panelConfig, 'utf8'));
const base = args.companion ? { ...installed, companion: resolve(args.companion),
  build_id: JSON.parse(await readFile(join(dirname(dirname(resolve(args.companion))), 'build-info.json'), 'utf8')).build_id } : installed;
const root = resolve(args.root ?? join(base.project_root, 'benchmark-runs'));
const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
const folder = join(root, stamp + '-tool-choice' + (args['no-guards'] ? '-no-guards' : ''));
const log = (...m: unknown[]) => console.log(new Date().toISOString().slice(11, 19), ...m);

async function bridge(action: string, params: Record<string, unknown> = {}): Promise<any> {
  const response = await fetch(base.bridge_url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, params, timeout: 120 }), signal: AbortSignal.timeout(140000) });
  return response.json();
}
const creative = (operation: string, params: Record<string, unknown> = {}) => bridge('creative', { operation, params });

/** One chat on one copy: Agent mode, Keep after each move, until the painter finishes or --max-moves. */
async function chat(scenario: Scenario, run: number): Promise<Run> {
  const dir = join(folder, `${scenario.id}-${run}`), data = join(dir, 'data');
  const copy = join(dir, basename(set.paintings[scenario.painting]));
  await mkdir(data, { recursive: true });
  for (const file of ['execution-settings.json', 'model-connections.json', 'model-catalog.json', 'decision-endpoints.json', 'capabilities/model-capabilities.json']) {
    await mkdir(dirname(join(data, file)), { recursive: true });
    await copyFile(join(base.data_dir, file), join(data, file)).catch((error: NodeJS.ErrnoException) => { if (error.code !== 'ENOENT') throw error; });
  }
  await copyFile(join(base.project_root, set.paintings[scenario.painting]), copy);
  const opened = await bridge('open_file', { path: copy });
  if (opened.error) throw new Error('Could not open the copy: ' + opened.error);
  const context = await creative('context');                         // the copy is now the active painting
  const canvas = { width: Number(context.width) || 1, height: Number(context.height) || 1 };
  const config = { ...base, paintings_dir: dir, data_dir: data, output: data, legacy_output: undefined, loopGuards: !args['no-guards'] };
  await writeFile(join(dir, 'companion-config.json'), JSON.stringify(config, null, 2));
  const companion: ChildProcessWithoutNullStreams = spawn(base.node, [base.companion], { cwd: dirname(base.companion),
    env: { ...process.env, KRITA_CREATIVE_CONFIG: join(dir, 'companion-config.json') } });
  let buffer = '', ready = false, busy = false, busyStarts = 0, idleSince = Date.now(), chatId: string | null = null;
  let lastMove: any = null, goal: any = null;
  const waiters = new Set<{ test: () => boolean; done: () => void }>();
  const notify = () => { for (const w of [...waiters]) if (w.test()) { waiters.delete(w); w.done(); } };
  const tick = setInterval(notify, 1000);
  const until = (test: () => boolean, ms: number, label: string) => new Promise<void>((done, fail) => {
    if (test()) return done();
    const timer = setTimeout(() => { waiters.delete(w); fail(new Error('Timed out waiting for ' + label)); }, ms);
    const w = { test, done: () => { clearTimeout(timer); done(); } };
    waiters.add(w);
  });
  companion.stdout.on('data', chunk => {
    buffer += chunk; const lines = buffer.split('\n'); buffer = lines.pop() ?? '';
    for (const line of lines) {
      let event: Event; try { event = JSON.parse(line); } catch { continue; }
      if (event.type === 'ready') ready = true;
      if (event.type === 'study') chatId = event.id;
      if (event.type === 'busy') { if (event.busy && !busy) busyStarts++; if (!event.busy && busy) idleSince = Date.now(); busy = event.busy; }
      if (event.type === 'move') lastMove = event.move;
      if (event.type === 'goal') goal = event.goal;
      if (event.type === 'error') log('error:', event.message);
      notify();
    }
  });
  companion.stderr.on('data', chunk => process.stderr.write(chunk));
  const send = (command: Record<string, unknown>) => companion.stdin.write(JSON.stringify(command) + '\n');
  const turn = async (command: Record<string, unknown>) => {
    const started = busyStarts; send(command);
    await until(() => busyStarts > started, 120000, command.type + ' to begin');
    await until(() => !busy && Date.now() - idleSince >= 4000, 30 * 60000, command.type + ' to finish');
  };
  try {
    await until(() => ready, 120000, 'the companion to start');
    await turn({ type: 'start', chat_mode: 'agent', prompt: scenario.prompt, provider, model, mode: 'current', name: scenario.id,
      experiment: 'free', canvas: { selected: true }, references: [], message_id: randomUUID() });
    for (let moves = 1; lastMove?.status === 'ready' && moves < maxMoves && !lastMove.request_done && !goal?.question; moves++)
      await turn({ type: 'move', action: 'keep', move: lastMove.number });
  } finally {
    send({ type: 'end' }); await new Promise(r => setTimeout(r, 5000)); send({ type: 'shutdown' });
    await new Promise(r => { companion.once('exit', r); setTimeout(r, 20000); });
    clearInterval(tick);
    const closed = await creative('close_benchmark_copy', { path: copy });
    if (!closed.closed) throw new Error('Krita did not close the copy ' + copy + ': ' + (closed.error ?? 'still open') + '. Close it, then rerun.');
    await rm(copy, { force: true }); await rm(copy + '~', { force: true });
  }
  const db = new DatabaseSync(join(data, 'records.sqlite'), { readOnly: true });
  const rows = db.prepare('SELECT entry FROM session_entries WHERE chat_id = ? ORDER BY key, seq').all(chatId) as { entry: string }[];
  db.close();
  const calls = toolCallsFromEntries(rows.map(row => JSON.parse(row.entry)));
  const scored = scoreToolChoice(calls, scenario, canvas);
  await writeFile(join(dir, 'calls.json'), JSON.stringify({ calls, ...scored }, null, 2));
  log(scenario.id, run, '·', scored.used.join(' ') || 'nothing', '· score', scored.score);
  return { run, used: scored.used, score: scored.score, painted: scored.used.some(m => !NOT_PAINTING.has(m)) };
}

const health = await creative('health');
if (health.build?.build_id !== base.build_id) throw new Error(`Krita runs build ${health.build?.build_id}, the companion is ${base.build_id}.`);
if (health.session_active) throw new Error('A chat holds a painting session; end it first.');
await mkdir(folder, { recursive: true });
const summaries = [], all: Record<string, Run[]> = {};
for (const scenario of scenarios) {
  all[scenario.id] = [];
  for (let run = 1; run <= runs; run++) {
    all[scenario.id].push(await chat(scenario, run).catch(error => { log(scenario.id, run, 'failed:', error.message);
      return { run, used: [], score: 0, painted: false }; }));
  }
  summaries.push(summarizeRuns(scenario, all[scenario.id]));
}
const report: Report & Record<string, unknown> = { build: base.build_id, loop_guards: !args['no-guards'], provider, model,
  runs_per_scenario: runs, scenarios: summaries, runs: all, finished_at: new Date().toISOString() };
await writeFile(join(folder, 'report.json'), JSON.stringify(report, null, 2));
for (const s of summaries) log(s.id.padEnd(16), 'good', JSON.stringify(s.good), 'bad', JSON.stringify(s.bad), 'mean', s.mean_score,
  s.changed_nothing.length ? 'changed nothing: runs ' + s.changed_nothing.join(',') : '');
if (args.compare) {
  const earlier = JSON.parse(await readFile(resolve(args.compare), 'utf8')) as Report;
  for (const row of compareReports(earlier, report)) for (const c of row.changes) log(row.id.padEnd(16), c.method.padEnd(22), c.before, '→', c.after, c.verdict);
}
log('report:', join(folder, 'report.json'));
