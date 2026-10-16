// The companion's only SQLite module. Node's built-in node:sqlite is still marked experimental in
// the bundled Node 22 runtime; that is accepted (storage-layout design 7), and only its warning is
// silenced. Everything else uses this small interface, so an API change touches one file.
const original = process.emitWarning;
process.emitWarning = (warning, ...rest) => {
  if (String(warning?.message ?? warning).includes('SQLite is an experimental')) return;
  return original.call(process, warning, ...rest);
};
const { DatabaseSync } = await import('node:sqlite');
process.emitWarning = original;

/**
 * Open a database: WAL, foreign keys, a busy timeout, numbered migrations through user_version and
 * a quick integrity check. `migrations[i]` brings the schema from version i to i + 1.
 */
export function openDatabase(path, { migrations = [], synchronous = 'NORMAL' } = {}) {
  const db = new DatabaseSync(path);
  db.exec(`PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000; PRAGMA synchronous = ${synchronous};`);
  const check = db.prepare('PRAGMA quick_check').get();
  if (check?.quick_check !== 'ok') { db.close(); throw Object.assign(new Error('The agent records database is damaged: ' + check?.quick_check), { code: 'DB_CORRUPT' }); }
  const version = db.prepare('PRAGMA user_version').get().user_version;
  if (version > migrations.length) {
    db.close();
    throw Object.assign(new Error('These agent records were written by a newer Creative Agent. Update the agent to open them.'), { code: 'DB_NEWER' });
  }
  const statements = new Map();
  const prepare = sql => { let statement = statements.get(sql); if (!statement) statements.set(sql, statement = db.prepare(sql)); return statement; };
  let depth = 0;
  const api = {
    path,
    get: (sql, ...params) => prepare(sql).get(...params),
    all: (sql, ...params) => prepare(sql).all(...params),
    run: (sql, ...params) => prepare(sql).run(...params),
    exec: sql => db.exec(sql),
    /** Run fn in one transaction (nested calls join the outer one); returns fn's result. */
    transaction(fn) {
      if (depth) return fn();
      db.exec('BEGIN IMMEDIATE'); depth++;
      try { const result = fn(); depth--; db.exec('COMMIT'); return result; }
      catch (error) { depth--; try { db.exec('ROLLBACK'); } catch {} throw error; }
    },
    /** A consistent copy of the whole database in one file. */
    backup(destination) { db.prepare('VACUUM INTO ?').run(destination); },
    close() { statements.clear(); db.close(); },
  };
  for (let index = version; index < migrations.length; index++) {
    api.transaction(() => { migrations[index](api); db.exec(`PRAGMA user_version = ${index + 1}`); });
  }
  return api;
}

/** Rows from a database another process owns (the plugin's journal), opened read-only; [] if absent. */
export function readRows(path, sql, ...params) {
  let db;
  try { db = new DatabaseSync(path, { readOnly: true }); }
  catch { return []; }
  try { return db.prepare(sql).all(...params); }
  catch { return []; }
  finally { db.close(); }
}

/** A database opened read-only (an archive being imported): get/all/close, nothing is written. */
export function openReadOnly(path) {
  const db = new DatabaseSync(path, { readOnly: true });
  return { get: (sql, ...params) => db.prepare(sql).get(...params), all: (sql, ...params) => db.prepare(sql).all(...params), close: () => db.close() };
}

/** A consistent single-file copy of a database another process may be writing (WAL included). */
export function snapshot(path, destination) {
  const db = new DatabaseSync(path, { readOnly: true });
  try { db.prepare('VACUUM INTO ?').run(destination); } finally { db.close(); }
}
