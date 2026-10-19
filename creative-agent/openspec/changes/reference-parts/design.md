## Decided with the project owner

- **Built after protected areas** (`openspec/changes/protected-areas`), which it relies on for safety.

- **The agent focuses on one thing at a time.** A part of a reference is how the artist names that thing: "the sky",
  not "the top third". One part is usually one Agent move.
- **Krita's own tools do the selecting**, not a copy of them in the panel. For a sky, similar colour select or the
  magnetic lasso picks it around spires and towers in a few clicks.
- **The flow, as approved in the mockup** (`.superpowers/brainstorm/…/reference-part-flow.html`, New Moscow):
  1. Click the reference in the panel; choose **Select a part in Krita…** (or **Crop in Krita…**).
  2. The reference opens in Krita; select the part; click **Use this part**.
  3. The part appears as its own reference, for example "Sky (part)", beside the original. The artist asks for it in
     a message ("Paint the sky from Sky"), and the agent paints only the sky, in the same place.
- **The painting is never touched** while a part is being made.

## How it works

### Where the actions live (builder's call, recorded here)
Clicking a reference thumbnail already opens `ReferencePreview` (purpose and notes). The two actions are buttons in
that dialog, so it stays one click on the thumbnail. They are disabled while the agent is busy, like the purpose and
notes ("Pause the agent to select a part").

### The temporary document
- The panel copies the reference to a temporary file and opens it with `Krita.instance().openDocument()` and a new view,
  so the artist's own file is never opened or saved. The selection tool is preselected (similar colour select for
  "Select a part", rectangle select for "Crop").
- While it is open the panel shows a bar: "Selecting a part of New Moscow · **Use this part** · **Cancel**", with the
  composer disabled. Nothing else in the panel changes.
- **Use this part** with an empty selection says "Select the part first" and keeps the document open.
- On Use or Cancel the temporary document closes without saving (`setModified(False)`, `close()`), the view of the
  painting that was active before is restored, and the temporary file is removed. If the artist closes the temporary
  document themselves, the bar disappears as if Cancel was pressed.
- Only one temporary document at a time.

### What gets saved
- **Select a part:** a PNG the size of the original. Each pixel's alpha is the reference's alpha times the selection's
  value at that pixel, so a feathered or anti-aliased selection gives a soft edge. Read with `Document.pixelData` and
  `Selection.pixelData` over the image bounds.
- **Crop:** a PNG of the selection's bounding rectangle, fully opaque (the pixels inside the rectangle, whatever the
  selection's shape). For a close-up of a face or a detail.
- The file goes where pasted references go (the temporary paste folder); the companion copies it into the chat on send,
  as with any attached reference.
- The panel asks for a short name, prefilled "Part of <original name>"; the reference's name is that plus " (part)" or
  " (crop)".

### What the agent is told
- The reference entry sent to the companion carries `part_of` (the original's id or path) and `bounds`
  ([x, y, width, height] of the part's opaque area or of the crop, in the original's pixels).
- The painter's reference context lists them, and one line of guidance: a part is the only area to follow from that
  reference; it is see-through elsewhere, so a transfer from it paints only the part, in the place it has in the
  original; a crop is a close-up of `bounds` of the original.
- **A part is the artist's permission for its own shape.** The transfer rules measure a rectangle; for a part they
  measure its opaque area and do not refuse it, because the artist drew the boundary. On a painting with protected
  areas (`openspec/changes/protected-areas`, built first) the size caps are gone anyway; this covers paintings without
  any. Protection still applies inside the part: a part never overrides a protected area. The second-half-of-plan rule
  still applies in Autopilot.
- No toned ground goes under a part (its alpha already rules this out in `groundStops`).

### Limits
- Parts count toward the four references per chat. The preview says so when the limit is reached ("Remove a
  reference to add a part").
- A part of a part is allowed (it is just a reference).

## Non-goals

- **No automatic "select the sky" by AI.** The artist selects; a model-made mask may come later.
- **No editing tools beyond selection.** Painting, transforming or colour-adjusting the reference is out of scope.
- **The canvas is not involved**: this changes references only. Selecting a region of the painting itself is a
  separate feature (messages already carry `region`).

## Anti-goals

- Touching or saving the artist's painting or reference files.
- A temporary document left open, or the artist left on the wrong document, after Use or Cancel.
- The agent painting outside the part.

## Verification

- Unit: the alpha composition (soft selection edge, opaque crop, empty selection refused) in the plugin tests; the part's
  `part_of` and `bounds` in the painter context; the transfer rules measure a part by its opaque area.
- `ui_smoke.py`: the two buttons, disabled while busy; the selecting bar; Cancel restores the panel.
- Live, on `new_moscow.kra` after a Krita restart: make "Sky" with similar colour select, ask Agent mode to paint the
  sky from it, and check that no building, spire or tower top changed.
