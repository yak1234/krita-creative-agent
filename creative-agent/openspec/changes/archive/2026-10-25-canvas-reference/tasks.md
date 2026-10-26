# Canvas reference: tasks

## 1. Companion

- [x] 1.1 `src/canvas-reference.ts` (strict): the command (`canvasReferenceRequest`, "in the <part>"), the edit prompt, the difference area (`differenceMask`, `canvasMask`), the side-by-side picture (`compareImage`), the card's flow (`canvasReferencer`: start, use, retry, discard; the upload notice once a chat; the wide-change warning) and the painter's note (`referenceMoveNote`). Verify: `tests/canvas-reference.test.mjs` (fake host, no network).
- [x] 1.2 `skill-commands.ts`: `/canvas-reference` (alias `/preview`) with `action: 'canvas_reference'`; `skills/canvas-reference/SKILL.md` for the painter; the prompt's trigger line (within its size cap). Verify: `skill-commands.test.mjs`, `brush-catalog.test.mjs`.
- [x] 1.3 `assets.mjs`: `requestAssetImage` (the backend the Image assets setting names, Codex by default) shared by make_asset and the canvas reference; `attachAsset`; `pngFromImage` (the sandbox converts a picture that is no plain PNG). `png-rgba.ts` `ignoreColour`. Verify: `assets.test.mjs`, `png-rgba.test.mjs`.
- [x] 1.4 `auto-approve.ts` `NEVER_AUTO_APPROVE` lists `canvas_reference`. Verify: `auto-approve.test.mjs`.
- [x] 1.5 `studio.mjs`: the command is answered before the painter; Use as the target attaches the reference as an asset, adopts the area (`adoptFoundArea`, auto `canvas-reference:<id>`; it stays for its move and a Keep that continues it, any other message ends it) and runs a move (`move_kind: canvas_reference`) with the note; Discard paints nothing. `main.mjs` routes `canvas_reference`. Verify: `tests/canvas-reference-studio.test.mjs` (fake bridge, fake Codex backend).
- [x] 1.6 Setting **Preview additions** (`preview_additions`, off): a plan's Add step about to paint waits for its canvas reference once (`holdForCanvasReference`); Use paints the step inside the area, Discard paints it as planned; with no AI image left it paints without one and says so. Verify: `execution-settings.test.mjs`, `canvas-reference-studio.test.mjs`.

## 2. Panel

- [x] 2.1 `creative_docker.py`: the `canvas_reference` card (`choice_card` with the picture and its notes always shown), answers sent once as `{type: canvas_reference, id, action}`; never offered to Auto-approve. `auto_approve.py` `NEVER` refuses it at any delay.
- [x] 2.2 `tests/ui_panel_canvas_reference.py` under PyQt5 and PyQt6, listed in `agent/ci.sh`.

## 3. Live (not run here)

- [ ] 3.1 Dostoevsky painting, Codex: `/canvas-reference add more ghosts and ghost-like lighting`; the card's picture and outline match the change; Use as the target paints only inside it (faces untouched); Undo removes the move.
- [ ] 3.2 `/canvas-reference more snow and crisp effects in the sky` with the shapes model ready: the area stays in the sky.
- [ ] 3.3 Tune the difference thresholds on real pictures: a Codex edit's re-rendered brushwork everywhere must not exceed ΔE 12 after the tone match (else the area covers the canvas and the card warns), and a real change must.
- [ ] 3.4 Preview additions on, a single-image plan with "Add: falling snow": the card before the step, the step painted inside its area.
