# Auto-approve: cards that wait take their default after a countdown

Status: requested by the artist (2026-10-25), built on branch `agent/auto-approve`; the live check is open.

## Why

The artist (2026-10-25): "add an auto approve if undo is not selected after 1 minute or something so it works more
automated … when I record it I'd love the options automatically selected"; "in general an auto approve mode, it's
standard in agentic systems".

An Agent-mode plan stops at every finished step ("Finished · keep it?"), at every move outside a plan, at the Sharpen
goal offer and at some questions. For a demo video the whole plan should run hands-free, and viewers should see what
would be chosen: each pause counts down visibly, then takes the default.

## Goals

1. A setting **Auto-approve**: Off (default) · Immediately · 10 s · 30 s · 60 s, declared once in `settings-schema.mjs`
   with the other execution settings, and a quick **Auto-approve** switch beside the panel's status line (always on
   screen) that turns it on with the last delay chosen, else 60 s. A switch made while painting is saved at the next pause.
2. Each card that waits for the artist takes its default answer after the delay, by the same path as its button:
   a finished plan step (also after a move's size limit) → Met; a move outside a plan (also limited) → Keep; the Sharpen
   goal offer → Sharpen, its review → Use sharpened; a question or close-up question → its `recommended` option only
   (the companion marks one where a default is safe; none marked: the card waits).
3. Any artist action stops the countdown and the card waits for them: Undo, Redo, Stop, typing or sending a message,
   any card button, editing the plan. A card stopped this way is not offered again.
4. The countdown shows on the card (the Now card, the move card, the chat card) and the status line:
   "Auto-approve: Keeping in 42 s — Undo or type to stop".
5. Every auto-answer is recorded in the diagnostics (`auto_approve`: card kind, answer, delay, card id).

## Non-goals

- Start painting is never pressed: the artist starts the run.
- Nothing destructive or irreversible is auto-answered: deleting or discarding the artist's work or protections,
  overwriting or closing documents, downloads or spending outside the normal model calls (the shapes model download,
  studying a big folder), accepting a requirement change.
- Autopilot needs nothing: it already runs on.
- No countdown on Krita's own Undo (Ctrl+Z on the canvas): only the panel's buttons.

## Done when

Unit tests (companion) and panel UI tests under PyQt5 and PyQt6 pass with a fake clock; on a copy of the New Moscow
folder, with Auto-approve at 10 s, Start painting runs the plan to its end without a click, each pause visibly counting
down, and a press of Undo or Redo during a countdown leaves that card waiting.

## Left to the builder

Wording, where the switch sits, which question cards recommend an option (listed in tasks.md).
