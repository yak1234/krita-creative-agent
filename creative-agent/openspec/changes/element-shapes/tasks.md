# Element shapes: tasks

Spec: `proposal.md`. Rules: tests first; companion modules strict TypeScript; plugin through `qt_compat`; no C++; the
reference tools unchanged; shapes never reach the canvas as pixels. Speed and memory are measured in tests and live.

## Phase 1

- [x] 1.1 **Shape worker** (companion, `src/shapes/`). A short-lived child process runs ONNX Runtime (`onnxruntime-node`)
  with base-plus: `study(imageHash, pixels)` once, then `shape(prompt) -> {mask, score, bounds}`. Providers in order:
  CUDA on Linux, DirectML on Windows, CPU (Mac default). Every call returns `{ms, peak_mb, provider}`. Tests with a
  tiny fixture model or a fake runtime; one opt-in benchmark test (skipped unless the model is present) on a copy of a
  real reference that asserts the timings stay under budget (study ≤ 3 s, shape ≤ 50 ms on a Mac M-series CPU) and
  prints them.
- [x] 1.2 **Model download** on first use into the app's data folder: pinned revision, checksums, size shown in the panel
  first, resumable, refused on a checksum mismatch. The model chosen is recorded on the chat; no fallback model. Tests
  with a local fake server.
- [x] 1.3 **Cache**: shapes kept in the chat folder by (reference hash, prompt); a repeat prompt never re-runs the model.
- [x] 1.4 **Guides from a shape**: `draw_guide` `from_reference` gains `shape: {box} | {points}`; the outline (and inner
  structure inside the shape) is traced with the existing tracing code; only lines reach the plugin. Tests: a synthetic
  tower inside a cluttered box gives lines on the tower only.
- [x] 1.5 **Selection from a shape** for one painting call on the painting itself (plugin: shape to Krita selection,
  restored afterwards, one undo step with the call). Tests in the plugin suite.
- [x] 1.6 **Protection from a shape**: `propose_protection` may carry a shape; the artist still confirms.
- [x] 1.7 **Failure handling**: one retry, then a plain panel message ("Finding shapes ran out of memory. Close some apps and
  try again."); never another model. (Done with one departure, recorded in AGENT-FORK.md: out of memory is not retried.)
- [x] 1.8 **Skill text**: guided-trace says one box or a few points per element, one box per member of a group; the word
  "shape", never "mask", in anything the artist reads.
- [ ] 1.9 **Timings live**: each shape and selection logs `{ms, peak_mb, provider}` to diagnostics and the test driver's
  report; the live test on a copy of the New Moscow scene records them. (Logging and the driver's `shape_timings` done and
  tested; the live New Moscow run is still to do.)

## Phase 2 (after phase 1 is used live)

- [ ] 2.1 Placement check after a move on a named element (canvas shape against reference shape: offset, size, overlap),
  skipped and noted when the score is low.
- [ ] 2.2 Painted-over check feeding Luna's automatic Undo.
- [ ] 2.3 Both checks report their time per move; budget ≤ 3 s per move on a Mac M-series CPU, measured live.
