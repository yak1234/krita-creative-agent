## Purpose

The companion is type-checked against its own annotations and Pi's type definitions, so mistakes and Pi updates surface
as compiler errors before they reach an artist, while model input is still validated at runtime.

## ADDED Requirements

### Requirement: Every companion module is type-checked
Every module in `krita-creative-agent/src/` SHALL be checked by `tsc` in CI, with no build step required to run the
companion. A module SHALL NOT be held as `any` because another module is unchecked.

#### Scenario: A misspelled field
- **WHEN** code reads `params.colour` from a tool whose schema declares `color`
- **THEN** `tsc` fails

#### Scenario: Running from a checkout
- **WHEN** the companion starts from a development checkout
- **THEN** it runs its source files directly, with no compile step

### Requirement: Tool parameters come from their schemas
Each painter tool SHALL be declared through Pi's `defineTool()`, so the type of its `params` comes from its TypeBox
schema, with no separately written type.

#### Scenario: A schema change
- **WHEN** a field is removed from a tool's schema
- **THEN** every use of that field in the tool's `execute` fails the type check

### Requirement: Model input is validated at runtime
Arguments a model sends SHALL be checked against the tool's schema before anything paints, including each action of a
batch. Type checking SHALL NOT replace this validation.

#### Scenario: A batch with one invalid action
- **WHEN** a `paint_batch` contains an action whose arguments do not match its tool's schema
- **THEN** nothing is painted and the error names the action and the failing field

### Requirement: Runs end when they should after a Pi update
Stop, the turn limits and Agent mode's one move per message SHALL end a run through a mechanism Pi's current types
declare. A Pi update that removes or renames that mechanism SHALL fail the type check.

#### Scenario: Stop during a run
- **WHEN** the artist presses Stop while the painter is working
- **THEN** the run ends after the current step, and no further painting operation starts

### Requirement: Chats stay in the chat database
Chats SHALL be stored in the SQLite chat database across a Pi update. A test SHALL save, reopen and append to a chat
and confirm that no JSONL session file is written.

#### Scenario: Reopening a chat after an update
- **WHEN** a chat saved before a Pi update is reopened after it
- **THEN** its messages load from the database and new messages are appended there
