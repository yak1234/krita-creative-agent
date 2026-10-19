#
#  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
"""Document.agentMove(name): an agent move as a context manager (Krita Agent).

    with document.agentMove("paint sky"):
        layer.paintPolylineStroke(points)

The move closes when the block ends, also when it raises, so a script error never leaves a move open.
"""

import contextlib
import warnings


@contextlib.contextmanager
def agent_move(document, name):
    """Opens an agent move on document for the block, and closes it after (an exception included).

    Only the move this block began is ended: if it was closed meanwhile (it closes by itself when the document is
    saved, when the artist undoes, or after a long pause, and continues with the script's next work) and another
    move has begun since, the block leaves that one open and warns.
    """
    if not document.beginAgentMove(name):
        raise RuntimeError(
            "agent move %r could not begin: another agent move or macro is open, or the document has no image"
            % name)
    move = document.agentMoveId()
    try:
        yield document
    finally:
        if document.agentMoveId() != move:
            warnings.warn("agent move %r was already closed; the move open now (%r) is left open"
                          % (name, document.agentMoveName()), RuntimeWarning, stacklevel=3)
        elif not document.endAgentMove():
            warnings.warn("agent move %r could not end (see Krita's log for the reason)" % name,
                          RuntimeWarning, stacklevel=3)


def install(document_class):
    """Adds agentMove(name) to the krita.Document class."""
    document_class.agentMove = agent_move
