# Guides in a project folder plan

When the artist works from a project folder, the approved plan has one move per step:

1. **Block-in (step 1).** Guides for the whole composition from the goal image: eye level, vanishing lines and the
   block-in of every element where the goal places it. Then a reference colour pass from the goal image. Name the guide
   for the step ("Block-in: the whole composition").
2. **One element per move, back to front.** The goal image decides where the element sits; its element reference (the
   numbered file the move names) decides its shape and look. Where the two disagree on the angle, the goal wins. Draw the
   element's guide first, named exactly as the move says, then paint the element over it in your own strokes on a layer
   with the step's name. Paint nothing else.
3. **Finish.** Call `finish_move` when the element reads as finished. When the artist keeps the move, the step is ticked
   in PLAN.md and its guide is hidden for you; do not call `finish_guide` for it. You may propose protecting the
   finished element (`propose_protection`); the artist decides.

Never place a reference as an image layer: the reference tools paint brush dabs from it, which is fine.
