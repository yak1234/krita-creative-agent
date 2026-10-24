# A project folder plan

When the artist works from a project folder, the approved plan has one move per step. By default it has two:

1. **Underpainting from the goal image (step 1).** The whole picture from the goal image with `paint_from_reference`
   (all of it onto the whole canvas). No guides: a guides step comes only when the artist asks for one, and then its
   name says so ("Guides: the whole composition").
2. **Accents (step 2).** `paint_accents` on the whole picture from the goal image: lights, glints, darks and lines, in
   the underpainting's own paint. No typed strokes over the underpainting.
3. **Then the artist decides.** The plan ends there and the host asks the artist what to refine next. The element
   images stay attached as references.

**An element step only when the artist asks for it** (by name, or by adding the step). The goal image decides where the
element sits; its element reference (the numbered file the move names) decides its look. Refine it where the
underpainting already has it: `paint_accents` on its area, Krita's layers and filters for light and colour, and only a
few small typed marks. Never repaint an element by hand unless the artist asks for hand-painted work. Draw its guide
first (named exactly as the move says) only when the artist asked for guides. Paint nothing else. The step is judged
against the goal image like any other: a batch that makes the canvas clearly less like it is undone.

**Finish.** Call `finish_move` when the step reads as finished. When the artist keeps the move, the step is ticked in
PLAN.md and any guide it had is hidden for you; do not call `finish_guide` for it. You may propose protecting a finished
element (`propose_protection`); the artist decides.

Never place a reference as an image layer: the reference tools paint brush dabs from it, which is fine.
