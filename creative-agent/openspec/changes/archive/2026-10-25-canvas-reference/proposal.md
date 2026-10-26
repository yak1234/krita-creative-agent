# Canvas reference: see an edit before it is painted

Status: requested by the artist (2026-10-25: "yes please"), built on branch `agent/canvas-reference`; the live check is open.

## Why

The artist (2026-10-25): "a skill … slash command /canvas-reference, it uses the chatgpt image generation to take image
of canvas say dostoevsky's painting … what would happen if we added more ghosts, ghost-like lighting, or more snow and
crisp effects … not make the edits but make a reference generation of what the edit would look like. That way the agent
has a visual of what it would look like"; "codex is default" (the image asset backend).

Today an addition (snow, ghosts, a light) is painted from words alone: the painter guesses what it should look like,
and the artist sees it only after a move has painted it. An image model can show the change on the painting itself
first, and that picture is a far better target for the painter than a sentence.

## Goals

1. `/canvas-reference <instruction>` (alias `/preview`; "in <part>" at the end, e.g. "… in the sky", limits it to Find
   it's outline of that part, else the whole canvas): the canvas as the painter sees it goes to the image backend the
   **Image assets** setting names (Codex by default, OpenRouter otherwise) as an edit. The prompt keeps everything else
   identical: composition and framing, figures and faces, style and brushwork, palette, and the light except where the
   change asks for it. The studio answers the command; the painter never reads it as a request.
2. A card beside the chat: the canvas and the reference side by side, the changed area outlined in red, with
   **Use as the target** / **Try again** / **Discard**. It is never answered by Auto-approve. Try again is a new picture
   from the same instruction; each picture counts against the chat's AI image allowance (checked before anything is sent).
   Discard drops it and paints nothing.
3. Use as the target: where the reference differs from the canvas becomes the move's Paint only here area (Krita blocks
   every write outside it, so faces and everything else stay), and a move paints toward the reference there
   (`paint_from_reference` over the whole canvas, only the dabs inside the area, then `paint_accents`). The card shows
   the area's share of the canvas; over 60% it warns that the model changed a lot and suggests a narrower instruction or
   an area.
4. In plans: the setting **Preview additions** (off by default). On, a plan's "Add: <thing>" step shows its canvas
   reference before it paints, once a step; Use paints the step toward it inside its area, Discard paints it as planned.
5. The first canvas reference of a chat says in its card where the canvas was sent (ChatGPT through the Codex sign-in,
   or an OpenRouter image model).

## The difference area

At the comparison size (the canvas view, at most 1024 px on its long side), in `src/canvas-reference.ts`:
the reference is scaled to the canvas view; its tone is matched to the canvas (each channel shifted by its median
difference, then fitted by gain 0.8–1.25 and offset over the pixels the shift found unchanged), so a picture the model
made warmer or lighter everywhere changes nothing; both are box-blurred (0.4% of the long side) and compared in CIELAB;
ΔE76 ≥ 12 differs; pieces and holes smaller than 0.2% of the picture are cleaned away; the area grows by 1% of the long
side (at least 3 px); with a part, only what lies inside it. At canvas size it is the Paint only here mask (nearest pixel),
cropped to its bounds.

## Non-goals

- The reference is never pasted into the painting: it is a target the painter repaints with brushes.
- No canvas reference in Autopilot's own run; no reference for a whole new painting (that is the goal image).
- No new image backend: the image asset backends and their prompts' rules are reused.

## Done when

The artist types `/canvas-reference add more ghosts and ghost-like lighting` on the Dostoevsky painting, sees the card
with both pictures and the outlined change, presses Use as the target, and the move paints the ghosts and their light
where the reference shows them while the faces and the rest stay as they were.
