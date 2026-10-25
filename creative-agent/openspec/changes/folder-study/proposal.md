# Folder study: a short note per image, the images opened on demand

Status: APPROVED by the artist (2026-10-24: "no go ahead please").

## Why

A project folder's planner and painter know its images by their file names (`04-kremlin-towers.png` -> "Kremlin towers")
and by a generation prompt when the folder has one. The planner sees only the goal image; the painter sees the goal and
the current step's element. Neither knows what the other elements show (their colours, shapes, where they sit in the
goal) unless every image is sent every turn, which is slow, costly and fills the context. A cheap vision model can read
each image once and write a short note; the notes travel as text, and an image is opened only when the agent needs it
(`view_reference`, as Cursor opens a file). Luna (the decision model) keeps its yes/no judging jobs; this does not
replace it.

## Goals

1. **Setting.** "Study folder images" (a generic panel setting in settings-schema.mjs): On (default) / Off. Off is
   today's behaviour (file names only).
2. **Small folders (at most 20 images).** The study runs by itself when the folder is attached to the chat, 4 images at a
   time; a line on the folder card shows "Studying N images… k/N" with a Stop button.
3. **Big folders (more than 20).** A card asks: ● Study only what the plan uses (the goal and the images the plan's
   steps refer to; default, with an estimated cost and time) ○ Study all N (estimate) ○ Let me pick… (the folder's image
   list with checkboxes; the choice remembered for that folder) ○ Don't study. "Only what the plan uses" studies the
   rest lazily, when the agent opens an image.
4. **Folder tab.** Each image shows studied ✓ / not studied / excluded; a right-click menu has Study / Exclude (and
   Include again). An excluded image is never sent to any model (painter, planner, Luna, study): it is not attached to
   the chat.
5. **The note.** Per image, kept in the chat's own data folder (never in the artist's folder), keyed by the image's
   content hash so it is redone only when the image changes: what it shows; where it sits in the goal image when it is
   part of it (rough position); key colours, shapes and details; about 60-120 words. The planner and painter read the
   notes as text (the study context's `folder`, studio `folderContext()`); `view_reference` opens an image when needed
   and studies it then when it has no note yet (lazy).
6. **Which model.** The chat's painter model when it reads images, else the Planner model when it reads images, else
   the recommended vision model `openrouter/qwen/qwen3-vl-235b-a22b-instruct` (measured 2026-10-24: reads up to 2560 px,
   10/10 at 2048 and 2560; about $0.0008 a 2048 px image). Through Pi's model runtime (`completeSimple`, as
   scripts/resolution-probe.ts calls models); images at most 2000 px on the long side (the Pi resize cap). 4 at a time,
   a timeout per image; a failed image is just "not studied" and is retried on demand. Cost and latency go to the
   diagnostics.

## Done when

The unit, plugin and panel suites pass; one real study of the New Moscow fixture folder (a copy) with qwen3-vl through
OpenRouter reports its time, cost and sample notes; and, in Toska on a copy (the lead), opening the folder studies its
13 images with the progress line, the plan turn's context carries the notes, Exclude keeps an image away from every model,
and a 21-image folder shows the choice card.
