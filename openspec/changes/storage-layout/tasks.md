Test rule for every task: tests write only to temporary folders they remove, and run through `npm run test:unit` (JS) or `unittest discover` (Python). Tests point the store at temporary record and cache directories, never the real Application Support or Caches folders. Live checks use a disposable project and document and delete them afterwards, pass or fail. Live checks wait until no painting session is active in Krita.

## 1. Paths and database module (phase A)

- [x] 1.1 `src/storage-paths.mjs`: `storagePaths()` for macOS, Windows and Linux (records, cache), overridable through config for tests. Verify with unit tests.
- [x] 1.2 `src/db.mjs`: the only `node:sqlite` import. Provides open (WAL, `busy_timeout`, `foreign_keys`), exec/get/all/run, `transaction(fn)`, numbered migrations via `user_version`, refusal to write a newer schema, and an integrity check on open. ExperimentalWarning is filtered for SQLite only. Verify with unit tests, including that another warning still prints.
- [x] 1.3 Schema v1 (phase A): projects, chats (one JSON record per chat plus indexed summary columns), the `chat_search` FTS5 index kept by triggers, settings, the `storage_usage` view. Later phases add session_entries, images, image_uses and artifacts as migrations 2+. Verify with migration tests.

## 2. Record store (phase A)

- [x] 2.1 `ProjectStore` on `db.mjs`, keeping its current interface (initialize, serialize, persist, list, resolve, delete). `project.json` keeps only the id. Existing project-store tests pass unchanged where the behaviour is the same.
- [x] 2.2 Image store: put-by-hash, uses, and deletion with the chat in one transaction. References, `.model-references` copies and review images go through it. Verify with unit tests, including the 20-copies case.
  Verified against implementation commit `7d0166f`: `SessionStore` stores images by SHA-256, tracks reference uses and derived model variants, and collects unused images during transactional chat deletion. `tests/session-store.test.mjs` covers 20 copies stored once and deletion; `tests/project-store.test.mjs` covers cross-chat reference deduplication, byte-for-byte restoration, legacy import, and variant cleanup after the last chat is deleted. `npm run test:unit` passed (exit 0) during checklist verification.
- [x] 2.3 Stroke plans are rebuilt on resume and checked against `plan_hash` instead of being stored (done 2026-10-12, with `scripts/clean-records.mjs`).
- [x] 2.4 Chat search through FTS5; `list({query})` uses it. Delete chat (cascade, images with no other use) and the `storage_usage` view. Verify with unit tests.
- [x] 2.5 Chat working folders under `data/chats/<id>/`; installer writes `data_dir`, `cache_dir` and points `output` there; the old project `.creative-agent` becomes the migration source. Verify with installer tests.
- [x] 2.6 Migration (phase A part): move each chat folder, insert its record in one transaction, rewrite paths, resume after interruption, report broken chats; `scripts/unmigrate.mjs` reverses it. Verify against a fixture project, including an interrupted run.
- [x] 2.7 Live: migrate a **copy** of this machine's project (39 chats), open three chats and compare plan, history and painting link; then migrate the real project with Krita idle.

## 3. SDK session adapter (phase B)

- [x] 3.1 `src/session-store.mjs`: `SqliteSessionManager` on `SessionManager.inMemory`, overriding `_persist` and loading through the internal index rebuild. All non-public SDK members are named in one place.
- [x] 3.2 Contract test: round-trip a session with branches, a compaction and images. `buildSessionContext()` must be equal and images inline again. Fails on SDK shape change.
- [x] 3.3 `runtime.mjs` and `studio.mjs` create and open sessions through the adapter: the painter, review and preparation sessions. Existing studio tests pass.

- [x] 3.4 `scripts/recode-images.mjs`: stored PNG chat images over 100 KB re-encoded as JPEG through Krita (`jpeg_copy`; transparent images stay PNG), the PNG rows deleted and the database vacuumed. Verified on a clone first: 1,565 images, 1.39 → 0.49 GB, all 427 logs unchanged in entries and image count.

## 4. Plugin journal (phase C)

- [x] 4.1 `kritamcp/journal_store.py` (`sqlite3`, `synchronous=FULL`): operations (intent then receipt), passes, progress, selections and filter masks. The path comes from `begin`. Verify with unit tests using a temporary database.
- [x] 4.2 `creative_tools.py` keeps operations and passes in `<chat folder>/journal.sqlite` (one row per operation, only changed pass rows). Remaining: saved selections and filter masks are still small files in the chat folder, and `.progress.json` stays a file on purpose (a live status rewritten every few strokes; forcing each write to disk would slow painting).
- [x] 4.3 Crash test: an intent committed with no receipt reports uncertain through `operation_status` after the plugin restarts.
- [x] 4.4 `dev_reload` reloads `journal_store` with the other creative modules.

## 5. Previews (phase D)

- [x] 5.1 Previews are scratch, not a cache: the picture the model saw is already in the chat database. While a chat is open nothing is removed (pass review works); when it closes, and for every closed chat at start, only what its record points to (the chat-list thumbnail, review images) and the two newest views are kept. Old chats' pass review shows "No snapshot". No cache directory or cap is needed.

## 6. Migration of file contents (phases B–D)

- [x] 6.1 `src/migrate-folders.mjs`: per-chat transactional import of docs, artifacts, references and session JSONL (images de-duplicated), skipping previews and caches, resumable, with progress events. Verify against a fixture folder with an interrupted run and one broken chat.
- [x] 6.2 Journal import through a bridge operation (`import_journal`) from `.operations.json` and `.passes.json`. Verify with plugin unit tests.
- [x] 6.3 Chat logs (phase B) and plugin journals (phase C) are imported and their files removed only after they read back; previews are dropped (phase D).
- [x] 6.4 Live on clones of this machine's records before each real run: 42 chats moved in 6.6 s with no differences; 427 logs (4.0 GB) into 1.39 GB with identical context; 31 journals with matching counts.

## 7. Export and import (phase E)

- [x] 7.1 Export a chat or a project to a `.creative-agent-archive` file (`VACUUM INTO`, filtered), including journal rows. Import merges by id; replace is optional. Verify with a round-trip unit test.

## 8. Panel and tools (phase E)

- [x] 8.1 Panel: migration progress, Delete chat (with confirmation), a storage view (per chat and total), Export/Import chat, and the "no chats here; import an archive?" notice. Verify with `ui_smoke.py`. Needs a Krita restart.
- [x] 8.2 Diagnostics reports read the chat record, chat logs and the plugin journal from the databases; `creative_inspect_state` follows the config `output` (now the data folder); `evaluate-layer-need.mjs` reads the store. A report still attaches records rather than an archive.
- [x] 8.3 Installers write `data_dir`/`cache_dir` and point `output` at the data folder; the companion creates the folders on start. Uninstall leaves records.

## 9. Acceptance

- [ ] 9.1 Live: a 50-action Autopilot run in a new project writes only the `.kra` file and `project.json` into the project folder. Its records survive killing Krita mid-pass, and the action is reported uncertain, not repainted. The cache stays under its cap.
- [ ] 9.2 Measure against the 2026-10-12 baseline: project folder size, record size per chat (the 471 MB chat log case), and journal write time per action at 2,000 actions.
- [x] 9.3 Docs: README storage section (where data lives, export/import, removing old records).
  Verified by reading `krita-creative-agent/README.md`, "Where your data lives", from commit `7d0166f`: project and application-data paths, records and journals, reference restoration, migration/rollback, Delete/Export/Import, and idle-only cleanup/recode commands are documented. Live acceptance (9.1) and baseline measurements (9.2) remain unverified.
