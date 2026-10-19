# Krita bridge 2.0.1

The running Krita bridge and installed source support the new controls through
`krita_batch`. Artist server source is also updated; its existing generic tool
makes the commands available without adding or reconnecting MCP tools.

## Commands

- `stroke`: native `[x,y,pressure]` points; alternatively `pressure` as a scalar
  or one value per point. Pressure is 0..1. Per-point values take precedence.
  `size`, `opacity`, `flow`, `rotation`, and `color` are accepted.
- `set_brush`: exact preset name (ambiguous partial names are rejected), size,
  opacity, flow, rotation in degrees. Defaults track the selected preset.
- `new_layer`: creates AND selects the layer, returning its unique ID.
- `select_layer`: unique `name` or `id`; ambiguous names are rejected.
- `brush_settings`: inspect preset property keys. `include_xml: true` returns
  full XML; `include_data: true` includes large embedded property values.
- `configure_brush`: `properties` object changes existing keys in memory.
- `restore_brush`: restores the current preset's original session XML.
- `set_brush_texture`: `path`, `scale` (0.01..10), `strength` (0..1).
  Import the image as **Patterns** through Settings > Manage Resources first.
  Requires a preset with existing texture properties, such as RGBA 04 Impasto.
  The bridge verifies the imported filename and image contents before applying it.

Example:

```json
{"action":"stroke","params":{"points":[[100,100,0.9],[300,160,0.5],[450,180,0.02]],"size":80,"color":"#43553a","rotation":25,"flow":0.7}}
```

## Known limits

Pressure paths use native `paintLine` for each segment. Brush dynamics may restart
at joins; this is not a continuous tablet event stream. Pressure response depends
on preset sensors. This installed Krita API accepts integer QPoint coordinates.

Preset edits are session-only, not saved custom .kpp resources. Restore after tests.
Disabling a preset's texture can cause Krita to omit its texture properties from
XML. Restore the preset before applying a different texture; merely toggling the
Enabled property does not restore the missing properties.

Texture overlap in buildup mode can obscure grain; short dabs or lower opacity
show the effect more clearly. These controls improve paint handling, not drawing
or anatomical accuracy by themselves.

## Validation

Four stroke-input regression tests cover legacy input, scalar/list pressure,
per-point overrides, and rejection of invalid input before painting. Live Krita
checks verified pressure taper, rotation, flow, layer selection, preset changes
and restoration, and custom pattern painting at two different scales.

- `brush_control_proof.kra/png`: pressure and rotation trials.
- `custom_texture_proof.kra/png`: identical custom weave at 0.5 and 2.0 scale.
- `textures/woven_canvas.png`: deterministic texture fixture, imported as Patterns.
- `backups/pre-brush-upgrade`: original bridge and artist server sources.
- `recovery`: recovery copies of the tree studies.

Development source: `krita-plugin/kritamcp/__init__.py` and `stroke_data.py`.
Installed bridge: `~/Library/Application Support/krita/pykrita/kritamcp/`.
Running artist server source: `~/plugins/krita-artist/server.py`.

Run `python3 -m unittest discover -s tests -v` from this directory.
A normal Krita restart loads installed changes. `reload_bridge.py` may be run
from Krita Scripter to update handlers without closing documents; it preserves
the active queue and server. Scripter can temporarily disrupt macOS menus;
selecting the original document restored them in this session.


## Bridge 2.1: semantic controls and diagnostic swatches

`brush_controls` takes `controls` with pigment, blend, scatter (0..1), pigment_dynamics and blend_dynamics (booleans). Unsupported properties and invalid values reject before changing the preset. Readback shows the actual stored properties. Settings remain in memory; restore_brush restores originals. These normalized controls describe Krita parameters, not calibrated physical paint quantities.

The former Memileo failure was incorrect option semantics, not loss of imported brush resources: PressureColorRate disables pigment entirely. Disable ColorRateUseCurve to remove dynamics. Both corrected raw settings and semantic controls were verified live.

`brush_probe` tests the active preset on a disposable 640x256 two-color ground. Returns mark_detected, changed_pixels, canvas_path. It closes the scratch document and restores the previous view, size, opacity, flow, rotation, and foreground color. Probe is a controlled visibility test, not proof of behavior on every layer or document. A zero-pigment, zero-blend impasto brush can still alter lightness through its tip; changed pixels do not imply pigment deposition.

Live verification: pigment stroke changed 20,538 pixels; blending-only stroke carried the left ground color into the right ground. Source canvas pixels were unchanged by the probe. Original presets restored. Eight unit tests pass, including public command registration and semantic option mapping.

## Bridge 2.2: precision and review tools

- `selection`: rectangle/ellipse with bounds [x,y,w,h], or polygon with points; modes replace/add/subtract/intersect/clear; optional feather radius 0..128 pixels. Combines with the existing selection. All geometry validated before replacing it. Native brush operations honor selections; raw pixel writes and pixel-fill helpers do not.
- `curve_stroke`: start [x,y] and cubic segments [[c1x,c1y,c2x,c2y,endx,endy],...], with size/opacity/flow/color. One QPainterPath render rather than separate line calls. This binding does not expose arbitrary pressure along a continuous path. Supplying pressure is explicitly rejected; use existing segmented stroke for variable pressure, with its documented dynamics limitation.
- `compare_region`: bounds, reference_path, reference_bounds, scale; matched aspect ratios required. Exports a labeled side-by-side PNG, without changing either source. Panels limited to 2048px. This is visual review, not a perceptual quality score.
- `duplicate_document`: unsaved native clone, with source filename cleared. Explicitly choose a layer after cloning.
- `layer_settings`: opacity 0..1 and/or visible boolean for the active layer. Useful for reducing an experimental pass without deleting it.

Installed and loaded live. Eleven unit tests pass. Live pixel checks verified exact rectangular clipping; ellipse/polygon protection; add, subtract and intersect; native cubic rendering; and pressure rejection. Practice on a copy of the portrait altered 22,184 pixels, all inside the two intended feathered skin regions; source PNG was unchanged. The blur pass was initially too strong and was reduced to 32% layer opacity. Result remains an impressionistic study, not a finished realistic portrait.

Practice deliverables: ../memileo_portrait_practice.kra and .png, plus portrait_blending_comparison.png (before at left, revised at right). Previous portrait remains unchanged.


## Bridge 2.3 — native editing controls

Installed and live-tested 2026-09-08. These commands operate on the active document/layer through the Krita API.

- `duplicate_layer {name}` clones the active layer above its original and selects the copy. Content, layer settings and masks follow Krita's native clone behavior.
- `move_layer {dx,dy}` translates an unlocked paint layer by integer canvas-pixel offsets, including negative offsets. It moves the WHOLE layer regardless of selection; isolate a feature on its own layer first. This is translation, not scaling/warping. Content may move outside the visible canvas.
- `layer_settings` now also accepts `alpha_locked` and `locked` booleans. Alpha lock protects existing transparency during native brush painting. Raw pixel writes bypass this; do not use them for protected editing.
- `modify_selection {operation,radius}` supports grow, shrink, feather (integer radius 1..128), and smooth (omit radius). Requires an existing selection. Changes a duplicate of the selection and installs it only after success.

Native integration proof: `editing_controls_proof.kra` and `.png`. Red original was cloned, translated +160px, alpha-locked and overpainted blue with a brush wider than the shape. Exported masks match exactly; original center remains RGB(192,64,48), copy RGB(48,96,192). A separate selection grew from [50,140,80,40] to [40,130,100,60], shrank to [45,135,90,50], then was smoothed and feathered; broad green paint remained confined to its softened mask. Locked-layer movement, fractional offsets and modifying a missing selection were rejected. Existing 11 unit checks pass including command discovery. Original Christmas painting was not edited in these tests.

API references: https://api.kde.org/legacy/krita/html/classNode.html and https://api.kde.org/legacy/krita/html/classSelection.html . Backups of prior installed bridge are in `backups/pre-editing-tools`.
