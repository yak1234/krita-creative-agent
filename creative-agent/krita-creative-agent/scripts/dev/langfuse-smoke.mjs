// Sends one real, small traced Agent Pi run to Langfuse, without Krita: a model
// call that uses a fake `observe_canvas` tool returning a 64x64 image.
//   node scripts/dev/langfuse-smoke.mjs [provider/model]
// Prints the trace id only. Needs Langfuse credentials (env or Keychain) and
// OpenRouter connected in Agent Pi.
import { join } from 'node:path';
import { projectDir } from '../project-dir.mjs';
import { tmpdir } from 'node:os';
import { deflateSync } from 'node:zlib';
import { createAgentSession, DefaultResourceLoader, getAgentDir, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import { Type } from 'typebox';
import { connectLangfuse } from '../../src/langfuse-tracing.mjs';
import { BUILD_INFO } from '../../src/build-info.mjs';

const [provider, ...rest] = (process.argv[2] ?? 'openrouter/google/gemini-3.8-flash').split('/');
let tracing;
try { tracing = await connectLangfuse({ release: BUILD_INFO.build_id, dotEnvPath: join(projectDir(), '.env'), env: { ...process.env, LANGFUSE_TRACING_ENVIRONMENT: 'smoke-test' } }); }
catch (error) { console.error(error.message + ' Nothing was sent.'); process.exit(2); }
const chatId = 'smoke-' + new Date().toISOString().replace(/[:.]/g, '-');

// A solid 64x64 PNG: dusk blue sky over a dark canal band.
function png() {
  const crc = buf => { let c = ~0; for (const b of buf) { c ^= b; for (let k = 0; k < 8; k++) c = c >>> 1 ^ (0xEDB88320 & -(c & 1)); } return ~c >>> 0; };
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(body)); return Buffer.concat([len, body, c]); };
  const rows = []; for (let y = 0; y < 64; y++) { rows.push(0); for (let x = 0; x < 64; x++) rows.push(...(y < 40 ? [40, 60, 140] : [15, 20, 35])); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(64, 0); ihdr.writeUInt32BE(64, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(Buffer.from(rows))), chunk('IEND', Buffer.alloc(0))]).toString('base64');
}
const observe = { name: 'observe_canvas', label: 'Observe canvas', description: 'Return the current canvas image.', parameters: Type.Object({}),
  execute: async () => ({ content: [{ type: 'text', text: 'Canvas 64x64, revision 1.' }, { type: 'image', data: png(), mimeType: 'image/png' }], details: {} }) };

const models = await ModelRuntime.create({ authPath: join(getAgentDir(), 'auth.json'), modelsPath: null, refreshOnCreate: false });
await models.refresh({ allowNetwork: false, signal: AbortSignal.timeout(15000) }).catch(() => {});
const model = models.getModel(provider, rest.join('/'));
if (!model) { console.error('Model not available: ' + provider + '/' + rest.join('/')); process.exit(2); }
const directory = tmpdir();
const settings = SettingsManager.inMemory({ packages: [], extensions: [], skills: [], retry: { enabled: false }, enableAnalytics: false });
const loader = new DefaultResourceLoader({ cwd: directory, agentDir: join(directory, 'langfuse-smoke-agent'), settingsManager: settings, noExtensions: true, noSkills: true,
  noContextFiles: true, noPromptTemplates: true, noThemes: true, systemPromptOverride: () => 'You are a painting assistant. Observe the canvas before describing it. Be brief.' });
await loader.reload();
const { session } = await createAgentSession({ cwd: directory, modelRuntime: models, model, resourceLoader: loader, settingsManager: settings,
  customTools: [observe], tools: ['observe_canvas'], sessionManager: SessionManager.inMemory(directory) });
const untrace = tracing.watchSession(session, { traceName: 'painter', generationName: 'choose-next-action',
  describe: () => ({ traceName: 'answer-artist', sessionId: chatId, tags: ['painter', 'smoke-test'], ids: { study_id: 'smoke' }, metadata: { objective: 'Smoke test' } }) });
let traceId;
const original = tracing.start.bind(tracing);
tracing.start = (...args) => { const o = original(...args); traceId ??= o.traceId; return o; };
await session.prompt('What colours are on my canvas? Use the tool, then answer in one sentence.');
untrace(); session.dispose();
tracing.score({ traceId, sessionId: chatId, name: 'review-passed', value: 1, dataType: 'BOOLEAN', comment: 'Smoke test score' });
await tracing.endSession(chatId, { metadata: { goal_status: 'smoke' } });
await tracing.shutdown();
console.log('trace_id ' + traceId + ' session ' + chatId + ' url ' + tracing.sessionUrl(chatId).replace(/project\/[^/]+/, 'project/…'));
