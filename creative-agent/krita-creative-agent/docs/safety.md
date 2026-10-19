# Safety: what the agent may change

The agent paints alongside the artist. These rules hold for every operation. They are enforced in the Krita plugin, not only in the painter's instructions.

## The artist's layers

- **Never repainted, moved, renamed or regrouped.** New work goes on layers the agent creates. Editing existing paint (`painting_toolbox` with `source_layer_id`) works on a copy, and the original is hidden. Rejecting the pass shows the original again.
- **Opacity and visibility only.** On any unlocked layer, `adjust_layer` and `set_layer` may change opacity and visibility. Every other setting can change only on layers the agent created:
  - blend mode;
  - alpha lock;
  - clipping;
  - name;
  - layer style.
- **Never filtered.** `apply_filter` refuses an artist layer as its target. To grade a whole area, the agent puts a filter layer inside one of its own groups. The filter then affects only what is below it in that group.
- **Never transformed.** `transform_layer` moves only the agent's own layers.
- **Clipping through masks.** A live clip (Krita's inherit alpha) clips to everything below it in its group. So when the agent clips to an artist layer, it adds a transparency mask to its *own* layer instead. The mask is made from the artist layer's alpha at that moment. The artist layer keeps its parent, position, pixels and properties.
- **Read only.** Selections from layer alpha, colour-range selections and `colorize_flats` read the artist's line art without changing it. The colorize helper is a copy the agent owns.

## The artist's selection and view

- **Selection.** `select` saves selections to the study folder. Fills and filters use those selections directly and never set the document's selection. A brush pass limited to a region restores the artist's selection afterwards.
- **Guides.** Composition guides are a view aid. The artist's own guides are saved first and come back when the chat ends.
- **Following the artist.** Selected layers and colours are read for context and never changed.

## Every change is reversible and recorded

- **Recorded first.** An operation is recorded before its first change. A crash leaves an uncertain outcome that blocks painting until someone inspects the canvas and acknowledges it. An interrupted operation is never repeated automatically.
- **Reject undoes the pass.** Each pass can be rejected:
  - a new layer, mask or filter is hidden;
  - a copy is hidden and its original shown again;
  - a `set_layer` change puts back every earlier setting, including the layer style.

  Agent mode's Undo rejects the whole move.
- **The artist's later edits win.** If the artist edits a layer after the agent's pass, rejecting that pass is refused rather than overwriting their work.

## Not covered

These rules protect the document's structure and the artist's layers. They don't judge artistic quality. A pass can follow every rule and still be a poor painting decision, which is what the independent review and the artist are for.
