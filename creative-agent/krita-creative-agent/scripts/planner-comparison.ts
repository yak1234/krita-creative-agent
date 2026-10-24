// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The planner comparison (openspec plan-from-request goal 5, the artist 2026-10-24: "send model comparison by model").
// Real calls, few: for each planner model,
//   (a) the app's own route check (ModelCapabilities.verify: an image read and a tool round trip) and a tool-calling check
//       in a Plan-mode chat (look up paint_finish with painting_tool_help, then propose_plan), both through the studio;
//   (b) the resolution probe is run apart (scripts/resolution-probe.ts --painter ... --record-to src/model-resolutions.json);
//   (c) one real planning turn a message on a copy of a project folder, exactly as the companion sends it: the studio
//       itself (StudioRuntime) with the painter model as the chat's model and the Planner model setting set to the
//       candidate, a fake Krita bridge (an empty canvas of the given size; nothing is painted before Start painting).
// Decision checks are off (the keywords read the stages), so the comparison is of the planners alone.
//   node scripts/planner-comparison.ts --folder <project folder> --painter deepseek/deepseek-flash \
//     --planner openrouter/deepseek/deepseek-v4.1-flash --planner painter --out comparison.json
// Keys come from Pi's own auth (as the app); they are never printed. The folder is copied first and only the copy is used.
import { parseArgs } from 'node:util';
import { cp, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { encodeRgba } from '../src/shapes/png.ts';

const { values } = parseArgs({ options: { folder: { type: 'string' }, painter: { type: 'string' }, planner: { type: 'string', multiple: true },
  message: { type: 'string', multiple: true }, out: { type: 'string' }, width: { type: 'string' }, height: { type: 'string' }, 'skip-checks': { type: 'boolean' } } });
if (!values.folder || !values.painter || !values.planner?.length || !values.out) {
  process.stderr.write('Give --folder, --painter provider/model, one or more --planner (provider/model or painter) and --out.\n'); process.exit(2);
}
const messages = values.message?.length ? values.message : ['paint the underpainting', 'paint it like the goal'];
const WIDTH = Number(values.width ?? 6000), HEIGHT = Number(values.height ?? 4500);
const split = (route: string) => { const at = route.indexOf('/'); return [route.slice(0, at), route.slice(at + 1)] as const; };

const { ModelRuntime, getAgentDir } = await import('@earendil-works/pi-coding-agent');
// @ts-ignore: .mjs modules (allowJs is off in the strict project)
const { inheritPiCatalog } = await import('../src/model-catalog.mjs');
// @ts-ignore
const { StudioRuntime } = await import('../src/studio.mjs');
// @ts-ignore
const { ModelCapabilities } = await import('../src/model-capabilities.mjs');
// @ts-ignore: the tests' in-memory Langfuse, so nothing is traced to the artist's Langfuse
const { recordingTracing } = await import('../tests/fake-langfuse.mjs');

const scratch = await mkdtemp(join(tmpdir(), 'planner-comparison-'));
const pi = getAgentDir();
const models = await ModelRuntime.create({ allowModelNetwork: false, authPath: join(pi, 'auth.json'), modelsPath: join(pi, 'models.json'),
  modelsStorePath: await inheritPiCatalog(pi, scratch), signal: AbortSignal.timeout(15000) });
const [painterProvider, painterId] = split(values.painter);
if (!models.getModel(painterProvider, painterId)) { process.stderr.write(`Pi has no model ${values.painter}.\n`); process.exit(2); }

// An empty canvas of the comparison's size, seen as a small view (the plugin's views are about 1568 px).
const viewWidth = 1568, viewHeight = Math.round(1568 * HEIGHT / WIDTH);
const view = encodeRgba({ width: viewWidth, height: viewHeight, data: new Uint8Array(viewWidth * viewHeight * 4).fill(255) });

type Any = any;
async function studio(output: string) {
  const events: Any[] = [], diagnostics: Any[] = [];
  const bridge = { async call(operation: string, params: Any) {
    if (operation === 'context') return { document_id: 'doc', active_document_id: 'doc', name: 'Untitled', filename: '', width: WIDTH, height: HEIGHT, modified: true, revision: 'revision-0' };
    if (['begin', 'peek', 'observe'].includes(operation)) {
      const path = join(params.output_dir ?? output, 'view.png'); await writeFile(path, view);
      return { status: 'ok', document_id: 'doc', name: 'Untitled', filename: '', modified: true, width: WIDTH, height: HEIGHT, image_path: path, layers: [],
        revision: 'revision-0', content_id: 'content-0', captured_at: new Date().toISOString() };
    }
    if (operation === 'painting_tool_help') return { tools: [] };
    return { status: 'ok' };
  } };
  const capabilities = { async initialize() {}, status() { return { status: 'verified', route_verified: true, images_supported: true, tools_supported: true }; },
    async verify() { return { route_verified: true, cached: true }; }, async invalidate() {} };
  const runtime = new StudioRuntime({ root: output, config: { output, prevent_idle_sleep: false }, models, bridge, capabilities, tracing: recordingTracing(), emit: (e: Any) => events.push(e) });
  runtime.diagnostics = { record: (event: Any) => diagnostics.push(event) };
  return { runtime, events, diagnostics };
}

/** Tokens and cost of the assistant messages the planner wrote in this chat's session. */
function usage(runtime: Any, planner: { provider: string; id: string }) {
  const out = { requests: 0, input: 0, output: 0, cache_read: 0, cost: 0 };
  for (const m of runtime.session?.messages ?? []) {
    if (m.role !== 'assistant' || m.provider !== planner.provider || m.model !== planner.id) continue;
    out.requests++; out.input += m.usage?.input ?? 0; out.output += m.usage?.output ?? 0; out.cache_read += m.usage?.cacheRead ?? 0; out.cost += m.usage?.cost?.total ?? 0;
  }
  out.cost = Math.round(out.cost * 1e6) / 1e6;
  return out;
}
const errorsOf = (events: Any[], runtime: Any) => [...events.filter(e => e.type === 'status' && e.phase === 'error').map(e => e.message),
  ...(runtime.runError ? [runtime.runError] : [])].map(String).filter((m, i, a) => a.indexOf(m) === i);

async function planningTurn(planner: string, message: string) {
  const output = await mkdtemp(join(scratch, 'chat-')), folder = join(output, 'folder');
  await cp(values.folder!, folder, { recursive: true });
  const { runtime, events, diagnostics } = await studio(output);
  await runtime.loadProbeRecords();
  await runtime.setExecutionSettings({ planner_model: planner });
  await runtime.openFolder({ path: folder });
  const plannerModel = planner === 'painter' ? { provider: painterProvider, id: painterId } : (([p, id]) => ({ provider: p, id }))(split(planner));
  const started = Date.now();
  let thrown: string | null = null;
  try { await runtime.start({ provider: painterProvider, model: painterId, chat_mode: 'agent', prompt: message, mode: 'copy' }); }
  catch (error) { thrown = (error as Error).message; }
  const ms = Date.now() - started;
  const brief = runtime.goal?.brief;
  const proposed = (runtime.goal?.revisions ?? []).some((r: Any) => r.source === 'model');
  const result = { planner, message, ms, proposed_by_model: proposed, stages: runtime.goal?.plan_stages ?? null,
    steps: (brief?.steps ?? []).map((s: Any) => ({ title: s.title, kind: s.kind ?? null, tool: s.tool ?? null, done_when: s.done_when, ...(s.parts ? { parts: s.parts } : {}), ...(s.checks ? { checks: s.checks } : {}) })),
    lookups: diagnostics.filter(d => d.type === 'planner_tool_help').map(d => d.name ?? '(catalogue)'),
    shaped: diagnostics.filter(d => d.type === 'folder_plan_shaped'), planner_used: diagnostics.find(d => d.type === 'planner_model') ?? null,
    tool_calls: (runtime.session?.messages ?? []).filter((m: Any) => m.role === 'assistant').flatMap((m: Any) => (m.content ?? []).filter((c: Any) => c.type === 'toolCall').map((c: Any) => c.name)),
    reply: (runtime.session?.messages ?? []).filter((m: Any) => m.role === 'assistant').flatMap((m: Any) => (m.content ?? []).filter((c: Any) => c.type === 'text').map((c: Any) => c.text)).join('\n').slice(0, 1500),
    errors: [...(thrown ? [thrown] : []), ...errorsOf(events, runtime)], usage: usage(runtime, plannerModel) };
  await runtime.end().catch(() => {}); runtime.dispose?.();
  return result;
}

async function toolCheck(planner: string) {
  const output = await mkdtemp(join(scratch, 'check-'));
  const { runtime, events, diagnostics } = await studio(output);
  await runtime.loadProbeRecords();
  await runtime.setExecutionSettings({ planner_model: planner });
  const plannerModel = planner === 'painter' ? { provider: painterProvider, id: painterId } : (([p, id]) => ({ provider: p, id }))(split(planner));
  const started = Date.now();
  let thrown: string | null = null;
  try { await runtime.start({ provider: painterProvider, model: painterId, chat_mode: 'plan', mode: 'copy',
    prompt: 'Tool check. First call painting_tool_help with the name paint_finish. Then call propose_plan with a one-step plan to paint a red circle in the centre (title, objective, requirements, freedom, completion and one step). Then stop.' }); }
  catch (error) { thrown = (error as Error).message; }
  const calls = (runtime.session?.messages ?? []).filter((m: Any) => m.role === 'assistant').flatMap((m: Any) => (m.content ?? []).filter((c: Any) => c.type === 'toolCall').map((c: Any) => ({ name: c.name, arguments: c.arguments })));
  const failed = (runtime.session?.messages ?? []).filter((m: Any) => m.role === 'toolResult' && m.isError).map((m: Any) => ({ tool: m.toolName, text: String(m.content?.[0]?.text ?? '').slice(0, 300) }));
  const result = { planner, ms: Date.now() - started, calls: calls.map((c: Any) => c.name), help_named: calls.some((c: Any) => c.name === 'painting_tool_help' && c.arguments?.name === 'paint_finish'),
    lookups: diagnostics.filter(d => d.type === 'planner_tool_help').map(d => d.name ?? '(catalogue)'), plan_saved: !!runtime.goal?.brief, failed_calls: failed,
    errors: [...(thrown ? [thrown] : []), ...errorsOf(events, runtime)], usage: usage(runtime, plannerModel) };
  await runtime.end().catch(() => {}); runtime.dispose?.();
  return result;
}

async function routeCheck(planner: string) {
  const [provider, id] = planner === 'painter' ? [painterProvider, painterId] : split(planner);
  const model = models.getModel(provider, id);
  if (!model) return { planner, error: 'not in the catalog' };
  const started = Date.now();
  const service = await new ModelCapabilities({ models, cacheDirectory: join(scratch, 'capabilities') }).initialize();
  try { const r = await service.verify(model, { force: true }); return { planner, ms: Date.now() - started, route_verified: !!r.route_verified, usage: r.usage ?? null }; }
  catch (error) { return { planner, ms: Date.now() - started, route_verified: false, error: (error as Error).message, code: (error as Any).code ?? null }; }
}

try {
  const results: Any = { measured_at: new Date().toISOString(), painter: values.painter, canvas: [WIDTH, HEIGHT], messages, decision_checks: 'off', planners: {} };
  for (const planner of values.planner) {
    const entry: Any = results.planners[planner] = {};
    process.stderr.write(`${planner}: checks\n`);
    if (!values['skip-checks']) { entry.route_check = await routeCheck(planner); entry.tool_check = await toolCheck(planner); }
    entry.turns = [];
    for (const message of messages) {
      process.stderr.write(`${planner}: "${message}"\n`);
      entry.turns.push(await planningTurn(planner, message));
    }
    await writeFile(values.out, JSON.stringify(results, null, 2) + '\n');
  }
  process.stderr.write(`Wrote ${values.out}.\n`);
} finally { await rm(scratch, { recursive: true, force: true }); }
process.exit(0);
