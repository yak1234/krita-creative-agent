// Langfuse credentials for the Creative Agent. The companion reads the project's
// .env first, then the environment, then the macOS Keychain. Values are never printed.
//   node scripts/langfuse-credentials.mjs --check            which project/org the keys open, and from where
//   node scripts/langfuse-credentials.mjs --store-keychain   copy the .env keys into the Keychain (fallback)
//   node scripts/langfuse-credentials.mjs --remove           remove the Keychain copy
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { join } from 'node:path';
import { projectDir } from './project-dir.mjs';
import { KEYCHAIN_SERVICE, connectLangfuse, langfuseCredentials } from '../src/langfuse-tracing.mjs';

const run = promisify(execFile);
const KEYS = ['LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL'];
const dotEnvPath = join(projectDir(), '.env');
const mode = process.argv[2] ?? '--check';

if (mode === '--check') {
  try {
    const tracing = await connectLangfuse({ dotEnvPath });
    console.log('Connected: ' + tracing.describe() + ' (' + tracing.baseUrl + ').');
    await tracing.shutdown();
  } catch (error) { console.error(error.message); process.exit(1); }
} else if (mode === '--remove') {
  for (const key of KEYS) await run('security', ['delete-generic-password', '-s', KEYCHAIN_SERVICE, '-a', key]).catch(() => {});
  console.log('Removed the Langfuse Keychain copy.');
} else if (mode === '--store-keychain') {
  if (process.platform !== 'darwin') { console.error('The Keychain fallback is macOS only.'); process.exit(2); }
  const credentials = await langfuseCredentials({}, async () => null, dotEnvPath);
  if (!credentials) { console.error('No Langfuse keys in ' + dotEnvPath + '. Nothing was stored.'); process.exit(2); }
  for (const key of KEYS) if (credentials[key]) await run('security', ['add-generic-password', '-U', '-s', KEYCHAIN_SERVICE, '-a', key, '-w', credentials[key]]);
  console.log('Stored the .env Langfuse keys in the Keychain (service ' + KEYCHAIN_SERVICE + ').');
} else { console.error('Usage: --check | --store-keychain | --remove'); process.exit(2); }
