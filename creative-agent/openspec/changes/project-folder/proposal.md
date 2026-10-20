# Project folders and guided trace

Status: APPROVED by the artist (2026-10-20), to be built: **guided trace first**, then the project folder.

## Why

The artist works from folders of reference material: his `new_moscow` folder holds a goal image (`final_goal.png`),
twelve numbered element photos (`01-moonlit-sky.png` … `12-vintage-convertible.png`), the prompts that made them
(`generation-prompts.json`) and an art brief. Today a reference is attached one at a time in the chat. He wants Toska to
work like Cursor with a code folder: point the panel at a folder, and the agent reads it, understands what each file is,
and paints from those references, one element at a time.

He also wants the agent to place things better. Tracing from a reference can help, but only as a painter's underdrawing,
never as a way to turn a photo into the painting.

## The rule that governs everything (the artist's, revised 2026-10-20)

Everything reaches the painting through painting tools: brush strokes, the reference tools
(`paint_reference`, `paint_reference_edges`, `paint_reference_surface`), fills and the like. Pasted, filtered or
projected reference pixels are fine as long as they go onto the canvas through those tools. What is not wanted is a
reference dropped onto the canvas as an image and called a painting. The reference tools are kept exactly as they are.

Guided trace and the reference tools do different jobs and combine: guided trace gives placement and shape (a few
construction lines, no colour), the reference tools give colour and light, the agent's own strokes give edges, detail
and finish.

## Goals

1. **Guided trace (first).** The agent draws construction lines from a reference on its own guide layer: horizon, the
   perspective, the main silhouettes and proportions. It paints the element over them in its own strokes, then hides the
   guide when that element is done.
2. **Project folder.** The artist chooses a folder in the panel; the agent reads it and shows what it found.
3. **Plan, then paint, in Agent mode.** The agent proposes an ordered plan of moves, one element per move; the artist
   approves, edits or trims it; only then does painting start.
4. **Resume.** The plan and a short log live in the folder as Markdown, so the work continues another day.

## Non-goals

- No reference dropped onto the canvas as an image layer (everything goes through painting tools; see the rule). A
  guide layer holds lines the agent drew, not photo pixels.
- Guide lines are never the final linework: the guide is hidden (or deleted) when its element is done, and nothing is
  merged from it.
- No running anything from the folder: no scripts, no programs, no links followed out to the internet.
- Not a file manager: the agent never moves, edits, or deletes images or other non-Markdown files.
- No heavy planning formats in the folder (no OpenSpec, no wiki): one plan file and one log.

## Anti-goals (would make it a failure even if it "works")

- The guide lines showing in the final image, or the agent tracing photo outlines as the finished drawing.
- The agent silently rewriting the artist's own brief.

## Guided trace

- **Source.** The goal image gives placement (where things sit in the picture). An element photo gives the element's
  own shape and proportions. Where an element photo's angle disagrees with the goal image, the goal wins.
- **What is drawn.** Simple construction lines with a thin brush on a dedicated guide layer: horizon line, vanishing
  lines, the silhouette or block-in of the element, key proportions. A light, clearly guide-like colour.
- **The layer.** One guide layer per element (named for it), locked against the artist's accidental painting, excluded
  from anything the agent samples as "the painting" (Luna's review, colour sampling, merges), and hidden when the element
  is finished. The artist can show a guide again at any time.
- **Undo.** The guide strokes belong to the element's move, so one Ctrl+Z removes the move including its guide.
- **Visible to the artist.** The panel says when a guide is drawn and when it is hidden.
- **Works without a folder too.** Guided trace is usable with a single attached reference in an ordinary chat, which is
  why it ships first.

## The project folder

- **Choosing it.** A control in the panel ("Open project folder"). The chosen folder is remembered for that painting.
- **What is read.**
  - Images: PNG, JPEG, WebP.
  - Markdown and plain text (`.md`, `.txt`): briefs, READMEs, notes.
  - JSON, read as text only (the artist's `generation-prompts.json` describes the images).
  - Everything else is ignored and listed in the panel as "skipped".
- **Limits.** A cap on how many images and how large a file are read, so a big folder cannot stall Krita. Files outside
  the folder, including through shortcuts or links, are never followed.
- **Understanding it.** The agent builds a short index: which file is the goal image, what each element photo shows
  (from file names, the prompts file and looking at the image), and what the brief asks for. The panel shows the index;
  the artist can correct a guess ("09 is lamps and trees").
- **Roles.** One goal image (decides the layout). Element references (decide how one thing looks). Brief or README
  (mood and rules), optional: without one, the agent works from names and prompts and says what it assumed.

## Plan, then paint (Agent mode)

1. After reading the folder, the agent shows a plan: an ordered list of moves, back to front, one element each. For each
   move: what it paints, the new layer's name, the reference it studies, and that it draws a guide first.
2. The artist approves, reorders, removes moves, or narrows it ("only the sky today"). Nothing touches the canvas before
   approval.
3. Each move: draw the guide, paint the element in its own strokes, hide the guide. One undo step per move; Luna reviews
   each move as today.
4. A finished element can be protected as a feature, so later moves paint around it.
5. The panel keeps the plan visible with the current move marked; the artist can stop, skip or reorder at any time.

## Markdown in the folder (the agent may write here)

- `PLAN.md`: a few lines of intent (goal image, mood, the artist's rules) and the checklist of moves, ticked as they
  finish. Example line: `- [ ] 3. Kremlin towers (04-kremlin-towers.png) · layer "Towers"`.
- `NOTES.md`: a short append-only log, one or two lines per session: what was painted, what the artist corrected, what
  to keep in mind.
- **Editing Markdown.** The agent may create and edit Markdown files in the folder freely. When it changes a Markdown
  file it did not create (for example the artist's brief), it first saves a copy beside it and the panel shows what
  changed. It edits the artist's own brief only when asked.
- **Resume.** Opening the folder again, the agent reads `PLAN.md` and `NOTES.md`, says where things stand ("3 of 12
  done, next: the towers"), and continues after the artist's OK.

## Constraints

- Toska (the fork) only; the stock plugin path need not support it.
- Everything the agent does to the painting goes through the existing painting operations (stroke jobs, fills, layers),
  inside agent moves, honouring protection.
- The existing reference features (attach a reference, view a reference, "Plan from a reference") are the starting point;
  extend them rather than build a parallel system.
- The folder is read through the plugin with the same safety as today's file handling (paths resolved inside the
  folder, size limits).

## Decided by the artist

- Guided trace yes, as an underdrawing on its own layer; copy-tracing and photo filters as the painting, no.
- Goal image plus element references; in Agent mode one element per move.
- The plan is shown and approved before painting.
- Only images and text-like files are read; nothing is ever run.
- Markdown files: the agent may edit freely; images and other files are read-only.
- One plan file and one log, not OpenSpec or a wiki.
- Guided trace is built first.

## Left to the builder

- The guide's colour, brush and line weights, and how the agent extracts placement lines from the goal image.
- The panel layout for the folder, index and plan (keep it minimal; a design pass may restyle it).
- The image and file-size caps.
- How the index is stored between sessions (in `PLAN.md`, or alongside it in Markdown).
- How the agent describes each image (file name, prompts file, vision) and how corrections are recorded.

## Builder check (2026-10-20) and where it was left

- **Reference tools stay (the artist).** The companion's `paint_reference`, `paint_reference_edges` and
  `paint_reference_surface` turn a reference into brush dabs (optionally over a toned ground). The artist had not known
  they existed and likes them: keep them as they are. The rule above therefore means: no pasted, filtered or projected
  reference pixels; brush strokes the agent lays from a reference (these tools) are fine.
- **Pacing (the artist):** after the plan is approved, the agent stops after each element for Keep / Undo / Refine, as
  Agent mode does today; it never runs the whole list on its own.
- **Lead's calls (recorded so a builder need not guess):** `PLAN.md` mirrors the agent's own durable brief; edits the
  artist makes to it between sessions are shown on resume and confirmed before they are followed. An element's guide
  lives on its own layer until the element is ticked, across several moves; undoing the element's first move removes it.
  The reference folder is attached to the painting, not the companion's project root: nothing hidden is written into it,
  only `PLAN.md`, `NOTES.md` and backups. Protection stays the artist's: the agent proposes protecting a finished
  element, the artist confirms with one click. Guided trace is its own setting ("Draw guides from references"), on by
  default in project-folder work; "Follow a construction map" stays for maps the artist draws.

## Future idea (not in v1): Luna checks the guide

Raised by the artist 2026-10-20, to build after guided trace has been tried live. Luna stays a checker, never the one
that draws: placing lines needs exact positions, which image models are weak at; the painter keeps drawing them from
the reference mapping.

- **When.** Once after `draw_guide`, before the element is painted (a wrong guide wastes the whole move), and optionally
  once after the element (did the painting follow its guide). This look includes the guides on purpose; every other
  Luna look stays guide-free.
- **Aligned with how Luna is used today (luna-visual-decisions).** Only the question shapes Luna measured well:
  naming the main difference from a reference (4/4), locating a difference in a 3×3 grid (9/9), and specific named
  choices ("horizon: higher / lower / same as the goal"). Never a general "is this guide good?" or reject question:
  that shape was 59% on planted flaws.
- **Wrong answers, both ways.** A missed problem costs no more than today (the guide is drawn as if unchecked). A false
  alarm is capped: Luna's finding is advice passed to the painter, never an automatic undo; at most one redraw per
  guide; a finding below the answer's confidence threshold is recorded, not acted on.
- **Same setting.** Follows "Luna decisions": Off does nothing, Evaluate only records and shows it, Guide agent passes
  findings to the painter.
- **Before it is built.** A small labelled set (guides drawn right and wrong against goal images) measures its
  false-alarm and miss rates first, as was done for the failure checklist.

## Future idea: Autopilot becomes "run my approved plan"

The artist (2026-10-20) moved Autopilot to experimental: it leans on Luna's weakest judgements (is the painting done,
what next) and its worst runs were Autopilot runs. It stays for unattended test runs. Once the project folder's plan
exists, Autopilot could run only the plan the artist approved, element by element, stopping as soon as Luna flags a
move, instead of painting open-ended until a review passes. Note for Group B: Plan mode's "Paint this plan" button
(`start_plan` in creative_docker.py) still switches to Autopilot; decide then whether it should start Agent mode on the
plan's first element instead.
