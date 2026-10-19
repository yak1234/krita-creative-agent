// @ts-check
// Chat logs in SQLite (storage-layout phase B). The Pi SDK's SessionManager keeps a session as a
// JSONL file; this adapter keeps the same entries as rows and every image once, by content hash.
// The session's "file" path stays its identity (chats/<id>/sessions/<name>.jsonl) but no file is
// written. The SDK is pinned (0.84.3); the members used here that are not public API are listed in
// SDK_INTERNALS and checked by tests/session-store.test.mjs.
import { createReadStream } from 'node:fs';
import { readdir, rm, stat } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { createHash } from 'node:crypto';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { SessionManager, migrateSessionEntries } from '@earendil-works/pi-coding-agent';

/** Non-public SessionManager members this adapter relies on (it overrides the first three). */
export const SDK_INTERNALS = ['_setSessionFile', '_rewriteFile', '_persist', 'fileEntries', 'flushed', '_buildIndex', 'newSession'];

/** Schema v2: sessions, their entries, images stored once and which entries use them. */
export function sessionSchema(db) {
  db.exec(`
    CREATE TABLE sessions (chat_id TEXT NOT NULL, key TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (chat_id, key)) STRICT;
    CREATE TABLE session_entries (chat_id TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL, entry TEXT NOT NULL,
      PRIMARY KEY (chat_id, key, seq), FOREIGN KEY (chat_id, key) REFERENCES sessions(chat_id, key) ON DELETE CASCADE) STRICT;
    CREATE TABLE images (sha256 TEXT PRIMARY KEY, mime TEXT NOT NULL, bytes BLOB NOT NULL, created_at TEXT NOT NULL) STRICT;
    CREATE TABLE entry_images (chat_id TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL, sha256 TEXT NOT NULL REFERENCES images(sha256),
      PRIMARY KEY (chat_id, key, seq, sha256), FOREIGN KEY (chat_id, key, seq) REFERENCES session_entries(chat_id, key, seq) ON DELETE CASCADE) STRICT;
    CREATE INDEX entry_images_by_image ON entry_images(sha256);
    DROP VIEW storage_usage;
    CREATE VIEW storage_usage AS SELECT c.id AS chat_id, c.project_id, c.title, length(c.record) AS record_bytes,
      (SELECT coalesce(sum(length(e.entry)), 0) FROM session_entries e WHERE e.chat_id = c.id) AS session_bytes,
      (SELECT coalesce(sum(length(i.bytes)), 0) FROM images i WHERE i.sha256 IN (SELECT sha256 FROM entry_images x WHERE x.chat_id = c.id)) AS image_bytes
      FROM chats c;
  `);
}

/** Schema v3: images a chat holds outside its log (references) and derived copies (variants). */
export function chatImageSchema(db) {
  db.exec(`
    CREATE TABLE chat_images (chat_id TEXT NOT NULL, role TEXT NOT NULL, sha256 TEXT NOT NULL REFERENCES images(sha256),
      PRIMARY KEY (chat_id, role, sha256)) STRICT;
    CREATE INDEX chat_images_by_image ON chat_images(sha256);
    CREATE TABLE image_variants (source TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT REFERENCES images(sha256),
      PRIMARY KEY (source, kind)) STRICT;
    DROP VIEW storage_usage;
    CREATE VIEW storage_usage AS SELECT c.id AS chat_id, c.project_id, c.title, length(c.record) AS record_bytes,
      (SELECT coalesce(sum(length(e.entry)), 0) FROM session_entries e WHERE e.chat_id = c.id) AS session_bytes,
      (SELECT coalesce(sum(length(i.bytes)), 0) FROM images i WHERE i.sha256 IN (SELECT sha256 FROM entry_images x WHERE x.chat_id = c.id)
        OR i.sha256 IN (SELECT sha256 FROM chat_images y WHERE y.chat_id = c.id)) AS image_bytes
      FROM chats c;
  `);
}

// Replace inline images with references, collecting the bytes; and the reverse.
function extractImages(value, found) {
  if (Array.isArray(value)) return value.map(item => extractImages(item, found));
  if (!value || typeof value !== 'object') return value;
  if (value.type === 'image' && typeof value.data === 'string') {
    const bytes = Buffer.from(value.data, 'base64'), sha256 = createHash('sha256').update(bytes).digest('hex');
    found.set(sha256, { mime: value.mimeType ?? 'application/octet-stream', bytes });
    const { data, ...rest } = value;
    return { ...rest, ref: sha256 };
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, extractImages(item, found)]));
}
function restoreImages(value, image) {
  if (Array.isArray(value)) return value.map(item => restoreImages(item, image));
  if (!value || typeof value !== 'object') return value;
  if (value.type === 'image' && typeof value.ref === 'string' && value.data === undefined) {
    const { ref, ...rest } = value;
    return { ...rest, data: image(ref) };
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, restoreImages(item, image)]));
}

export class SessionStore {
  constructor(db, chatsDirectory) { this.db = db; this.chatsDirectory = resolve(chatsDirectory); }
  /** chats/<chat>/<key> -> {chat, key}; null for a path outside the chat folders. */
  locate(path) {
    const part = relative(this.chatsDirectory, resolve(path)).split(sep);
    if (part.length < 2 || part[0] === '..') return null;
    return { chat: part[0], key: part.slice(1).join('/') };
  }
  has({ chat, key }) { return !!this.db.get('SELECT 1 AS found FROM sessions WHERE chat_id = ? AND key = ?', chat, key); }
  count({ chat, key }) { return this.db.get('SELECT count(*) AS n FROM session_entries WHERE chat_id = ? AND key = ?', chat, key).n; }
  /** Session keys of a chat under a folder ("sessions/", "reviews/"), oldest first. */
  keys(chat, folder = '') {
    return this.db.all('SELECT key FROM sessions WHERE chat_id = ? AND key LIKE ? ORDER BY key', chat, folder + '%').map(row => row.key);
  }
  write(where, seq, entry) {
    const found = new Map(), stored = extractImages(entry, found), now = new Date().toISOString();
    this.db.run('INSERT INTO sessions(chat_id, key, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING', where.chat, where.key, now);
    for (const [sha256, { mime, bytes }] of found)
      this.db.run('INSERT INTO images(sha256, mime, bytes, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', sha256, mime, bytes, now);
    this.db.run('INSERT INTO session_entries(chat_id, key, seq, entry) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id, key, seq) DO UPDATE SET entry = excluded.entry',
      where.chat, where.key, seq, JSON.stringify(stored));
    this.db.run('DELETE FROM entry_images WHERE chat_id = ? AND key = ? AND seq = ?', where.chat, where.key, seq);
    for (const sha256 of found.keys())
      this.db.run('INSERT INTO entry_images(chat_id, key, seq, sha256) VALUES (?, ?, ?, ?)', where.chat, where.key, seq, sha256);
  }
  append(where, seq, entry) { this.db.transaction(() => this.write(where, seq, entry)); }
  replace(where, entries) {
    this.db.transaction(() => {
      this.db.run('DELETE FROM session_entries WHERE chat_id = ? AND key = ?', where.chat, where.key);
      entries.forEach((entry, seq) => this.write(where, seq, entry));
      if (!entries.length) this.db.run('INSERT INTO sessions(chat_id, key, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING', where.chat, where.key, new Date().toISOString());
    });
  }
  load(where) {
    const cache = new Map();
    const image = sha256 => {
      if (!cache.has(sha256)) cache.set(sha256, Buffer.from(this.db.get('SELECT bytes FROM images WHERE sha256 = ?', sha256)?.bytes ?? []).toString('base64'));
      return cache.get(sha256);
    };
    return this.db.all('SELECT entry FROM session_entries WHERE chat_id = ? AND key = ? ORDER BY seq', where.chat, where.key)
      .map(row => restoreImages(JSON.parse(row.entry), image));
  }
  /** Entries as stored (images as references), for diagnostics. */
  stored(where) { return this.db.all('SELECT entry FROM session_entries WHERE chat_id = ? AND key = ? ORDER BY seq', where.chat, where.key).map(row => JSON.parse(row.entry)); }
  /** Stored PNG images larger than minBytes, largest first: candidates for a JPEG copy. */
  pngImages(minBytes = 100 * 1024) {
    // Only chat-log images: references must keep their exact pixels (the reference painter samples them).
    return this.db.all(`SELECT sha256, length(bytes) AS size FROM images WHERE mime = 'image/png' AND length(bytes) > ?
      AND sha256 NOT IN (SELECT sha256 FROM chat_images) AND sha256 NOT IN (SELECT sha256 FROM image_variants WHERE sha256 IS NOT NULL)
      ORDER BY size DESC`, minBytes);
  }
  imageBytes(sha256) { return Buffer.from(this.db.get('SELECT bytes FROM images WHERE sha256 = ?', sha256).bytes); }
  /** Replace an image with a smaller encoding in one transaction: the new row, every entry that
   *  points to it, and the old row deleted. Returns the bytes saved. */
  replaceImage(oldSha, bytes, mime) {
    const newSha = createHash('sha256').update(bytes).digest('hex');
    if (newSha === oldSha) return 0;
    return this.db.transaction(() => {
      const before = this.db.get('SELECT length(bytes) AS n FROM images WHERE sha256 = ?', oldSha)?.n;
      if (before === undefined) return 0;
      this.db.run('INSERT INTO images(sha256, mime, bytes, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', newSha, mime, bytes, new Date().toISOString());
      const swap = value => {
        if (Array.isArray(value)) return value.map(swap);
        if (!value || typeof value !== 'object') return value;
        if (value.type === 'image' && value.ref === oldSha) return { ...value, ref: newSha, mimeType: mime };
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, swap(item)]));
      };
      for (const use of this.db.all('SELECT chat_id, key, seq FROM entry_images WHERE sha256 = ?', oldSha)) {
        const row = this.db.get('SELECT entry FROM session_entries WHERE chat_id = ? AND key = ? AND seq = ?', use.chat_id, use.key, use.seq);
        this.db.run('UPDATE session_entries SET entry = ? WHERE chat_id = ? AND key = ? AND seq = ?', JSON.stringify(swap(JSON.parse(row.entry))), use.chat_id, use.key, use.seq);
        this.db.run('INSERT INTO entry_images(chat_id, key, seq, sha256) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', use.chat_id, use.key, use.seq, newSha);
      }
      this.db.run('DELETE FROM entry_images WHERE sha256 = ?', oldSha);
      this.db.run('DELETE FROM images WHERE sha256 = ?', oldSha);
      return before - bytes.length;
    });
  }
  /** Delete a chat's sessions and held images, then any image nothing uses any more. */
  deleteChat(chat) {
    this.db.transaction(() => {
      this.db.run('DELETE FROM sessions WHERE chat_id = ?', chat);
      this.db.run('DELETE FROM chat_images WHERE chat_id = ?', chat);
      this.collectImages();
    });
  }
  /** Remove images no log entry or chat uses, and variants of them. */
  collectImages() {
    const used = 'SELECT sha256 FROM entry_images UNION SELECT sha256 FROM chat_images';
    this.db.run(`DELETE FROM image_variants WHERE source NOT IN (${used})`);
    this.db.run(`DELETE FROM images WHERE sha256 NOT IN (${used}) AND sha256 NOT IN (SELECT sha256 FROM image_variants WHERE sha256 IS NOT NULL)`);
  }
  /** Store bytes once; returns their SHA-256. */
  putImage(bytes, mime) {
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    this.db.run('INSERT INTO images(sha256, mime, bytes, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING', sha256, mime, bytes, new Date().toISOString());
    return sha256;
  }
  hasImage(sha256) { return !!this.db.get('SELECT 1 AS found FROM images WHERE sha256 = ?', sha256); }
  /** The images a chat holds in a role (e.g. its references) become exactly these. */
  holdImages(chat, role, shas) {
    this.db.transaction(() => {
      this.db.run('DELETE FROM chat_images WHERE chat_id = ? AND role = ?', chat, role);
      for (const sha256 of new Set(shas)) this.db.run('INSERT INTO chat_images(chat_id, role, sha256) VALUES (?, ?, ?)', chat, role, sha256);
    });
  }
  /** A derived copy of an image: undefined = not made yet, null = the original serves, else {bytes, mime}. */
  variant(source, kind) {
    const row = this.db.get('SELECT v.sha256, i.mime, i.bytes FROM image_variants v LEFT JOIN images i ON i.sha256 = v.sha256 WHERE v.source = ? AND v.kind = ?', source, kind);
    if (!row) return undefined;
    return row.sha256 ? { bytes: Buffer.from(row.bytes), mime: row.mime } : null;
  }
  putVariant(source, kind, bytes, mime) {
    this.db.transaction(() => {
      const sha256 = bytes ? this.putImage(bytes, mime) : null;
      this.db.run('INSERT INTO image_variants(source, kind, sha256) VALUES (?, ?, ?) ON CONFLICT(source, kind) DO UPDATE SET sha256 = excluded.sha256', source, kind, sha256);
    });
  }
  /** SessionManager factory with the SDK's create/open shape, storing in this database. */
  managers() {
    const store = this;
    // Overrides SessionManager's private storage (_setSessionFile, _persist, _rewriteFile and the
    // fields they use), which Pi's .d.ts hides, so the base is untyped here. Check these internals
    // whenever Pi is updated: a renamed one would silently send chats back to JSONL files.
    const Base = /** @type {new (...args: any[]) => any} */ (/** @type {unknown} */ (SessionManager));
    class DbSessionManager extends Base {
      _setSessionFile(sessionFile) {
        this.sessionFile = resolve(sessionFile);
        const where = store.locate(this.sessionFile);
        if (!where) throw new Error('A chat log must live in a chat folder: ' + this.sessionFile);
        if (!store.has(where)) {                              // a new session at an explicit path
          const path = this.sessionFile; this.newSession(); this.sessionFile = path; return;
        }
        this.fileEntries = store.load(where);
        const header = this.fileEntries.find(entry => entry.type === 'session');
        this.sessionId = header?.id ?? this.sessionId;
        const version = header?.version;
        migrateSessionEntries(this.fileEntries);
        if (header?.version !== version) store.replace(where, this.fileEntries);
        this._buildIndex();
        this.flushed = true;
      }
      _rewriteFile() {
        if (!this.persist || !this.sessionFile) return;
        store.replace(store.locate(this.sessionFile), this.fileEntries);
      }
      // As the SDK does: nothing is stored until the model has replied once.
      _persist(entry) {
        if (!this.persist || !this.sessionFile) return;
        const where = store.locate(this.sessionFile);
        if (!this.fileEntries.some(e => e.type === 'message' && e.message.role === 'assistant')) {
          if (this.flushed) store.append(where, this.fileEntries.length - 1, entry);
          return;
        }
        if (!this.flushed) { store.replace(where, this.fileEntries); this.flushed = true; }
        else store.append(where, this.fileEntries.length - 1, entry);
      }
      createBranchedSession() { throw new Error('Branching chats is not supported by the chat database.'); }
    }
    return {
      create: (cwd, sessionDir) => new DbSessionManager(cwd, sessionDir, undefined, true),
      open: (sessionFile, sessionDir, cwd) => new DbSessionManager(cwd ?? dirname(dirname(sessionFile)), sessionDir ?? dirname(sessionFile), sessionFile, true),
    };
  }
  /**
   * Import a chat's JSONL logs (sessions/, reviews/, preparations/) into the database and delete
   * each file once its entries read back. Streams lines, so a 500 MB log is fine. Resumable.
   */
  async importChat(chat) {
    const report = { files: 0, entries: 0, bytes: 0, errors: [] };
    for (const folder of ['sessions', 'reviews', 'preparations']) {
      const directory = join(this.chatsDirectory, chat, folder);
      for (const name of (await readdir(directory).catch(() => [])).filter(name => name.endsWith('.jsonl')).sort()) {
        const path = join(directory, name), where = { chat, key: folder + '/' + name };
        try {
          const entries = [];
          const lines = createInterface({ input: createReadStream(path, 'utf8'), crlfDelay: Infinity });
          for await (const line of lines) { if (!line.trim()) continue; try { entries.push(JSON.parse(line)); } catch { /* a torn last line */ } }
          if (!entries.length) { await rm(path); continue; }
          migrateSessionEntries(entries);
          if (this.has(where) && this.count(where) !== entries.length) throw new Error('Already imported with a different number of entries; the file was kept.');
          if (!this.has(where)) this.replace(where, entries);
          if (this.count(where) !== entries.length) throw new Error('The imported entries did not read back; the file was kept.');
          report.bytes += (await stat(path)).size;
          await rm(path);
          report.files++; report.entries += entries.length;
        } catch (error) { report.errors.push({ chat, file: folder + '/' + name, error: error.message }); }
      }
    }
    return report;
  }
}
