## Context

- **Plugin.** Every canvas change goes through the journal in `creative_tools.py`. The agent may change only layers it created or copied, except for opacity and visibility, which it may set on any unlocked layer. Each change is a pass that reject undoes.
- **Painter.** An Agent Pi session (`@earendil-works/pi-coding-agent` 0.84.3). It is created with only custom tools and with `noSkills`, `noExtensions` and `noContextFiles` set (`src/runtime.mjs:229-240`).
- **Pi skills.** Pi follows the Agent Skills standard: skill names and descriptions go into the system prompt, and the model loads a full `SKILL.md` with Pi's `read` tool when a task matches. The painter has no `read` tool.

## Goals / Non-Goals

**Goals:**
- One action, not ten, to hide a set of failed passes.
- No batch stops because a layer the painter wanted gone is already gone.
- The painter can see a layer by itself before deciding to hide it.
- Workflow guidance comes out of the per-call tool descriptions.

**Non-Goals:**
- Image generation as a source for layers (discussed separately).
- Changing the ownership rule.
- Giving the painter file-system access.
- Undo through Krita's own history.

## Decisions

### 1. Remove computer use instead of fixing it
The traces show no case where it changed a painting. Its failure mode stopped a run, and the jobs it did in Codex have, or get here, dedicated tools.
- **Alternative rejected:** keep it, but make failures non-fatal. That keeps a macOS permission, a signed helper app and a dependency for a tool nobody uses successfully.

### 2. `set_layer` takes a list; `adjust_layer` goes
`set_layer({layers: [{layer: "<id or exact name>", visible?, opacity?, blend_mode?, ...}]})`, 1–50 entries.
- **One pass, one image.** All entries are validated first. A call is one pass with one canvas image, and reject restores every touched layer.
- **The ownership rule is unchanged.** Opacity and visibility apply to any unlocked layer, and other settings only to agent layers. It is checked per entry before anything changes.
- **Old transcripts keep working.** `adjust_layer` calls in a resumed transcript are translated to a one-entry `set_layer`, but `adjust_layer` is no longer offered.
- **Why:** 530 `adjust_layer` actions in 1,000 calls, with batches filled entirely by hides. A list makes cleanup one cheap action and frees batch slots for painting.

### 3. Layer references: id or exact name; a missing layer is fine when hiding
- **Lookup.** A reference is tried as an id first, then as an exact layer name. A name shared by two or more layers is refused, and the error lists their ids.
- **Missing layer, hide only.** If the entry is `visible: false` or `opacity: 0` and the layer isn't found, it is reported as `already_gone` and does not fail.
- **Missing layer, anything else.** Every other unknown reference fails with up to five current layer names that share a word with it.
- **`$N` references** inside a batch are unchanged.

### 4. `view_layers`: one contact sheet
A new plugin operation `layer_previews` renders each requested layer alone, as its own pixels over a checkerboard, ignoring blend mode and the layers above. It returns a single image of at most 1568 px on its long side, with each tile labelled by layer name and id, plus `bounds` and `pixel_share` (the share of the canvas the layer covers) for each.
- Up to 12 layers, defaulting to the 12 newest.
- Read-only: no pass and no checkpoint.
- **Alternative rejected:** toggling visibility and observing the canvas for each layer. That is two passes per layer and pollutes the history.

### 5. Coerce, don't reject
- **Filter settings.** Values are coerced to the type Krita reports: int settings are rounded, `"true"`/`"false"` become booleans, and numeric strings become numbers. The result lists any coerced keys.
- **Selection shapes.** Rectangles, polygons and ellipses are clipped to the image. A shape that ends up empty is still an error.
- **`apply_filter` on an artist layer.** It runs in `mode: copy`: a filtered copy is made, and the original is hidden through the same visibility right `set_layer` has. Reject removes the copy and shows the original again. The result says `mode: copy (artist layer)`.

### 6. Skills the Pi way, scripts in Pyodide
- **Loading.** Skills load as in Pi: bundled skill paths with Pi's discovery off. A custom tool named `read`, which opens skill files only, makes Pi list the skills in the system prompt. `/skill:name` expands in the studio before its context is added.
- **Why not bash or Krita's Python.** Krita's Python is unsandboxed and bypasses the journal.
- **Why Pyodide.** Gondolin needs QEMU or Apple-Silicon krun and a 1 GiB VM, and neither Gondolin nor sandbox-runtime runs on Windows. Pyodide runs the same everywhere, with two locks: an empty `js` module and Node's permission model. Pyodide's NODEFS needs a `process.binding('constants')` shim under `--permission`.
- **Where image work happens.** The companion does no image work itself. Every crop, resize, cut-out and palette match is a Pyodide script, so nothing native ships per platform.

## Risks / Trade-offs

- **The painter skips skills.** Each slimmed tool description keeps one line, such as "Workflow: read_skill layer-cleanup". If benchmark runs show the skill unread and cleanup worse, restore the descriptions.
- **A bulk hide removes good paint.** It is one pass, so reject restores everything. `view_layers` and the skill both say to look first.
- **Name matching surprises.** It is exact only, never fuzzy. A shared name is refused.
