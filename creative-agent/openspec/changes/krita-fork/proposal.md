## Why

The artist decided on 18 October 2026 to build our own Krita: an agent that is part of Krita from launch, in a
Photoshop-like interface, painting much faster than a plugin can. The plugin has reached the limits of Krita's
scripting API (docs/2026-10-18-krita-fork-painting-speed-report.md):

- Krita doing the work took 31.3 h of tool time against 12.4 h of model time (Langfuse, 9–19 October, 98 chats), so a
  faster model does not make painting faster.
- Scripts can only call a full `refreshProjection()`, which recomposites every layer and filter mask and blocks the UI
  thread. Hand painting redraws only changed tiles. Reference transfers ran at 15 / 63 / 296 strokes/s (p10 / p50 /
  p90), and one New Moscow observe took 909 s.
- Results were lost while Krita was busy (5 × "Lost the painting operation result"), and the agent starts only after
  a painting is open.
- Pressure, area refresh, contiguous selection and image analysis were proven on 19 October 2026 through a native
  helper on stock 5.3.3 and the plugin's own numpy and OpenCV, never through libkis (design sections 2 and 7).
- Workarounds we built show what the API lacks:
  - the plugin keeps its own brush tips (material-stamp), because scripts cannot make one from an area;
  - protected areas are selection masks in a locked group;
  - kept work is merged and filter masks baked by hand-written projection copies (`merge_agent_work`).

The licence is settled: Krita is GPL-3.0-or-later, and the project was relicensed to match on 19 October 2026, so the
fork can take Krita's and Krita-Revamp's code directly.

## What Changes

In priority order:

1. **Foundation:** the fork itself, on Krita master on Qt6 (Qt6, the newest libkis, including `paintPolylineStroke`
   with tilt and speed, and Krita-Revamp's port target; pressure itself already works on 5.3.3 through the native
   helper). This step also covers:
   - the plugin ported to PyQt6 first;
   - a separate settings folder, so the artist's working Krita 5.3.3 is untouched;
   - a macOS build pipeline;
   - a policy for staying in sync with upstream.
2. **Krita's own bottleneck, and an agent channel into its core:** painting speed independent of document size.
   Krita's core already has most of what this needs; its scripting layer (`libs/libkis`) just does not expose it
   (source study of master, 19 October 2026, design section 2):
   - a region refresh scripts can call;
   - strokes that run off the UI thread with real job status, waiting per job instead of for the whole image;
   - a cheap canvas revision and changed-area reports, from the core's own update signal, marked artist or agent,
     instead of hashing 108 MB per observation;
   - scaled views read without copying the full canvas;
   - pressure strokes as the agent's stroke path;
   - undo history, named steps, fill and selection functions, and change events, which the core has and libkis does
     not (gap study, design section 2);
   - fixes for libkis traps: `Filter.apply` and `Node.setPixelData` without undo or selection, `Selection.contract`
     adding a rectangle, and scripted strokes inheriting the view's mirror and selection;
   - one named undo step per agent move, so a move never uses up the 200-step undo limit.

   Measured before and after with the plugin's `timings_ms`.
3. **A Photoshop-like interface, from Krita-Revamp** (GPL-3.0, a fork of Krita 5.2.14), ported to master and Qt6:
   - brush stroke previews;
   - folder-style layer groups and clipping masks;
   - scrubby zoom and an instant overview;
   - resizable toolbars, and brush presets that keep changed settings;
   - its curated plugins.

   Krita's Photoshop shortcut scheme and a matching workspace become the default.
4. **The agent built in:**
   - the agent panel is available from launch, before a painting is open, and creates `.kra` files and assets itself;
   - a project view of paintings, references, brushes and generated assets;
   - on-canvas overlays for proposed protection, Luna's findings and move previews.
5. **The scripting gaps, made native:**
   - brush tips and presets from an area or image, created from scripts without a restart;
   - merge kept work and bake filter masks as Krita operations.
6. **A feature map of the painting:** named regions ("Sky", "Moon", "Tower 3") saved in the `.kra`, built with the
   selection tools Krita already has for people (similar colour, contiguous, edge-snapping outlines, lazy-brush
   segmentation), and asked spatial questions (what is here, what touches this, "Sky minus Moon"). The agent pinpoints
   by name instead of rebuilding a selection each move. Protection becomes a property of a feature, replacing the
   plugin's protected-area masks. Runs 10 and 11 show why: the painter protected only the moon though the artist named
   the buildings, and a hand-drawn skyline polygon left bands of old sky.

## Capabilities

### New Capabilities
- `fork-foundation`: the fork's base, build, settings isolation, upstream sync and GPL compliance.
- `agent-speed-api`: scripting APIs that make agent painting as fast as hand painting: async jobs, change reports,
  cheap views, pressure, and agent undo steps.
- `canvas-features`: named, saved regions of the painting, built with Krita's selection tools and asked spatial
  questions; protection is a feature property.
- `photoshop-workspace`: the Photoshop-like interface, from Krita-Revamp and Krita's own Photoshop scheme.
- `built-in-agent`: the agent as part of Krita from launch, with a project view and canvas overlays.
- `native-agent-craft`: brush tips from an area, merge and bake.

## Impact

- One repository: the fork of KDE/krita master, with the plugin, companion and helper moved into its tree (task 1.5).
  Artists download our Krita, so nothing is designed around stock Krita's limits (the artist's decision, 19 October).
- The plugin: PyQt6 through `qt_compat.py`, which was started by material-stamp (PyQt5 5.15 accepts the scoped enum
  names, so the port can land before the fork exists).
- The companion is unchanged at first and gains native operations as each API lands. Stock Krita support is frozen
  and dropped once the artist paints in the fork.
- Licence: the fork ships GPL-3.0-or-later; new files in Krita's libraries take that library's compatible licence
  (LGPL-2.0-or-later or GPL-2.0-or-later); MIT notices kept for included MIT code.
