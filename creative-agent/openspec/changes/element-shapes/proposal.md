# Element shapes

Status: PROPOSED (2026-10-21), for the artist's OK. Follows guided trace and developed guides (both merged).

**Amended by crisp-accents (2026-10-23, the artist):** visible tracing is removed. Goal 1 (`draw_guide from_reference` with `shape`) goes with tracing. Shapes
on the painting (passes inside a shape, protection from a shape) stay, and `paint_accents` may use an element's
shape as its area when the shapes model is already allowed.

## Why

Guides traced from a rectangle of the reference pick up everything inside it: the tower's box also holds clouds and the
buildings behind. The painter model places things by eye and is weak at exact positions and sizes. A test on a copy of
the New Moscow goal image (scratch, 2026-10-21) gave each element's exact pixels from one rough box:

| Model | Disk | First look at an image | Each element | Peak memory | Skyscraper cluster | Car | Tower |
|---|---|---|---|---|---|---|---|
| EdgeTAM | ~40 MB | 0.11 s | 12 ms | ~0.3 GB | 0.46 (grabs clouds) | 0.84 | 0.91 |
| SAM 2.1 base-plus | ~330 MB | 1.3 s | 12 ms | ~1.6 GB | 0.72 (towers only) | 0.95 | 0.96 |

(Scores are each model's own estimate of its mask; the pictures agreed. Apple M-series CPU, ONNX Runtime.)

## Words

An element's **shape** is the set of pixels that belong to one named element (the tower, the moon). It is computed, kept
with the chat, and turned into things Krita already has: guide lines, a selection while painting, a protected area. It is
never a layer and never a Krita mask (transparency, filter or selection mask); the panel and the agent say "shape", not
"mask".

## Decided by the artist

- **SAM 2.1 base-plus finds every shape used for guides and tracing.** No smaller model is used for that.
- **One model for everything** (artist, 2026-10-21): reference shapes, guides, selections, protection and the later
  canvas checks all use base-plus, so a check compares like with like. EdgeTAM stays only an option if a check ever has
  to run many times inside one move.
- **Time is measured, in small tests and especially live**: every shape and every check records how long it took and
  its peak memory; the numbers reach the diagnostics and the live test reports.
- The model is chosen once and kept for the chat; shapes are computed once and cached. Nothing switches model because
  the Mac is busy: a busy Mac makes it slower, never different.
- No silent fallback: if finding shapes fails twice, the panel says so and what to do.
- Accelerators: ONNX Runtime with CUDA (NVIDIA, Linux), DirectML (Windows), the CPU everywhere else. On a Mac the CPU
  is the default: CoreML was slower for EdgeTAM and failed on SAM 2.1 (an ONNX Runtime CoreML shape error). PyTorch
  (and so MPS) is not bundled.
- Luna keeps judging meaning and quality; shapes give geometry. Neither replaces the other.

## Goals

**Phase 1: shapes for guides, selections and protection.**
1. `draw_guide` `from_reference` gains `shape: {box: [x,y,w,h]} | {points: [[x,y,label]...]}` on the reference. The guide
   is the traced outline of that shape (plus inner structure inside it), only lines, as today.
2. A shape on the painting itself turns into a Krita selection for one painting call ("paint inside the moon"), then is
   dropped.
3. Proposing protection for a finished element uses its shape; the artist still confirms with one click.
4. Guided-trace instructions: one box (or points) per element; a group (a skyline) is one box per member.

**Phase 2 (after phase 1 is used live): checks on the canvas, with base-plus.**
5. Placement check after a move on a named element: its shape on the canvas against its shape in the reference
   (offset, size, overlap), given to the painter as numbers. Skipped and noted when the canvas is too loose (low score).
6. Painted-over check: a kept element's shape shrinking sharply is evidence for Luna's existing automatic Undo.

## Non-goals

- No "segment everything": only elements the plan or the painter names.
- No shape is ever painted onto the canvas, and no reference pixels reach it (the artist's rule).
- The reference tools stay as they are.

## How it runs (builder's guidance; open to the reviewer)

- In the companion, in a short-lived worker process, so the 1.6 GB peak is freed right after; ONNX Runtime's Node
  package (`onnxruntime-node`) with the per-platform providers above. The package is about 300 MB with every platform's
  binaries; the app bundle keeps only its own platform's (about tens of MB).
- The model is downloaded on first use into the app's data folder, from `onnx-community/sam2.1-hiera-base-plus-ONNX` at a
  pinned revision (`bab18593f44e652f04cf18b60b3690f60e8996b0`) with checksums, after the panel shows its size (~330 MB);
  SAM 2.1 is Apache-2.0. *My call*: download rather than bundle, so Toska's download stays the same size.
- A reference is studied once per chat (the image encoder, ~1.3 s); each shape is then ~12 ms; shapes are cached in the
  chat folder by reference hash and prompt.

## Left to the builder

The worker protocol, the cache format, how a shape becomes a selection in the plugin, and the exact contour tracing (the
developed-guides tracing code is the starting point).
