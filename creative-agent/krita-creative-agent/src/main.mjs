// @ts-check
import { LiveDiagnostics } from './live-diagnostics.mjs';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PaintingBridge } from './bridge.mjs';
import { StudioRuntime } from './studio.mjs';
import { splitJsonLines } from './files.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configPath = process.env.KRITA_CREATIVE_CONFIG || resolve(root, '.local-config.json');
const emit = event => process.stdout.write(JSON.stringify(event) + '\n');
/** @type {any} */   // StudioRuntime; typed once studio.mjs and runtime.mjs are checked
let runtime;
let buffer = '';
let shuttingDown = false;
const pending = new Set();
try {
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  runtime = new StudioRuntime({ root, config, bridge: new PaintingBridge(root, config), emit });
  const diagnostics=new LiveDiagnostics(runtime); diagnostics.attach();
  await runtime.initialize();
  try {await diagnostics.start();}
  catch(error) {runtime.emit({type:'error',message:'Live diagnostics unavailable: '+runtime.redact(error.message)});}
} catch (error) {
  emit({ type: 'error', message: 'Could not start the creative assistant: ' + (runtime?.redact(error.message) ?? error.message) });
  await runtime?.bridge.close().catch(() => {});
  await runtime?.releaseLock().catch(() => {});
  process.exit(1);
}

async function handle(command) {
  try {
    if (shuttingDown) return;
    switch (command.type) {
      case 'start': await runtime.start(command); break;
      case 'resume': command.path ? await runtime.resumeFile(command.path) : await runtime.resume(command.id); break;
      case 'prompt': await runtime.prompt(command.text, command); break;
      case 'reconnect': await runtime.reconnect(); break;
      case 'context': await runtime.canvas(command); break;
      case 'diagnostic_ui': runtime.diagnostics.ui={captured_at:new Date().toISOString(),connection:command.connection}; break;
      case 'export_diagnostics': {
        const result = await runtime.diagnostics.report();
        emit({type:'diagnostics_exported',...result}); break;
      }
      case 'history': await runtime.history(command.query); break;
      case 'relink': await runtime.relink(command.id,command.path); break;
      case 'delete_chat': await runtime.deleteChat(command.id); break;
      case 'export_archive': await runtime.exportArchive(command); break;
      case 'import_archive': await runtime.importArchive(command); break;
      case 'set_reference_purpose': await runtime.setReferencePurpose(command); break;
      case 'remove_reference': await runtime.removeReference(command); break;
      case 'open_folder': await runtime.openFolder(command); break;
      case 'folder_guess': await runtime.folderGuess(command); break;
      case 'inspect_result': await runtime.inspectResult(); break;
      case 'reconcile': await runtime.reconcile(); break;
      case 'review_pass': await runtime.reviewPass(command); break;
      case 'set_model': await runtime.setModel(command.provider,command.model); break;
      case 'set_mode': await runtime.setMode(command.mode); break;
      case 'use_attached_canvas': await runtime.useAttachedCanvas(); break;
      case 'edit_plan': await runtime.editPlan(command.brief); break;
      case 'comic': await runtime.setComic(command.comic ?? null); break;
      case 'set_execution_settings': await runtime.setExecutionSettings(command.settings); break;
      case 'set_limits': await runtime.setLimits(command.limits); break;
      case 'stop': runtime.stop(); break;
      case 'observe': await runtime.observe(); break;
      case 'end': await runtime.end(); break;
      case 'models': runtime.emitModels(); break;
      case 'refresh_models': await runtime.refreshModels(command.provider || 'openrouter'); break;
      case 'configure_provider': await runtime.configureProvider(command); break;
      case 'decisions': await runtime.configureDecisions(command); break;
      case 'move': await runtime.moveAction(command); break;
      case 'shapes_model': runtime.shapes.answer(['accept', 'enable'].includes(command.action) ? command.action : 'decline'); break;   // shapes_model_needed's answer, or Ask again
      case 'shutdown': await shutdown(); break;
      default: throw new Error('Unknown panel command.');
    }
  } catch (error) { emit({ type: 'error', message: runtime.redact(error.message) }); }
}

async function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  runtime.stop();
  await Promise.allSettled([...pending]);
  runtime.busy = false;
  await runtime.end().catch(() => {});
  await runtime.shapes?.close().catch(() => {});
  runtime.dispose?.();
  await runtime.bridge.close().catch(() => {});
  await runtime.diagnostics.close().catch(() => {});
  await runtime.tracing?.shutdown();
  await runtime.releaseLock().catch(() => {});
  process.exit(0);
}

process.stdin.setEncoding('utf8');
process.stdin.on('data', data => {
  buffer += data;
  if (Buffer.byteLength(buffer) > 2 * 1024 * 1024) { emit({ type: 'error', message: 'Panel message is too large.' }); buffer = ''; return; }
  const split = splitJsonLines(buffer); buffer = split.rest;
  for (const line of split.lines) {
    if (!line.trim()) continue;
    try {
      const command = JSON.parse(line);
      if (command.type === 'shutdown') { void shutdown(); continue; }
      const task = handle(command);
      pending.add(task);
      void task.finally(() => pending.delete(task));
    }
    catch { emit({ type: 'error', message: 'Invalid panel message.' }); }
  }
});
process.stdin.on('end', () => void shutdown());
process.on('SIGTERM', () => void shutdown());
process.on('SIGINT', () => void shutdown());
