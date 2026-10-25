import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, readFile, stat } from 'node:fs/promises';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';
import { deflateSync, crc32 } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { listSkills, expandSkillCommand, skillReadTool, SKILLS_DIR } from '../src/skills.mjs';
import { runPython } from '../src/python-sandbox.mjs';
import { assetTools, ASSET_MODELS, fitSize, transferSteps, ASSET_QUESTIONS, CODEX_MODEL, codexSize, requestAssetImage } from '../src/assets.mjs';
import { imageInfo } from '../src/files.mjs';

// An RGB PNG: a dark green triangle on a plain cream background, like a model's isolated subject.
function subjectPng(w = 240, h = 320) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const inside = y > 30 && y < 290 && Math.abs(x - w / 2) < (y - 30) * 0.4;
    raw.set(inside ? [30, 110, 50] : [238, 232, 220], y * (w * 3 + 1) + 1 + x * 3);
  }
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

async function studyRuntime() {
  const directory = await mkdtemp(join(tmpdir(), 'assets-test-'));
  const events = [];
  // The asset pipeline is tested with no AI image limit; the allowance has its own test.
  const runtime = { study: { directory, references: [] }, executionSettings: { assets: 'openrouter' }, goal: { limits: { ai_images: null }, ai_images_used: 0 }, emit: e => events.push(e), persist: async () => {}, publish: () => {},
    imageKey: async () => 'test-key', callNative: async () => { throw new Error('no canvas in this test'); } };
  return { runtime, events, directory, close: () => rm(directory, { recursive: true, force: true }) };
}

test('bundled skills are listed and /skill:name expands to the skill\'s instructions plus the request', () => {
  const skills = listSkills();
  assert.ok(skills.some(s => s.name === 'image-asset' && s.description.length > 40));
  const text = expandSkillCommand('/skill:image-asset a decorated Christmas tree');
  assert.match(text, /^<skill name="image-asset" location=".*SKILL\.md">/);
  assert.match(text, /paint_from_reference/);
  assert.ok(text.endsWith('a decorated Christmas tree'));
  assert.equal(expandSkillCommand('paint a tree'), 'paint a tree', 'ordinary messages are unchanged');
  assert.throws(() => expandSkillCommand('/skill:nope x'), /Unknown skill "nope".*image-asset/);
});

test('the painter\'s read tool opens skill files and nothing else', async () => {
  const read = skillReadTool();
  const own = await read.execute('r', { path: join(SKILLS_DIR, 'image-asset/SKILL.md') });
  assert.match(own.content[0].text, /^---\nname: image-asset/);
  const relativeRead = await read.execute('r', { path: 'image-asset/scripts/cutout.py' });
  assert.match(relativeRead.content[0].text, /flood fill/);
  for (const path of ['../package.json', '/etc/hosts', join(homedir(), '.pi/agent/auth.json'), 'image-asset/../../src/assets.mjs'])
    await assert.rejects(read.execute('r', { path }), /skill files only|No such skill file/, path);
});

test('Python runs in a sandbox: only /work is visible, js has no process or fetch, and the result comes back', { timeout: 180000 }, async () => {
  const work = await mkdtemp(join(tmpdir(), 'py-work-'));
  const outside = await mkdtemp(join(tmpdir(), 'py-outside-'));
  try {
    await writeFile(join(outside, 'secret.txt'), 'key');
    const { result } = await runPython({ work, args: { outside: join(outside, 'secret.txt'), n: 21 }, code: [
      'import os, js',
      'from PIL import Image',
      'Image.new("RGB", (4, 4), "red").save("/work/made.png")',
      'RESULT = {"double": ARGS["n"] * 2, "outside_visible": os.path.exists(ARGS["outside"]), "home_visible": os.path.exists(' + JSON.stringify(homedir()) + '),',
      '          "js_process": hasattr(js, "process"), "js_fetch": hasattr(js, "fetch"), "files": os.listdir("/work")}',
    ].join('\n') });
    assert.deepEqual(result, { double: 42, outside_visible: false, home_visible: false, js_process: false, js_fetch: false, files: ['made.png'] });
    assert.ok((await stat(join(work, 'made.png'))).size > 0, 'Python wrote into the work folder on disk');
    await assert.rejects(runPython({ work, code: 'raise ValueError("bad input")' }), /Python failed:[\s\S]*bad input/);
  } finally { await rm(work, { recursive: true, force: true }); await rm(outside, { recursive: true, force: true }); }
});

test('make_asset generates with Seedream, cuts out the plain background and attaches a paintable asset', { timeout: 180000 }, async () => {
  const h = await studyRuntime();
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body), auth: options.headers.Authorization });
    return { ok: true, json: async () => ({ choices: [{ message: { images: [{ image_url: { url: 'data:image/png;base64,' + subjectPng().toString('base64') } }] } }], usage: { cost: 0.018 } }) };
  };
  try {
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    const result = await makeAsset.execute('m1', { name: 'Christmas tree', prompt: 'a tall fir tree, oil painting', mode: 'generate', aspect_ratio: '3:4', cutout: true });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, 'https://openrouter.ai/api/v1/chat/completions');
    assert.equal(requests[0].body.model, ASSET_MODELS.generate.model);
    assert.deepEqual(requests[0].body.image_config, { aspect_ratio: '3:4' });
    assert.match(requests[0].body.messages[0].content[0].text, /uniform mid-grey \(#808080\) background/);
    assert.equal(requests[0].auth, 'Bearer test-key');
    const [reference] = h.runtime.study.references;
    assert.equal(reference.role, 'asset');
    assert.equal(reference.name, 'Christmas tree');
    assert.ok(reference.path.startsWith(join(h.directory, 'assets')));
    const info = imageInfo(await readFile(reference.path));
    assert.equal(info.mimeType, 'image/png');
    assert.ok(info.width < 240 && info.height < 320, 'cropped to the subject');
    const answer = JSON.parse(result.content[0].text);
    assert.equal(answer.reference_id, reference.id);
    assert.equal(answer.cost_usd, 0.018);
    assert.ok(answer.transparent_share > 0.3, 'the background is transparent');
    assert.match(answer.next, /paint_from_reference/);
    assert.equal(result.content[1].type, 'image');
  } finally { await h.close(); }
});

test('make_asset edits keep the framing (Muse on /images), and inputs are validated', async () => {
  const h = await studyRuntime();
  const requests = [];
  const fetchImpl = async (url, options) => { requests.push({ url, body: JSON.parse(options.body) }); return { ok: false, status: 400, json: async () => ({ error: { message: 'stop here' } }) }; };
  try {
    const source = join(h.directory, 'reference-sky.png');
    await writeFile(source, subjectPng());
    h.runtime.study.references.push({ id: 'reference-sky', path: source, role: 'reference' });
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    await assert.rejects(makeAsset.execute('e', { name: 'Sky', prompt: 'repaint only the sky', mode: 'edit', edit_reference_id: 'reference-sky' }), /refused: stop here/);
    assert.equal(requests[0].url, 'https://openrouter.ai/api/v1/images');
    assert.equal(requests[0].body.model, ASSET_MODELS.edit.model);
    assert.equal(requests[0].body.aspect_ratio, 'auto');
    assert.equal(requests[0].body.input_references.length, 1);
    await assert.rejects(makeAsset.execute('e', { name: 'Sky', prompt: 'repaint only the sky', mode: 'edit' }), /exactly one of edit_region/);
    await assert.rejects(makeAsset.execute('e', { name: 'Sky', prompt: 'a new sky please', mode: 'generate', edit_reference_id: 'reference-sky' }), /for mode edit/);
    await assert.rejects(makeAsset.execute('e', { name: 'Sky', prompt: 'a new sky please', mode: 'generate', style_reference_id: 'missing' }), /Unknown reference_id/);
  } finally { await h.close(); }
});

test('run_skill_script runs a bundled script on an attached image and attaches what it writes', { timeout: 180000 }, async () => {
  const h = await studyRuntime();
  try {
    const source = join(h.directory, 'reference-tree.png');
    await writeFile(source, subjectPng());
    h.runtime.study.references.push({ id: 'reference-tree', path: source, role: 'reference' });
    const [, runScript] = assetTools(h.runtime);
    const result = await runScript.execute('s', { skill: 'image-asset', script: 'cutout.py', inputs: { input: 'reference-tree' }, args: { tolerance: 30 }, name: 'Tree cut-out' });
    const asset = h.runtime.study.references.find(r => r.role === 'asset');
    assert.equal(asset.name, 'Tree cut-out');
    assert.equal(JSON.parse(result.content[0].text).reference_id, asset.id);
    assert.equal(result.content[1].type, 'image');
    for (const [skill, script] of [['image-asset', '../x.py'], ['../skills', 'cutout.py'], ['image-asset', 'asset_ops.pyc'], ['image-asset', 'missing.py']])
      await assert.rejects(runScript.execute('s', { skill, script }), /Name a bundled skill|No script/, skill + '/' + script);
  } finally { await h.close(); }
});

test('assets are sized to their canvas target at its exact aspect, with transfer steps under the sample cap', () => {
  assert.deepEqual(fitSize([320, 141, 384, 512]), [384, 512], 'a small target: the asset is the target size');
  assert.deepEqual(fitSize([0, 0, 6000, 1500]), [2560, 640], 'a large target: exact 4:1 within 2560 px');
  const [w, h] = fitSize([10, 10, 1000, 618]);
  assert.equal(w / h, 1000 / 618);
  assert.deepEqual(transferSteps(384, 512), [6, 2.5, 1.2], 'small sources keep the default steps');
  const [coarse, fine] = transferSteps(1248, 1664);    // the source that failed live with the defaults
  assert.ok(1248 * 1664 / coarse ** 2 + 1248 * 1664 / fine ** 2 <= 200000);
});

test('a cut-out on a textured "paper" background leaves no specks, and fit_to returns ready transfer arguments', { timeout: 180000 }, async () => {
  const h = await studyRuntime();
  try {
    const raw = join(h.directory, 'assets');
    await (await import('node:fs/promises')).mkdir(raw, { recursive: true });
    await runPython({ work: raw, code: [
      'import numpy as np', 'from PIL import Image, ImageDraw',
      'rng = np.random.default_rng(3)',
      'paper = np.clip(np.full((600, 450, 3), 232) + rng.normal(0, 9, (600, 450, 3)), 0, 255).astype("uint8")',
      'im = Image.fromarray(paper); d = ImageDraw.Draw(im)',
      'd.polygon([(225, 40), (60, 540), (390, 540)], fill=(30, 105, 60))',
      'im.save("/work/paper_tree.png"); RESULT = 1'].join('\n') });
    const fetchImpl = async () => ({ ok: true, json: async () => ({ choices: [{ message: { images: [{ image_url: { url: 'data:image/png;base64,' + (await readFile(join(raw, 'paper_tree.png'))).toString('base64') } }] } }] }) });
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    const result = await makeAsset.execute('m', { name: 'Tree', prompt: 'a fir tree in oil paint', mode: 'generate', cutout: true, fit_to: [320, 141, 384, 512] });
    const answer = JSON.parse(result.content[0].text);
    assert.deepEqual(answer.paint_from_reference, { reference_id: answer.reference_id, source: [0, 0, 384, 512], target: [320, 141, 384, 512], steps: [6, 2.5, 1.2] });
    const asset = h.runtime.study.references.at(-1);
    const { result: specks } = await runPython({ work: raw, args: { file: (await import('node:path')).basename(asset.path) }, code: [
      'import numpy as np', 'from PIL import Image',
      'a = np.asarray(Image.open("/work/" + ARGS["file"]).convert("RGBA")).astype(int)',
      'light = (a[..., :3].min(axis=2) > 190) & (a[..., 3] > 8)',
      'RESULT = {"light_opaque": int(light.sum()), "size": [a.shape[1], a.shape[0]]}'].join('\n') });
    assert.deepEqual(specks.size, [384, 512]);
    assert.ok(specks.light_opaque < 200, 'no leftover paper around the tree: ' + specks.light_opaque + ' light opaque pixels');
  } finally { await h.close(); }
});

test('Luna checks each asset: in Guide, leftover background is cut out again before the painter sees it; Off asks nothing', { timeout: 180000 }, async () => {
  const h = await studyRuntime();
  const asked = [];
  const verdicts = [{ leftover_background: 0.92, cut_off: 0.05, extra_content: 0.1 }, { leftover_background: 0.12, cut_off: 0.05, extra_content: 0.1 }];
  h.runtime.lunaMode = () => 'guide';
  h.runtime.luna = async () => ({ decide: async request => { asked.push(request);
    const v = verdicts[asked.length - 1];
    return { answers: Object.fromEntries(Object.entries(v).map(([k, p]) => [k, { type: 'noul', noul: p }])), usage: { cost: 0.0004 } }; } });
  const recorded = [];
  h.runtime.diagnostics = { record: e => recorded.push(e) };
  const fetchImpl = async () => ({ ok: true, json: async () => ({ choices: [{ message: { images: [{ image_url: { url: 'data:image/png;base64,' + subjectPng().toString('base64') } }] } }] }) });
  try {
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    const result = await makeAsset.execute('m', { name: 'Tree', prompt: 'a fir tree in oil paint', mode: 'generate', cutout: true });
    assert.equal(asked.length, 2, 'checked, cut out again, checked again');
    assert.equal(asked[0].purpose, 'check-asset');
    assert.deepEqual(Object.keys(asked[0].questions), ['leftover_background', 'cut_off', 'extra_content']);
    assert.deepEqual(asked[0].questions.leftover_background, ASSET_QUESTIONS.leftover_background);
    assert.equal(asked[0].parts[1].type, 'image');
    const answer = JSON.parse(result.content[0].text);
    assert.equal(answer.asset_check.cutout_retried_at_tolerance, 70);
    assert.deepEqual(answer.asset_check.findings, []);
    assert.equal(h.runtime.study.references.length, 1, 'only the final asset is attached');
    assert.deepEqual(recorded.map(e => [e.type, e.status, e.findings]), [['asset_check', 'ok', ['leftover_background']], ['asset_check', 'ok', []]]);
    h.runtime.lunaMode = () => 'off';
    await makeAsset.execute('m', { name: 'Tree 2', prompt: 'a fir tree in oil paint', mode: 'generate', cutout: true });
    assert.equal(asked.length, 2, 'Off asks Luna nothing');
  } finally { await h.close(); }
});

// An RGBA PNG: a green triangle on a fully transparent background, as Codex returns a cut-out.
function transparentPng(w = 200, h = 300) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const inside = y > 20 && y < 280 && Math.abs(x - w / 2) < (y - 20) * 0.35;
    raw.set(inside ? [30, 110, 50, 255] : [0, 0, 0, 0], y * (w * 4 + 1) + 1 + x * 4);
  }
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr.set([8, 6, 0, 0, 0], 8);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

test('Codex is the default image backend: the sign-in, a transparent cut-out from the model, and no cost', { timeout: 180000 }, async () => {
  const h = await studyRuntime();
  delete h.runtime.executionSettings.assets;
  const claims = Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acct-123' } })).toString('base64url');
  h.runtime.codexKey = async () => 'eyJhbGciOiJub25lIn0.' + claims + '.sig';
  const requests = [];
  const sse = 'event: x\ndata: ' + JSON.stringify({ type: 'response.output_item.done', item: { type: 'image_generation_call', result: transparentPng().toString('base64') } }) + '\n\ndata: ' + JSON.stringify({ type: 'response.completed' }) + '\n';
  const fetchImpl = async (url, options) => { requests.push({ url, body: JSON.parse(options.body), headers: options.headers }); return { ok: true, status: 200, text: async () => sse }; };
  try {
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    const result = await makeAsset.execute('m', { name: 'Tree', prompt: 'a fir tree in oil paint', mode: 'draft', aspect_ratio: '3:4', cutout: true });
    const [request] = requests;
    assert.equal(request.url, 'https://chatgpt.com/backend-api/codex/responses');
    assert.equal(request.body.model, CODEX_MODEL);
    assert.deepEqual(request.body.tools, [{ type: 'image_generation', output_format: 'png', size: '1024x1536', quality: 'low', background: 'transparent' }]);
    assert.match(request.body.input[0].content[0].text, /isolated on a transparent background/);
    assert.equal(request.headers['chatgpt-account-id'], 'acct-123');
    assert.match(request.headers.Authorization, /^Bearer eyJ/);
    const answer = JSON.parse(result.content[0].text);
    assert.equal(answer.cost_usd, 0);
    assert.match(answer.model, /^codex\//);
    assert.ok(answer.transparent_share > 0.3, 'the model\'s transparency is kept');
    assert.equal(codexSize('16:9'), '1536x1024'); assert.equal(codexSize(undefined), 'auto');
    h.runtime.codexKey = async () => null;
    await assert.rejects(makeAsset.execute('m', { name: 'Tree', prompt: 'a fir tree in oil paint', mode: 'generate' }), /sign in with Codex.*or choose OpenRouter/);
  } finally { await h.close(); }
});

test('workflow skills are reusable slash commands: /name and /skill:name both expand; other /words stay as typed', async () => {
  const names = listSkills().map(s => s.name).sort();
  assert.deepEqual(names, ['canvas-reference', 'fix-region', 'guided-trace', 'image-asset', 'paint-scene', 'paint-sky', 'place-subject', 'reference-transfer', 'repaint-area', 'repeat-motif']);
  for (const skill of listSkills()) assert.ok(skill.description.length >= 60 && skill.description.length <= 1024, skill.name + ' has a usable description');
  const sky = expandSkillCommand('/paint-sky a stormy dusk');
  assert.match(sky, /^<skill name="paint-sky"/);
  assert.ok(sky.endsWith('a stormy dusk'));
  assert.equal(expandSkillCommand('/skill:paint-sky a stormy dusk'), sky);
  assert.equal(expandSkillCommand('/shrug this looks off'), '/shrug this looks off', 'a /word that names no skill is an ordinary message');
  // Every workflow points at image-asset for tool details, and only names tools the painter has.
  const { paintingTools } = await import('../src/tools.mjs');
  const tools = new Set(paintingTools({ study: { directory: tmpdir(), references: [] } }).map(t => t.name));
  for (const name of ['paint-sky', 'place-subject', 'fix-region', 'paint-scene']) {
    const text = await readFile(join(SKILLS_DIR, name, 'SKILL.md'), 'utf8');
    for (const tool of text.match(/\b(make_asset|run_skill_script|paint_from_reference|paint_reference_surface|paint_reference_edges|observe_canvas|create_layer|paint_pass|paint_recipe|set_layer|smart_patch|bucket_fill|enclose_and_fill|krita_gradient)\b/g) ?? [])
      assert.ok(tools.has(tool), name + ' names ' + tool);
  }
  for (const name of ['repaint-area', 'repeat-motif', 'reference-transfer']) {
    const text = await readFile(join(SKILLS_DIR, name, 'SKILL.md'), 'utf8');
    for (const tool of text.match(/\b(select|split_by_color|fill_region|apply_filter|clone_layer|transform_layer|krita_action|krita_capabilities|sample_canvas_colors|observe_canvas|set_layer|paint_recipe|create_layer|paint_from_reference|paint_reference_edges|paint_reference_surface|continue_reference_painting|list_reference_paintings|paint_contours|paint_pass)\b/g) ?? [])
      assert.ok(tools.has(tool), name + ' names ' + tool);
  }
  const trace = await readFile(join(SKILLS_DIR, 'guided-trace', 'SKILL.md'), 'utf8');
  for (const tool of trace.match(/\b(draw_guide|finish_guide|view_reference|paint_from_reference|paint_contours|paint_pass|fill_region)\b/g) ?? [])
    assert.ok(tools.has(tool), 'guided-trace names ' + tool);
});

test('the painter is told its AI image allowance; with no limit, assets are free only on the Codex plan', async () => {
  const { aiImageGuidance } = await import('../src/studio.mjs');
  assert.match(aiImageGuidance(null, 0, 'codex'), /included in the artist's ChatGPT plan: use make_asset freely/);
  assert.match(aiImageGuidance(null, 0, 'codex'), /paint-sky, place-subject, fix-region, paint-scene/);
  assert.match(aiImageGuidance(null, 0, 'openrouter'), /cost the artist money/);
  assert.doesNotMatch(aiImageGuidance(null, 0, 'openrouter'), /freely/);
  assert.match(aiImageGuidance(0, 0, 'codex'), /AI images are off for this chat \(allowance 0\).*do not call make_asset.*raise AI images for this chat in the panel/);
  assert.doesNotMatch(aiImageGuidance(0, 0, 'codex'), /freely/);
  assert.match(aiImageGuidance(3, 1, 'codex'), /up to 2 more AI images.*a sky, a colour field or a background is usually better painted by hand/);
  assert.match(aiImageGuidance(1, 0, 'openrouter'), /up to 1 more AI image .*costs the artist money/);
  assert.match(aiImageGuidance(2, 2, 'codex'), /allowance \(2\) is used up.*do not call make_asset/);
  const { ASSET_LIMIT, CODEX_ASSET_LIMIT } = await import('../src/assets.mjs');
  assert.ok(CODEX_ASSET_LIMIT > ASSET_LIMIT);
});

test('the sandbox runner refuses to run when its permission lock is not active', async () => {
  const { spawnSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const runner = fileURLToPath(new URL('../src/pyodide-runner.mjs', import.meta.url));
  // Started without --permission, as a runtime that ignores the flags (Bun 1.4) effectively does.
  const run = spawnSync(process.execPath, [runner], { input: JSON.stringify({ pyodide: '/nonexistent', cache: tmpdir(), work: tmpdir(), code: 'RESULT=1' }), encoding: 'utf8' });
  const reply = JSON.parse(run.stdout.trim().split('\n').at(-1));
  assert.equal(reply.ok, false);
  assert.match(reply.error, /not locked.*nothing was run/);
});

test('make_asset keeps to the chat\'s AI image allowance: refused before any image request, counted only when made', async () => {
  const h = await studyRuntime();
  let requests = 0, fail = false;
  const fetchImpl = async () => { requests++;
    if (fail) return { ok: false, status: 500, json: async () => ({ error: { message: 'model down' } }), text: async () => 'model down' };
    return { ok: true, json: async () => ({ choices: [{ message: { images: [{ image_url: { url: 'data:image/png;base64,' + subjectPng().toString('base64') } }] } }], usage: { cost: 0.018 } }) };
  };
  const ask = { name: 'Sky', prompt: 'a night sky with a red moon', mode: 'generate', aspect_ratio: '4:3' };
  try {
    const [makeAsset] = assetTools(h.runtime, { fetchImpl });
    h.runtime.goal = { limits: { ai_images: 0 }, ai_images_used: 0 };
    await assert.rejects(makeAsset.execute('a0', ask), /AI images are off for this chat \(allowance 0\)[\s\S]*raise AI images for this chat in the panel/);
    assert.equal(requests, 0, 'at 0 no image model is called');
    h.runtime.goal = { limits: { ai_images: 1 }, ai_images_used: 0 };
    fail = true; await assert.rejects(makeAsset.execute('a1', ask));
    assert.equal(h.runtime.goal.ai_images_used, 0, 'a failed generation does not count');
    fail = false; await makeAsset.execute('a2', ask);
    assert.equal(h.runtime.goal.ai_images_used, 1);
    const before = requests;
    await assert.rejects(makeAsset.execute('a3', ask), /allowance \(1\) is used up/);
    assert.equal(requests, before, 'used up: no image request');
    h.runtime.goal = undefined;
    await assert.rejects(makeAsset.execute('a4', ask), /allowance 0/, 'no chat means no AI images');
  } finally { await h.close(); }
});

test('every bundled skill that makes AI images keeps to the allowance, and those that need one have a hand-painted route', () => {
  const skills = listSkills().map(s => ({ ...s, text: readFileSync(s.filePath, 'utf8') }));
  const makers = skills.filter(s => s.text.includes('make_asset'));
  assert.ok(makers.length >= 4, 'paint-sky, place-subject, fix-region, paint-scene and image-asset make assets');
  for (const skill of makers) {
    assert.match(skill.text, /how many (AI images )?this chat allows/, skill.name + ' reads the allowance');
    assert.match(skill.text, /do not call `make_asset`|Never call `make_asset` with none left/, skill.name + ' stops at 0');
  }
  for (const name of ['paint-sky', 'place-subject', 'fix-region'])
    assert.match(skills.find(s => s.name === name).text, /## Hand-painted route/, name + ' has a hand-painted route');
});

test('one edit request for a canvas reference: the backend the assets setting names (Codex by default), the canvas as its input', async () => {
  const claims = Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'acct-123' } })).toString('base64url');
  const requests = [], image = subjectPng(40, 30);
  const sse = 'data: ' + JSON.stringify({ type: 'response.output_item.done', item: { type: 'image_generation_call', result: image.toString('base64') } }) + '\n';
  const fetchImpl = async (url, options) => { requests.push({ url, body: JSON.parse(options.body) });
    return url.startsWith('https://chatgpt.com') ? { ok: true, status: 200, text: async () => sse }
      : { ok: true, json: async () => ({ data: [{ b64_json: image.toString('base64') }] }) }; };
  const runtime = { executionSettings: {}, codexKey: async () => 'eyJhbGciOiJub25lIn0.' + claims + '.sig', imageKey: async () => 'test-key' };
  const input = { data: Buffer.from('canvas'), mimeType: 'image/png' };
  const made = await requestAssetImage(runtime, { mode: 'edit', prompt: 'Edit this painting: more snow', inputs: [input], aspect: '4:3', fetchImpl });
  assert.deepEqual(made.data, image); assert.match(made.model, /^codex\//);
  assert.equal(requests[0].body.tools[0].size, '1536x1024', 'a wide canvas asks for a wide picture');
  assert.equal(requests[0].body.tools[0].quality, 'medium');
  assert.match(requests[0].body.input[0].content[1].image_url, /^data:image\/png;base64,/);
  runtime.executionSettings.assets = 'openrouter';
  await requestAssetImage(runtime, { mode: 'edit', prompt: 'Edit this painting: more snow', inputs: [input], aspect: '4:3', fetchImpl });
  assert.equal(requests[1].url, 'https://openrouter.ai/api/v1/images'); assert.equal(requests[1].body.model, ASSET_MODELS.edit.model);
  assert.equal(requests[1].body.aspect_ratio, 'auto', 'an edit keeps its input\'s framing');
});

test('a picture that is no plain PNG is converted in the sandbox for a canvas reference, and its work files go', { timeout: 180000 }, async () => {
  const { pngFromImage } = await import('../src/assets.mjs');
  const { decodeRgba } = await import('../src/png-rgba.ts');
  const h = await studyRuntime();
  try {
    // A palette PNG (colour type 3), which the companion's own reader leaves alone.
    const w = 3, h2 = 2, raw = Buffer.alloc((w + 1) * h2);
    for (let y = 0; y < h2; y++) for (let x = 0; x < w; x++) raw[y * (w + 1) + 1 + x] = (x + y) % 2;
    const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
    const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h2, 4); ihdr.set([8, 3, 0, 0, 0], 8);
    const palette = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('PLTE', Buffer.from([255, 0, 0, 0, 0, 255])), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
    assert.equal(decodeRgba(palette), null);
    const png = await pngFromImage(h.runtime, palette);
    const read = decodeRgba(png);
    assert.deepEqual([read.width, read.height], [3, 2]);
    assert.deepEqual([...read.data.subarray(0, 8)], [255, 0, 0, 255, 0, 0, 255, 255]);
    const { readdir } = await import('node:fs/promises');
    assert.deepEqual((await readdir(join(h.runtime.study.directory, 'assets'))).filter(n => n.startsWith('convert-')), []);
  } finally { await h.close(); }
});
