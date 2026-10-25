# Layer plan: tasks

## 1. Met merges — branch agent/layer-plan
- [x] 1.1 Why it did not merge (LIVE 2026-10-25, New Moscow 6000x4500: 146 layers, 10.1 GiB after Underpainting, Finish and one refine step): `merge_kept` is on by default and Keep / Met called `merge_passes` for the move, but the plugin merged only runs of adjacent plain `paint_pass` layers; Finish and accents groups, transfers' craft layers, blended or clipped layers and the hidden leftovers between them broke every run, so nothing merged
- [x] 1.2 Plugin: `merge_passes` `whole` merges the stage's own group into one paint layer in its place, named (fork: `Document.mergeGroups`, as Krita renders it; stock: the group's projection copied); only a visible, unlocked, normal, not pass-through group holding only the agent's layers and no guides; else the runs as before; every pass inside points to the merged layer (goal 4)
- [x] 1.3 Hidden leftovers go: a whole merge drops the move's hidden rejected passes and replaced originals with it; `tidy_kept` also removes the stage groups it leaves empty (an undone move's group no longer stays behind) (goal 5)
- [x] 1.4 Companion: Keep and Met send `whole`; a plan step's layer is named after the step ("Underpainting", "Finish", "Refine: Domed church…", an element's name), a move outside the plan keeps "Move N · title" (`kept-layers.ts`)
- [x] 1.5 Undo: Redo / Undo of the current unkept move still rejects it per pass; a kept move is one pass (Met means kept)

## 2. Underpainting locked
- [x] 2.1 Met on the underpainting step merges it into one "Underpainting" layer, locked (`lock`); the next move paints in its own group above it (goal 1)

## 3. The painter sees the stack
- [x] 3.1 One line in the painter's context before each move (`layer_stack`): the top-level layers bottom to top (the 12 nearest the top, the rest counted), group sizes and hidden counts, locked layers, and the group this move paints in (goal 6). The observation's layer list (eyes-and-history) is unchanged

## 4. Measured offline
- [x] 4.1 Plugin suite on a fake Krita: one move of 12 nodes (strokes, a blended layer, a Finish group, an accents group, a rejected pass) becomes 1 layer (13 nodes in the painting before, 2 after)
- [x] 4.2 The live stack's shape through painting_weight's estimate (layer metadata, every layer at the full 6000x4500 bounds, an upper bound): 144 nodes, 36 groups, 108 paint layers, about 15.5 GB before; 4 layers, about 0.4 GB after. Krita measured 10.1 GiB before (it stores only painted tiles). Krita's undo history keeps the merged-away layers until those steps leave it, so the memory falls as the history moves on or when the painting is reopened

## 5. Left for later (reported)
- [ ] 5.1 One group per element or plane and clipped light / shadow layers (goals 2, 3): not cheap on top of the merge (the painting tools place their own layers and groups); each kept move is already one named layer
- [ ] 5.2 Value check layer (goal 7) and automatic snapshots (goal 8): snapshot time and memory need the live Toska measurement on a 6000x4500 copy before building; not built

## 6. Release
- [ ] 6.1 Live check in Toska on a copy of the New Moscow folder: Underpainting Met (one locked "Underpainting" layer), Finish Met, a refine step Met (one layer each), Redo of an unkept move, layer count and Krita memory before and after; then reviews, merge, CI, publish, package, install
