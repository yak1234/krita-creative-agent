## Context

- Krita 5.3.3's `libkis` exposes `Krita.resources(type)`, `Resource` (`name`, `image`, `setImage`, `setName`, `type`),
  `Preset(resource)` (`toXML`, `fromXML`) and `View.setCurrentBrushPreset`. Nothing creates or imports a resource.
  This was checked against the installed library's symbols and the Context7 Krita API docs.
- Pi extensions can register tools (`ExtensionAPI.registerTool`), as well as hooks like `tool_result`. The studio
  already registers extensions inline (`extensions.mjs`) and hands each a port (`reviewHost`).
- Pass bookkeeping, protection erase, the move review and the weight monitor all key on a native operation that makes
  one agent layer and returns `layer_id`, `revision` and `passes`.

## Decisions

### Split: TypeScript decides, Python paints
- **`extensions/material-stamp.ts`** registers `make_material` and `stamp_material`, validates them, and turns the
  painter's request into a dab list:
  - a seeded generator places `count` dabs uniformly in the area's bounds;
  - per dab: scale, rotation, opacity and tip index.

  The list goes to Krita through a port, `MaterialHost`: `native(operation, params)`, `study()`, `mode()`. It runs
  through the studio's `callNative`, so revision checks, `stage_id`, protection and pass history apply unchanged.
- **`material_stamp.py`** (plugin) does what needs pixels:
  - cuts tips;
  - keeps each dab inside the area's selection;
  - samples colour per dab;
  - paints all dabs with one `QPainter` onto a QImage the size of the area's bounds, written once with
    `setPixelData` to a new paint layer.

  *(my call: pixels never cross the bridge for a stamp; only the dab list does, a few KB.)*

### Materials
- `make_material {name, source, kind, count?, size?}`:
  - `source` is one of `{area}`, `{layer_id}` or `{reference_id}`;
  - `kind`:
    - `light` (default): light over its blurred surroundings, as cut for clouds, highlights and foam;
    - `shape`: the source's alpha, as for a cut-out leaf, snowflake or figure asset;
  - `count` is 1–8 (default 6) and `size` is 64–512 px (default 220).
- **Cutting tips:**
  - smooth the source (a 4 px blur) so specks and snow do not become tips;
  - score candidate patches by mean detail and keep the best `count`;
  - normalise each patch to its peak, then apply a soft round falloff;
  - patches that overlap a protected area are skipped.
- **Storage and preview:** tips are saved under the chat's `materials/<id>/` as greyscale PNGs, with `material.json`.
  The result carries a contact sheet image so the painter sees what it made.

### Stamping
- `stamp_material {material_id, name, area|selection, count, size:[min,max], opacity:[min,max], rotate?, tint?, seed?}`:
  - at most 2000 dabs per call;
  - `tint` is `{color, amount 0–1, toward: 'top'|'all'}`: the dab colour moves toward `color`, and with `top` more
    strongly the higher the dab is in the area;
  - `color` is the canvas colour at the dab, blurred over 40 px plus 60% of its local light. This is the spike's rule,
    which kept the stamped clouds in the painting's palette.
- **Compositing:**
  - with premultiplied alpha throughout (the spike's first bug: un-premultiplied RGBA made every dab nearly opaque);
  - masked by the area's selection at write time, so nothing lands outside it.
- **One pass:** the stamp makes one new layer. It records a pass with before and after images, and Undo rejects it
  like any pass.

### Agent moves and Luna
- A stamp is a painting call: it counts toward the move's calls and the pace, and Luna reviews its batch.
- The `paint-sky` and `repaint-area` skills say how to use it:
  1. make a `light` material from the painting's own clouds or texture;
  2. stamp it into a selection of the sky, never over the whole canvas;
  3. then a small stroke pass for edges.

## Non-Goals
- Krita brush presets or resource files: no restart, and nothing outside the chat.
- Pressure dynamics, smudging or wet mixing: a stamp is opaque-over compositing of tips.
- A materials library across paintings. Later, if materials prove useful: materials are already files.

## Risks
- **Too smooth:** the spike's stamped clouds lacked painted texture. The skills follow a stamp with strokes for
  edges, and Luna reviews the result.
- **A wrong area paints over subjects:** in the spike, a colour-only sky test caught the glass towers. The tool takes
  the area from selection steps, the same as `fill_region`, and protection erases what lands in protected areas.
- **Large areas:** a 6000×1600 QImage is 38 MB, which is fine. The area's bounds are capped at the canvas, and the
  layer is written once.
