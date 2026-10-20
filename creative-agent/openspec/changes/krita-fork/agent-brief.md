# Standing rules for agents working on the fork

The lead pastes a task-specific brief; these rules apply to every task. They come from this fork's reviews.

## Looking things up
- **Krita master (C++ and libkis): read the source.** The fork's tree is the truth (`libs/libkis/*.h` doc comments, `AGENT-FORK.md`,
  `git log`/`git blame`). No online reference has our additions or master's changes.
- **Qt 6 and PyQt6 differences (Qt5 to Qt6 ports, scoped enums, removed classes such as QRegExp/QStringRef/QDesktopWidget, signal
  and slot changes): use Context7**, which has the Qt 6.8 and 6.5 documentation and PyQt6:
  `npx -y ctx7@latest library qt "<question>"` then `npx -y ctx7@latest docs /websites/doc_qt_io_qt-6_8 "<question>"`;
  `npx -y ctx7@latest library pyqt6 "<question>"`. Check a Qt claim there before relying on memory; say in the report which
  lookups mattered. (Library ids: Qt 6.8 `/websites/doc_qt_io_qt-6_8`, Qt 6.5 `/websites/doc_qt_io_qt-6_5`, PyQt6
  `/websites/riverbankcomputing_static_pyqt6`, Krita Python API `/websites/apidoc_krita_maou-maou_fr` (a mirror of the
  RELEASED stock API: it lacks the fork's additions).)
- **Never write version numbers from memory:** read them from the tree or the tool.

## Running things
- C++ tests only through `agent/run-tests.sh` (never `_build/bin/<test>` directly); builds only through `agent/build-macos.sh`
  (never Homebrew's ninja on `_build`: it deletes `.ninja_log`); `CMAKE_BUILD_PARALLEL_LEVEL` at most 6, `nice -n 19`.
- Python: `uv run -q --with pyqt5 --with pillow --with numpy --with httpx --with opencv-python-headless python -m unittest discover
  -s tests -p 'test_*.py'` from `creative-agent/krita-creative-agent`; JS: `npm run -s test:unit` and `npm run -s typecheck`.
- A test must FAIL cleanly, never segfault or open a dialog: QVERIFY every pointer and bool; no iterators from temporaries;
  stubs return valid empty values. After each run look at `ls -t ~/Library/Logs/DiagnosticReports | head -3`.
- Scratch files only under the session scratchpad's own folder for the task; tests delete what they write.
- Never launch the Krita GUI or touch running Krita apps; never open or write the artist's paintings (use a copy).

## Writing code
- Never end the artist's open strokes (`setRequestsOtherStrokesToEnd(false)`), never `image->waitForDone()` in a libkis call,
  bounded waits only, a timed-out operation is cancelled, one undo step or part of an agent move.
- Never trust input: NaN/inf/huge numbers, empty lists, wrong types, duplicate names, OverflowError from `math.isfinite(10**400)`.
- The artist's own painting must be unaffected: nothing on a hot path, nothing registered in core code.
- Keep upstream edits minimal and list each in AGENT-FORK.md. Licence headers: libkis LGPL-2.0-or-later; libs/image and libs/ui
  GPL-2.0-or-later; our scripts, plugin and companion GPL-3.0-or-later; copyright Yakub Rabiutheen. No AI attribution in commits.
- Commit after each green item (a stall must never lose work). Do not stop to ask: make rulings and list them.
