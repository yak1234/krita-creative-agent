# Stage One: Material — evaluation protocol

Status: **prepared, not yet run on the 0.2 candidate**. The user's original `painting.kra` must not be modified. A successful API call, an independent model review or a numerical texture score cannot establish artistic improvement.

## Known starting point

The source is the 768 × 1024 red color-field study. Its recorded original SHA-256 is `c6c2e8de7340c4c8000308d698313936e78184fda4ca8045d4e4246c448a219a`. It has a blurred upper orange-red field and lower crimson field, with prior dry marks and banding. Observe the actual document and compare its disk and live revision before making the working copy.

Stage One changes material in the upper-field core only: `[100,150,580,330]` in document coordinates. Composition, overall colour relationship, outer silhouette and the lower field are protected. The user supplied neighbours `#c0422a`, `#d2563a`, `#a52c1c`; sample the current field and report their relationship before treating that palette as suitable.

## Prerequisites

- UI, companion and native bridge report an identical current-source build ID.
- The source painting is open and independently identified by filename, dimensions and document ID.
- No other painting session owns a canvas; the existing chat is paused and preserved.
- The chosen route passes its read-only image/tool capability check. Record provider/model and allowances.
- Every run has a new test output directory. Retain failed trials and their errors.

## Calibration run

Use the standalone Node and companion belonging to the loaded release:

```sh
NODE scripts/evaluate-stage-one.mjs \
  --companion /path/to/loaded-release/companion \
  --output /path/to/new-evaluation-folder \
  --source /path/to/painting.kra \
  --provider openrouter --model deepseek/deepseek-v4.1-flash
```

`NODE` is a placeholder for that release's `runtime/bin/node`, not a shell environment requirement.

The script first asks “Do you see this painting?” with a freshly captured actual canvas and checks that Ask attempts no artwork mutation. It then creates a new working copy and allows exactly two calibration paint operations: two short strokes with **g) Dry Textured Creases**, and two with **g) Dry Bristles**, on separate named layers. Size is 60–80 pixels, stroke opacity 0.15–0.30, within the stated palette and region. It prohibits adjustment operations and verifies the new document identity before painting.

The paint-count ceiling prevents a third painting call, while the shared eight-minute allowance permits the final independent visual review. The stage must stop after calibration. Capture full-resolution images and the source revision afterward; the source document and original file must remain unchanged.

The report distinguishes completed trials, operation limits, stage review, reviewer acceptance and artistic success. A run can correctly stop with an unsuccessful artistic trial. Preserve that distinction.

## Compare the actual result

With Python plus Pillow available on the evaluation machine:

```sh
python scripts/compare-stage-one.py /path/to/evaluation-folder/evaluation.json
```

The script reads the two actual full-resolution snapshots and writes:

- `comparison.json`: exact changed-pixel counts inside/outside the allowed region, source-preservation flags, boundary flags, image hashes and build/model identity.
- `review.html`: a standalone before/after view at 100%, the upper-field crop at 100%, and thumbnail scale. It embeds the original snapshots and does not alter them.

**Zero changed pixels outside the permitted region is required.** Numerical change inside the region is descriptive only. Judge grain, dry breakup, stripes, seams, overall value and silhouette from the images. Record which preset/settings produced what, including visible failures.

## Material pass after calibration

Proceed only after calibration has been explicitly reviewed and a behaving brush chosen. This is a separate bounded stage on the test copy. Hide or reduce a failed trial through the guarded pass-review controls; retain the evidence.

Use low-opacity marks on a new named stage layer. Irregular gaps, varying lengths, diagonal wander, overlapping clumps and untouched patches should prevent a ladder or grid. Some marks may cross the field's horizontal flow. Preserve the sampled colour relationship; a new band of different colour is a failure.

Stop after one judgeable pass and inspect it at 100% and thumbnail scale. Success requires dry granular breakup and a softened interior tonal seam while the field remains one soft rectangle. The protected outer silhouette and lower field must be unchanged. If stripes appear, fade/reject the trial rather than adding more paint automatically.

## Reversal and interruption checks

On separate disposable copies, verify hide, strength, pass rejection and stage rejection. Add an independent manual layer after an agent pass and verify its bytes/visibility survive reversal. A later manual edit on the agent's own layer must disable automatic reversal with an explanation rather than discarding that work.

Interrupt during model waiting, native painting, saving and independent review. Record the final settled state and operation IDs. A repeated response may replay its saved result but must never paint twice. A lost outcome must stay quarantined until the artist inspects and explicitly acknowledges it.

## Result record

For each run record build, source hashes/revisions, model route, plan revision, exact allowance, brush parameters, actual images, outside-region differences, stopping state, visible strengths/failures and next correction. Mark artistic improvement only after visual comparison supports it. Do not change model weights or infer general expert-painting ability from one successful material study.
