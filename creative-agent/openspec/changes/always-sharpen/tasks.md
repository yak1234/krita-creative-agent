# Always sharpen: tasks

## 1. Companion (goal-sharpen.ts, studio.mjs, settings-schema.mjs)

- [x] 1.1 Setting "Sharpen the goal": Always (default) / Ask / Never; tests/execution-settings, ui_smoke (PyQt5, PyQt6).
- [x] 1.2 Always: no offer or review card; an offered card or a waiting review in an existing chat is taken by itself.
- [x] 1.3 `waitForGoal({forWhat, signal, cancelled})`: ready / swapped / stopped; the swap happens while a move waits
      (nothing paints); progress "Sharpening the goal for the <step>: N%…", said again when a move starts waiting.
- [x] 1.4 `gate` (Plan Start, Autopilot) waits through `waitForGoal`; Stop holds the step ("Stopped while the goal image
      was sharpening").
- [x] 1.5 The goal-reading tools wait (outermost wrapper in buildTools); brushwork goal crops wait in brushworkHost.
      A call that waited through a swap returns "Nothing was painted… call again" with the new size.
- [x] 1.6 Estimate: megapixels x measured seconds per megapixel (goal-sharpen.json), default 140 s/MP, plus 5 s; shown on
      the Ask card and in Always's "sharpening it 4x on this Mac (about 4 min)" line.
- [x] 1.7 Early start: check() when a chat message starts (besides the folder opened and a goal attached).
- [x] 1.8 Tests fake the sharpener and the model (studio harnesses get a failing fake: no model downloads in tests).

## 2. Live check (the artist)

- [ ] 2.1 New Moscow (1448 x 1086 on 6000 x 4500): no card; the status line shows the sharpening for the underpainting;
      the underpainting starts only after it, from the sharpened goal.
- [ ] 2.2 Stop during the wait: nothing paints; the sharpening finishes in the background and is used.
- [ ] 2.3 The second run's estimate matches the measured time within about 20%.
