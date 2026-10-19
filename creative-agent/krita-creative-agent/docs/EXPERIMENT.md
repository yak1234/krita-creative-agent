# Construction versus execution experiment

## Question

Can the same DeepSeek model execute a supplied visual construction more successfully than it can derive a construction independently from the reference?

Use a Rothko-inspired two-field color study as a narrow first task. Evaluate relationships between the fields, their margins and spacing, color hierarchy, layering, and edge variation. Native textured strokes alone do not establish success.

## Pair of trials

Hold constant the model/provider, thinking setting, reference image, canvas dimensions, brush catalog, task instruction, and limits. Use a fresh Pi session and a separate new Krita study for each trial.

1. **Guided:** attach the reference plus a separately prepared construction map. Choose **Follow a construction map**. The map should mark major field boundaries and margins, with a small palette and a few explicit edge intentions. Record who authored it.
2. **Independent:** attach the same reference and choose **Plan from a reference**. The companion excludes construction maps from this session. Ask the model to determine field placement and proportions from the image.

Review each construction before texture becomes the dominant source of visual differences. Give the same type of localized correction to each completed study, then compare whether the result visibly improves.

## Common task

> Make a layered native-brush study of the attached color-field painting. Establish its large field proportions, margins, spacing and color hierarchy first. Add restrained interior variation and deliberately varied edges. Inspect each checkpoint and correct the largest visible error. Finish after a coherent study and one revision; report the main remaining weakness.

## Evidence and assessment

Keep both `study.json` manifests, Pi session logs, reference files, and all checkpoints. Record provider/model, elapsed time, number of model turns, painting passes, errors, and saved artifacts. Do not compare two runs that changed several important conditions as if they were a controlled model benchmark.

Score each item 0–2, supported by visible evidence:

| Item | 0 | 1 | 2 |
|---|---|---|---|
| Field proportions and spacing | Major mismatch | Partly controlled | Close to intended relationships |
| Value and color hierarchy | Relationships obscured | Partly convincing | Deliberate and coherent |
| Layering and edges | Flat or uniformly blurred | Some variation | Controlled variation supporting the composition |
| Self-critique | Misses main error | Identifies it vaguely | Identifies a specific visible error |
| Correction | Worsens or misses the error | Partial improvement | Clear localized improvement |

Assess tool reliability separately: unknown arguments, wrong-document refusal, completed saves, actual image delivery, and interruptions. A returned `ok` is not an artistic score. Human review is the acceptance criterion; pixel measurements can support geometric checks.

## Interpretation

- Better guided construction suggests planning is a larger bottleneck than execution.
- Poor execution of a clear supplied map points toward tool use, instruction following, or an inadequate map.
- Accurate critique followed by ineffective changes isolates correction as a separate weakness.
- Repeat with unfamiliar proportions and palettes before claiming the ability transfers.

This protocol is implemented in the panel, but the paired artistic experiment is only complete when both runs and their visual reviews are recorded. A functional plugin demonstration does not count as that evaluation.
