/** Real-provider calibration on a NEW working copy, never on the source painting.
 * Run with the Node and companion root from the same loaded Krita release.
 * Successful execution is not a claim of artistic success: inspect the images.
 */
import { parseArgs } from 'node:util';
import { readFile, writeFile, mkdir, realpath, copyFile } from 'node:fs/promises';
import { resolve, join, relative, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { homedir } from 'node:os';

const {values} = parseArgs({options:{
  companion:{type:'string'}, output:{type:'string'}, source:{type:'string'},
  provider:{type:'string',default:'openrouter'}, model:{type:'string',default:'deepseek/deepseek-v4.1-flash'},
}});
if (!values.companion || !values.output || !values.source)
  throw new Error('Provide --companion (loaded release companion folder), --output (new evaluation folder), and --source (existing painting.kra).');
const companion = await realpath(values.companion), destination = resolve(values.output), source = await realpath(values.source);
const {StudioRuntime} = await import(pathToFileURL(join(companion,'src/studio.mjs')));
const {PaintingBridge} = await import(pathToFileURL(join(companion,'src/bridge.mjs')));
const build = JSON.parse(await readFile(join(companion,'build-info.json'),'utf8'));
const hash = async path => createHash('sha256').update(await readFile(path)).digest('hex');
const originalHash = await hash(source);
await mkdir(destination); // refuse an existing run; retained failures are evidence
const actualDestination = await realpath(destination);
const events = [], mutations = [], stateChanges = [];
const presets = ['g) Dry Textured Creases','g) Dry Bristles'];
const palette = ['#c0422a','#d2563a','#a52c1c'];
const completedPresets = new Set();
const config = {output:join(actualDestination,'.creative-agent'),paintings_dir:actualDestination,project_root:actualDestination,
  bridge_url:'http://127.0.0.1:5678',model_idle_timeout_ms:90000};
const bridge = new PaintingBridge(companion,config);
const native = bridge.call.bind(bridge);
let sourceDocument, copyDocument;
bridge.call = async (operation,params = {},...rest) => {
  const mutation = ['begin','paint_pass','adjust_layer','review_pass'].includes(operation);
  const attempt = mutation ? {operation,params,at:new Date().toISOString(),dispatched:false,completed:false}:null;
  if (attempt) mutations.push(attempt);
  if (operation === 'begin') {
    if (params.mode !== 'copy' || !sourceDocument || params.source_document_id !== sourceDocument.document_id)
      throw new Error('Evaluation only permits a new working copy of the verified source document.');
    const output = resolve(params.painting_path ?? '');
    const part = relative(actualDestination,output);
    if (!part || part==='..' || part.startsWith('../') || isAbsolute(part) || output===source)
      throw new Error('The evaluation painting must stay inside its new output folder.');
  }
  if (['adjust_layer','review_pass'].includes(operation)) throw new Error('Calibration permits only two new brush-test layers; layer changes are outside this run.');
  if (operation === 'paint_pass') {
    if (!copyDocument || copyDocument === sourceDocument?.document_id) throw new Error('A separate working copy has not been verified.');
    if (!presets.includes(params.preset) || completedPresets.has(params.preset)) throw new Error('Test each specified dry brush exactly once.');
    if (params.strokes?.length !== 2 || JSON.stringify(params.region)!==JSON.stringify([100,150,580,330]))
      throw new Error('Each brush trial must have two strokes clipped to the upper-field core.');
    for (const stroke of params.strokes) {
      if (stroke.size<60 || stroke.size>80 || stroke.opacity<0.15 || stroke.opacity>0.30 || !palette.includes(stroke.color?.toLowerCase()))
        throw new Error('Use the specified palette, 60–80 px brush size and 0.15–0.30 stroke opacity.');
    }
  }
  if (attempt) attempt.dispatched = true;
  try {
    const result = await native(operation,params,...rest);
    if (attempt) { attempt.completed = true; attempt.replayed = !!result.replayed; attempt.document_id=result.document_id; attempt.filename=result.filename; }
    if (operation === 'begin') {
      copyDocument = result.document_id;
      if (!copyDocument || copyDocument===sourceDocument.document_id) throw new Error('Native copy did not return a separate document identity.');
    }
    if (operation === 'paint_pass') completedPresets.add(params.preset);
    return result;
  } catch(error) { if(attempt) attempt.error = String(error.message); throw error; }
};
const runtime = new StudioRuntime({root:companion,config,bridge,emit:event=>{
  if (event.type === 'ready') return;
  events.push(event);
  if (event.type === 'status' && stateChanges.at(-1) !== event.message) {
    stateChanges.push(event.message); process.stdout.write(event.message+'\n');
  }
  if (event.type === 'error') process.stdout.write('Paused: '+event.message+'\n');
}});
const report = {build,source,original_hash:originalHash,provider:values.provider,model:values.model,
  started_at:new Date().toISOString(),live_provider:true,artistic_success:false,requires_visual_assessment:true};
try {
  // Carry the user's actual Pi routes into the isolated evaluation catalogue.
  // Diagnostic runs must never rewrite the shared Pi model store.
  await mkdir(config.output,{recursive:true});
  try { await copyFile(join(homedir(),'.pi/agent/models-store.json'),join(config.output,'model-catalog.json')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await runtime.initialize();
  if (runtime.bridgeCompatible === false) throw new Error('Load the same build in Krita before evaluating.');
  sourceDocument = await native('context');
  if (!sourceDocument.filename || await realpath(sourceDocument.filename)!==source || sourceDocument.width!==768 || sourceDocument.height!==1024)
    throw new Error('Open the expected 768 × 1024 source painting before evaluation.');
  if ((await native('health')).session_active) throw new Error('Pause and end the other painting run before this test.');
  report.source_document = sourceDocument;
  await runtime.start({provider:values.provider,model:values.model,chat_mode:'ask',mode:'copy',
    name:'Stage One — calibration',prompt:'Do you see this painting? Describe the upper and lower fields in two sentences. Do not paint or save.'});
  report.ask_mutations = mutations.filter(m=>m.dispatched).length;
  if (mutations.length) throw new Error('Ask mode attempted a native mutation.');
  if (runtime.runError) throw new Error('The Ask response failed: '+runtime.runError);
  report.before_snapshot = runtime.canvasContext.canvas;
  if (report.before_snapshot?.document_id!==sourceDocument.document_id) throw new Error('Ask did not include the verified source canvas.');
  report.before_full_snapshot = await native('peek',{output_dir:runtime.study.directory,document_id:sourceDocument.document_id,region:[0,0,768,1024]},runtime.study.id);
  report.destination_color_samples=await native('sample_colors',{document_id:sourceDocument.document_id,points:[[220,220],[400,270],[550,350],[400,440]]},runtime.study.id);
  await runtime.editPlan({title:'Stage One: Material — calibration only',
    objective:'Choose a brush that produces dry, granular broken marks on the upper field while preserving the painting.',
    requirements:['Preserve composition, overall colour and outer edges.','Leave the lower field completely unchanged.',
      'Use only #c0422a, #d2563a and #a52c1c at low opacity.','Work only inside x 100–680, y 150–480.',
      'Make two short strokes with g) Dry Textured Creases and two with g) Dry Bristles, on separate new named layers, size 60–80 px and opacity 0.15–0.30.',
      'Stop after the two calibration passes. Do not begin a material pass or work on the lower field.'],
    freedom:['Use whisper-light tooth. Place the four marks irregularly without a grid. No preference question is needed for this calibration.'],
    steps:[{title:'Calibrate two dry brushes',scope:'Upper-field core only; two short strokes per brush on separate layers.',
      region:[100,150,580,330],stop_after:true,max_operations:2,
      done_when:'Two brush trials can be judged at full resolution for granular breakup versus stripes, with no change outside the upper-field core.'}],
    completion:['Calibration trials are visible and reversible.','The run stops for review without continuing the painting.']});
  // Painting and review share the time allowance; reaching two passes prevents
  // further brushwork while still allowing the independent final inspection.
  await runtime.setLimits({minutes:8,passes:2});
  await runtime.prompt('Run only the agreed four calibration strokes, then stop. Inspect each trial and explain which brush gives broken granular marks.',{chat_mode:'agent',start_plan:true});
  if (runtime.runError) throw new Error(runtime.runError);
  report.final_snapshot = runtime.lastObservation;
  if (runtime.study.bound) report.final_full_snapshot = await native('observe',{region:[0,0,768,1024]},runtime.study.id);
  const passes = mutations.filter(m=>m.operation==='paint_pass' && m.completed && !m.replayed);
  report.calibration_completed = passes.length===2 && completedPresets.size===2;
  report.operation_boundary_respected = mutations.filter(m=>m.operation==='paint_pass' && m.dispatched).length<=2 && !runtime.busy;
  report.stage_review_completed = runtime.goal.reviews.length>0;
  report.stage_boundary_respected = report.calibration_completed && report.operation_boundary_respected &&
    report.stage_review_completed && ['paused','limited'].includes(runtime.goal.status);
  report.stage_accepted_by_review = runtime.goal.stage_pending_advance===true;
  if (!report.calibration_completed) throw new Error('The run stopped without completing both validated brush trials. Retain the result for inspection.');
} catch(error) {
  report.error = runtime.redact(error.message); process.exitCode = 1;
} finally {
  const cleanupErrors = [];
  const retainFailure = (phase,error) => {cleanupErrors.push({phase,error:runtime.redact(error.message)});process.exitCode=1;};
  if (runtime.study) { report.study_id=runtime.study.id;report.painting_file=runtime.study.painting_file; }
  if (runtime.goal) report.goal=structuredClone(runtime.goal);
  report.mutations=mutations;
  // Capture the source itself, not the active working copy. This also detects
  // unintended unsaved source edits that a disk checksum alone would miss.
  if (report.before_full_snapshot && runtime.study) {
    try {
      report.source_after_snapshot=await native('peek',{output_dir:runtime.study.directory,document_id:sourceDocument.document_id,region:[0,0,768,1024]},runtime.study.id);
      if (!report.source_after_snapshot.filename || await realpath(report.source_after_snapshot.filename)!==source)
        throw new Error('The source inspection resolved a different painting. Source preservation is unverified.');
      report.original_live_unchanged=report.source_after_snapshot.revision===report.before_full_snapshot.revision;
      if (!report.original_live_unchanged) process.exitCode=1;
    } catch(error) {retainFailure('inspect source after run',error);}
  }
  try {runtime.stop();} catch(error) {retainFailure('pause runtime',error);}
  if (!runtime.busy) {try {await runtime.end();} catch(error) {retainFailure('close conversation',error);}}
  else retainFailure('close conversation',new Error('A native action is still unsettled; ownership was preserved for inspection.'));
  try {await bridge.close();} catch(error) {retainFailure('close bridge',error);}
  try {await runtime.releaseLock();} catch(error) {retainFailure('release runtime lock',error);}
  try {report.original_unchanged=await hash(source)===originalHash;} catch(error) {retainFailure('verify source file',error);}
  if (report.original_unchanged===false) process.exitCode=1;
  report.cleanup_errors=cleanupErrors;report.finished_at=new Date().toISOString();
  await writeFile(join(actualDestination,'evaluation.json'),JSON.stringify(report,null,2));
  await writeFile(join(actualDestination,'events.json'),JSON.stringify(events,null,2));
  process.stdout.write(JSON.stringify({report:join(actualDestination,'evaluation.json'),error:report.error,
    original_unchanged:report.original_unchanged,original_live_unchanged:report.original_live_unchanged,
    calibration_completed:report.calibration_completed,stage_boundary_respected:report.stage_boundary_respected,requires_visual_assessment:true})+'\n');
}
