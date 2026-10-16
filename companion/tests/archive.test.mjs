import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { ProjectStore } from '../src/project-store.mjs';
import { exportChats, importArchive } from '../src/archive.mjs';

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9kAAAAASUVORK5CYII=';
const user = (text, extra = []) => ({ role: 'user', content: [{ type: 'text', text }, ...extra], timestamp: 1 });
const reply = text => ({ role: 'assistant', content: [{ type: 'text', text }], api: 'openai-completions', provider: 't', model: 'm',
  usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: 'stop', timestamp: 2 });
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function machine(root, name) {
  const project = join(root, name, 'project'); await mkdir(project, { recursive: true });
  const store = new ProjectStore({ projectRoot: project, dataDirectory: join(root, name, 'data') }); await store.initialize();
  return { project, store };
}

test('a chat moves to another machine through one archive file', async t => {
  const root = await mkdtemp(join(tmpdir(), 'archive-')); t.after(() => rm(root, { recursive: true, force: true }));
  const a = await machine(root, 'a'), b = await machine(root, 'b');
  t.after(() => { a.store.close(); b.store.close(); });
  const id = randomUUID(), directory = a.store.studyDirectory(id);
  await mkdir(join(directory, '.previews'), { recursive: true });
  await writeFile(join(directory, 'reference-1.png'), 'reference bytes');
  await writeFile(join(directory, '.previews', 'view.jpg'), 'scratch');
  await writeFile(join(a.project, 'painting.kra'), 'art'); await writeFile(join(b.project, 'painting.kra'), 'art copy');
  await a.store.saveStudy({ id, directory, name: 'Kremlin', painting_file: 'painting.kra', references: [{ path: join(directory, 'reference-1.png') }] },
    { status: 'paused', brief: { objective: 'Warm dusk' } });
  const manager = a.store.sessions.managers().create(directory, join(directory, 'sessions'));
  manager.appendMessage(user('Paint it', [{ type: 'image', data: png, mimeType: 'image/png' }])); manager.appendMessage(reply('Painting.'));
  // The plugin's journal with recent writes still in its WAL file (its connection open).
  const journal = new DatabaseSync(join(directory, 'journal.sqlite'));
  journal.exec("PRAGMA journal_mode = WAL; CREATE TABLE operations (operation_id TEXT PRIMARY KEY); INSERT INTO operations VALUES ('op-1')");

  const archivePath = join(root, 'Kremlin.creative-agent-archive');
  assert.deepEqual((await exportChats(a.store, archivePath, { ids: [id] })).chats, 1);
  journal.close();
  assert.deepEqual((await readdir(root)).filter(n => n.startsWith('Kremlin')), ['Kremlin.creative-agent-archive'], 'one standalone file');
  const before = sha(await readFile(archivePath));
  const inArchive = new DatabaseSync(archivePath, { readOnly: true });
  assert.deepEqual(inArchive.prepare('SELECT path FROM files ORDER BY path').all().map(r => r.path), ['journal.sqlite'], 'the reference travels as an image, not a file');
  assert.equal(inArchive.prepare("SELECT count(*) AS n FROM chat_images WHERE role = 'reference'").get().n, 1);
  inArchive.close();

  const report = await importArchive(b.store, archivePath);
  assert.deepEqual(report, { imported: [id], skipped: [], replaced: [] });
  assert.equal(sha(await readFile(archivePath)), before, 'importing never changes the archive');
  const record = await b.store.load(id);
  assert.equal(record.study.name, 'Kremlin'); assert.equal(record.paintingPath, join(b.project, 'painting.kra'));
  assert.equal(await readFile(record.study.references[0].path, 'utf8'), 'reference bytes');
  assert.ok(record.study.references[0].path.startsWith(b.store.studyDirectory(id)));
  assert.deepEqual((await b.store.list({ query: 'kremlin' })).map(c => c.id), [id], 'searchable after import');
  const reopened = b.store.sessions.managers().open(manager.getSessionFile().replace(a.store.chatsDirectory, b.store.chatsDirectory), join(b.store.studyDirectory(id), 'sessions'), b.store.studyDirectory(id));
  assert.deepEqual(reopened.buildSessionContext(), manager.buildSessionContext());
  const copied = new DatabaseSync(join(b.store.studyDirectory(id), 'journal.sqlite'), { readOnly: true });
  assert.deepEqual(copied.prepare('SELECT operation_id FROM operations').all().map(r => r.operation_id), ['op-1'], 'the journal includes its WAL writes');
  copied.close();
  await assert.rejects(readdir(join(b.store.studyDirectory(id), '.previews')), { code: 'ENOENT' }, 'previews are scratch and stay behind');

  assert.deepEqual((await importArchive(b.store, archivePath)).skipped, [id], 'a chat already here is skipped');
  await b.store.saveStudy({ ...record.study, name: 'Changed here' }, record.goal);
  assert.deepEqual((await importArchive(b.store, archivePath, { replace: true })).replaced, [id]);
  assert.equal((await b.store.load(id)).study.name, 'Kremlin');
  assert.equal(b.store.db.get('SELECT count(*) AS n FROM images').n, 2, 'the log image and the reference, each once');
});

test('a whole project exports; an unknown archive format is refused', async t => {
  const root = await mkdtemp(join(tmpdir(), 'archive-')); t.after(() => rm(root, { recursive: true, force: true }));
  const a = await machine(root, 'a'); t.after(() => a.store.close());
  for (const name of ['One', 'Two']) { const id = randomUUID(); await a.store.saveStudy({ id, directory: a.store.studyDirectory(id), name, references: [] }, { status: 'draft' }); }
  const path = join(root, 'project.creative-agent-archive');
  assert.equal((await exportChats(a.store, path)).chats, 2);
  const db = new DatabaseSync(path); db.exec("UPDATE meta SET value = '99' WHERE key = 'format'"); db.close();
  const b = await machine(root, 'b'); t.after(() => b.store.close());
  await assert.rejects(importArchive(b.store, path), /different Creative Agent version/);
  assert.deepEqual(await b.store.list(), []);
});
