# Element-scoped painting: select it, protect it, paint only inside it

Status: PROPOSED (2026-10-23), for the artist's OK. Follows element shapes phase 1 and the project folder.

## Why

Three live New Moscow chats on 2026-10-23 (Langfuse sessions 5d200527…, 6f948a9e…, ae1a93e7…) failed the same way:
Toska cannot work on one element of the reference or the painting.

- **Protection missed the buildings.** For "protect the buildings on the left and right" the painter magic-wanded the
  *sky* (seven seeds, tolerance 40–50, grown) and protected the inverse. The blue-glass skyscrapers are sky-coloured, so
  they counted as sky and the next move painted over them. The painter then said they were "protected" while the area
  was only proposed.
- **"Only the sky" from the whole reference fails.** The painter tried the right thing (transfer the sky reference into
  the top band); `wholeReferenceRefusal` refused it (a first transfer must be the whole picture), the flat-fill nudge
  pushed it off a gradient, and it then hand-painted clouds for eight attempts (slivers, stripes, "torn paper",
  "sausage bands"), most undone by Luna. Another chat generated its own AI cloud asset that did not match the painting.
- **The whole underpainting is excellent.** The same engine (colours and positions sampled from the reference, coarse
  to fine, real bristle presets) only lacks a boundary.
- **Selecting a part of a reference** handed the artist Similar Color Selection, a colour wand that grabs look-alike
  pixels across the image. (Fixed already on `agent/project-folder`: it is now the Freehand Selection Tool.)

## Decided by the artist

- **Pointing beats naming.** The artist selects; names are a convenience and are confirmed before use.
- **The Freehand Selection Tool**, not a wand, whenever the artist is handed a selection tool.
- **Protection never comes from a magic wand** (the artist, 2026-10-23).
- **"Paint the sky" is the full underpainting engine on the goal reference, only inside the sky** (the artist,
  2026-10-23: "only inside the sky that would be great").

## Goals

1. **Select object** (panel button). The artist clicks the thing on the canvas (or drags a rough box; Shift-click adds,
   Alt-click removes). SAM 2.1 base-plus finds its shape on the painting and it becomes a normal Krita selection
   (marching ants) the artist can still change with any Krita tool. Then: **Protect** (the shield, as today), **Paint
   only here** (the next move stays inside it), or **Name it** ("Moscow City") for later messages. Uses the existing
   shapes model, consent and timings; a painting is studied once per revision.
2. **Adjust a proposed protection with a selection tool, not the brush.** Adjust loads the proposal as the document
   selection (`Document.setSelection`) and switches to the Freehand Selection Tool (`KisToolSelectOutline`), with the
   Magnetic Selection Tool (`KisToolSelectMagnetic`, snaps to edges, good for skylines) one click away in the bar.
   Done writes the selection back into the area's mask; Cancel restores it; the artist's own earlier selection is put
   back either way.
3. **The painter's protection**: `propose_protection` accepts `shape` (one per object), polygons and a layer's alpha.
   Magic-wand seeds and colour ranges (with or without invert) are refused by the host with a message pointing to
   `shape`. Its replies say "proposed, shown in red" until the artist keeps it, and the panel lists pending proposals
   in the Protected section ("No features yet" no longer shows while some are pending).
4. **Naming confirms.** "Protect the buildings" or "paint the sky" with no selection: the painter finds the shapes,
   shows them in red and asks "this?" before anything paints or is proposed.
5. **Reference transfer inside a boundary.** `paint_from_reference` gains `inside`: an artist selection (Paint only
   here), a named element, or element shapes (the sky = the area above the horizon minus the buildings' shapes). The
   transfer is exactly today's (same sampling, passes, presets and ground) but only dabs whose centre lies inside the
   boundary are painted. The boundary is grown about 2% of the canvas past edges that later elements will cover
   (painters lay the sky behind the skyline) and fades out over open edges.
6. **Rules that let a scoped transfer through.** A transfer `inside` an element is measured by that element, like a
   reference part today (`partShare`): it may be the first transfer, the 20% patch cap does not apply to an element no
   transfer has painted yet, and the whole-picture refusal does not apply. Whole-picture transfers keep today's rules.
   The flat-fill nudge stays quiet in a move whose element has a scoped transfer available.
7. **Element references go to their element.** A folder element or an asset reference (`01-moonlit-sky.png`) is
   transferred inside its element's boundary, never whole-canvas, even when it has the canvas's proportions.
8. **AI assets only for what the references lack.** If an attached reference shows the element, `make_asset` is
   refused for it with a pointer to the scoped transfer; otherwise the painter asks the artist first, and the asset
   prompt describes the goal reference's look (palette, light, brushwork).

## Non-goals

- The reference tools are not removed or weakened; whole-picture transfer works as today.
- No reference pixels are placed as an image layer; scoped transfers are brush dabs like every transfer.
- No "segment everything": only what the artist points at or names.
- Luna keeps judging; shapes give geometry.

## Left to the builder

How the transfer engine masks dabs (plugin side, reusing protection enforcement or the part alpha), the horizon
estimate for "the sky" (from guides, or the lowest sky-shape row), the panel layout of Select object, and the exact
refusal wording. Phase order: 2 and 3 first (small, fix today's damage), then 5–7, then 1 and 4, then 8.
