/** Read-only real-provider route check with generated pixels and no artwork. */
import { parseArgs } from 'node:util';
import { readFile, mkdir, writeFile, copyFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { ModelCapabilities } from '../src/model-capabilities.mjs';

const { values } = parseArgs({ options: { provider:{type:'string'}, model:{type:'string'}, output:{type:'string'} } });
if (!values.provider || !values.model || !values.output) throw new Error('Provide --provider, --model and --output.');
const directory = resolve(values.output);
await mkdir(directory); // keep each check's evidence, never replace an earlier run
const report = { provider:values.provider, model:values.model, started_at:new Date().toISOString(),
  real_provider:true, artwork_sent:false, artwork_tools_available:false,
  probe_source_sha256:createHash('sha256').update(await readFile(new URL('../src/model-capabilities.mjs',import.meta.url))).digest('hex') };
try {
  // Match the user's Pi catalogue without letting a diagnostic rewrite it.
  try { await copyFile(join(homedir(),'.pi/agent/models-store.json'),join(directory,'model-catalog.json')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const models = await ModelRuntime.create({ allowModelNetwork:false, authPath:join(homedir(),'.pi/agent/auth.json'),
    modelsStorePath:join(directory,'model-catalog.json'), signal:AbortSignal.timeout(15000) });
  const model = models.getModel(values.provider, values.model);
  if (!model) throw Object.assign(new Error('This model route is not registered in Pi.'),{code:'model_not_registered'});
  if (!models.hasConfiguredAuth(values.provider)) throw Object.assign(new Error('This provider has no configured Pi authentication.'),{code:'provider_not_connected'});
  const verifier = await new ModelCapabilities({models,cacheDirectory:directory,timeoutMs:45000,
    onStatus:event=>process.stdout.write(event.message+'\n')}).initialize();
  report.result = await verifier.verify(model,{force:true});
} catch(error) {
  report.error_code = error.code ?? 'setup_failed';
  if (error.diagnostic) report.diagnostic = error.diagnostic;
  // CapabilityError messages are classified safe strings. Avoid printing any
  // unexpected provider/setup error, which may contain endpoint credentials.
  report.error = error.name === 'CapabilityError' ? error.message : 'The route check could not be prepared; inspect the local model configuration.';
  process.exitCode = 1;
}
report.finished_at = new Date().toISOString();
await writeFile(join(directory,'verification.json'),JSON.stringify(report,null,2)+'\n',{mode:0o600});
process.stdout.write(JSON.stringify(report)+'\n');
