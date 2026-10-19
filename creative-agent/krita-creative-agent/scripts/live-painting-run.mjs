// Development only: one unattended painting run in the live Krita, through the installed companion,
// driven over stdin/stdout exactly as the panel drives it. Plan from a reference → allowance → Autopilot,
// then the final image, the chat's Langfuse benchmark and a report. Not published (curate-public-repo.py).
//   node scripts/live-painting-run.mjs --name rothko --reference ref.png --prompt "Paint ..." [--minutes 20]
//     [--width 1200 --height 1500] [--provider deepseek --model deepseek-flash]
//     [--root ~/Documents/digital_art/benchmark-runs] [--note "what this run tests"]
// Each run gets its own data folder (its own chats and records), with copies of the artist's settings, so it
// never touches their chats. It starts with the canvas detached and paints on a new document.
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const exec = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, a, i, all) => a.startsWith('--') ? [...pairs, [a.slice(2), all[i + 1]?.startsWith('--') ? 'yes' : all[i + 1]]] : pairs, []));
const need = key => { if (!args[key]) { console.error('Missing --' + key); process.exit(2); } return args[key]; };
const name = need('name'), prompt = need('prompt'), reference = resolve(need('reference'));
const minutes = Number(args.minutes ?? 20), width = Number(args.width ?? 1200), height = Number(args.height ?? 1500);
const provider = args.provider ?? 'deepseek', model = args.model ?? 'deepseek-flash';
const panelConfig = process.env.KRITA_CREATIVE_CONFIG || join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json');
const installed = JSON.parse(await readFile(panelConfig, 'utf8'));
// --companion <release>/companion/src/main.mjs runs another installed build, e.g. the one Krita has loaded
// while a newer one waits for a restart, or the build a baseline ran on (an A/B must change one thing).
const base = args.companion ? { ...installed, companion: resolve(args.companion),
  build_id: JSON.parse(await readFile(join(dirname(dirname(resolve(args.companion))), 'build-info.json'), 'utf8')).build_id } : installed;
const root = resolve(args.root ?? join(base.project_root, 'benchmark-runs'));
const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
const run = join(root, stamp + '-' + name), data = join(run, 'data');
const log = (...m) => console.log(new Date().toISOString().slice(11, 19), ...m);

async function bridge(action, params = {}) {
  const response = await fetch(base.bridge_url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, params, timeout: 30 }), signal: AbortSignal.timeout(40000) });
  return response.json();
}

// Preflight: the bridge runs the same build, and no chat holds a painting session.
const health = await bridge('creative', { operation: 'health', params: {} });
if (health.build?.build_id !== base.build_id) throw new Error('Krita runs build ' + health.build?.build_id + ', the companion is ' + base.build_id + '.');
if (health.session_active) throw new Error('Another chat holds a painting session; end it first.');

await mkdir(data, { recursive: true });
const source = base.data_dir;
// --fresh-capabilities leaves the capability cache behind, so the companion probes the model itself.
const copied = ['execution-settings.json', 'model-connections.json', 'model-catalog.json', 'decision-endpoints.json', ...('fresh-capabilities' in args ? [] : ['capabilities/model-capabilities.json'])];
for (const file of copied) {
  await mkdir(dirname(join(data, file)), { recursive: true });
  await copyFile(join(source, file), join(data, file)).catch(error => { if (error.code !== 'ENOENT') throw error; });
}
// --setting key=value overrides one copied execution setting (an A/B run), e.g. --setting reasoning=low.
if (args.setting) {
  const [key, raw] = args.setting.split('='), file = join(data, 'execution-settings.json');
  const settings = JSON.parse(await readFile(file, 'utf8').catch(() => '{}'));
  settings[key] = /^\d+$/.test(raw) ? Number(raw) : raw === 'true' ? true : raw === 'false' ? false : raw;
  await writeFile(file, JSON.stringify(settings));
}
const config = { ...base, paintings_dir: run, data_dir: data, output: data, legacy_output: undefined };
const configPath = join(run, 'companion-config.json');
await writeFile(configPath, JSON.stringify(config, null, 2));
await copyFile(reference, join(run, 'reference' + reference.slice(reference.lastIndexOf('.'))));

const report = { name, note: args.note ?? null, setting: args.setting ?? null, prompt, reference, minutes, width, height, provider, model, build: base.build_id,
  started_at: new Date().toISOString(), chat_id: null, status: null, questions_answered: 0, errors: [], timeline: [] };
const companion = spawn(base.node, [base.companion], { cwd: dirname(base.companion), env: { ...process.env, KRITA_CREATIVE_CONFIG: configPath } });
let lastMove = null;
let buffer = '', goal = null, busy = false, lastCanvas = null, ready = false, busyStarts = 0, idleSince = Date.now();
const waiters = new Set();
setInterval(() => notify(), 1000).unref();   // re-checks time-based conditions such as "idle for 4 s"
const notify = () => { for (const w of [...waiters]) if (w.test()) { waiters.delete(w); w.resolve(); } };
const until = (test, ms, label) => new Promise((resolve, reject) => {
  if (test()) return resolve();
  const w = { test, resolve: () => { clearTimeout(timer); resolve(); } };
  const timer = setTimeout(() => { waiters.delete(w); reject(new Error('Timed out waiting for ' + label)); }, ms);
  waiters.add(w);
});
companion.stdout.on('data', chunk => {
  buffer += chunk; const lines = buffer.split('\n'); buffer = lines.pop();
  for (const line of lines) {
    let event; try { event = JSON.parse(line); } catch { continue; }
    if (event.type === 'ready') ready = true;
    if (event.type === 'study') report.chat_id = event.id;
    if (event.type === 'busy') { if (event.busy && !busy) busyStarts++; if (!event.busy && busy) idleSince = Date.now(); busy = event.busy; }
    if (event.type === 'goal') goal = event.goal;
    if (event.type === 'move') lastMove = event.move;
    if (event.type === 'canvas' && event.path) lastCanvas = event;
    if (event.type === 'error') { report.errors.push(event.message); log('error:', event.message); }
    if (event.type === 'status' && /Move|Step|review|Paused|allowance|Ready/i.test(event.message ?? '')) log(event.message);
    if (['busy', 'study', 'question', 'review', 'ended'].includes(event.type)) report.timeline.push({ at: new Date().toISOString(), type: event.type, ...(event.type === 'busy' ? { busy: event.busy } : {}) });
    notify();
  }
});
companion.stderr.on('data', chunk => process.stderr.write(chunk));
const send = command => companion.stdin.write(JSON.stringify(command) + '\n');
// A turn: the companion goes busy after the command, then stays idle for a few seconds (one request can
// make several busy periods). Busy pulses from before the command, such as start-up imports, do not count.
async function turn(command, ms) {
  const started = busyStarts;
  send(command);
  await until(() => busyStarts > started, 120000, command.type + ' to begin');
  await until(() => !busy && Date.now() - idleSince >= 4000, ms, command.type + ' to finish');
}
const answer = async mode => { report.questions_answered++; log('answering:', goal.question.question);
  await turn({ type: 'prompt', text: 'You decide.', chat_mode: mode, message_id: randomUUID() }, 15 * 60000); };

// --mode agent: the artist's Agent workflow instead of a plan: one request, then Keep after every move, until the
// painter marks a move as finishing the request (Keep then ends it) or makes an empty move, or --max-moves (10)
// or --minutes (30) run out.
async function agentRun() {
  const maxMoves = Number(args['max-moves'] ?? 10), budget = Number(args.minutes ?? 30) * 60000, started = Date.now();
  report.mode = 'agent'; report.moves = [];
  log('companion ready; agent mode', name);
  const record = () => { const m = lastMove; if (!m) return;
    report.moves.push({ number: m.number, title: m.title ?? null, status: m.status, actions: m.actions, strokes: m.strokes,
      finished_by_painter: !!m.finished, request_done: !!m.request_done, hit_size_limit: !!m.limited, seconds: m.finished_at && m.started_at ? (Date.parse(m.finished_at) - Date.parse(m.started_at)) / 1000 : null });
    log('move', m.number, m.status, '·', m.actions, 'actions ·', m.strokes, 'strokes ·', m.limited ? 'size limit' : m.finished ? 'painter finished' : '', '·', m.title ?? ''); };
  await turn({ type: 'start', chat_mode: 'agent', prompt, provider, model, mode: 'new', name: 'Benchmark ' + name, width, height, experiment: 'free',
    canvas: { selected: false }, references: [{ path: reference, role: 'reference', name: basename(reference), purpose: 'general', notes: '' }],
    message_id: randomUUID() }, 30 * 60000);
  record();
  while (lastMove?.status === 'ready' && report.moves.length < maxMoves && Date.now() - started < budget) {
    if (goal?.question) { await answer('agent'); record(); continue; }
    const done = !!lastMove.request_done;
    await turn({ type: 'move', action: 'keep', move: lastMove.number }, 30 * 60000);   // the panel's Keep button
    if (done) break;                                                                    // Keep ended the request; no new move
    record();
  }
  const ended = !!lastMove?.request_done;
  report.artist_actions = { requests: 1, keeps: Math.max(0, report.moves.length - (ended ? 0 : 1)) };   // what the artist had to do
  report.painting_minutes = Math.round((Date.now() - started) / 600) / 100;
  report.stopped_because = ended ? 'request done' : lastMove?.status !== 'ready' ? 'move ' + lastMove?.status : report.moves.length >= maxMoves ? 'max moves' : 'time';
}

try {
  await until(() => ready, 120000, 'the companion to start');
  if (args.mode === 'agent') { await agentRun(); throw null; }
  log('companion ready; planning', name);
  await turn({ type: 'start', chat_mode: 'plan', prompt, provider, model, mode: 'new', name: 'Benchmark ' + name, width, height, experiment: 'free',
    canvas: { selected: false }, references: [{ path: reference, role: 'reference', name: basename(reference), purpose: 'general', notes: '' }],
    message_id: randomUUID() }, 15 * 60000);
  for (let i = 0; i < 3 && goal?.question; i++) await answer('plan');
  if (!goal?.brief) await turn({ type: 'prompt', text: 'Make the plan now.', chat_mode: 'plan', message_id: randomUUID() }, 15 * 60000);
  if (!goal?.brief) throw new Error('No plan was made.');
  report.plan = { title: goal.brief.title, steps: goal.brief.steps.map(s => s.title) };
  log('plan:', goal.brief.title, '·', goal.brief.steps.length, 'steps');
  send({ type: 'set_limits', limits: { minutes, passes: 0 } });
  send({ type: 'set_mode', mode: 'autopilot' });
  await until(() => goal?.limits?.minutes === minutes, 30000, 'the allowance');
  const painting = Date.now();
  await turn({ type: 'prompt', text: 'Start painting from this plan.', chat_mode: 'autopilot', start_plan: true, message_id: randomUUID() }, (minutes + 20) * 60000);
  for (let i = 0; i < 3 && goal?.question && goal.status !== 'complete'; i++) await answer('autopilot');
  report.painting_minutes = Math.round((Date.now() - painting) / 600) / 100;
} catch (error) { if (error !== null) { report.errors.push(String(error.message)); log('run stopped:', error.message); } }

report.status = goal?.status ?? null;
report.passes = goal?.passes ?? 0; report.tokens = goal?.tokens ?? 0; report.ai_images_used = goal?.ai_images_used ?? 0;
const review = goal?.reviews?.at(-1);
report.last_review = review ? { verdict: review.verdict, met: review.checks?.filter(c => c.met).length, total: review.checks?.length, summary: review.summary } : null;
if (lastCanvas?.path) { await copyFile(lastCanvas.path, join(run, 'final' + lastCanvas.path.slice(lastCanvas.path.lastIndexOf('.')))).catch(() => {}); report.checkpoint = lastCanvas.checkpoint ?? null; }
send({ type: 'end' });
await new Promise(r => setTimeout(r, 5000));
send({ type: 'shutdown' });
await new Promise(r => { companion.once('exit', r); setTimeout(r, 20000); });
report.finished_at = new Date().toISOString();
// Langfuse takes a moment to ingest the last traces (the final review); benchmark after it has them.
if (report.chat_id) await new Promise(r => setTimeout(r, 60000));
if (report.chat_id) {
  try {
    const { stdout } = await exec(process.execPath, [join(here, 'benchmark-run.mjs'), report.chat_id, '--json', join(run, 'benchmark.json')],
      { env: { ...process.env, KRITA_PROJECT_DIR: base.project_root, NODE_OPTIONS: '' }, timeout: 300000 });
    report.benchmark = stdout.trim();
  } catch (error) { report.errors.push('benchmark: ' + error.message.slice(0, 300)); }
}
await writeFile(join(run, 'report.json'), JSON.stringify(report, null, 2));
log('done:', report.status, '·', report.painting_minutes, 'min ·', report.last_review ? report.last_review.met + '/' + report.last_review.total + ' checks' : 'no review', '·', run);
