## Purpose

Gives the painter reusable Agent Skills, the way Pi itself has them: workflow know-how that loads only when a task needs it, a `/skill:name` command for the artist, and sandboxed scripts the skills can run. The first skill turns generated or edited images into assets the painter repaints with native strokes.

## ADDED Requirements

### Requirement: Bundled skills load the way Pi loads skills
The companion SHALL bundle Agent Skills in `krita-creative-agent/skills/<name>/SKILL.md`, in the Agent Skills format (frontmatter `name` and `description`). It SHALL pass them to Pi as additional skill paths, with Pi's own discovery off, so no user or project skills load.

While the painter's `read` tool is active, Pi SHALL list the bundled skills in the system prompt. That tool SHALL open only files inside the skills folder; real paths outside it, including through `..` or symlinks, SHALL be refused.

#### Scenario: A painter session starts
- **WHEN** a painter session is created in plan or agent phase with a vision model
- **THEN** its system prompt lists `image-asset` with its description, and no other skills

#### Scenario: Reading outside the skills
- **WHEN** the painter calls `read` with `../package.json` or `~/.pi/agent/auth.json`
- **THEN** the call is refused, and nothing is read

### Requirement: The artist can type /skill:name
A message that starts with `/skill:name` SHALL reach the model as that skill's instructions, followed by the rest of the message, in the same format Pi uses. The studio SHALL expand the command before adding its own context.

The transcript and the move title SHALL keep what the artist typed. An unknown skill SHALL be refused, with the available names listed.

#### Scenario: A skill command in Agent mode
- **WHEN** the artist sends `/skill:image-asset a decorated Christmas tree`
- **THEN** the painter's prompt contains the image-asset instructions and "a decorated Christmas tree", and the move is titled with the typed text

### Requirement: Skill scripts run in a sandbox that works on every platform
Skill scripts and asset preparation SHALL run in Pyodide (numpy and Pillow), inside a child Node process started with `--permission`. That process SHALL:
- have no environment variables;
- be allowed to read only the runner, Pyodide, the package cache, the job's work folder and the skill's `scripts/` folder;
- be allowed to write only the work folder and the cache.

Python's `js` module SHALL be empty, with no `process` and no `fetch`. A job SHALL be stopped after 120 seconds. The release SHALL ship Pyodide and the wheels it needs, so nothing downloads on an artist's machine.

#### Scenario: A script tries to escape
- **WHEN** a script checks for a file outside its work folder, the home folder, or `js.process`
- **THEN** none of them is visible, and reading `~/.pi/agent/auth.json` from the runner's JavaScript fails with ERR_ACCESS_DENIED

### Requirement: make_asset creates a reference, never pixels in the painting
`make_asset` SHALL generate (`generate`: Seedream 5.0 Flash; `draft`: FLUX 3 Klein) or edit (`edit`: Muse, keeping the input's framing) an image through OpenRouter, using the painter's OpenRouter key. An edit SHALL start from a canvas region or an attached reference.

The tool SHALL prepare the image in the sandbox as a PNG under 4.5 MB. With `cutout`, it SHALL ask the model for a plain background, make that background transparent and crop to the subject. The result SHALL be attached as a reference with role `asset`, up to 12 per conversation and apart from the artist's 4 references.

The result SHALL give the painter the reference id, size, cost and a preview, and SHALL tell it to repaint the asset with `paint_from_reference`.

#### Scenario: A tree asset
- **WHEN** the painter calls `make_asset` with mode generate, aspect 3:4 and cutout
- **THEN** a transparent-background tree PNG is attached as an asset, and the result names its reference id and cost

### Requirement: run_skill_script runs only bundled scripts
`run_skill_script` SHALL run a `.py` file from a bundled skill's `scripts/` folder, with images passed as reference ids or canvas regions. Images the script writes into its work folder SHALL be attached as new assets.

Skill and script names SHALL match `^[a-z0-9-]+$` and `^[a-z0-9_]+\.py$`, and an unknown script SHALL be refused with the available ones listed.

#### Scenario: Cutting out an asset again
- **WHEN** the painter runs `image-asset/cutout.py` on an asset with tolerance 60
- **THEN** a new cut-out asset is attached and previewed
