/** Live image-asset test: a real painter model, the real Krita bridge and real image models, no mocks.
 *
 *   node scripts/live-asset-test.mjs --companion <this checkout> --output <new scratch folder> --report <report.json>
 *     --provider openrouter --model deepseek/deepseek-v4.1-flash [--width 1024 --height 768]
 *
 * Starts an Agent-mode chat on a new disposable canvas and sends each --step message (default: a
 * Christmas tree, then the sky) as one move, typed as "/skill:image-asset ...". Records every tool the
 * painter called, what the assets cost, and the canvas after each move. Copies the assets and canvases
 * next to the report, then deletes the study folder (--output), pass or fail.
 * Exit 0 passed, 1 failed, 2 blocked.
 */
import { parseArgs } from 'node:util';
import { writeFile, copyFile, mkdir, rm } from 'node:fs/promises';
import { join, resolve, basename } from 'node:path';
import { pathToFileURL } from 'node:url';
import { projectDir } from './project-dir.mjs';

const DEFAULT_STEPS = [
  '/skill:image-asset Paint a simple Christmas painting on this blank canvas. Start with one decorated Christmas tree standing in the centre, its base on a snowy ground line about 85% down the canvas, filling about two thirds of the canvas height.',
  '/skill:image-asset Now paint the sky behind the tree: a deep blue snowy night sky with a soft moon, painted in the same style, without covering the tree.',
];
const { values: args } = parseArgs({ options: { companion: { type: 'string' }, output: { type: 'string' }, report: { type: 'string' },
  provider: { type: 'string' }, model: { type: 'string' }, width: { type: 'string', default: '1024' }, height: { type: 'string', default: '768' },
  step: { type: 'string', multiple: true }, 'idle-seconds': { type: 'string', default: '180' } } });

async function main() {
  const report = { status: 'blocked', provider: args.provider, model: args.model, moves: [] };
  if (!args.companion || !args.output || !args.report || !args.provider || !args.model)
    throw Object.assign(new Error('Give --companion, --output, --report, --provider and --model.'), { blocked: true });
  const companion = resolve(args.companion), output = resolve(args.output), reportPath = resolve(args.report);
  const evidence = reportPath.replace(/\.json$/, '');
  await mkdir(evidence, { recursive: true });
  let runtime, bridge;
  const calls = [];
  try {
    const { PaintingBridge } = await import(pathToFileURL(join(companion, 'src/bridge.mjs')));
    const { StudioRuntime } = await import(pathToFileURL(join(companion, 'src/studio.mjs')));
    const config = { project_root: projectDir(), paintings_dir: output, output: join(output, '.creative-agent'), bridge_url: 'http://127.0.0.1:5678', model_idle_timeout_ms: Number(args['idle-seconds']) * 1000 };
    bridge = new PaintingBridge(companion, config); await bridge.connect();
    const health = await bridge.call('health');
    report.krita_build = health.build?.build_id;
    if (health.session_active) throw Object.assign(new Error('Another Creative Agent session owns the canvas.'), { blocked: true });
    runtime = new StudioRuntime({ root: companion, config, bridge, emit: event => {
      if (event.type === 'tool_start' || event.type === 'tool') calls.push({ tool: event.name ?? event.tool, at: new Date().toISOString() });
      if (event.type === 'error') report.last_error = runtime?.redact(event.message) ?? event.message;
    } });
    await runtime.initialize();
    if (!runtime.models.hasConfiguredAuth(args.provider)) throw Object.assign(new Error('No key for ' + args.provider + '.'), { blocked: true });
    if (!runtime.models.getModel(args.provider, args.model)?.input.includes('image')) throw Object.assign(new Error('Choose a vision painter.'), { blocked: true });
    // Every tool call the painter makes, with its arguments and whether it failed.
    const toolLog = [];
    const original = runtime.buildTools.bind(runtime);
    runtime.buildTools = () => original().map(tool => ({ ...tool, execute: async (id, params, signal) => {
      const entry = { tool: tool.name, params: JSON.stringify(params).slice(0, 600), started: Date.now() };
      toolLog.push(entry);
      try { const result = await tool.execute(id, params, signal); entry.ok = true; entry.result = result?.content?.find(c => c.type === 'text')?.text?.slice(0, 600); return result; }
      catch (error) { entry.ok = false; entry.error = String(error.message).slice(0, 400); throw error; }
      finally { entry.seconds = (Date.now() - entry.started) / 1000; }
    } }));
    await runtime.setExecutionSettings({ routing: 'guide', move_size: 'large' });   // Guide: Luna checks every asset
    const steps = args.step?.length ? args.step : DEFAULT_STEPS;
    // Ask first (no painting), so the limits are set before the first move: every reference-transfer
    // chunk counts as a painting pass, so the run is bounded by time only.
    await runtime.start({ provider: args.provider, model: args.model, chat_mode: 'ask', mode: 'new', width: Number(args.width), height: Number(args.height),
      name: 'Asset test (Christmas)', prompt: 'Reply with one word: ready. Do not paint.' });
    report.chat_id = runtime.study.id;
    await runtime.canvas({ action: 'detach' });        // a new painting: it belongs to no open document
    await runtime.setLimits({ minutes: 40, passes: 0 });
    await runtime.setMode('agent');
    report.status = 'running';
    for (const [index, text] of steps.entries()) {
      const before = toolLog.length;
      const started = Date.now();
      await runtime.prompt(text, { chat_mode: 'agent' });
      const move = runtime.goal.moves?.at(-1);
      const observed = await bridge.call('observe', {}, runtime.study.id).catch(() => null);
      const image = join(evidence, 'move-' + (index + 1) + '.png');
      if (observed?.image_path) await copyFile(observed.image_path, image);
      const log = toolLog.slice(before);
      report.moves.push({ request: text.slice(0, 200), minutes: (Date.now() - started) / 60000, move_status: move?.status, move_request: move?.request?.slice(0, 120),
        tools: log.map(e => ({ tool: e.tool, ok: e.ok, seconds: e.seconds, params: e.params, ...(e.error ? { error: e.error } : {}), ...(e.ok && ['make_asset', 'run_skill_script', 'paint_from_reference', 'read'].includes(e.tool) ? { result: e.result } : {}) })),
        canvas: observed?.image_path ? image : null, reply: runtime.goal.messages?.filter(m => m.role === 'assistant').at(-1)?.text?.slice(0, 1500) });
      console.log('move', index + 1, 'tools:', log.map(e => e.tool + (e.ok ? '' : '!')).join(' '));
    }
    const assets = runtime.study.references.filter(r => r.role === 'asset');
    report.assets = [];
    for (const asset of assets) {
      const target = join(evidence, basename(asset.path));
      await copyFile(asset.path, target).catch(() => {});
      report.assets.push({ id: asset.id, name: asset.name, width: asset.width, height: asset.height, source: asset.source, file: target });
    }
    const all = report.moves.flatMap(m => m.tools);
    const used = name => all.filter(t => t.tool === name);
    report.summary = { read_skill: used('read').length, make_asset: used('make_asset').length, run_skill_script: used('run_skill_script').length,
      paint_from_reference: used('paint_from_reference').length, failed_calls: all.filter(t => !t.ok).length, assets: assets.length,
      asset_cost_usd: all.filter(t => t.tool === 'make_asset' && t.ok).reduce((sum, t) => { try { return sum + (JSON.parse(t.result).cost_usd ?? 0); } catch { return sum; } }, 0) };
    const ok = report.summary.make_asset > 0 && report.summary.paint_from_reference > 0 && assets.length > 0;
    report.status = ok ? 'passed' : 'failed';
  } catch (error) {
    report.reason = runtime?.redact?.(error.message) ?? error.message;
    report.status = error.blocked ? 'blocked' : report.status === 'running' ? 'failed' : 'blocked';
    console.error(report.status.toUpperCase() + ': ' + report.reason);
  } finally {
    if (runtime) { runtime.stop(); await runtime.writeQueue?.catch?.(() => {}); await runtime.end().catch(() => {}); await runtime.releaseLock().catch(() => {}); }
    await bridge?.close?.().catch(() => {});
    report.finished_at = new Date().toISOString();
    await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
    await rm(output, { recursive: true, force: true });
  }
  return report;
}

const report = await main().catch(error => ({ status: 'blocked', reason: error.message }));
console.log(report.status.toUpperCase(), report.summary ? JSON.stringify(report.summary) : report.reason ?? '');
process.exit(report.status === 'passed' ? 0 : report.status === 'failed' ? 1 : 2);
