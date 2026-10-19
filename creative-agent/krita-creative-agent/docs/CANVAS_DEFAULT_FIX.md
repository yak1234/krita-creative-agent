# Canvas default fix — 2026-09-13

Root cause: the native docker selected New painting during construction whenever no document was open. That hidden setting persisted when a document was opened later, and was sent as an explicit new-canvas request. New chat also retained the preceding conversation's creation choice.

The docker now always starts with Current canvas. New chat resets the target choice to Current canvas. New painting and Copy current painting remain available as explicit choices. Existing bound conversations are not silently redirected to another document.

Regression coverage in tests/ui_smoke.py constructs the panel with activeDocument() returning None, verifies a subsequent message uses current mode, and checks new chats reset both new and copy choices. The full Qt smoke suite passes.

Installed native file matches source, SHA256 1b6d0af8c5420850514239049066c46e4ed2d551f278cc5b817214cfe0f65657. This direct hotfix preserves the shutdown callback fix. No interaction with running Krita, no model request, and no painting modification were performed. Load on the next Krita restart; live verification remains pending. The already-misbound conversation still requires the existing Use this canvas as painting target action on Creative painting 5.kra.
