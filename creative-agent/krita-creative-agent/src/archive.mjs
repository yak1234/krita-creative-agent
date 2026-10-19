// @ts-check
// Export and import of chats as one `.creative-agent-archive` file (storage-layout phase E). The
// archive is itself a SQLite database: the chats' records, their chat logs, the images those logs
// use (each once), and every file in the chats' folders (journal, references, reviews…). Paths in
// records are chat- or project-relative, so a chat moves to another machine or project unchanged.
import { mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { dirname, join, relative, sep } from 'node:path';
import { tmpdir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { openDatabase, openReadOnly, snapshot } from './db.mjs';

export const ARCHIVE_FORMAT = 1;
const ARCHIVE_SCHEMA = [db => db.exec(`
  CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
  CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, painting_file TEXT, status TEXT NOT NULL, mode TEXT NOT NULL,
    thumbnail TEXT, search_text TEXT NOT NULL, record TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
  CREATE TABLE sessions (chat_id TEXT NOT NULL, key TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (chat_id, key)) STRICT;
  CREATE TABLE session_entries (chat_id TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL, entry TEXT NOT NULL, PRIMARY KEY (chat_id, key, seq)) STRICT;
  CREATE TABLE images (sha256 TEXT PRIMARY KEY, mime TEXT NOT NULL, bytes BLOB NOT NULL, created_at TEXT NOT NULL) STRICT;
  CREATE TABLE entry_images (chat_id TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY (chat_id, key, seq, sha256)) STRICT;
  CREATE TABLE files (chat_id TEXT NOT NULL, path TEXT NOT NULL, bytes BLOB NOT NULL, PRIMARY KEY (chat_id, path)) STRICT;
  CREATE TABLE chat_images (chat_id TEXT NOT NULL, role TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY (chat_id, role, sha256)) STRICT;
  CREATE TABLE image_variants (source TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT, PRIMARY KEY (source, kind)) STRICT;
`)];
const CHAT_COLUMNS = 'id, title, painting_file, status, mode, thumbnail, search_text, record, created_at, updated_at';
// Scratch that is rebuilt anyway: previews, reduced references, live status, SQLite side files.
const SKIP = name => name === '.previews' || name === '.model-references' || name === '.progress.json' || /-(wal|shm)$/.test(name);

async function chatFiles(directory, base = directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true }).catch(() => [])) {
    if (SKIP(entry.name) || entry.isSymbolicLink()) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await chatFiles(path, base));
    else if (entry.isFile()) files.push(relative(base, path).split(sep).join('/'));
  }
  return files;
}

/** Write chats (default: every chat of the store's project) to an archive file. */
export async function exportChats(store, destination, { ids } = /** @type {{ids?: string[]}} */ ({})) {
  await store.initialize();
  const chosen = ids ?? store.db.all('SELECT id FROM chats WHERE project_id = ?', store.projectId).map(row => row.id);
  if (!chosen.length) throw new Error('There are no chats to export.');
  await rm(destination, { force: true });
  const archive = openDatabase(destination, { migrations: ARCHIVE_SCHEMA });
  try {
    archive.run('INSERT INTO meta(key, value) VALUES (?, ?), (?, ?), (?, ?)', 'format', String(ARCHIVE_FORMAT),
      'exported_at', new Date().toISOString(), 'chats', String(chosen.length));
    for (const id of chosen) {
      // The journal must be complete in its main file before it is copied.
      archive.transaction(() => {
        const chat = store.db.get(`SELECT ${CHAT_COLUMNS} FROM chats WHERE id = ? AND project_id = ?`, id, store.projectId);
        if (!chat) throw new Error('Conversation not found: ' + id);
        archive.run(`INSERT INTO chats(${CHAT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, ...CHAT_COLUMNS.split(', ').map(column => chat[column]));
        for (const row of store.db.all('SELECT chat_id, key, created_at FROM sessions WHERE chat_id = ?', id))
          archive.run('INSERT INTO sessions VALUES (?, ?, ?)', row.chat_id, row.key, row.created_at);
        for (const row of store.db.all('SELECT chat_id, key, seq, entry FROM session_entries WHERE chat_id = ?', id))
          archive.run('INSERT INTO session_entries VALUES (?, ?, ?, ?)', row.chat_id, row.key, row.seq, row.entry);
        for (const row of store.db.all('SELECT chat_id, key, seq, sha256 FROM entry_images WHERE chat_id = ?', id))
          archive.run('INSERT INTO entry_images VALUES (?, ?, ?, ?)', row.chat_id, row.key, row.seq, row.sha256);
        for (const row of store.db.all('SELECT chat_id, role, sha256 FROM chat_images WHERE chat_id = ?', id))
          archive.run('INSERT INTO chat_images VALUES (?, ?, ?)', row.chat_id, row.role, row.sha256);
        for (const row of store.db.all('SELECT source, kind, sha256 FROM image_variants WHERE source IN (SELECT sha256 FROM chat_images WHERE chat_id = ?)', id))
          archive.run('INSERT INTO image_variants VALUES (?, ?, ?) ON CONFLICT DO NOTHING', row.source, row.kind, row.sha256);
        for (const row of store.db.all(`SELECT i.sha256, i.mime, i.bytes, i.created_at FROM images i WHERE i.sha256 IN (SELECT sha256 FROM entry_images WHERE chat_id = ?)
            OR i.sha256 IN (SELECT sha256 FROM chat_images WHERE chat_id = ?)
            OR i.sha256 IN (SELECT v.sha256 FROM image_variants v JOIN chat_images c ON c.sha256 = v.source WHERE c.chat_id = ?)`, id, id, id))
          archive.run('INSERT INTO images VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', row.sha256, row.mime, row.bytes, row.created_at);
      });
      const directory = store.studyDirectory(id);
      const rebuilt = new Set(store.rebuildableFiles(id).map(path => relative(directory, path).split(sep).join('/')));   // references: in images
      for (const path of (await chatFiles(directory)).filter(path => !rebuilt.has(path))) {
        let bytes;
        if (path.endsWith('.sqlite')) {                    // the plugin's journal: a snapshot including its WAL
          const copy = join(tmpdir(), 'creative-journal-' + randomUUID() + '.sqlite');
          try { snapshot(join(directory, path), copy); bytes = await readFile(copy); } finally { await rm(copy, { force: true }); }
        } else bytes = await readFile(join(directory, path));
        archive.run('INSERT INTO files(chat_id, path, bytes) VALUES (?, ?, ?)', id, path, bytes);
      }
    }
    // One standalone file: no WAL side files to lose when it is copied.
    archive.exec('VACUUM'); archive.exec('PRAGMA journal_mode = DELETE');
  } finally { archive.close(); }
  for (const suffix of ['-wal', '-shm']) await rm(destination + suffix, { force: true });
  return { chats: chosen.length, bytes: (await stat(destination)).size };
}

/** Add an archive's chats to the store's project. Chats already present are skipped unless replace. */
export async function importArchive(store, source, { replace = false } = {}) {
  await store.initialize();
  const archive = openReadOnly(source);                 // the archive is never changed
  const report = { imported: [], skipped: [], replaced: [] };
  try {
    const format = Number(archive.get("SELECT value FROM meta WHERE key = 'format'")?.value);
    if (format !== ARCHIVE_FORMAT) throw new Error('This archive was made by a different Creative Agent version.');
    for (const chat of archive.all(`SELECT ${CHAT_COLUMNS} FROM chats ORDER BY id`)) {
      const existing = store.db.get('SELECT project_id FROM chats WHERE id = ?', chat.id);
      if (existing && !replace) { report.skipped.push(chat.id); continue; }
      if (existing) await store.delete(chat.id).catch(error => { throw new Error('Could not replace ' + chat.title + ': ' + error.message); });
      const directory = store.studyDirectory(chat.id);
      await rm(directory, { recursive: true, force: true });
      for (const file of /** @type {{path: string, bytes: Uint8Array}[]} */ (archive.all('SELECT path, bytes FROM files WHERE chat_id = ?', chat.id))) {
        const path = join(directory, ...file.path.split('/'));
        if (!path.startsWith(directory + sep)) throw new Error('The archive has a file outside its chat folder.');
        await mkdir(dirname(path), { recursive: true });
        await writeFile(path, file.bytes);
      }
      store.db.transaction(() => {
        store.db.run(`INSERT INTO chats(project_id, ${CHAT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          store.projectId, ...CHAT_COLUMNS.split(', ').map(column => chat[column]));
        for (const row of archive.all('SELECT key, created_at FROM sessions WHERE chat_id = ?', chat.id))
          store.db.run('INSERT INTO sessions(chat_id, key, created_at) VALUES (?, ?, ?)', chat.id, row.key, row.created_at);
        for (const row of archive.all('SELECT key, seq, entry FROM session_entries WHERE chat_id = ?', chat.id))
          store.db.run('INSERT INTO session_entries(chat_id, key, seq, entry) VALUES (?, ?, ?, ?)', chat.id, row.key, row.seq, row.entry);
        for (const row of archive.all('SELECT DISTINCT i.sha256, i.mime, i.bytes, i.created_at FROM images i JOIN entry_images e ON e.sha256 = i.sha256 WHERE e.chat_id = ?', chat.id))
          store.db.run('INSERT INTO images(sha256, mime, bytes, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', row.sha256, row.mime, row.bytes, row.created_at);
        for (const row of archive.all('SELECT key, seq, sha256 FROM entry_images WHERE chat_id = ?', chat.id))
          store.db.run('INSERT INTO entry_images(chat_id, key, seq, sha256) VALUES (?, ?, ?, ?)', chat.id, row.key, row.seq, row.sha256);
        const held = archive.all('SELECT role, sha256 FROM chat_images WHERE chat_id = ?', chat.id);
        for (const row of archive.all(`SELECT sha256, mime, bytes, created_at FROM images WHERE sha256 IN (SELECT sha256 FROM chat_images WHERE chat_id = ?)
            OR sha256 IN (SELECT v.sha256 FROM image_variants v JOIN chat_images c ON c.sha256 = v.source WHERE c.chat_id = ?)`, chat.id, chat.id))
          store.db.run('INSERT INTO images(sha256, mime, bytes, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', row.sha256, row.mime, row.bytes, row.created_at);
        for (const row of held) store.db.run('INSERT INTO chat_images(chat_id, role, sha256) VALUES (?, ?, ?) ON CONFLICT DO NOTHING', chat.id, row.role, row.sha256);
        for (const row of archive.all('SELECT source, kind, sha256 FROM image_variants WHERE source IN (SELECT sha256 FROM chat_images WHERE chat_id = ?)', chat.id))
          store.db.run('INSERT INTO image_variants(source, kind, sha256) VALUES (?, ?, ?) ON CONFLICT DO NOTHING', row.source, row.kind, row.sha256);
      });
      (existing ? report.replaced : report.imported).push(chat.id);
    }
  } finally { archive.close(); }
  return report;
}
