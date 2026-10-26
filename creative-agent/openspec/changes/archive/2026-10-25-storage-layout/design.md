## Context

Today `ProjectStore` puts all agent state under `<project>/.creative-agent/`:
- **Project:** `project.json`, `execution-settings.json`, `active-session.json`.
- **Per chat** (`studies/<id>/`):
  - companion files: `study.json`, `goal.json`, `record.json`, `resume.json`, `sessions/*.jsonl` (the Pi SDK's chat log), `reviews/`, `preparations/`, `recipes/`, `reference-paintings/`, `.model-references/`, attached `reference-*.png`;
  - plugin files: `.previews/`, `.operations.json`, `.passes.json`, `.progress.json`, `.selections/`, `.filter-masks/`.

The store refuses any state directory outside the project. That was a deliberate choice so a project folder carried its chats. The Pi SDK (`@earendil-works/pi-coding-agent` 0.84.3, pinned) owns the chat log through `SessionManager`, which writes JSONL with `appendFileSync`/`writeFileSync`. Its `_persist(entry)` method is public in the typings.

The bundled runtime is Node 22.23.2, where `node:sqlite` (`DatabaseSync`) works but is marked experimental. Krita's Python has the standard `sqlite3`.

## Goals / Non-Goals

**Goals:**
- Nothing large or frequently rewritten in the artist's project folder.
- Records that survive crashes: every journal write is a transaction.
- Images stored once; disk use bounded for caches.
- The SDK used unchanged, with its internals pinned by a test.
- Existing users keep their chats.

**Non-Goals:**
- Sync between machines.
- Artwork in the database.
- A history or search UI.
- A server or other external database.

## Decisions

### 1. Three tiers, each in its standard place
| Tier | Contents | Location (macOS) | Loss is |
|---|---|---|---|
| Artwork | `.kra` | project folder | the artist's work |
| Records | chats, plans, run state, journal, references, app files (model connections, settings, lock, diagnostics) | `~/Library/Application Support/Creative Agent/data/` | lost history |
| Cache | previews, reduced model images | `~/Library/Caches/Creative Agent/` | nothing (rebuilt or "No snapshot") |

Each chat keeps a working folder, `data/chats/<id>/`, for what is still a file while the phases land (the SDK log until phase B, the plugin journal until phase C, previews until phase D). The installer writes `data_dir` and `cache_dir` into the companion config and points `output` at `data_dir`, so every app file the companion already writes under `output` moves with it. One function, `storagePaths()`, returns these for the platform (`%APPDATA%`/`%LOCALAPPDATA%`, `$XDG_DATA_HOME`/`$XDG_CACHE_HOME`). The companion passes the paths to the plugin at `begin`; the plugin never chooses them. Application Support is not synced by iCloud Drive, and the Caches directory is excluded from Time Machine.

Alternative: one SQLite file inside the project. Rejected because a database open in WAL mode inside a synced folder can be corrupted when the main file and its `-wal`/`-shm` files sync separately, and the folder would still grow.

### 2. Project identity instead of location
`<project>/.creative-agent/project.json` stays (under 1 KB) and holds the project `id`. Records are keyed by that id, so moving or renaming a project folder keeps its chats. A project copied to another machine without an export opens with no chats, and the panel says so and offers Import.

### 3. Companion database: `records.sqlite`
One database per user, holding every project. One connection, WAL, `busy_timeout` 5 s, `foreign_keys` on, `synchronous=NORMAL` (WAL makes committed transactions durable against an app crash; FULL is used for the journal, see 5). Tables (schema version in `PRAGMA user_version`, numbered migrations in `db.mjs`):
- `projects(id, root, name, created_at, last_opened_at)`
- `chats(id, project_id, name, mode, status, created_at, updated_at, painting_path)`
- `chat_docs(chat_id, kind, json, updated_at)`. `kind` is study, goal, record or resume. Each is replaced whole: these are small documents written by today's code paths unchanged.
- `session_entries(chat_id, seq, entry_id, parent_id, type, json)`, with primary key `(chat_id, seq)`.
- `images(sha256 PRIMARY KEY, mime, width, height, bytes BLOB, created_at)`
- `image_uses(sha256, chat_id, role)`. `role` is reference, model-reference, review or entry; used for deletion.
- `artifacts(chat_id, kind, key, json)` for reviews, preparations, recipes and reference-painting jobs. Stroke plans are not stored: since 2026-10-12 a resumed job rebuilds its plan from the recipe, the reference and the canvas size and checks it against `plan_hash` (all 27 stored plans on this machine rebuilt identically).
- `chat_search` (FTS5, external content on `chats` plus brief text): the chat list's search box queries it instead of loading every record.
- `settings(key, json)`

Ordinary app practice applies: indexes on every foreign key and on `chats(project_id, updated_at)`, `ON DELETE CASCADE` from chats to their rows, prepared statements cached per connection, `STRICT` tables, `updated_at` maintained by triggers, and a `storage_usage` view (bytes per chat: records, images, working folder, cache) for the panel's storage view. Chat deletion is one transaction. Images with no remaining `image_uses` are removed in the same transaction.

### 4. SDK session adapter
`SqliteSessionManager` wraps `SessionManager.inMemory(cwd)`:
- **Writing:** it overrides `_persist(entry)`. Image content (`{type:'image', data, mimeType}`) is replaced by `{type:'image', ref:'sha256:…', mimeType}` after the bytes are inserted into `images`. The entry is then inserted into `session_entries` in one transaction.
- **Opening a chat:** entries are read in `seq` order, image refs are put back inline, and the manager's entries are rebuilt through the same path `SessionManager.open` uses (`parseSessionEntries`, then the internal index rebuild).
- **Contract test:** the parts that are not public API (internal entry list and index rebuild) are named in one file. A test fails if SDK 0.84.3's shape changes: round-trip a session with branches, a compaction and images, and compare `buildSessionContext()` before and after.

Alternative: keep JSONL and move images out of the file when a chat ends. Simpler, but it leaves two record systems, loose files and no transactions.

### 5. Plugin journal: `journal.sqlite`
Owned by the plugin and written only by it. One per chat, `<chat folder>/journal.sqlite`, so it moves and deletes with its chat. `synchronous=FULL`, because this is the record that prevents a repainted action. Tables:
- `operations(session_id, operation_id, fingerprint, status, receipt_json, updated_at)`: an intent row is inserted before the first mutation and replaced by the receipt after it. Each is one transaction.
- `passes(session_id, id, seq, layer_id, stage_id, json)`: a pass record is an insert, and review changes are updates.
- `progress(session_id, json)`, `selections(session_id, name, mask BLOB, json)`, `filter_masks(session_id, layer_id, mask BLOB)`.

Receipts never contain the layer list or pass history. That trimming already shipped on 2026-10-12, and replay re-reads both. The companion keeps reading the journal only through the bridge (`operation_status`, `observe`), so the two databases never share a writer.

### 6. Previews are scratch
Every canvas observation writes a picture to the chat folder. The one sent to the model is also stored in the chat database (phase B), so after the action the file is a second copy; pass review needs them only while the chat is open. While a chat is open nothing is removed. When it closes, and for every closed chat at companion start, only the previews its record points to (the chat-list thumbnail, review images) and the two newest are kept. This replaced the planned capped cache: on this machine it removed the remaining 1.5 GB without losing anything a chat needs.

### 7. Experimental `node:sqlite`
Accepted. `db.mjs` is the only module that imports it, behind a small interface (`open`, `exec`, `get`, `all`, `run`, `transaction`), so an API change touches one file. The bundled runtime version is pinned. The ExperimentalWarning is filtered for the `SQLite` category only, through `process.on('warning')`. Other warnings still print.

### 8. Migration from project folders
On companion start, for each known project with a `.creative-agent/studies/` folder and no `migrated_at` in `project.json`:
1. Each chat's folder is **moved** (a rename on the same volume; copy-then-delete otherwise) to `data/chats/<id>/`, and its record is inserted in **one transaction**. Paths in the record are rewritten relative to the chat folder. Later phases fold the folder's files into the databases (session entries and images in phase B, journal in phase C, previews to the cache in phase D). Moving instead of copying avoids doubling 5+ GB on disk.
2. **Progress** is shown in the panel ("Moving chat 12 of 38…"). A chat already present (same id and entry count) is skipped, so an interrupted import resumes.
3. **After every chat imports and re-reads cleanly**, `project.json` gets `migrated_at` and the emptied `studies/` folder is removed. Nothing the artist made is deleted: artwork never moves, and every chat's files are in `data/chats/`.
4. **Rollback**: `scripts/unmigrate.mjs` moves chat folders back into the project and restores `record.json` from the database.

A chat that fails to import is listed with its error and left in place. The others still move.

### 9. Export and import
- **Export:** a chat or a project is written to one `.creative-agent-archive` file, a SQLite database built with `VACUUM INTO` and filtered to those chats and the images they use, plus the plugin journal rows.
- **Import:** merges by id. A chat already present is skipped unless the artist chooses to replace it.

### 10. Readers of files
- **Diagnostics:** `creative_inspect_state`, `creative_collect_report`, `diagnostics.mjs`, `live-diagnostics.mjs` and `scripts/evaluate-layer-need.mjs` read through the store. `collect_report` exports the chat as an archive instead of copying files.
- **Langfuse tracing:** unchanged.

## Risks / Trade-offs

- **SDK internals change on upgrade** → the adapter names them in one file, and the contract test fails before release. Upgrades are deliberate because the version is pinned.
- **`node:sqlite` changes or has a bug** → it sits behind one module and a pinned runtime. If it fails, the fallback is the `better-sqlite3` native module with the same interface; that adds a native build per platform.
- **Long first migration on large folders (18 GB)** → only records move, and previews (about 75%) are skipped. It runs per chat with progress, can resume, and the panel stays usable.
- **Loss of "copy the folder" portability** → `project.json` id plus export and import. The panel explains it when a project opens with no chats.
- **Lost or corrupted database file** → WAL plus transactions. A daily `VACUUM INTO records.backup.sqlite` keeps one backup at companion start. An integrity check runs on open, and the panel offers restoring the backup.
- **One database for every project** → it is keyed by project id; a busy project does not lock others because writes are short transactions.

## Migration Plan

1. Ship the store behind the existing `ProjectStore` interface: new chats go to SQLite while migration is off, so the JSONL path still works for existing chats.
2. Turn migration on after live checks on a copy of a real project folder (this machine's 38 chats).
3. Release with the rollback script and the storage view available.
4. **Rollback:** `scripts/unmigrate.mjs` moves the chat folders back and writes their `record.json` files, so a previous build sees them again. Chats created after migration are included.

## Phases

Each phase ships working and is live-checked before the next:
- **A. Records and locations:** paths, `db.mjs`, schema, the record store on SQLite (chats, documents, search, settings, delete, storage view), chat folders and app files moved out of the project, migration and rollback.
- **B. Chat logs:** the SDK adapter, session entries and de-duplicated images in SQLite; existing JSONL imported.
- **C. Plugin journal:** `journal.sqlite`; existing journals imported.
- **D. Previews:** deleted when a chat closes, except what its record points to.
- **E. Export/import and panel:** archives, Delete chat, storage view, migration progress.

## Open Questions

- Whether reference images should keep a copy in the project folder for artists who want them next to the artwork. Proposed: no; Export covers it.
- Default cache cap: 2 GB is proposed; a panel setting could come later.
