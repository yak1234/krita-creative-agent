# Always sharpen: the goal is sharpened before anything paints from it

Status: asked for by the artist (2026-10-25): "the underpainting waits for sharpening to finish and it's by default always".

## Why

Live, 2026-10-25, a 1448 x 1086 goal for a 6000 x 4500 canvas (4.1x smaller). The Sharpen card said "Your goal image is
4.1x smaller than the canvas… Sharpen it 4x on this Mac (about 20 s)?", then a review card asked "Use sharpened" /
"Keep original". The sharpening (Real-ESRGAN, `src/goal-sharpen.ts`) took 3.5-4 minutes, not 20 s. Painting was held
only until the artist answered the offer, so the underpainting started on the soft goal while the sharpening ran, and
the sharpened goal arrived after the move that needed it most.

## Goals

1. **Always by default.** The setting "Sharpen the goal" (execution settings, `sharpen_goal`): Always (the default),
   Ask, Never. Always: a goal (the folder's, or an attached goal of the canvas's proportions) smaller than the canvas by
   more than ENLARGEMENT is sharpened by itself (no offer card) and used by itself (no review card). Ask is today's
   cards. Never does neither. An existing chat with a card offered (or a result waiting for review) under Always takes
   it without asking.
2. **Painting waits.** Every move that reads the goal (paint_from_reference, continue_reference_painting, the edges and
   surface transfers, paint_finish, refine_to_goal, texture_architecture, paint_accents, paint_snow, and the goal crops
   of brushwork and dabs) waits for a sharpening in progress, its progress on the Now card and the status line
   ("Sharpening the goal for the underpainting: 44%…"). Plan Start during the sharpening: the first step waits rather
   than starting on the soft goal. Stop ends the wait (the sharpening goes on). A failure paints from the original,
   said once. A call written for the old pixels while it waited is told the new size and asked again.
3. **An honest estimate.** The time is the goal's megapixels at this computer's measured seconds per megapixel (recorded
   after each run in the companion's data folder, `goal-sharpen.json` `seconds_per_mp`, whatever provider it ran on),
   else a conservative default from the live run (1.6 MP in ~220 s: 140 s/MP), plus the model's load.
4. **As early as possible.** The sharpening starts as soon as the goal and the canvas are known: the folder opened, a
   goal attached, a chat's first message, in the background, so it is usually done by the time the plan is approved.
5. **Auto-approve.** Always shows no card, so there is nothing to answer; Ask keeps Auto-approve's current answers
   (Sharpen, Use sharpened).

## Not in scope

- A faster sharpening (tile size, provider choice).
- A per-chat override of the setting.
