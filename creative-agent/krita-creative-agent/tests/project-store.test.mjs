import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, readdir, rename, rm, symlink } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { ProjectStore } from '../src/project-store.mjs';

async function fixture(t) {
  const outer = await mkdtemp(join(tmpdir(), 'creative-store-'));
  const root = join(outer, 'project'); await mkdir(root);
  // Every store a test opens goes through open(), so cleanup closes them all before deleting the folder:
  // Windows cannot delete an open database. close() is safe to repeat.
  const stores = [], open = options => { const opened = new ProjectStore(options); stores.push(opened); return opened; };
  const store = open({ projectRoot: root }); await store.initialize();
  t.after(() => { for (const opened of stores) opened.close(); return rm(outer, { recursive: true, force: true }); });
  const id = randomUUID(), directory = store.studyDirectory(id);
  const study = { id, directory, name: 'Rothko material study', painting_file: 'painting.kra', references: [], bound: false };
  const goal = { version: 1, mode: 'agent', status: 'paused', brief: { objective: 'Dry chalky texture' }, locked_requirements: ['Keep the lower field unchanged'] };
  return { outer, root, store, id, directory, study, goal, open };
}

test('records live outside the project; a moved project keeps its chats', async t => {
  const f = await fixture(t), data = join(f.outer, 'data');
  f.root = join(f.outer, 'fresh project'); await mkdir(f.root);       // not touched by the fixture's store
  const store = f.open({ projectRoot: f.root, dataDirectory: data });
  const directory = store.studyDirectory(f.id); await mkdir(directory, { recursive: true });
  const ref = join(directory, 'reference.png'); await writeFile(ref, 'reference bytes');
  const study = { ...f.study, directory, references: [{ path: ref, source_path: '/external/private/reference.png', name: 'Reference' }] };
  f.goal.messages = [{ role: 'user', attachments: [{ image_path: ref }] }];
  await writeFile(join(f.root, 'painting.kra'), 'original painting');
  await store.saveStudy(study, f.goal);
  const raw = store.recordText(f.id);
  assert.ok(!raw.includes(f.root) && !raw.includes(data)); assert.ok(!raw.includes('/external/private'));
  assert.deepEqual((await readdir(f.root)).sort(), ['.creative-agent', 'painting.kra']);
  assert.deepEqual(await readdir(join(f.root, '.creative-agent')), ['project.json'], 'only the project id is in the project folder');
  store.close();
  const moved = join(f.outer, 'renamed project'); await rename(f.root, moved);
  const reopened = f.open({ projectRoot: moved, dataDirectory: data });
  const record = await reopened.load(f.id);
  assert.equal(record.paintingPath, join(moved, 'painting.kra'));
  assert.equal(record.study.references[0].path, ref, 'chat files stay in the records folder');
  assert.equal(record.goal.messages[0].attachments[0].image_path, ref);
  assert.equal(record.missingPainting, false);
  assert.equal((await reopened.list())[0].id, f.id);
  assert.equal(await readFile(record.paintingPath, 'utf8'), 'original painting');
  reopened.close();
});

test('search uses the full-text index; delete removes the record and folder, never artwork', async t => {
  const f = await fixture(t); f.goal.brief.title = 'Kremlin at dusk';
  await writeFile(join(f.root, 'painting.kra'), 'art'); await mkdir(f.directory, { recursive: true });
  await writeFile(join(f.directory, 'note.txt'), 'x'.repeat(1000));
  await f.store.saveStudy(f.study, f.goal);
  const other = { ...f.study, id: randomUUID(), name: 'Moscow winter', painting_file: undefined };
  await f.store.saveStudy(other, { ...f.goal, brief: { objective: 'Snow and amber lamps' }, locked_requirements: [] });
  assert.deepEqual((await f.store.list({ query: 'rothk' })).map(c => c.id), [f.id], 'word prefix');
  assert.deepEqual((await f.store.list({ query: 'amber snow' })).map(c => c.id), [other.id], 'all words, any order');
  assert.deepEqual((await f.store.list({ query: 'painting.kra' })).map(c => c.id), [f.id]);
  assert.equal((await f.store.list({ query: '"quoted' })).length, 0, 'quotes in the search box are safe');
  const usage = await f.store.storageUsage();
  assert.equal(usage.chats.length, 2); assert.ok(usage.chats[0].folder_bytes >= 1000);
  await f.store.delete(f.id);
  assert.deepEqual((await f.store.list()).map(c => c.id), [other.id]);
  assert.deepEqual((await f.store.list({ query: 'rothko' })), [], 'the search index follows deletes');
  await assert.rejects(readdir(f.directory), { code: 'ENOENT' });
  assert.equal(await readFile(join(f.root, 'painting.kra'), 'utf8'), 'art');
  await assert.rejects(f.store.delete(f.id), { code: 'ENOENT' });
});

test('a newer database is refused; app files move to the data directory, caches go, script output stays', async t => {
  const f = await fixture(t), data = join(f.outer, 'data'), state = join(f.root, '.creative-agent');
  await writeFile(join(state, 'model-connections.json'), '{"keys":"kept"}');
  await mkdir(join(state, 'capabilities')); await writeFile(join(state, 'capabilities', 'route.json'), 'verified');
  await mkdir(join(state, 'previews')); await writeFile(join(state, 'previews', 'v.png'), 'cache');
  await mkdir(join(state, 'live-tests')); await writeFile(join(state, 'companion.lock'), JSON.stringify({ pid: 999999 }));
  const store = f.open({ projectRoot: f.root, dataDirectory: data }); await store.initialize();
  assert.equal(await readFile(join(data, 'model-connections.json'), 'utf8'), '{"keys":"kept"}');
  assert.equal(await readFile(join(data, 'capabilities', 'route.json'), 'utf8'), 'verified');
  const left = await readdir(state);
  for (const gone of ['model-connections.json', 'capabilities', 'previews', 'companion.lock']) assert.ok(!left.includes(gone), gone);
  assert.ok(left.includes('live-tests'), 'script output is not the agent\'s to move');
  store.db.exec('PRAGMA user_version = 99'); store.close();
  await assert.rejects(f.open({ projectRoot: f.root, dataDirectory: data }).initialize(), /newer Creative Agent/);
});

async function oldLayout(f, data) {
  // A chat as the store kept it before storage-layout: project-relative paths in record.json.
  const old = join(f.root, '.creative-agent', 'studies', f.id);
  await mkdir(join(old, 'sessions'), { recursive: true });
  await writeFile(join(old, 'reference.png'), 'image'); await writeFile(join(old, 'sessions', 's.jsonl'), '{"entry":1}\n');
  await writeFile(join(f.root, 'painting.kra'), 'artwork');
  const prefix = '.creative-agent/studies/' + f.id + '/';
  await writeFile(join(old, 'record.json'), JSON.stringify({ version: 1, updated_at: '2026-10-01T00:00:00.000Z',
    study: { id: f.id, name: 'Old chat', painting_file: 'painting.kra', references: [{ path: prefix + 'reference.png' }], session_file: prefix + 'sessions/s.jsonl', directory: prefix.slice(0, -1) },
    goal: { ...f.goal, status: 'active', brief: { objective: 'Old objective' } } }));
  await writeFile(join(old, '.operations.json'), JSON.stringify({ op: ['fp', { checkpoint: '../../../painting.kra', image_path: '.previews/v.jpg' }] }));
  return { old, store: f.open({ projectRoot: f.root, dataDirectory: data }) };
}

test('chats in the project folder move to the records folder, artwork stays, paths still resolve', async t => {
  const f = await fixture(t), data = join(f.outer, 'data'), { old, store } = await oldLayout(f, data);
  const progress = [];
  const report = await store.migrateProjectFolder({ onProgress: (done, total) => progress.push([done, total]) });
  assert.deepEqual(report, { imported: [f.id], skipped: [], errors: [] }); assert.deepEqual(progress, [[1, 1]]);
  await assert.rejects(readdir(old), { code: 'ENOENT' });
  await assert.rejects(readdir(join(f.root, '.creative-agent', 'studies')), { code: 'ENOENT' });
  assert.ok(JSON.parse(await readFile(join(f.root, '.creative-agent', 'project.json'), 'utf8')).migrated_at);
  const chat = store.studyDirectory(f.id), record = await store.load(f.id);
  assert.equal(record.study.references[0].path, join(chat, 'reference.png'));
  assert.equal(await readFile(record.study.references[0].path, 'utf8'), 'image');
  assert.equal(record.study.session_file, join(chat, 'sessions', 's.jsonl'));
  assert.equal(record.goal.status, 'active'); assert.equal(record.paintingPath, join(f.root, 'painting.kra'));
  assert.equal((await store.list())[0].status, 'paused', 'listed as paused, like before');
  const { resolve } = await import('node:path');
  const operations = JSON.parse(await readFile(join(chat, '.operations.json'), 'utf8'));
  assert.equal(resolve(chat, operations.op[1].checkpoint), join(f.root, 'painting.kra'), 'the journal still finds the painting');
  assert.equal(resolve(chat, operations.op[1].image_path), join(chat, '.previews', 'v.jpg'));
  assert.deepEqual((await readdir(chat)).sort(), ['.operations.json', 'reference.png', 'sessions']);
  assert.equal(await readFile(join(f.root, 'painting.kra'), 'utf8'), 'artwork');
  assert.deepEqual(await store.migrateProjectFolder(), { imported: [], skipped: [], errors: [] }, 'idempotent');
});

test('an interrupted move resumes, and a broken chat stays in place', async t => {
  const f = await fixture(t), data = join(f.outer, 'data'), { old, store } = await oldLayout(f, data);
  await store.initialize();
  await mkdir(store.chatsDirectory, { recursive: true }); await rename(old, store.studyDirectory(f.id));   // moved, then quit
  const empty = join(f.root, '.creative-agent', 'studies', randomUUID()); await mkdir(empty);
  const broken = randomUUID(), brokenDir = join(f.root, '.creative-agent', 'studies', broken);
  await mkdir(brokenDir); await writeFile(join(brokenDir, 'record.json'), '{not json');
  const report = await store.migrateProjectFolder();
  assert.deepEqual(report.imported, [f.id]); assert.equal(report.errors.length, 1); assert.equal(report.errors[0].id, broken);
  await assert.rejects(readdir(empty), { code: 'ENOENT' }, 'an empty chat folder is simply removed');
  assert.equal((await store.load(f.id)).study.name, 'Old chat');
  assert.equal(await readFile(join(brokenDir, 'record.json'), 'utf8'), '{not json', 'left exactly as it was');
  assert.ok(!JSON.parse(await readFile(join(f.root, '.creative-agent', 'project.json'), 'utf8')).migrated_at);
  const { resolve } = await import('node:path');
  const operations = JSON.parse(await readFile(join(store.studyDirectory(f.id), '.operations.json'), 'utf8'));
  assert.equal(resolve(store.studyDirectory(f.id), operations.op[1].checkpoint), join(f.root, 'painting.kra'));
});

test('Finder move needs relink and cannot recreate old painting; relink preserves plan paused', async t => {
  const f = await fixture(t); await writeFile(join(f.root, 'painting.kra'), 'manual edits');
  f.study.bound = true; f.goal.status = 'active'; await f.store.saveStudy(f.study, f.goal);
  const moved = join(f.root, 'my final.kra'); await rename(join(f.root, 'painting.kra'), moved);
  const missing = await f.store.load(f.id); assert.equal(missing.missingPainting, true);
  assert.equal((await f.store.list())[0].status, 'needs_relink');
  const linked = await f.store.relink(f.id, moved);
  assert.equal(linked.study.painting_file, 'my final.kra'); assert.equal(linked.study.bound, false);
  assert.equal(linked.goal.status, 'paused'); assert.deepEqual(linked.goal.brief, f.goal.brief);
  assert.equal((await f.store.findByPainting(moved)).study.id, f.id);
  await assert.rejects(readFile(join(f.root, 'painting.kra')), { code: 'ENOENT' });
  assert.equal(await readFile(moved, 'utf8'), 'manual edits');
  await assert.rejects(f.store.relink(f.id, join(f.root, 'missing.kra')), { code: 'ENOENT' });
  await assert.rejects(f.store.relink(f.id, join(f.root, 'wrong.png')), /\.kra/);
});

test('history searches title, painting filename and requirements; drafts need no artwork', async t => {
  const f = await fixture(t); delete f.study.painting_file; f.goal.status = 'draft';
  await f.store.saveStudy(f.study, f.goal);
  assert.equal((await f.store.list({ query: 'ROTHKO' })).length, 1);
  assert.equal((await f.store.list({ query: 'lower field' })).length, 1);
  assert.equal((await f.store.list({ query: 'unrelated' })).length, 0);
  assert.equal((await f.store.load(f.id)).missingPainting, false);
  assert.equal((await f.store.list())[0].filename, null);
});

test('legacy migration copies state, leaves artwork and original records unchanged, and is idempotent', async t => {
  const f = await fixture(t), legacy = join(f.root, 'old-output'), source = join(legacy, f.id);
  await mkdir(join(source, 'sessions'), { recursive: true });
  const original = { ...f.study, directory: source, references: [{ path: join(source, 'reference.png') }] };
  const bytes = JSON.stringify(original); await writeFile(join(source, 'study.json'), bytes);
  await writeFile(join(source, 'goal.json'), JSON.stringify({ ...f.goal, status: 'reviewing' }));
  await writeFile(join(source, 'sessions', 'session.jsonl'), '{"historic":"record"}\n');
  await writeFile(join(source, 'reference.png'), 'image'); await writeFile(join(source, 'painting.kra'), 'legacy painting');
  await writeFile(join(f.root, 'painting.kra'), 'already moved artwork');
  await symlink(join(f.root, 'painting.kra'), join(source, 'outside-link'));
  const report = await f.store.migrateLegacy(legacy);
  assert.deepEqual(report.imported, [f.id]); assert.deepEqual(report.errors, []);
  const record = await f.store.load(f.id);
  assert.equal(record.goal.status, 'paused'); assert.equal(record.paintingPath, join(f.root, 'painting.kra'));
  assert.equal(await readFile(record.study.references[0].path, 'utf8'), 'image');
  assert.equal(await readFile(join(source, 'study.json'), 'utf8'), bytes);
  assert.equal(await readFile(join(source, 'painting.kra'), 'utf8'), 'legacy painting');
  await assert.rejects(readFile(join(f.directory, 'painting.kra')), { code: 'ENOENT' });
  await assert.rejects(readFile(join(f.directory, 'outside-link')), { code: 'ENOENT' });
  assert.deepEqual((await f.store.migrateLegacy(legacy)).skipped, [f.id]);
});

test('load imports one legacy conversation and protects unsupported/corrupt records', async t => {
  const f = await fixture(t), legacy = join(f.root, 'legacy'), source = join(legacy, f.id);
  await mkdir(source, { recursive: true });
  await writeFile(join(source, 'study.json'), JSON.stringify({ id: f.id, name: 'Legacy draft', references: [] }));
  const store = f.open({ projectRoot: f.root, legacyRoots: [legacy] });
  const record = await store.load(f.id); assert.equal(record.study.name, 'Legacy draft');
  assert.equal(record.paintingPath, null);
  await assert.rejects(store.load('../outside'), /identifier/);
  assert.throws(() => new ProjectStore({ projectRoot: f.root, stateDir: '..' }), /separate folder/);
});

test('concurrent saves commit matching study and goal revisions', async t => {
  const f = await fixture(t);
  await Promise.all(Array.from({ length: 12 }, (_, i) => f.store.saveStudy({ ...f.study, revision: i }, { ...f.goal, revision: i })));
  const record = await f.store.load(f.id);
  assert.equal(record.study.revision, 11); assert.equal(record.goal.revision, 11);
  const files = await readdir(f.directory); assert.ok(!files.some(file => file.endsWith('.tmp')));
});

test('legacy native ledgers remap previews but retain real artwork paths across directory depth changes', async t => {
  const f = await fixture(t), legacy = join(f.root, 'legacy-output'), source = join(legacy, f.id);
  await mkdir(join(source, '.previews'), { recursive: true });
  await writeFile(join(source, 'study.json'), JSON.stringify({ id: f.id, name: 'Old native ledger', references: [], painting_file: 'painting.kra' }));
  await writeFile(join(source, '.previews', 'pass.png'), 'saved preview');
  await writeFile(join(source, 'painting.kra'), 'legacy canvas left in place');
  await writeFile(join(f.root, 'painting.kra'), 'current canvas left in place');
  const native = {
    first: ['fingerprint-1', { image_path: '.previews/pass.png', path: '.previews/pass.png',
      checkpoint: '../../painting.kra', filename: '../../painting.kra' }],
    older: ['fingerprint-2', { checkpoint: 'painting.kra', filename: join(source, 'painting.kra') }],
  };
  const passes = [{ id: 'first', before_path: '.previews/pass.png', after_path: join(source, '.previews/pass.png') }];
  await writeFile(join(source, '.operations.json'), JSON.stringify(native));
  await writeFile(join(source, '.passes.json'), JSON.stringify(passes));
  await f.store.migrateLegacy(legacy);
  const imported = JSON.parse(await readFile(join(f.directory, '.operations.json'), 'utf8'));
  const importedPass = JSON.parse(await readFile(join(f.directory, '.passes.json'), 'utf8'))[0];
  const { resolve } = await import('node:path');
  assert.equal(resolve(f.directory, imported.first[1].checkpoint), join(f.root, 'painting.kra'));
  assert.equal(resolve(f.directory, imported.first[1].filename), join(f.root, 'painting.kra'));
  assert.equal(resolve(f.directory, imported.older[1].checkpoint), join(source, 'painting.kra'));
  assert.equal(resolve(f.directory, imported.older[1].filename), join(source, 'painting.kra'));
  assert.equal(resolve(f.directory, imported.first[1].image_path), join(f.directory, '.previews/pass.png'));
  assert.equal(resolve(f.directory, importedPass.after_path), join(f.directory, '.previews/pass.png'));
  assert.equal(resolve(f.directory, importedPass.before_path), join(f.directory, '.previews/pass.png'));
  assert.deepEqual(JSON.parse(await readFile(join(source, '.operations.json'), 'utf8')), native);
});

test('rollback moves chats back in the old format, and migrating again restores them', async t => {
  const f = await fixture(t), data = join(f.outer, 'data'), { old, store } = await oldLayout(f, data);
  const before = JSON.parse(await readFile(join(old, 'record.json'), 'utf8'));
  const beforeOps = await readFile(join(old, '.operations.json'), 'utf8');
  await store.migrateProjectFolder();
  assert.equal((await store.importSessionLogs()).files, 1, 'the chat log moved into the database');
  await assert.rejects(readFile(join(store.studyDirectory(f.id), 'sessions', 's.jsonl')), { code: 'ENOENT' });
  const report = await store.unmigrateProjectFolder();
  assert.deepEqual(report, { restored: [f.id], errors: [] });
  const after = JSON.parse(await readFile(join(old, 'record.json'), 'utf8'));
  assert.deepEqual(after.study.references, before.study.references); assert.equal(after.study.session_file, before.study.session_file);
  assert.equal(after.goal.brief.objective, 'Old objective');
  assert.deepEqual(JSON.parse(await readFile(join(old, '.operations.json'), 'utf8')), JSON.parse(beforeOps), 'journal paths are back as they were');
  assert.equal(await readFile(join(old, 'reference.png'), 'utf8'), 'image');
  assert.deepEqual(await store.list(), []);
  assert.equal(JSON.parse(await readFile(join(old, 'sessions', 's.jsonl'), 'utf8')).entry, 1, 'the log is a file again');
  assert.equal(store.db.get('SELECT count(*) AS n FROM session_entries').n, 0);
  assert.deepEqual((await store.migrateProjectFolder()).imported, [f.id]);
  assert.equal((await store.load(f.id)).study.name, 'Old chat');
});

test('references live in the images table: once across chats, recreated on open, freed with the last chat', async t => {
  const f = await fixture(t), bytes = Buffer.from('a reference picture');
  const chat = async name => {
    const id = randomUUID(), directory = f.store.studyDirectory(id); await mkdir(directory, { recursive: true });
    await writeFile(join(directory, 'reference-1.png'), bytes);
    await f.store.saveStudy({ id, directory, name, references: [{ id: 'reference-1', path: join(directory, 'reference-1.png') }] }, { status: 'draft' });
    return { id, path: join(directory, 'reference-1.png') };
  };
  const one = await chat('One'), two = await chat('Two');
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 1, 'the same reference is stored once');
  assert.equal(f.store.db.get("SELECT count(*) AS n FROM chat_images WHERE role = 'reference'").n, 2);
  assert.deepEqual(f.store.rebuildableFiles(one.id), [one.path]);
  const orphan = join(f.store.studyDirectory(one.id), 'reference-' + randomUUID() + '.png'); await writeFile(orphan, 'removed reference');
  assert.deepEqual((await f.store.removableFiles(one.id)).sort(), [one.path, orphan].sort(), 'a removed reference\'s copy goes too');
  await rm(orphan);
  await rm(one.path);                                           // a closed chat's copy was cleaned up
  const record = await f.store.load(one.id);
  assert.deepEqual(await readFile(record.study.references[0].path), bytes, 'recreated byte for byte on open');
  assert.match(record.study.references[0].sha256, /^[0-9a-f]{64}$/);
  f.store.sessions.putVariant(record.study.references[0].sha256, 'model-1568', Buffer.from('small copy'), 'image/jpeg');
  assert.equal(f.store.sessions.variant(record.study.references[0].sha256, 'model-1568').bytes.toString(), 'small copy');
  await f.store.delete(one.id);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 2, 'still used by the other chat (and its copy)');
  await f.store.delete(two.id);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 0, 'freed with the last chat, copy included');
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM image_variants').n, 0);
});

test('references of chats saved before they were images are imported, keeping their order in the list', async t => {
  const f = await fixture(t);
  const id = randomUUID(), directory = f.store.studyDirectory(id); await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'reference-1.png'), 'old reference');
  const record = { version: 1, updated_at: '2026-01-01T00:00:00.000Z', study: { id, name: 'Old', references: [{ id: 'reference-1', path: 'chat:reference-1.png' }] }, goal: { status: 'draft' } };
  f.store.write(record);
  assert.equal(await f.store.importReferences(), 1);
  assert.equal(await f.store.importReferences(), 0, 'once');
  assert.equal(f.store.db.get('SELECT updated_at FROM chats WHERE id = ?', id).updated_at, '2026-01-01T00:00:00.000Z');
  assert.match((await f.store.load(id)).study.references[0].sha256, /^[0-9a-f]{64}$/);
});
