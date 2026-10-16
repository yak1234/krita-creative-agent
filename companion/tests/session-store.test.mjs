import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { SessionManager } from '@earendil-works/pi-coding-agent';
import { ProjectStore } from '../src/project-store.mjs';
import { SDK_INTERNALS } from '../src/session-store.mjs';

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9kAAAAASUVORK5CYII=';
const image = { type: 'image', data: png, mimeType: 'image/png' };
const user = (text, extra = []) => ({ role: 'user', content: [{ type: 'text', text }, ...extra], timestamp: 1 });
const reply = text => ({ role: 'assistant', content: [{ type: 'text', text }], api: 'openai-completions', provider: 't', model: 'm',
  usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: 'stop', timestamp: 2 });

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'session-store-'));
  const project = join(root, 'project'); await mkdir(project);
  const store = new ProjectStore({ projectRoot: project, dataDirectory: join(root, 'data') }); await store.initialize();
  t.after(() => { store.close(); return rm(root, { recursive: true, force: true }); });   // close before deleting (Windows)
  const id = randomUUID(), directory = store.studyDirectory(id);
  await store.saveStudy({ id, directory, name: 'Chat', references: [] }, { status: 'draft' });
  return { root, store, id, directory, managers: store.sessions.managers() };
}
// The same conversation written through any SessionManager: branches, a compaction and images.
function converse(manager) {
  manager.appendMessage(user('Paint the Kremlin', [image]));
  const first = manager.appendMessage(reply('Starting with the sky.'));
  manager.appendMessage(user('Warmer', [image]));
  manager.appendMessage(reply('Warmer sky.'));
  manager.appendCompaction('The artist wants a warm Kremlin at dusk.', first, 1000);
  manager.appendMessage(user('Now the towers', [image]));
  manager.appendMessage(reply('Towers next.'));
  manager.branch(first);                                        // go back and take another path
  manager.appendMessage(user('Actually a night scene'));
  manager.appendMessage(reply('Night it is.'));
}

test('SDK contract: the internals the adapter overrides exist on the pinned SessionManager', () => {
  const memory = SessionManager.inMemory('/tmp');
  for (const name of SDK_INTERNALS) assert.ok(name in memory || name in SessionManager.prototype, name);
});

test('a session with branches, a compaction and images rebuilds the same context as the SDK file store', async t => {
  const f = await fixture(t);
  const fileManager = SessionManager.create(f.directory, join(f.root, 'jsonl'));
  const dbManager = f.managers.create(f.directory, join(f.directory, 'sessions'));
  converse(fileManager); converse(dbManager);
  const path = dbManager.getSessionFile();
  await assert.rejects(readFile(path), { code: 'ENOENT' }, 'no JSONL file is written');
  const reopened = f.managers.open(path, join(f.directory, 'sessions'), f.directory);
  const fromFile = SessionManager.open(fileManager.getSessionFile(), join(f.root, 'jsonl'), f.directory);
  const strip = context => JSON.parse(JSON.stringify(context, (key, value) => key === 'id' || key === 'parentId' || key === 'timestamp' || key === 'firstKeptEntryId' ? undefined : value));
  assert.deepEqual(strip(reopened.buildSessionContext()), strip(fromFile.buildSessionContext()));
  assert.equal(reopened.getEntries().length, fromFile.getEntries().length);
  assert.equal(reopened.getLeafId(), dbManager.getLeafId());
  assert.ok(reopened.getEntries().some(entry => entry.type === 'compaction'));
  const images = reopened.getEntries().flatMap(entry => entry.message?.content ?? []).filter(c => c.type === 'image');
  assert.equal(images.length, 3); assert.ok(images.every(c => c.data === png && !c.ref), 'images are inline again');
  // Appending after reopening continues the same stored session.
  reopened.appendMessage(user('One more')); reopened.appendMessage(reply('Done.'));
  assert.equal(f.managers.open(path, join(f.directory, 'sessions'), f.directory).getEntries().length, fromFile.getEntries().length + 2);
});

test('each image is stored once however often it is sent; deleting the chat removes it', async t => {
  const f = await fixture(t);
  const manager = f.managers.create(f.directory, join(f.directory, 'sessions'));
  for (let i = 0; i < 20; i++) { manager.appendMessage(user('again ' + i, [image])); manager.appendMessage(reply('ok')); }
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 1);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM entry_images').n, 20);
  const stored = f.store.db.get("SELECT entry FROM session_entries WHERE entry LIKE '%\"ref\"%' LIMIT 1").entry;
  assert.ok(!stored.includes(png), 'entries hold a reference, not the bytes');
  const usage = await f.store.storageUsage();
  assert.ok(usage.chats[0].image_bytes > 0 && usage.chats[0].image_bytes < 200);
  await f.store.delete(f.id);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 0);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM session_entries').n, 0);
});

test('nothing is stored until the model replies, as the SDK does', async t => {
  const f = await fixture(t);
  const manager = f.managers.create(f.directory, join(f.directory, 'sessions'));
  manager.appendMessage(user('hello'));
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM session_entries').n, 0);
  manager.appendMessage(reply('hi'));
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM session_entries').n, 3, 'header, question and reply together');
});

test('JSONL logs import into the database and the files go; a mismatch keeps the file', async t => {
  const f = await fixture(t);
  const fileManager = SessionManager.create(f.directory, join(f.directory, 'sessions'));
  converse(fileManager);
  const reviews = SessionManager.create(f.directory, join(f.directory, 'reviews'));
  reviews.appendMessage(user('Review this', [image])); reviews.appendMessage(reply('Looks done.'));
  const reviewFile = reviews.getSessionFile();
  await writeFile(reviewFile, (await readFile(reviewFile, 'utf8')) + '{"torn":', 'utf8');      // a torn last line
  const expected = SessionManager.open(fileManager.getSessionFile(), join(f.directory, 'sessions'), f.directory).buildSessionContext();
  const report = await f.store.importSessionLogs();
  assert.equal(report.files, 2); assert.deepEqual(report.errors, []);
  assert.deepEqual(await readdir(join(f.directory, 'sessions')), []); assert.deepEqual(await readdir(join(f.directory, 'reviews')), []);
  const reopened = f.managers.open(fileManager.getSessionFile(), join(f.directory, 'sessions'), f.directory);
  assert.deepEqual(reopened.buildSessionContext(), expected);
  assert.deepEqual(f.store.sessions.keys(f.id, 'reviews/').length, 1);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 1, 'the same image across logs is one row');
  // A file that disagrees with what is already stored is kept, not overwritten.
  await writeFile(fileManager.getSessionFile(), JSON.stringify({ type: 'session', version: 3, id: 'x', timestamp: 't', cwd: '/' }) + '\n');
  const again = await f.store.importSessionLogs();
  assert.equal(again.errors.length, 1); assert.match(again.errors[0].error, /different number/);
  assert.ok((await readdir(join(f.directory, 'sessions'))).length === 1);
});

test('an image can be replaced by a smaller copy: entries follow it and the old bytes are deleted', async t => {
  const f = await fixture(t);
  const manager = f.managers.create(f.directory, join(f.directory, 'sessions'));
  for (let i = 0; i < 3; i++) { manager.appendMessage(user('step ' + i, [image])); manager.appendMessage(reply('ok')); }
  const [{ sha256 }] = f.store.sessions.pngImages(0);
  const jpeg = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2w==', 'base64');                 // stands in for Krita's copy
  const saved = f.store.sessions.replaceImage(sha256, jpeg, 'image/jpeg');
  assert.equal(saved, Buffer.from(png, 'base64').length - jpeg.length);
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM images').n, 1, 'the PNG row is gone');
  assert.equal(f.store.db.get("SELECT mime FROM images").mime, 'image/jpeg');
  assert.equal(f.store.db.get('SELECT count(*) AS n FROM entry_images WHERE sha256 = ?', sha256).n, 0);
  const reopened = f.managers.open(manager.getSessionFile(), join(f.directory, 'sessions'), f.directory);
  const images = reopened.getEntries().flatMap(e => e.message?.content ?? []).filter(c => c.type === 'image');
  assert.equal(images.length, 3);
  assert.ok(images.every(c => c.mimeType === 'image/jpeg' && c.data === jpeg.toString('base64')));
  assert.deepEqual(f.store.sessions.pngImages(0), []);
});
