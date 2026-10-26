## ADDED Requirements

### Requirement: Storage locations
The companion SHALL keep artwork, records and caches in three places:
- artwork (`.kra`) in the project folder;
- records in the platform's application-data directory (`~/Library/Application Support/Creative Agent/` on macOS);
- caches, if any, in the platform's cache directory (`~/Library/Caches/Creative Agent/` on macOS).

The only agent file in a project folder SHALL be `.creative-agent/project.json`, which holds the project id. One function SHALL resolve these paths. The plugin SHALL use the record and cache paths given to it at `begin` and SHALL NOT choose its own.

#### Scenario: Painting writes nothing else into the project
- **WHEN** an Autopilot run of 50 actions finishes in a new project
- **THEN** the project folder holds the `.kra` file and `.creative-agent/project.json` and nothing else from the agent

#### Scenario: Moving a project keeps its chats
- **WHEN** the artist moves the project folder and opens it from the new place
- **THEN** its chats are listed, found by the id in `project.json`

### Requirement: Record database
The companion SHALL store projects, chats, chat documents (study, goal, record, resume), artifacts (reviews, preparations, recipes, reference-painting jobs) and settings in one SQLite database (`records.sqlite`) in WAL mode. The schema version SHALL be stored in the database, and the companion SHALL apply numbered migrations on open. A database newer than the companion understands SHALL NOT be opened for writing. Each document change and each chat deletion SHALL be one transaction.

#### Scenario: Crash during a write
- **WHEN** the companion is killed while saving a goal
- **THEN** on restart the goal is either the previous version or the new one, never a partial document

#### Scenario: Newer database
- **WHEN** the database's schema version is higher than the companion's
- **THEN** the companion refuses to write, and the panel asks the artist to update the agent

#### Scenario: Searching chats
- **WHEN** the artist types "kremlin" in the chat list's search box with 500 chats stored
- **THEN** matching chats come from the full-text index without loading every chat's record

#### Scenario: Deleting a chat
- **WHEN** the artist deletes a chat and confirms
- **THEN** its rows, its working folder and images no other chat uses are removed, its artwork is untouched, and the storage view no longer counts it

### Requirement: Images stored once
Image bytes in records (references, reduced model copies, review images, images inside chat entries) SHALL be stored once in an `images` table keyed by SHA-256, with each use recorded. Chat entries SHALL hold a reference in place of inline image data. Deleting a chat SHALL delete images no other chat uses, in the same transaction.

#### Scenario: A reference attached many times
- **WHEN** the same 8 MB reference appears in 20 chat messages
- **THEN** its bytes are stored once, and the database grows by its size once

#### Scenario: Deleting a chat
- **WHEN** a chat whose reference is also used by another chat is deleted
- **THEN** that reference stays, and images only that chat used are removed

### Requirement: SDK chat storage
A session manager adapter SHALL store the Pi SDK's chat entries in `records.sqlite` instead of JSONL files, writing each entry in one transaction as the SDK persists it. Opening a chat SHALL rebuild the same session context the SDK would build from the equivalent JSONL. The adapter SHALL name every non-public SDK member it uses in one module. A contract test SHALL round-trip a session with branches, a compaction and images, and fail if the result differs.

#### Scenario: Resume after restart
- **WHEN** a chat with 200 entries, one compaction and 30 images is reopened after a companion restart
- **THEN** `buildSessionContext()` equals the context before the restart, with the images inline again

#### Scenario: SDK upgrade changes internals
- **WHEN** the SDK version is changed and the internals the adapter uses differ
- **THEN** the contract test fails before release

### Requirement: Plugin operation journal
The plugin SHALL store operation intents and receipts, passes, progress, saved selections and filter masks in its own SQLite database (`journal.sqlite`) with `synchronous=FULL`. Before the first change of an action it SHALL commit an intent row. After the action it SHALL replace that row with the receipt in one transaction. Receipts SHALL NOT contain the layer list or pass history. Only the plugin SHALL write this database; the companion SHALL read it only through bridge operations.

#### Scenario: Krita crashes mid-action
- **WHEN** Krita exits during a paint pass after its intent was committed
- **THEN** after restart, `operation_status` reports that action as uncertain, and it is never painted again without inspection

#### Scenario: Journal cost does not grow with history
- **WHEN** a session has 2,000 recorded actions
- **THEN** recording the next action writes one row, not the whole history

### Requirement: Previews are scratch
Canvas previews SHALL never be required for correctness: a missing preview SHALL show "No snapshot" in pass review. While a chat is open its previews SHALL be kept. When a chat closes, and for every closed chat at companion start, the companion SHALL delete its previews except those its record points to and the two newest.

#### Scenario: Closing a long chat
- **WHEN** a chat with 1,700 previews is closed
- **THEN** only its thumbnail, any review image and the two newest previews remain

#### Scenario: Old pass without a preview
- **WHEN** the artist opens pass review on a pass whose preview was removed
- **THEN** the dialog shows "No snapshot", and the pass can still be hidden, faded or rejected

### Requirement: Experimental SQLite module accepted
The companion SHALL use Node's built-in `node:sqlite` through a single module that exposes open, exec, get, all, run and transaction. The bundled Node runtime version SHALL stay pinned. The companion SHALL suppress Node's ExperimentalWarning for SQLite only. Other warnings SHALL still be shown.

#### Scenario: Starting the companion
- **WHEN** the companion starts on the bundled runtime
- **THEN** no SQLite ExperimentalWarning is printed, and other Node warnings still are

### Requirement: Migration from project folders
On start, the companion SHALL import each project's existing `.creative-agent/studies/` records into the databases, one chat per transaction:
- chat documents, artifacts, reference images and session entries go into `records.sqlite`, with images de-duplicated;
- operation and pass journals go into `journal.sqlite` through the plugin;
- previews and other cache files are not imported.

The import SHALL move each chat's folder to the data directory instead of copying it, show progress in the panel, skip chats already imported, and resume after an interruption. After every chat imports and is read back successfully, it SHALL record `migrated_at` in `project.json`. Artwork SHALL never move. A chat that fails to import SHALL be listed with its error and left in place. A rollback script SHALL move chats back so an earlier build can read them.

#### Scenario: Interrupted migration
- **WHEN** Krita quits while chat 12 of 38 is being imported
- **THEN** on the next start, chats 1–11 are skipped, chat 12 is imported from the start, and no chat appears twice

#### Scenario: One broken chat
- **WHEN** one chat's record file is unreadable
- **THEN** the other chats move, the broken one stays in the project folder and is listed with its error, and `migrated_at` is not set

#### Scenario: Rollback
- **WHEN** an older build is needed after migration
- **THEN** the rollback script moves every chat back into the project folder with its `record.json`, and the older build lists them

### Requirement: Export and import
The panel SHALL export one chat or a whole project to a single `.creative-agent-archive` file containing its records, the images they use and its journal rows. Importing an archive SHALL add its chats by id, skip chats already present unless the artist chooses to replace them, and keep the archive unchanged.

#### Scenario: Moving to another machine
- **WHEN** the artist exports a project, copies the archive and the project folder to another Mac, and imports the archive there
- **THEN** opening the project lists its chats, and a chat resumes with its plan, history and references
