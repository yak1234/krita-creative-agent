# Plan step controls: Skip, Good enough → next step, Met / Redo

Status: APPROVED by the artist (2026-10-23, from a brainstorm with mockups: "yes that's good").

## Why

A plan is approved as a whole today: Start painting runs every step, and the artist's only per-step tools are editing
the table or keep/undo after a move. Live chat 34deca0e (2026-10-23) shows the cost: the plan held a step "Soften the
foreground into readable masses…" that repainted a finished underpainting by hand. And the painter does not always know
when a step is done; the artist does.

## Decided by the artist

- **No checkboxes or ticks** (two kinds of tick would confuse): plain-word buttons, coloured by meaning (mockup B).
- **Before painting**: each step has **Skip**; a skipped step is greyed and struck through, with **Restore**. Start
  painting runs only the steps not skipped.
- **While a step is painting**: that step shows **✓ Good enough → next step**. Pressing it lets the batch in progress
  finish (never mid-stroke), paints nothing more for that step, marks it met by the artist, and starts the next step
  that is not skipped.
- **After a step finishes on its own**: **✓ Met** (keep it, go on) and **↺ Redo** (undo it and try again; the artist
  may type what to change). These are the existing keep/undo of a move, shown on the step.
- Colours: green for met/good enough, amber for redo, grey for skipped and neutral buttons; Toska Night and Day themes.

## Goals

1. The panel's plan list shows the controls above per step, in both themes, readable at the panel's narrow width.
2. The companion honours them: skipped steps never run (and the planner does not re-add them); "good enough" ends the
   current move after the running batch and starts the next step in Agent mode, and in Autopilot moves on to the next
   step; Met/Redo map to keep/undo of that step's move.
3. The project folder's `PLAN.md` records skipped, met (by the artist or by "good enough") and redone steps; a resumed
   chat restores them.
4. Every "good enough" and "redo" is recorded as a lesson (step, time, batches so far, Luna's last verdict and, when
   built, the goal-likeness score) for later tuning; nothing is sent anywhere.

## Non-goals

- No change to how the painter plans steps (a rule against "repaint into masses" steps is a separate, unapproved fix).
- No new review model; Luna's checks stay.

## Done when

On a copy of the New Moscow folder: a plan step can be skipped before painting and never runs; "Good enough → next step"
during the underpainting move's follow-up ends it and starts the next step; Met and Redo work after a step; PLAN.md and
a resumed chat show the same state. Panel UI tests under PyQt5 and PyQt6.

## Left to the builder

Layout details, wording of tooltips, where the lesson records live in the chat folder.
