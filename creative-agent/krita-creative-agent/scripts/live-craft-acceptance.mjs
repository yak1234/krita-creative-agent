/** Live native-craft acceptance and benchmark: a real painter model, the real Krita bridge, no mocks.
 *
 *   node scripts/live-craft-acceptance.mjs --scenario sphere|starry --companion <this checkout>
 *     --output <empty scratch folder> --report <report.json> --provider deepseek --model deepseek-flash
 *     [--craft on|off] [--routing off|evaluate|guide] [--minutes 20] [--reference <png>] [--idle-seconds 120]
 *
 * sphere (task 7.1): a lit sphere with a cast shadow in at most 6 craft operations, no paint_pass,
 * and the independent review passes. starry (task 7.2): the Starry Night brief with native craft
 * on or off, for the speed table. Each run paints a new disposable document, writes its report and
 * final canvas image next to --report, and deletes its study folder (--output) afterwards, pass or fail.
 * Exit 0 passed, 1 failed, 2 blocked.
 */
import { parseArgs } from 'node:util';
import { readFile, writeFile, copyFile, mkdir, rm } from 'node:fs/promises';
import { join, dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { projectDir } from './project-dir.mjs';

const { values: args } = parseArgs({ options: { scenario: { type: 'string' }, companion: { type: 'string' }, output: { type: 'string' },
  report: { type: 'string' }, provider: { type: 'string' }, model: { type: 'string' }, craft: { type: 'string', default: 'on' },
  routing: { type: 'string', default: 'guide' }, minutes: { type: 'string' }, reference: { type: 'string' }, 'idle-seconds': { type: 'string', default: '120' } } });

const SCENARIOS = {
  sphere: {
    width: 512, height: 512, minutes: 10, passes: 10,
    brief: { title: 'Lit sphere', objective: 'A single sphere lit from the upper left, sitting on a ground plane, with a cast shadow.',
      requirements: ['One round sphere near the centre, lit from the upper left: a lighter side towards the upper left and a darker core shadow towards the lower right.',
        'A cast shadow on the ground to the lower right of the sphere, darkest where the sphere touches the ground.',
        'A plain backdrop with a visible ground plane behind and under the sphere.'],
      freedom: ['Colours of the sphere and backdrop.'],
      steps: [{ title: 'Sphere, light and shadows', done_when: 'The sphere reads as round and lit from the upper left, with a cast shadow on the ground.' }],
      completion: ['The sphere reads as a three-dimensional form lit from the upper left.', 'A cast shadow lies on the ground to the lower right of the sphere.'] },
    prompt: 'Paint the plan with native craft only: flats, clipped multiply and screen layers with gradients, and filters. Use at most 6 craft operations and no brush strokes.',
  },
  starry: {
    width: 800, height: 600, minutes: 20, passes: 150,
    brief: { title: 'Starry Night study', objective: 'A compact, expressive study of the supplied Starry Night reference on the 800×600 canvas, keeping its sweeping sky, cypress, moon and village.',
      requirements: ['Use the supplied reference as the guide for composition and colour on the 800×600 canvas.',
        'A deep ultramarine and cobalt night sky fills most of the upper canvas, with swirling, directional movement.',
        'A large luminous yellow moon in the upper right and several glowing stars with haloes.',
        'A tall, dark, flame-shaped cypress rises from the lower left foreground.',
        'Rolling dark blue hills and a small village with a church spire across the bottom.'],
      freedom: ['Exact brushwork and the number of stars.'],
      steps: [{ title: 'Block in sky and landscape masses', done_when: 'Sky, hills, village band and cypress are placed in their main colours.' },
        { title: 'Swirling sky and lights', done_when: 'The swirls, moon and star haloes read clearly.' },
        { title: 'Foreground and village', done_when: 'The cypress, village and spire are legible.' }],
      completion: ['The composition reads clearly as the Starry Night: swirling sky, moon upper right, cypress left, village below.',
        'Cool blues and warm yellows contrast strongly, with visible directional texture.',
        'The main silhouettes and lights are legible at canvas size.'] },
    prompt: 'Paint the plan.',
  },
};
const STROKE_OPERATIONS = ['paint_pass', 'painting_toolbox'];

async function main() {
  const scenario = SCENARIOS[args.scenario];
  const report = { status: 'blocked', scenario: args.scenario, craft: args.craft, routing: args.routing, provider: args.provider, model: args.model, checks: [] };
  const check = (name, ok, evidence) => { report.checks.push({ name, status: ok ? 'passed' : 'failed', ...evidence }); console.log((ok ? 'PASS ' : 'FAIL ') + name, JSON.stringify(evidence)); };
  if (!scenario || !args.companion || !args.output || !args.report || !args.provider || !args.model || !['on', 'off'].includes(args.craft))
    throw Object.assign(new Error('Give --scenario sphere|starry, --companion, --output, --report, --provider, --model and --craft on|off.'), { blocked: true });
  const companion = resolve(args.companion), output = resolve(args.output), reportPath = resolve(args.report);
  await mkdir(dirname(reportPath), { recursive: true });
  let runtime, bridge;
  const operations = [];
  const startedAt = Date.now();
  try {
    // A release bundles the companion into one file, so the checkout's sources run here; Krita's loaded build is recorded.
    const build = await readFile(join(companion, 'build-info.json'), 'utf8').then(JSON.parse, () => null);
    const { PaintingBridge } = await import(pathToFileURL(join(companion, 'src/bridge.mjs')));
    const { StudioRuntime } = await import(pathToFileURL(join(companion, 'src/studio.mjs')));
    const { CRAFT_OPERATIONS } = await import(pathToFileURL(join(companion, 'src/craft.mjs')));
    // project_root finds the project's Langfuse keys (.env), so benchmark-run.mjs can read the chat; paintings stay in --output.
    const config = { project_root: projectDir(), paintings_dir: output, output: join(output, '.creative-agent'), bridge_url: 'http://127.0.0.1:5678', model_idle_timeout_ms: Number(args['idle-seconds']) * 1000 };
    bridge = new PaintingBridge(companion, config); await bridge.connect();
    const health = await bridge.call('health');
    report.build = health.build?.build_id;
    if (build && health.build?.build_id !== build.build_id) throw Object.assign(new Error('Krita has build ' + health.build?.build_id + '; reload ' + build.build_id + ' first.'), { blocked: true });
    if (health.session_active) throw Object.assign(new Error('Another Creative Agent session owns the canvas. Start a new chat in the panel first.'), { blocked: true });
    const native = bridge.call.bind(bridge);
    bridge.call = async (operation, params = {}, ...rest) => {
      const receipt = await native(operation, params, ...rest);     // observed, never replaced
      if (['paint_pass', 'painting_toolbox', 'adjust_layer', ...CRAFT_OPERATIONS].includes(operation))
        operations.push({ operation, replayed: !!receipt?.replayed, status: receipt?.status, at_ms: Date.now() - startedAt,
          strokes: Array.isArray(params.strokes) ? params.strokes.length : 0, filter: params.filter, layer_id: receipt?.layer_id });
      return receipt;
    };
    const events = {};
    runtime = new StudioRuntime({ root: companion, config, bridge, emit: event => { events[event.type] = (events[event.type] ?? 0) + 1;
      if (event.type === 'error') report.last_error = runtime?.redact(event.message) ?? event.message; } });
    await runtime.initialize();
    if (!runtime.models.hasConfiguredAuth(args.provider)) throw Object.assign(new Error('No key for ' + args.provider + '.'), { blocked: true });
    if (!runtime.models.getModel(args.provider, args.model)?.input.includes('image')) throw Object.assign(new Error('Choose a vision painter.'), { blocked: true });
    await runtime.setExecutionSettings({ routing: args.routing, native_craft: args.craft === 'on' });
    const references = args.scenario === 'starry' && args.reference ? [{ path: resolve(args.reference), purpose: 'composition' }] : [];
    await runtime.start({ provider: args.provider, model: args.model, chat_mode: 'ask', mode: 'new', width: scenario.width, height: scenario.height,
      name: 'Craft ' + args.scenario + ' (' + args.craft + ')', prompt: 'Reply with one word: ready. Do not paint.', references });
    report.chat_id = runtime.study.id;
    await runtime.canvas({ action: 'detach' });        // a new painting: the plan belongs to no open document
    await runtime.editPlan(scenario.brief);
    await runtime.setLimits({ minutes: Number(args.minutes ?? scenario.minutes), passes: scenario.passes });
    await runtime.setMode('autopilot');
    report.status = 'running';
    const paintStart = Date.now();
    await runtime.prompt(scenario.prompt, { start_plan: true });
    report.painting_minutes = (Date.now() - paintStart) / 60000;
    const goal = runtime.goal;
    const ran = operations.filter(o => !o.replayed);
    const count = names => ran.filter(o => names.includes(o.operation)).length;
    const review = goal.reviews.at(-1);
    report.summary = { goal_status: goal.status, passes: goal.passes, tokens: goal.tokens,
      craft_operations: count(CRAFT_OPERATIONS), stroke_operations: count(STROKE_OPERATIONS), paint_pass: count(['paint_pass']),
      strokes: ran.reduce((sum, o) => sum + o.strokes, 0), by_operation: Object.fromEntries([...new Set(ran.map(o => o.operation))].map(n => [n, count([n])])),
      reviews: goal.reviews.length, last_review: review ? { met: review.checks.filter(c => c.met).length, total: review.checks.length, passed: review.checks.every(c => c.met) } : null,
      model_turn_events: events.assistant ?? events.message ?? null };
    const final = await native('observe', {}, runtime.study.id);
    if (final?.image_path) { const image = reportPath.replace(/\.json$/, '') + '.png'; await copyFile(final.image_path, image); report.final_image = image; }
    if (args.scenario === 'sphere') {
      check('at most 6 craft operations', report.summary.craft_operations >= 1 && report.summary.craft_operations <= 6, { craft_operations: report.summary.craft_operations, by_operation: report.summary.by_operation });
      check('no paint_pass', report.summary.paint_pass === 0, { paint_pass: report.summary.paint_pass, stroke_operations: report.summary.stroke_operations });
      check('the independent review passes', !!report.summary.last_review?.passed, { last_review: report.summary.last_review, goal_status: goal.status });
    } else {
      check('the painting ran and was reviewed or stopped at its allowance', ran.length > 0, { operations: ran.length, goal_status: goal.status });
      if (args.craft === 'off') check('craft off: no craft operation reached Krita', report.summary.craft_operations === 0, { craft_operations: report.summary.craft_operations });
    }
    report.status = report.checks.every(c => c.status === 'passed') ? 'passed' : 'failed';
  } catch (error) {
    report.reason = runtime?.redact?.(error.message) ?? error.message;
    report.status = error.blocked ? 'blocked' : report.status === 'running' ? 'failed' : 'blocked';
    console.error(report.status.toUpperCase() + ': ' + report.reason);
  } finally {
    if (runtime) { runtime.stop(); await runtime.writeQueue?.catch?.(() => {}); await runtime.end().catch(() => {}); await runtime.releaseLock().catch(() => {}); }
    await bridge?.close?.().catch(() => {});
    report.operations = operations; report.finished_at = new Date().toISOString();
    await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
    await rm(output, { recursive: true, force: true });          // the study folder, pass or fail
  }
  return report;
}

const report = await main().catch(error => ({ status: 'blocked', reason: error.message }));
console.log(report.status.toUpperCase(), report.summary ? JSON.stringify(report.summary) : report.reason ?? '');
process.exit(report.status === 'passed' ? 0 : report.status === 'failed' ? 1 : 2);
