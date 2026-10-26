# Eyes and history: views the models read, close-ups, a history that does not abort moves

Status: APPROVED by the artist (2026-10-24: "you need to hurry up 1-3 please").

## Why

The artist's chats of 2026-10-23/24 show the painter seeing less than we send and losing moves to bookkeeping:

- Pi shrinks every image over 2000 px on a side (its per-model image resize), so the 2048 px view choice was silently
  shrunk; DeepSeek shrinks the painter's images server-side to about 1.69 MP, so a larger whole view adds nothing.
- The resolution probe misread models whose provider caches the image (Anthropic through OpenRouter reported 4 input
  tokens at every size), so claude-haiku-5.5 was labelled "reads 1024" although it scored 10/10 up to 2560.
- A slow history compaction counted as a silent model: the 90 s watchdog aborted the move ("This operation was
  aborted", three times in one chat).
- An observe over its text limit lost the whole layer list and the revision (40 times in 7 chats).
- Undone agent passes stay as hidden layers (46-81 layers in a chat).
- "The painting changed since the last observation" stopped Agent moves (9 times in 6 chats).

## Goals

1. **Views capped at 2000 px**: the view size choices and Auto stop at 2000 (a saved 2048 becomes 2000); the probe caps
   the recommended view there too.
2. **Close-ups of the area being worked**: when an Agent move works in an area (Paint only here, a region or box its
   calls pass, an observe region), each whole-canvas observe also carries up to 2 crops of that area at canvas
   resolution (each at most the painter model's measured crop side, default 1536), labelled with their rectangle and
   scale. Older crops leave the history with the other images.
3. **Probe fixes**: tokens are input + cache read + cache write; without tokens, cost growth decides; sizes 1280 and
   1792 are probed; four painter models re-measured and recorded (sides capped at 2000).
4. **Compaction is not silence**: the model watchdog pauses while Pi compacts the history.
5. **Shorter history**: tool results older than the last few turns reach the model as one line (the session keeps them).
6. **No layer blindness**: an observe over its limit keeps a compact layer index (then top-level layers and counts),
   the revision, document id, size; never the bare stub.
7. **Fewer layers**: when the artist keeps a move, the hidden passes of earlier undone moves (agent layers only) are
   removed, as Keep already does for the kept move's own leftovers.
8. **A changed painting does not stop the move**: every native result's revision refreshes the expected revision; in
   an Agent move a `canvas_changed` re-observes and hands the painter the fresh canvas with a note.

## Not in this change

Plan stages, the planner model, painting_tool_help's size and the compaction threshold (agent/plan-request).
