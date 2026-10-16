import { pathToFileURL } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { openDatabase } from '../src/db.mjs';

const migrations = [db => db.exec('CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL) STRICT'),
  db => db.exec('ALTER TABLE notes ADD COLUMN tag TEXT')];

test('migrations run once in order; a newer database is refused', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'db-')); t.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, 'a.sqlite');
  let db = openDatabase(path, { migrations: migrations.slice(0, 1) });
  db.run('INSERT INTO notes(text) VALUES (?)', 'first'); db.close();
  db = openDatabase(path, { migrations });
  assert.equal(db.get('PRAGMA user_version').user_version, 2);
  assert.equal(db.get('SELECT text, tag FROM notes').text, 'first');
  assert.equal(db.get('PRAGMA journal_mode').journal_mode, 'wal');
  assert.equal(db.get('PRAGMA foreign_keys').foreign_keys, 1);
  db.close();
  assert.throws(() => openDatabase(path, { migrations: migrations.slice(0, 1) }), { code: 'DB_NEWER' });
});

test('a transaction commits all or nothing; nested calls join it; backup is a full copy', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'db-')); t.after(() => rm(dir, { recursive: true, force: true }));
  const db = openDatabase(join(dir, 'a.sqlite'), { migrations });
  assert.throws(() => db.transaction(() => { db.run('INSERT INTO notes(text) VALUES (?)', 'lost'); db.run('INSERT INTO notes(text) VALUES (NULL)'); }));
  assert.equal(db.get('SELECT count(*) AS n FROM notes').n, 0);
  db.transaction(() => { db.run('INSERT INTO notes(text) VALUES (?)', 'a'); db.transaction(() => db.run('INSERT INTO notes(text) VALUES (?)', 'b')); });
  assert.equal(db.get('SELECT count(*) AS n FROM notes').n, 2);
  db.backup(join(dir, 'copy.sqlite')); db.close();
  const copy = openDatabase(join(dir, 'copy.sqlite'), { migrations });
  assert.deepEqual(copy.all('SELECT text FROM notes ORDER BY id').map(r => r.text), ['a', 'b']); copy.close();
});

test('only the SQLite experimental warning is silenced', () => {
  const module = fileURLToPath(new URL('../src/db.mjs', import.meta.url));
  const run = spawnSync(process.execPath, ['--input-type=module', '-e',
    `await import(${JSON.stringify(pathToFileURL(module).href)}); process.emitWarning('other warning'); await new Promise(r => setTimeout(r, 50));`], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.doesNotMatch(run.stderr, /SQLite/); assert.match(run.stderr, /other warning/);
});
