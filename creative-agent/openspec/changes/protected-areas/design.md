## Decided with the project owner

- **The artist should not need to know Krita's tools.** The panel offers a button and a section; asking in words is
  the first way in.
- **Three ways to add a protected area:** ask the agent, paint over it, use my selection (mockup:
  `.superpowers/brainstorm/…/protected-areas.html`, New Moscow with "Woman and car" in red).
- **An area the agent proposes is not active until the artist presses Keep.**
- **The agent tells the artist right away** when it runs into a protected area.
- **The 20% guard existed because of agent mistakes.** The artist's own marking replaces it.
- **Protected areas are built before reference parts** (`openspec/changes/reference-parts`): they make every run safer.

## The rule

**Nothing the agent does may change a visible pixel inside a protected area.** Every enforcement and test below follows
from this one sentence.

## How it works

### Where a protected area lives
- A protected area is a **selection mask in the painting**, named by the artist ("Woman and car"), so it is saved in
  the `.kra`, survives a restart, and travels with the file. The plugin finds them by a marker it controls (a name
  prefix, or a node it owns holding them), never by guessing at the artist's own masks.
- **Builder's call, to verify in Krita first:** where a document-wide selection mask can live in the layer tree
  (Krita attaches masks to layers; a locked, empty group owned by the plugin, holding the masks, is the expected answer)
  and that it does not alter the rendered image.
- **Locked layers** are protected by their own alpha, read live; they are listed in the section as "Locked layers ·
  N layers · automatic" and cannot be removed there (unlock the layer instead).

### The panel section
- **Protected areas**, under the references: one row per area (red swatch, name, who made it, 👁 show, ✕ remove) and
  the automatic "Locked layers" row.
- 👁 shows that area as a red overlay on the canvas until clicked again; red is not shown otherwise.
- Buttons: **Ask the agent…** (puts "Protect " in the composer, focused), **Paint over it**, **Use my selection**.
- Disabled while the agent is painting ("Pause to change protection"), like the other allowances.

### Ask the agent
- New tool `propose_protection(name, area)`: `area` is the existing selection steps (shapes, polygons, a layer's alpha,
  a colour range), so the painter can outline "the woman and the car" from what it sees. It creates the mask as
  **pending**, shows it in red, and the chat shows **Keep / Adjust / Discard**.
- **Keep** makes it active. **Adjust** opens Paint over it on that mask. **Discard** deletes it.
- Offered in every mode. Pending areas never protect anything and are dropped if the chat moves on without a choice.
- The agent **cannot remove or change** a protection; only the artist can (✕, or Adjust).

### Paint over it
- Makes the mask the active node and selects a round brush, so the brush adds protection and the eraser removes it,
  with Krita's red selection overlay on. A bar in the panel: "Painting protection · **Done** · **Cancel**". Cancel
  restores the mask as it was. The painting's pixels are never touched.
- Builder to confirm the Krita behaviour (painting on a selection mask with the brush and eraser) on Krita 5.2 and 5.3.

### Use my selection
- Copies the current selection into a new area, asking for a name ("Protected 1" prefilled). Empty selection: "Select
  an area first."

### Enforcement
- In `cmd_creative`, after every mutating operation and before its receipt is stored, the plugin applies the rule:
  - **Pixel layers the agent made** (stroke passes, reference transfers, toolbox edits, fills on paint layers, copies,
    transforms): erase the protected area from them.
  - **Layers whose effect is not their own pixels** (fill and generator layers, filter layers, filter masks, layer
    styles): give them a transparency mask that excludes the protected area.
  - **Settings of the artist's layers** (`adjust_layer`, `set_layer` opacity, visibility, blend mode): refused when that
    layer has visible pixels inside a protected area, with a message naming it.
- **Backstop:** the projection inside the protected area is compared before and after; any remaining change is a
  failed operation (rejected, as an uncertain change is today), so a new operation type cannot slip through.
- The amount removed is measured (share of the pass and pixels) and named per area.

### Telling the artist and the painter
- The operation's result carries `protected: [{name, share}]`. The companion emits it as a chat line right away:
  "Move 3 reached into 'Woman and car'. I kept that area untouched (about 4% of the pass)." In Autopilot the run keeps
  painting (nothing protected changed).
- The painter's tool result says the same, so it can adjust; three hits on the same area in one step add: "You keep
  painting into 'Woman and car'. Leave it alone."
- The painter's context lists the active areas by name with their bounds.

### The 20% guard
- `transferRefusal` keeps its plan-stage rule, but its existing-painting and second-transfer size caps do not apply
  when the painting has at least one active protected area (locked layers alone do not count: they are usually the
  whole background).

## Non-goals

- **No automatic protection** without the artist (no "the agent decided to protect the face").
- **No protection of references**, only the painting.
- **Not a permission system** for the artist's own brush: the artist can still paint anywhere.

## Anti-goals

- A protected pixel that changes.
- A protection the artist did not keep, or one the agent removed.
- Protection that silently swallows work: every hit is reported.

## Verification

- Plugin tests: each operation type above paints into a protected area and the projection there is unchanged; the
  report names the area and share; a pending area protects nothing; settings changes on overlapping artist layers are
  refused.
- Companion tests: `propose_protection` creates a pending area and waits; the hit message reaches the chat and the
  painter; `transferRefusal` lifts its caps only with an active area.
- `ui_smoke.py`: the section, the three buttons, Keep / Adjust / Discard, disabled while busy.
- Live on `new_moscow.kra`: protect "Woman and car" by asking, ask Agent mode to repaint the street, and confirm the
  woman and the car are pixel-identical before and after.
