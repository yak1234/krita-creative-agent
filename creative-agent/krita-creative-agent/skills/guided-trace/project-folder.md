# Guides in a project folder plan

When the artist works from a project folder, the approved plan has one move per step:

1. **Underpainting from the goal image (step 1).** The whole picture from the goal image with `paint_from_reference`
   (all of it onto the whole canvas). No guides: a guides step comes only when the artist asks for one, and then its
   name says so ("Guides: the whole composition").
2. **One element per move, back to front.** The goal image decides where the element sits; its element reference (the
   numbered file the move names) decides its shape and look. Where the two disagree on the angle, the goal wins. Paint
   the element in your own strokes over the underpainting, on a layer with the step's name; draw its guide first (named
   exactly as the move says) only when the artist asked for guides. Paint nothing else.
3. **Finish.** Call `finish_move` when the element reads as finished. When the artist keeps the move, the step is ticked
   in PLAN.md and any guide it had is hidden for you; do not call `finish_guide` for it. You may propose protecting the
   finished element (`propose_protection`); the artist decides.

Never place a reference as an image layer: the reference tools paint brush dabs from it, which is fine.
