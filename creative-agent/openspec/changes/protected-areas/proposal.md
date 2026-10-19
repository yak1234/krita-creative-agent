## Why

The agent sometimes paints where it should not. On New Moscow a finishing run's first move was a whole-canvas
reference transfer that stamped dabs over the finished painting. The fix so far is a blunt guard: on an existing
painting a transfer may cover at most 20% of the canvas. It guesses what matters instead of asking, it refuses work
the artist actually wants (repainting the New Moscow sky, about a third of the canvas), and it covers transfers only:
a brush pass, a fill or a filter can still change anything.

The artist knows what must not change. Krita can hold that as a shape (a selection mask, saved in the file), but this
plugin is for people who want to direct Krita through an agent and may not know Krita's selection tools. So the panel
makes protecting an area as easy as asking for it.

## What Changes

- **A Protected areas section in the panel**, listing each protected area by name with show (👁) and remove (✕).
- **Three ways to add one, easiest first:**
  - **Ask the agent**: "Protect the woman and the car". The agent marks the area, shows it in red, and asks
    **Keep / Adjust / Discard**. Nothing is protected until the artist keeps it.
  - **Paint over it**: the brush paints red protection on the painting; the eraser removes it. The painting's pixels
    are not changed.
  - **Use my selection**: the current Krita selection becomes a protected area.
- **Locked layers are protected automatically** and listed.
- **Enforced by the plugin on every painting operation**, not requested of the model: whatever the agent paints inside
  a protected area is removed before the operation completes.
- **The agent says so right away**: a chat line names the area and how much of the pass was kept out, and the painter
  is told in the tool result.
- **Protection replaces the 20% guard** on paintings that have a protected area.

## Capabilities

- Protected areas: the artist marks areas of the painting the agent must never change, from the panel, in words, by
  painting, or from a selection; the plugin enforces it on every operation and reports each hit.

## Impact

- `krita-mcp/krita-plugin/kritamcp/creative_tools.py`: one enforcement step after every mutating operation; the hit
  report in the result.
- New plugin module for protected areas: reading, creating and removing them in the document; the paint-over mode.
- `creative_docker.py`: the Protected areas section, Keep / Adjust / Discard, the hit line in the transcript.
  **Needs a Krita restart.**
- `krita-creative-agent`: a `propose_protection` tool, protection in the painter's context, the hit message, and
  `transferRefusal` lifting its size caps on a painting with protection.
