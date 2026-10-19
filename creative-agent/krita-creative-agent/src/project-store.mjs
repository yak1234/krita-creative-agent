// @ts-check
/** Agent records for one project, in SQLite. Artwork is never moved, opened, or saved here.
 *
 * The project folder holds only `.creative-agent/project.json` (its id). Records live in the data
 * directory: `records.sqlite` (every project's chats) and `chats/<id>/`, each chat's working folder
 * for what is still a file (SDK log, reviews, the plugin journal, previews). By default the data
 * directory is the project's `.creative-agent` (development and tests); the installer points it at
 * the platform's application-data directory (storage-layout design 1 and 3).
 */
import { access, copyFile, cp, mkdir, readFile, readdir, realpath, rename, rm, rmdir, stat, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { openDatabase, readRows } from './db.mjs';
import { SessionStore, sessionSchema, chatImageSchema } from './session-store.mjs';
import { imageInfo } from './files.mjs';

const SCHEMA = 1;
const ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const PATH_KEYS = new Set(['path', 'image', 'image_path', 'last_image', 'before_path', 'after_path', 'thumbnail', 'thumbnail_path', 'session_file', 'painting_path', 'checkpoint']);
// App files that used to live in the project's .creative-agent: moved to the data directory, or
// removed when they are rebuilt anyway. Anything else there (scripts' output) is left alone.
const APP_FILES = ['model-connections.json', 'execution-settings.json', 'decision-endpoints.json', 'model-catalog.json',
  'active-session.json', 'last-migration.json', 'diagnostic-events.jsonl', 'diagnostic-events.jsonl.previous', 'capabilities', 'diagnostics', 'recovery'];
const REBUILT_FILES = ['previews', 'diagnostics-endpoint.json'];
// A relative path as records store it: always "/" so a chat saved on Windows opens on macOS and Linux
// (and is moved between machines by archives). Node resolves "/" on Windows too.
const stored = (from, to) => relative(from, to).split(sep).join('/');
const within = (root, file) => { const part = relative(root, file); return part !== '..' && !part.startsWith('..' + sep) && !isAbsolute(part); };
const exists = async file => { try { await access(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; } };
const readJson = async file => JSON.parse(await readFile(file, 'utf8'));
async function atomicJson(file, value) {
  const temporary = file + '.' + randomUUID() + '.tmp';
  try { await writeFile(temporary, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 }); await rename(temporary, file); }
  finally { await rm(temporary, { force: true }); }
}
function mapPaths(value, transform, key = '') {
  if (Array.isArray(value)) return value.map(item => mapPaths(item, transform));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([name]) => name !== 'source_path')
    .map(([name, item]) => [name, mapPaths(item, transform, name)]));
  return typeof value === 'string' && PATH_KEYS.has(key) && value ? transform(value) : value;
}
const CHAT = 'chat:';
// FTS5 query for a search box: every word must match as a word prefix.
const ftsQuery = text => text.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean).map(word => '"' + word.replaceAll('"', '""') + '"*').join(' ');

const MIGRATIONS = [
  db => db.exec(`
    CREATE TABLE projects (id TEXT PRIMARY KEY, root TEXT NOT NULL, created_at TEXT NOT NULL, last_opened_at TEXT NOT NULL) STRICT;
    CREATE TABLE chats (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      title TEXT NOT NULL DEFAULT '', painting_file TEXT, status TEXT NOT NULL DEFAULT 'draft', mode TEXT NOT NULL DEFAULT 'ask',
      thumbnail TEXT, search_text TEXT NOT NULL DEFAULT '',
      record TEXT NOT NULL CHECK (json_valid(record)),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
    CREATE INDEX chats_by_project ON chats(project_id, updated_at DESC);
    CREATE INDEX chats_by_painting ON chats(project_id, painting_file);
    CREATE VIRTUAL TABLE chat_search USING fts5(title, search_text, content='chats', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER chats_search_insert AFTER INSERT ON chats BEGIN
      INSERT INTO chat_search(rowid, title, search_text) VALUES (new.rowid, new.title, new.search_text); END;
    CREATE TRIGGER chats_search_delete AFTER DELETE ON chats BEGIN
      INSERT INTO chat_search(chat_search, rowid, title, search_text) VALUES ('delete', old.rowid, old.title, old.search_text); END;
    CREATE TRIGGER chats_search_update AFTER UPDATE OF title, search_text ON chats BEGIN
      INSERT INTO chat_search(chat_search, rowid, title, search_text) VALUES ('delete', old.rowid, old.title, old.search_text);
      INSERT INTO chat_search(rowid, title, search_text) VALUES (new.rowid, new.title, new.search_text); END;
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL CHECK (json_valid(value))) STRICT;
    CREATE VIEW storage_usage AS SELECT id AS chat_id, project_id, title, length(record) AS record_bytes FROM chats;
  `),
  sessionSchema,                                        // v2: chat logs and images (phase B)
  chatImageSchema,                                      // v3: references and derived copies as images
];

export class ProjectStore {
  constructor({ projectRoot, stateDir = '.creative-agent', dataDirectory, legacyRoots = [] }) {
    if (!projectRoot) throw new Error('Choose a project folder.');
    this.projectRoot = resolve(projectRoot);
    this.projectStateDirectory = resolve(this.projectRoot, stateDir);
    if (!within(this.projectRoot, this.projectStateDirectory) || this.projectStateDirectory === this.projectRoot)
      throw new Error('Agent records must use a separate folder inside the project.');
    // App files (settings, model connections, decision endpoints) live with the records.
    this.stateDirectory = resolve(dataDirectory ?? this.projectStateDirectory);
    this.chatsDirectory = join(this.stateDirectory, 'chats');
    this.studiesDirectory = this.chatsDirectory;               // the name earlier modules use
    this.oldStudiesDirectory = join(this.projectStateDirectory, 'studies');
    this.legacyRoots = [...new Set(legacyRoots.map(root => resolve(root)))];
    /** @type {Promise<unknown>} */
    this.writeQueue = Promise.resolve();
  }
  studyDirectory(id) {
    if (!ID.test(id)) throw new Error('Invalid conversation identifier.');
    return join(this.chatsDirectory, id);
  }
  allocateDirectory(id) { return this.studyDirectory(id); }
  async initialize() {
    if (this.initialized) return this.initialized;
    return this.initialized = (async () => {
      await mkdir(this.projectStateDirectory, { recursive: true });
      await mkdir(this.chatsDirectory, { recursive: true });
      const manifest = join(this.projectStateDirectory, 'project.json');
      if (!await exists(manifest)) await atomicJson(manifest, { version: SCHEMA, id: randomUUID(), created_at: new Date().toISOString() });
      const info = await readJson(manifest);
      if (info.version !== SCHEMA) throw new Error('This project needs a compatible Creative Agent version.');
      this.projectId = info.id;
      this.db = openDatabase(join(this.stateDirectory, 'records.sqlite'), { migrations: MIGRATIONS });
      this.sessions = new SessionStore(this.db, this.chatsDirectory);
      const now = new Date().toISOString();
      this.db.run(`INSERT INTO projects(id, root, created_at, last_opened_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET root = excluded.root, last_opened_at = excluded.last_opened_at`, info.id, this.projectRoot, info.created_at ?? now, now);
      if (this.stateDirectory !== this.projectStateDirectory) await this.moveAppFiles();
      return info;
    })().catch(error => { this.initialized = null; throw error; });
  }
  close() { this.db?.close(); this.db = null; this.initialized = null; }
  async moveAppFiles() {
    for (const name of APP_FILES) {
      const from = join(this.projectStateDirectory, name), to = join(this.stateDirectory, name);
      if (await exists(from) && !await exists(to)) await moveFolder(from, to);
    }
    for (const name of REBUILT_FILES) await rm(join(this.projectStateDirectory, name), { recursive: true, force: true });
    // A companion lock whose process is gone (a live one stays: that companion still runs).
    const lock = join(this.projectStateDirectory, 'companion.lock');
    try { process.kill(JSON.parse(await readFile(lock, 'utf8')).pid, 0); }
    catch (error) { if (error.code === 'ESRCH' || error instanceof SyntaxError) await rm(lock, { force: true }); }
  }
  async checkDirectory(id) {
    const directory = this.studyDirectory(id);
    await mkdir(directory, { recursive: true });
    if (!within(await realpath(this.chatsDirectory), await realpath(directory)))
      throw new Error('Conversation records point outside the agent records.');
    return directory;
  }
  // Paths in a record: inside the chat folder as `chat:<relative>`, inside the project as
  // project-relative (so a moved project keeps working), anything else absolute.
  encoder(id) {
    const chat = this.studyDirectory(id);
    return path => {
      const absolute = resolve(this.projectRoot, path);
      if (within(chat, absolute)) return CHAT + stored(chat, absolute);
      if (within(this.projectRoot, absolute)) return stored(this.projectRoot, absolute);
      return absolute;
    };
  }
  decoder(id) {
    const chat = this.studyDirectory(id);
    return path => path.startsWith(CHAT) ? join(chat, path.slice(CHAT.length)) : resolve(this.projectRoot, path);
  }
  serialize(study, goal) {
    const encode = this.encoder(study.id);
    const saved = mapPaths(study, encode);
    delete saved.directory;
    if (study.painting_file) saved.painting_file = stored(this.projectRoot, resolve(this.projectRoot, study.painting_file));
    saved.path_schema = 'chat-relative-v2';
    return { version: SCHEMA, updated_at: new Date().toISOString(), study: saved, goal: mapPaths(goal ?? null, encode) };
  }
  async createStudy(study, goal = null) {
    await this.initialize();
    if (this.db.get('SELECT 1 AS found FROM chats WHERE id = ?', study.id)) throw new Error('This conversation already exists.');
    return this.saveStudy(study, goal);
  }
  async saveStudy(study, goal = null) {
    const record = this.serialize(structuredClone(study), structuredClone(goal));
    const task = this.writeQueue.catch(() => {}).then(async () => {
      await this.initialize();
      const directory = await this.checkDirectory(study.id);
      await this.storeReferences(record, study);
      this.db.transaction(() => { this.write(record); this.holdReferences(record); });
      return this.hydrate(record, directory);
    });
    this.writeQueue = task;
    return task;
  }
  write(record) {
    const { study, goal } = record;
    const decode = this.decoder(study.id);
    const thumbnail = study.thumbnail || study.thumbnail_path || study.last_image || goal?.context?.snapshot?.image_path || null;
    const title = study.name || goal?.brief?.title || 'Untitled painting';
    const search = [study.painting_file ? basename(study.painting_file) : '', goal?.brief?.objective ?? '',
      ...(goal?.locked_requirements ?? []).map(r => typeof r === 'string' ? r : JSON.stringify(r))].join(' ');
    const status = ['active', 'reviewing'].includes(goal?.status) ? 'paused' : goal?.status ?? 'draft';
    this.db.run(`INSERT INTO chats(id, project_id, title, painting_file, status, mode, thumbnail, search_text, record, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET title = excluded.title, painting_file = excluded.painting_file, status = excluded.status,
        mode = excluded.mode, thumbnail = excluded.thumbnail, search_text = excluded.search_text, record = excluded.record, updated_at = excluded.updated_at`,
      study.id, this.projectId, title, study.painting_file ?? null, status, goal?.mode ?? 'ask', thumbnail ? decode(thumbnail) : null, search,
      JSON.stringify(record), record.updated_at, record.updated_at);
  }
  // References live in the images table (each once, across chats); the file in the chat folder is
  // a copy recreated on open (storage-layout 2.2). A new reference is stored the first time it is saved.
  async storeReferences(record, study) {
    const decode = this.decoder(record.study.id);
    for (const [index, reference] of (record.study.references ?? []).entries()) {
      if (reference.sha256 && this.sessions.hasImage(reference.sha256)) continue;
      let bytes;
      try { bytes = await readFile(decode(reference.path)); } catch { continue; }
      let mime = 'application/octet-stream'; try { mime = imageInfo(bytes).mimeType; } catch {}
      reference.sha256 = this.sessions.putImage(bytes, mime);
      if (study?.references?.[index]) study.references[index].sha256 = reference.sha256;
    }
  }
  holdReferences(record) {
    this.sessions.holdImages(record.study.id, 'reference', (record.study.references ?? []).map(r => r.sha256).filter(Boolean));
  }
  /** Recreate reference files a chat folder no longer has, from the images table. */
  async restoreReferences(study) {
    for (const reference of study.references ?? []) {
      if (!reference.sha256 || !reference.path || await exists(reference.path) || !this.sessions.hasImage(reference.sha256)) continue;
      if (!within(this.studyDirectory(study.id), reference.path)) continue;
      await mkdir(dirname(reference.path), { recursive: true });
      await writeFile(reference.path, this.sessions.imageBytes(reference.sha256));
    }
  }
  /** Files of a chat that the database can recreate (its stored references), for cleanup when closed. */
  rebuildableFiles(id) {
    let record; try { record = JSON.parse(this.recordText(id)); } catch { return []; }
    const decode = this.decoder(id);
    return (record.study?.references ?? []).filter(r => r.sha256 && r.path && this.sessions.hasImage(r.sha256))
      .map(r => decode(r.path)).filter(path => within(this.studyDirectory(id), path));
  }
  /** Reference copies in a chat folder that its record no longer lists (a removed reference), plus
   *  the rebuildable ones: everything cleanup may delete when the chat is closed. */
  async removableFiles(id) {
    let record; try { record = JSON.parse(this.recordText(id)); } catch { return []; }
    const decode = this.decoder(id), listed = new Set((record.study?.references ?? []).map(r => r.path && decode(r.path)));
    const orphans = (await readdir(this.studyDirectory(id)).catch(() => []))
      .filter(name => /^reference-[0-9a-f-]{36}\.(png|jpe?g|gif)$/i.test(name)).map(name => join(this.studyDirectory(id), name)).filter(path => !listed.has(path));
    return [...this.rebuildableFiles(id), ...orphans];
  }
  /** Store every chat's references in the images table (chats from before storage-layout 2.2). */
  async importReferences() {
    await this.initialize();
    let stored = 0;
    for (const { id, record: text } of this.db.all('SELECT id, record FROM chats WHERE project_id = ?', this.projectId)) {
      const record = JSON.parse(text);
      const missing = (record.study.references ?? []).filter(r => !r.sha256);
      if (!missing.length && this.db.get('SELECT 1 AS found FROM chat_images WHERE chat_id = ?', id)) continue;
      await this.storeReferences(record);
      this.db.transaction(() => { this.write(record); this.holdReferences(record); });   // keeps updated_at
      stored += missing.filter(r => r.sha256).length;
    }
    return stored;
  }
  resolvePainting(study) {
    return study.painting_file ? resolve(this.projectRoot, study.painting_file) : null;
  }
  async hydrate(record, directory) {
    if (record.version !== SCHEMA) throw new Error('This conversation needs a compatible Creative Agent version.');
    const decode = this.decoder(record.study.id);
    const study = mapPaths(record.study, decode);
    study.directory = directory;
    // Keep the ordinary artwork link relative; tool boundaries resolve it.
    study.painting_file = record.study.painting_file;
    await this.restoreReferences(study);
    const goal = mapPaths(record.goal, decode);
    const paintingPath = this.resolvePainting(study);
    return { study, goal, directory, paintingPath, missingPainting: !!paintingPath && !await exists(paintingPath), updated_at: record.updated_at };
  }
  /** The stored record text of a chat (for tools that look for file references in it). */
  recordText(id) { return this.db?.get('SELECT record FROM chats WHERE id = ?', id)?.record ?? ''; }
  async load(id) {
    await this.initialize();
    const directory = this.studyDirectory(id);
    const row = this.db.get('SELECT project_id, record FROM chats WHERE id = ?', id);
    if (row) {
      if (row.project_id !== this.projectId) throw new Error('This conversation belongs to another project. Open that project to continue it.');
      return this.hydrate(JSON.parse(row.record), directory);
    }
    if (await exists(join(this.oldStudiesDirectory, id, 'record.json')) || await exists(join(directory, 'record.json'))) {
      const report = await this.migrateProjectFolder({ id });
      if (report.errors.length) throw new Error(report.errors[0].error);
      return this.load(id);
    }
    for (const root of this.legacyRoots) {
      if (await exists(join(root, id, 'study.json'))) {
        const report = await this.migrateLegacy(root, { id });
        if (report.errors.length) throw new Error(report.errors[0].error);
        return this.load(id);
      }
    }
    throw Object.assign(new Error('Conversation not found. Locate its project folder.'), { code: 'ENOENT' });
  }
  async list({ query = '' } = {}) {
    await this.initialize();
    const match = ftsQuery(query);
    const rows = match
      ? this.db.all(`SELECT c.id, c.title, c.painting_file, c.status, c.mode, c.thumbnail, c.updated_at FROM chat_search s
          JOIN chats c ON c.rowid = s.rowid WHERE chat_search MATCH ? AND c.project_id = ? ORDER BY c.updated_at DESC`, match, this.projectId)
      : this.db.all('SELECT id, title, painting_file, status, mode, thumbnail, updated_at FROM chats WHERE project_id = ? ORDER BY updated_at DESC', this.projectId);
    const items = [];
    for (const row of rows) {
      const paintingPath = row.painting_file ? resolve(this.projectRoot, row.painting_file) : null;
      const missing = !!paintingPath && !await exists(paintingPath);
      items.push({ id: row.id, title: row.title, filename: paintingPath ? basename(paintingPath) : null, painting_path: paintingPath,
        updated_at: row.updated_at, status: missing ? 'needs_relink' : row.status, thumbnail: row.thumbnail,
        missing_painting: missing, mode: row.mode });
    }
    return items;
  }
  async relink(id, paintingPath) {
    if (extname(paintingPath).toLowerCase() !== '.kra') throw new Error('Choose the existing Krita painting (.kra).');
    const actual = await realpath(paintingPath);
    if (!(await stat(actual)).isFile()) throw new Error('Choose an existing painting file.');
    const record = await this.load(id);
    const previous = record.study.painting_file ?? null;
    record.study.painting_file = stored(await realpath(this.projectRoot), actual);
    record.study.bound = false;
    record.study.binding_started = false;
    record.study.relinks = [...(record.study.relinks ?? []), { previous, current: record.study.painting_file, at: new Date().toISOString() }];
    if (record.goal && ['active','reviewing'].includes(record.goal.status)) record.goal.status = 'paused';
    return this.saveStudy(record.study, record.goal);
  }
  async findByPainting(paintingPath) {
    await this.initialize();
    const actual = await realpath(paintingPath);
    for (const row of this.db.all('SELECT id, painting_file FROM chats WHERE project_id = ? AND painting_file IS NOT NULL ORDER BY updated_at DESC', this.projectId)) {
      try { if (await realpath(resolve(this.projectRoot, row.painting_file)) === actual) return this.load(row.id); } catch { /* An external move can race with listing. */ }
    }
    return null;
  }
  /** Delete a chat: its record and its working folder. Its artwork is never touched. */
  async delete(id) {
    await this.initialize();
    const row = this.db.get('SELECT project_id FROM chats WHERE id = ?', id);
    if (!row) throw Object.assign(new Error('Conversation not found.'), { code: 'ENOENT' });
    if (row.project_id !== this.projectId) throw new Error('This conversation belongs to another project.');
    this.db.transaction(() => { this.sessions.deleteChat(id); this.db.run('DELETE FROM chats WHERE id = ?', id); });
    await rm(this.studyDirectory(id), { recursive: true, force: true });
  }
  /** Bytes per chat of this project: its record and its working folder. */
  async storageUsage() {
    await this.initialize();
    const size = async path => {
      let total = 0;
      for (const entry of await readdir(path, { withFileTypes: true }).catch(() => [])) {
        const child = join(path, entry.name);
        if (entry.isDirectory()) total += await size(child);
        else if (entry.isFile()) total += (await stat(child).catch(() => ({ size: 0 }))).size;
      }
      return total;
    };
    const chats = [];
    for (const row of this.db.all('SELECT * FROM storage_usage WHERE project_id = ?', this.projectId))
      chats.push({ id: row.chat_id, title: row.title, record_bytes: row.record_bytes, session_bytes: row.session_bytes, image_bytes: row.image_bytes,
        folder_bytes: await size(this.studyDirectory(row.chat_id)) });
    const total = chat => chat.record_bytes + chat.session_bytes + chat.image_bytes + chat.folder_bytes;
    chats.sort((a, b) => total(b) - total(a));
    // Images shared by several chats count once in the total.
    const images = this.db.get(`SELECT coalesce(sum(length(bytes)), 0) AS n FROM images WHERE sha256 IN
      (SELECT sha256 FROM entry_images x JOIN chats c ON c.id = x.chat_id WHERE c.project_id = ?)`, this.projectId).n;
    return { chats, total_bytes: chats.reduce((sum, chat) => sum + total(chat) - chat.image_bytes, 0) + images };
  }
  /** This project's chats that still keep the plugin journal as JSON files (before phase C). */
  async chatsWithJsonJournal() {
    await this.initialize();
    const found = [];
    for (const { id } of this.db.all('SELECT id FROM chats WHERE project_id = ? ORDER BY id', this.projectId))
      if (await exists(join(this.studyDirectory(id), '.operations.json')) || await exists(join(this.studyDirectory(id), '.passes.json'))) found.push(id);
    return found;
  }
  /** Import every chat's JSONL logs into the database (phase B); see SessionStore.importChat. */
  async importSessionLogs({ onProgress } = /** @type {{onProgress?: (...progress: any[]) => void}} */ ({})) {
    await this.initialize();
    const totals = { chats: 0, files: 0, entries: 0, bytes: 0, errors: [] };
    const chats = this.db.all('SELECT id FROM chats WHERE project_id = ? ORDER BY id', this.projectId).map(row => row.id);
    let done = 0;
    for (const chat of chats) {
      const result = await this.sessions.importChat(chat);
      if (result.files) totals.chats++;
      totals.files += result.files; totals.entries += result.entries; totals.bytes += result.bytes; totals.errors.push(...result.errors);
      onProgress?.(++done, chats.length, chat);
    }
    return totals;
  }
  /**
   * Move chats from the project's `.creative-agent/studies/` (records before storage-layout) into
   * the data directory: each chat's folder is moved, not copied, then its record is inserted in one
   * transaction. Resumable: a folder that moved before an interruption still carries its
   * record.json. Artwork never moves. `onProgress(done, total, id)` reports each chat.
   */
  async migrateProjectFolder({ id, onProgress } = /** @type {{id?: string, onProgress?: (...progress: any[]) => void}} */ ({})) {
    await this.initialize();
    const report = { imported: [], skipped: [], errors: [] };
    const pending = new Set();
    for (const entry of await readdir(this.oldStudiesDirectory, { withFileTypes: true }).catch(() => []))
      if (entry.isDirectory() && ID.test(entry.name)) pending.add(entry.name);
    // Folders already moved whose record was not yet inserted.
    for (const entry of await readdir(this.chatsDirectory, { withFileTypes: true }).catch(() => []))
      if (entry.isDirectory() && ID.test(entry.name) && await exists(join(this.chatsDirectory, entry.name, 'record.json'))) pending.add(entry.name);
    const ids = [...pending].filter(name => !id || name === id).sort();
    let done = 0;
    for (const identifier of ids) {
      const source = join(this.oldStudiesDirectory, identifier), destination = this.studyDirectory(identifier);
      try {
        if (this.db.get('SELECT 1 AS found FROM chats WHERE id = ?', identifier)) {
          if (await exists(source)) throw new Error('A chat with this id already exists in the agent records; its project copy was left in place.');
          report.skipped.push(identifier); continue;
        }
        if (await exists(source) && !(await readdir(source)).length) {     // an empty folder: nothing to keep
          await rmdir(source); report.skipped.push(identifier); onProgress?.(++done, ids.length, identifier); continue;
        }
        if (await exists(source)) {
          if (!within(await realpath(this.projectStateDirectory), await realpath(source))) throw new Error('Conversation folder points outside its project.');
          if (!await exists(join(source, 'record.json'))) throw new Error('This conversation has no record.json; it was left in place.');
          await readJson(join(source, 'record.json'));                 // unreadable records stay where they are
          if (await exists(destination)) throw new Error('A partial copy exists in the agent records; preserve it and inspect before retrying.');
          await moveFolder(source, destination);
        }
        // The plugin's journal holds paths relative to the chat folder (the painting is
        // '../../painting.kra' from the old place); rewrite them once for the new place.
        if (!await exists(join(destination, '.paths-moved'))) {
          await migrateNativePaths(source, destination, destination);
          await writeFile(join(destination, '.paths-moved'), '');
        }
        const record = await readJson(join(destination, 'record.json'));
        if (record.version !== SCHEMA) throw new Error('This conversation needs a compatible Creative Agent version.');
        // Old records were project-relative; paths into the old chat folder now point at its new home.
        const remap = path => {
          const absolute = resolve(this.projectRoot, path);
          return within(source, absolute) ? join(destination, relative(source, absolute)) : absolute;
        };
        const study = mapPaths(record.study, remap); study.id = identifier;
        const goal = mapPaths(record.goal, remap);
        this.write({ ...this.serialize(study, goal), updated_at: record.updated_at ?? new Date().toISOString() });
        for (const name of ['record.json', 'study.json', 'goal.json', '.paths-moved']) await rm(join(destination, name), { force: true });
        report.imported.push(identifier);
      } catch (error) { report.errors.push({ id: identifier, error: error.message }); }
      onProgress?.(++done, ids.length, identifier);
    }
    if (!id && !report.errors.length) {
      await rmdir(this.oldStudiesDirectory).catch(() => {});      // only when empty
      if (report.imported.length) {
        const manifest = join(this.projectStateDirectory, 'project.json');
        await atomicJson(manifest, { ...await readJson(manifest), migrated_at: new Date().toISOString() });
      }
    }
    return report;
  }
  /** Rollback for migrateProjectFolder: move this project's chats back into its
   *  `.creative-agent/studies/` with a project-relative record.json, as earlier builds read them. */
  async unmigrateProjectFolder() {
    await this.initialize();
    const report = { restored: [], errors: [] };
    for (const { id } of this.db.all('SELECT id FROM chats WHERE project_id = ? ORDER BY id', this.projectId)) {
      const source = this.studyDirectory(id), destination = join(this.oldStudiesDirectory, id);
      try {
        const record = JSON.parse(this.recordText(id));
        if (await exists(destination)) throw new Error('The project already has a folder for this chat.');
        const decode = this.decoder(id);
        const encode = path => {
          const absolute = decode(path);
          return stored(this.projectRoot, within(source, absolute) ? join(destination, relative(source, absolute)) : absolute);
        };
        const study = mapPaths(record.study, encode);
        study.directory = stored(this.projectRoot, destination); study.path_schema = 'project-relative-v1';
        await mkdir(source, { recursive: true });
        // The plugin's journal database back to the JSON files earlier builds read.
        const journal = join(source, 'journal.sqlite');
        if (await exists(journal)) {
          const operations = readRows(journal, 'SELECT operation_id, fingerprint, receipt FROM operations');
          await atomicJson(join(source, '.operations.json'), Object.fromEntries(operations.map(r => [r.operation_id, [r.fingerprint, JSON.parse(r.receipt)]])));
          await atomicJson(join(source, '.passes.json'), readRows(journal, 'SELECT entry FROM passes ORDER BY seq').map(r => JSON.parse(r.entry)));
          for (const suffix of ['', '-wal', '-shm']) await rm(journal + suffix, { force: true });
        }
        await migrateNativePaths(source, destination, source);
        // Chat logs back to the JSONL files earlier builds read.
        for (const key of this.sessions.keys(id)) {
          await mkdir(dirname(join(source, key)), { recursive: true });
          await writeFile(join(source, key), this.sessions.load({ chat: id, key }).map(entry => JSON.stringify(entry)).join('\n') + '\n');
        }
        this.sessions.deleteChat(id);
        await atomicJson(join(source, 'record.json'), { version: SCHEMA, updated_at: record.updated_at, study, goal: mapPaths(record.goal, encode) });
        await moveFolder(source, destination);
        this.db.run('DELETE FROM chats WHERE id = ?', id);
        report.restored.push(id);
      } catch (error) { report.errors.push({ id, error: error.message }); }
    }
    const manifest = join(this.projectStateDirectory, 'project.json'), info = await readJson(manifest);
    delete info.migrated_at; await atomicJson(manifest, info);
    return report;
  }
  async migrateLegacy(root, { id } = /** @type {{id?: string}} */ ({})) {
    await this.initialize();
    root = resolve(root);
    if (!this.legacyRoots.includes(root)) this.legacyRoots.push(root);
    if (root === this.chatsDirectory || root === this.stateDirectory || root === this.projectStateDirectory || !await exists(root)) return { imported: [], skipped: [], errors: [] };
    const report = { imported: [], skipped: [], errors: [] };
    const ids = id ? [id] : (await readdir(root, { withFileTypes: true })).filter(e => e.isDirectory() && ID.test(e.name)).map(e => e.name);
    for (const identifier of ids) {
      const destination = this.studyDirectory(identifier), source = join(root, identifier);
      if (this.db.get('SELECT 1 AS found FROM chats WHERE id = ?', identifier)) { report.skipped.push(identifier); continue; }
      try {
        if (!within(await realpath(root), await realpath(source))) throw new Error('Legacy conversation is outside its project.');
        const study = await readJson(join(source, 'study.json'));
        let goal = null;
        try { goal = await readJson(join(source, 'goal.json')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
        const staging = join(this.stateDirectory, 'migration-' + randomUUID());
        try {
          await copyRecords(source, staging);
          await migrateNativePaths(source, destination, staging);
          const remap = path => {
            const absolute = resolve(source, path);
            return within(source, absolute) ? join(destination, relative(source, absolute)) : absolute;
          };
          const migrated = mapPaths(study, remap);
          migrated.id = identifier; migrated.directory = destination;
          // Legacy painting_file was rooted at the configured artwork folder;
          // an absent field meant painting.kra in that legacy study directory.
          const legacyPainting = join(source, 'painting.kra');
          if (study.painting_file) migrated.painting_file = stored(this.projectRoot, resolve(this.projectRoot, study.painting_file));
          else if (await exists(legacyPainting) || study.bound || study.binding_started)
            migrated.painting_file = stored(this.projectRoot, legacyPainting);
          else delete migrated.painting_file;
          migrated.migrated_from = stored(this.projectRoot, source);
          migrated.bound = false; migrated.binding_started = false;
          const migratedGoal = mapPaths(goal, remap);
          if (migratedGoal && ['active','reviewing'].includes(migratedGoal.status)) migratedGoal.status = 'paused';
          if (await exists(destination)) throw new Error('Partial migration exists; preserve it and inspect before retrying.');
          await rename(staging, destination);
          await this.saveStudy(migrated, migratedGoal);
          report.imported.push(identifier);
        } finally { await rm(staging, { recursive: true, force: true }); }
      } catch (error) { report.errors.push({ id: identifier, error: error.message }); }
    }
    await atomicJson(join(this.stateDirectory, 'last-migration.json'), { at: new Date().toISOString(), source: root, ...report });
    return report;
  }
}

// A rename on one volume; copy then delete across volumes (EXDEV).
async function moveFolder(source, destination) {
  await mkdir(dirname(destination), { recursive: true });
  try { await rename(source, destination); }
  catch (error) {
    if (error.code !== 'EXDEV') throw error;
    await cp(source, destination, { recursive: true, errorOnExist: true, force: false });
    await rm(source, { recursive: true, force: true });
  }
}

async function migrateNativePaths(source, destination, staging) {
  const keys = new Set(['path', 'image_path', 'before_path', 'after_path', 'checkpoint', 'filename']);
  const remap = (value, key = '') => {
    if (Array.isArray(value)) return value.map(item => remap(item));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, remap(item, name)]));
    if (typeof value !== 'string' || !value || !keys.has(key)) return value;
    const original = resolve(source, value);
    // Preview/session records move; artwork is deliberately left in place.
    const relocated = within(source, original) && !/\.kra(?:~|\..*)?$/i.test(original)
      ? join(destination, relative(source, original)) : original;
    return stored(destination, relocated);
  };
  for (const name of ['.operations.json', '.passes.json']) {
    const file = join(staging, name);
    if (await exists(file)) await atomicJson(file, remap(await readJson(file)));
  }
}

async function copyRecords(source, destination) {
  await mkdir(destination, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    // Artwork, backups and live locks remain exactly where they are. Symlinks
    // are excluded so importing state cannot copy outside the chosen folder.
    if (entry.isSymbolicLink() || /\.kra(?:~|\..*)?$/i.test(entry.name) || ['companion.lock','active-session.json'].includes(entry.name)) continue;
    const from = join(source, entry.name), to = join(destination, entry.name);
    if (entry.isDirectory()) await copyRecords(from, to);
    else if (entry.isFile()) await copyFile(from, to);
  }
}
