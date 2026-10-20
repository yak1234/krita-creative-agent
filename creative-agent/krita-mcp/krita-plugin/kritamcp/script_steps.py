"""One undo step for a loop of Krita calls (krita-fork 2.9).

In the Krita Agent fork every libkis pixel write (`Node.setPixelData`) is an undo step, and a loop of them would flood
the artist's history and purge their redo stack once per strip. `one_step(doc, name)` wraps such a loop in one agent
move, so it is one step, "Agent: <name>". On stock Krita (no agent moves), inside a move that is already open
(the loop joins it), or while a macro is open (a move cannot begin), it does nothing.
"""
import contextlib


@contextlib.contextmanager
def one_step(doc, name):
    begin = getattr(doc, 'beginAgentMove', None)
    if begin is None or doc.agentMoveOpen():
        yield
        return
    if not begin(name):
        yield
        return
    move = doc.agentMoveId()
    try:
        yield
    finally:
        if doc.agentMoveId() == move:    # still the move this block began
            doc.endAgentMove()
