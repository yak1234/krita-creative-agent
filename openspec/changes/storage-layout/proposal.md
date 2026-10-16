## Why

Everything the agent keeps lives in a hidden `.creative-agent/` folder inside the artist's project, as loose JSON, JSONL and PNG files. That works for one developer but not for a plugin many people install. Measured on 2026-10-12, after two weeks of use on one machine:

- **Size:** the folder reached **18 GB**. 13.8 GB were canvas previews (a 1 MB PNG before and after every action; one reference job alone left 3.5 GB). Chat logs were 2.8 GB, because the SDK stores every image inline as base64, and the same 11 MB reference was stored 20 times in one log.
- **Sync:** projects usually sit in `~/Documents`, which iCloud Drive syncs on many Macs, and Dropbox or Google Drive users keep projects in synced folders. Thousands of preview files and large files rewritten every few seconds turn into gigabytes of upload, conflicts and full disks the artist never asked for.
- **Crash safety:** the plugin's operation journal is what stops a crashed action from being painted twice. It is one JSON file rewritten in full twice per action, 97 MB in one run. A crash or full disk during that rewrite puts the recovery record itself at risk, and Krita did crash during a run that day.
- **No lifecycle:** nothing caps size. Previews were only pruned after the fact (shipped 2026-10-12). Formats have no schema version beyond the project manifest.
- **Two writers:** the Python plugin and the Node companion write related files in the same folder with no coordination beyond writing whole files.

## What Changes

- **Three storage tiers in their proper places.**
  - Artwork (`.kra`) stays in the project folder.
  - Records (chats, plans, run state, the operation journal) move to SQLite databases in `~/Library/Application Support/Creative Agent/`.
  - Previews and other caches move to `~/Library/Caches/Creative Agent/`, with a size cap.
- **The project folder keeps one small file.** `.creative-agent/project.json` holds the project id, so a moved or renamed project still finds its chats. Nothing else is written there.
- **The companion's records go into one SQLite database.**
  - Chats, goals, records, settings and the SDK's chat entries live in tables, under a schema version with migrations.
  - Each image is stored **once**, by content hash. Chat entries keep a short reference to it, and it is put back inline when a chat is opened.
- **The plugin's journal goes into its own SQLite database.**
  - Operation receipts, passes, saved selections and filter masks become rows.
  - Recording an action is one small transaction instead of a whole-file rewrite.
  - The two processes never write the same database.
- **The SDK keeps working unchanged.** A session manager adapter saves the Pi SDK's chat entries to SQLite instead of JSONL. A contract test pins the SDK internals it relies on.
- **Node's built-in `node:sqlite`.** It is still marked experimental in the bundled Node 22 runtime. That is accepted; its warning is filtered for this module only. The plugin uses Python's standard `sqlite3`.
- **Migration on first start.**
  - Existing `.creative-agent/` folders are moved one chat at a time (no copy, so no doubled disk use), can resume if interrupted, and a rollback script moves them back.
  - Later phases fold each chat folder's files into the databases, with images de-duplicated.
- **Export and import.** A chat or a whole project can be exported to one `.creative-agent-archive` file for moving to another machine. This replaces "copy the project folder" portability.

## Capabilities

### New Capabilities
- `agent-storage`: where artwork, records and caches live, the record databases and their schema, image de-duplication, the SDK session adapter, the plugin journal, the cache cap, migration from project folders, and export and import.

### Modified Capabilities
<!-- None in openspec/specs; earlier changes describe behaviour that this keeps, only its storage moves. -->

## Impact

- **Companion** (`krita-creative-agent/src/`):
  - `project-store.mjs` is rewritten on a new `db.mjs` (connection, migrations, the image store).
  - New `session-store.mjs` (the SDK adapter); `previews.mjs` becomes cache management.
  - `studio.mjs` and `runtime.mjs` read and write through the store. `diagnostics.mjs`, `live-diagnostics.mjs` and scripts that read study files read the database instead.
- **Plugin** (`plugin/kritamcp/`):
  - New `journal_store.py`.
  - `creative_tools.py` stores operations, passes and progress through it.
  - `region_craft.py` and `filters.py` store selections and masks as rows.
  - Previews are written to the cache directory the companion passes at `begin`.
- **Panel** (`creative_docker.py`): migration progress, Delete chat, a storage view, Export/Import chat. Needs a Krita restart.
- **MCP tools** (`creative_inspect_state`, `creative_collect_report`): read the new locations.
- **Installer:** creates the Application Support and Caches directories. Uninstall leaves records unless asked.
- **Non-goals:**
  - syncing chats between machines (export and import only);
  - storing `.kra` artwork in the database;
  - Windows and Linux directory layouts beyond using each platform's standard data and cache directories through one function;
  - a chat search UI (the schema allows it later).
