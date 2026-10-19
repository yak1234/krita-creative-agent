import test, { after } from 'node:test';
import { mkdtemp as makeTemp, rm } from 'node:fs/promises';
import { tmpdir as osTmp } from 'node:os';
import { join as joinPath } from 'node:path';
import assert from 'node:assert/strict';
import { PROTOCOLS } from '../src/decisions/protocols.ts';
import { BUILT_IN_ENDPOINTS, builtInEndpoint, customEndpoint, resolveEndpoint } from '../src/decisions/endpoints.ts';
import { DecisionClient, checkImages } from '../src/decisions/client.ts';

// Every temporary folder a test makes is removed when the file finishes.
const temps = [];
const tempDir = async prefix => { const dir = await makeTemp(joinPath(osTmp(), prefix)); temps.push(dir); return dir; };
after(() => Promise.all(temps.map(dir => rm(dir, { recursive: true, force: true }))));

const questions = {
  seam: { type: 'noul', instructions: 'Is there a seam?', criteria: { true: 'A hard join.', false: 'No join.' } },
  next: { type: 'choice', instructions: 'What next?', criteria: { continue_focus: 'Keep going.', request_review: 'Review now.' } },
  progress: { type: 'score', instructions: 'How far along?', criteria: ['Not started.', 'Begun.', 'Mostly.', 'Done.'] },
};
const image = { data: 'AAAA', mimeType: 'image/png' };

test('System One requests keep keyed questions and chat-style image parts', () => {
  const body = PROTOCOLS.systemone.body({ model: 'm', parts: ['CANVAS:', image], questions });
  assert.deepEqual(body.state, [{ type: 'text', text: 'CANVAS:' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,AAAA' } }]);
  assert.equal(body.questions, questions);
});

test('OpenAI requests translate questions, and answers come back in System One form', () => {
  const body = PROTOCOLS.openai.body({ model: 'gpt-6-luna', parts: ['CANVAS:', image], questions });
  assert.deepEqual(body.input[0].content, [{ type: 'input_text', text: 'CANVAS:' }, { type: 'input_image', image_url: 'data:image/png;base64,AAAA' }]);
  assert.deepEqual(body.questions.map(q => [q.name, q.type]), [['seam', 'predicate'], ['next', 'choice'], ['progress', 'score']]);
  assert.match(body.questions[0].instructions, /True: A hard join/);
  assert.deepEqual(body.questions[1].choices, [{ value: 'continue_focus', description: 'Keep going.' }, { value: 'request_review', description: 'Review now.' }]);
  assert.deepEqual(body.questions[2].levels.map(l => l.label), questions.progress.criteria);
  const answers = PROTOCOLS.openai.answers({ answers: [
    { name: 'seam', type: 'predicate', probability: 0.12 },
    { name: 'next', type: 'choice', choice: 'request_review', confidence: 0.8, probabilities: [{ value: 'continue_focus', probability: 0.2 }, { value: 'request_review', probability: 0.8 }] },
    { name: 'progress', type: 'score', score: 2.4, confidence: 0.6, probabilities: [{ probability: 0 }, { probability: 0.1 }, { probability: 0.4 }, { probability: 0.5 }] },
  ] });
  assert.deepEqual(answers.seam, { type: 'noul', noul: 0.12 });
  assert.deepEqual(answers.next, { type: 'choice', choice: 'request_review', confidence: 0.8, probabilities: { continue_focus: 0.2, request_review: 0.8 } });
  assert.equal(answers.progress.score, 2.4); assert.equal(answers.progress.probabilities['3'], 0.5);
});

test('OpenRouter lists its current decision models with image support, image models first', async () => {
  let url;
  const fetch = async u => { url = u; return new Response(JSON.stringify({ data: [
    { id: 'typesafe/jev-1.13', architecture: { input_modalities: ['text'], output_modalities: ['decisions'] }, pricing: { prompt: '0.000000042' } },
    { id: 'cloudflare/clef-flash', architecture: { input_modalities: ['text', 'image'], output_modalities: ['decisions'] }, pricing: { prompt: '0.000000038' } },
    { id: 'openai/gpt-6-luna', architecture: { input_modalities: ['text', 'image'], output_modalities: ['text'] }, pricing: { prompt: '0.000001' } },
  ] })); };
  const models = await BUILT_IN_ENDPOINTS.openrouter.listModels({ fetch });
  assert.match(url, /output_modalities=decisions/);
  assert.deepEqual(models.map(m => [m.id, m.images]), [['cloudflare/clef-flash', true], ['typesafe/jev-1.13', false]]);
});

test('custom endpoints must be HTTPS or local, and list models when they can', async () => {
  assert.throws(() => customEndpoint({ id: 'x', url: 'http://example.com/v1/systemone' }), /HTTPS/);
  assert.throws(() => customEndpoint({ id: 'x', url: 'https://user:pw@example.com/v1/systemone' }), /key field/);
  const local = customEndpoint({ id: 'unsloth', url: 'http://localhost:8888/v1/systemone' });
  const models = await local.listModels({ fetch: async u => (assert.equal(u, 'http://localhost:8888/v1/models'), new Response(JSON.stringify({ data: [{ id: 'laya' }, { id: 'my-krita-clef' }] }))) });
  assert.deepEqual(models, [{ id: 'laya', name: 'laya', images: null }, { id: 'my-krita-clef', name: 'my-krita-clef', images: null }]);
  assert.equal(resolveEndpoint('unsloth', { unsloth: { url: 'http://localhost:8888/v1/systemone' } }).protocol, 'systemone');
  assert.throws(() => resolveEndpoint('nope'), /Unknown/);
});

test('a text-only model never receives a visual decision, and the image check measures it', async () => {
  const calls = [];
  const fetch = async (url, init) => { const body = JSON.parse(init.body); calls.push(body);
    const orange = JSON.stringify(body.state).includes(body.__orange ?? 'XXXX');
    return new Response(JSON.stringify({ answers: { orange: { type: 'noul', noul: orange ? 0.9 : 0.1 } } })); };
  const textOnly = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.typesafe, apiKey: 'k', fetch, images: false });
  assert.equal((await textOnly.decide({ parts: ['CANVAS:', image], questions })).fallback, 'text_only_model');
  assert.equal(calls.length, 0);
  assert.ok((await textOnly.decide({ parts: ['move the boat'], questions: { next: questions.next } })).fallback !== 'text_only_model', 'text routing still works');
  // A model that ignores images answers the same for both control images: not image-capable.
  const blind = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, apiKey: 'k', fetch: async () => new Response(JSON.stringify({ answers: { orange: { type: 'noul', noul: 0.5 } } })) });
  assert.deepEqual((await checkImages(blind)).images, false);
  let n = 0;
  const seeing = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, apiKey: 'k', fetch: async () => new Response(JSON.stringify({ answers: { orange: { type: 'noul', noul: n++ === 0 ? 0.95 : 0.05 } } })) });
  assert.equal((await checkImages(seeing)).images, true);
});

test('an unchecked model gets no visual decisions until it passes the image check', async () => {
  let posted = 0;
  const client = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, model: 'cloudflare/clef-flash', apiKey: 'k',
    fetch: async () => (posted++, new Response(JSON.stringify({ answers: { orange: { type: 'noul', noul: 0.01 } } }))) });
  assert.equal(client.images, null);
  assert.equal((await client.decide({ parts: ['CANVAS:', image], questions })).fallback, 'images_unverified');
  assert.equal(posted, 0);
  assert.equal((await checkImages(client)).images, false, 'answers that ignore the colour fail the check');
  assert.equal(posted, 2, 'only the check sent images');
});

test('the service resolves keys (saved, then .env, then environment), stores them privately and remembers image checks', async () => {
  const { DecisionService } = await import('../src/decisions/service.ts');
  const { mkdtemp, writeFile: write, stat, readFile: read } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os'); const { join } = await import('node:path');
  const dir = await tempDir('decisions-');
  await write(join(dir, '.env'), 'OPENAI_API_KEY="sk-from-dotenv"\n');
  const secrets = [];
  const service = await new DecisionService({ stateDirectory: dir, envPath: join(dir, '.env'), secrets, env: { TYPESAFE_API_KEY: 'ts-env' },
    painterKey: async () => 'sk-or-painter', fetch: async () => new Response(JSON.stringify({ data: [] })) }).load();
  assert.equal(await service.key('openrouter'), 'sk-or-painter');
  assert.equal(await service.key('openai'), 'sk-from-dotenv');
  assert.equal(await service.key('typesafe'), 'ts-env');
  await service.saveKey('openai', 'sk-saved');
  assert.equal(await service.key('openai'), 'sk-saved', 'a saved key wins');
  // Windows has no POSIX permissions; the file is private through the user's profile folder instead.
  if (process.platform !== 'win32') assert.equal((await stat(join(dir, 'decision-endpoints.json'))).mode & 0o777, 0o600);
  assert.ok(['sk-or-painter', 'sk-from-dotenv', 'ts-env', 'sk-saved'].every(k => secrets.includes(k)), 'every key is redacted');
  const endpoints = await service.endpoints();
  assert.ok(!JSON.stringify(endpoints).includes('sk-'), 'endpoint listings never carry keys');
  await service.addEndpoint({ id: 'unsloth', url: 'http://localhost:8888/v1/systemone', default_model: 'my-clef' });
  assert.ok((await service.endpoints()).some(e => e.id === 'unsloth' && e.custom));
  await assert.rejects(service.addEndpoint({ id: 'openai', url: 'https://x.test/v1/systemone' }), /built-in/);
  service.store.images['unsloth:my-clef'] = true;
  assert.equal((await service.client({ endpoint: 'unsloth', model: 'my-clef' })).images, true, 'a passed check is remembered');
  assert.equal((await service.client({ endpoint: 'openrouter', model: 'openai/gpt-6-luna-decisions' })).images, true, 'Luna is verified');
  await service.removeEndpoint('unsloth');
  assert.ok(!JSON.parse(await read(join(dir, 'decision-endpoints.json'), 'utf8')).keys.unsloth);
});

test('the service redacts each key once, including keys added with an endpoint', async () => {
  const { DecisionService } = await import('../src/decisions/service.ts');
  const { mkdtemp } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os'); const { join } = await import('node:path');
  const secrets = [];
  const service = await new DecisionService({ stateDirectory: await tempDir('decisions-'), secrets, env: { TYPESAFE_API_KEY: 'ts-env' },
    painterKey: async () => 'sk-or-painter', fetch: async () => new Response(JSON.stringify({ data: [] })) }).load();
  for (let i = 0; i < 3; i++) await service.endpoints();
  assert.deepEqual(secrets.filter(k => k === 'ts-env').length, 1, 'refreshing the panel does not grow the redaction list');
  await service.addEndpoint({ id: 'local', url: 'http://localhost:8888/v1/systemone', key: ' sk-local-key ' });
  assert.ok(secrets.includes('sk-local-key'), 'a key added with an endpoint is redacted at once');
});

test('an unreadable endpoint store is kept aside, not overwritten', async () => {
  const { DecisionService } = await import('../src/decisions/service.ts');
  const { mkdtemp, writeFile: write, readFile: read, readdir } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os'); const { join } = await import('node:path');
  const dir = await tempDir('decisions-');
  const broken = '{"custom":{"mine":{"url":"http://localhost:8888/v1/systemone"}},"keys":{"mine":"sk-precious"';
  await write(join(dir, 'decision-endpoints.json'), broken);
  const service = await new DecisionService({ stateDirectory: dir, secrets: [] }).load();
  assert.ok(service.recoveredFrom, 'the service says where the old store went');
  assert.equal(await read(service.recoveredFrom, 'utf8'), broken, 'the old store is kept byte for byte');
  await service.saveKey('openai', 'sk-new');
  assert.deepEqual(JSON.parse(await read(join(dir, 'decision-endpoints.json'), 'utf8')).keys, { openai: 'sk-new' });
  assert.ok(!(await readdir(dir)).some(f => f.endsWith('.tmp')), 'saves leave no temporary files');
});

test('tracing describes the parts the request sends: an empty part is dropped, an image without a type is a PNG', async () => {
  let traced;
  const tracing = { observeGeneration: async (_name, options, run) => { traced = options.input; return run(); } };
  const client = new DecisionClient({ endpoint: BUILT_IN_ENDPOINTS.openrouter, apiKey: 'k', images: true, tracing,
    fetch: async () => new Response(JSON.stringify({ answers: {} })) });
  await client.decide({ parts: ['CANVAS:', null, undefined, { data: 'QUJD' }], questions: {} });
  assert.deepEqual(traced.state, ['CANVAS:', { type: 'image_url', image_url: { url: 'data:image/png;base64,QUJD' } }]);
});

test('endpoint ids are looked up as own keys only: constructor is not a built-in endpoint', () => {
  assert.equal(builtInEndpoint('constructor'), undefined);
  assert.equal(builtInEndpoint('toString'), undefined);
  assert.throws(() => resolveEndpoint('constructor'), /Unknown decision endpoint: constructor/);
  assert.throws(() => resolveEndpoint('toString', {}), /Unknown decision endpoint: toString/);
  assert.equal(resolveEndpoint('constructor', { constructor: { url: 'https://decide.example/v1/systemone' } }).custom, true);
});
