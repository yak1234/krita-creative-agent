# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's Paint only here (element-scoped-painting goal 1; the artist, 2026-10-23), above the message box.

  * "Paint only here" captures the document's current selection (its pixels: Freehand, Magnetic, any selection tool) as the
    chat's one area: the plugin protects the rest of the painting (paint_only_here.py) and the companion keeps the area
    (paint-only-here.ts). Without a selection it switches to the Freehand Selection tool and says what to do.
  * The chip "Painting only inside: <name or your selection>" with ✕ to clear it. A new Paint only here replaces the area.
  * Typing "paint only in my selection" with a selection does the same, sent with that message.
  * The painter's question for one part (ask_for_selection): Select with Freehand, Use my selection (once a selection
    exists), Paint everywhere.
  * The document follows the chat: a resumed chat's area is put back from the companion's mask file and a protection no chat
    holds is removed (never while the agent writes). The protection is a transient feature, outside the undo history, so
    none of this touches the artist's Undo and Redo; the bridge puts it back before an agent write if it is gone.

The panel calls this through a few hooks (creative_docker.py); its own state is the pending area (no chat yet) and what it
sent last, so a goal event that crosses a just-sent change does not undo it.
"""
import os
import uuid

from krita import Krita

from .creative_document_identity import document_id
from .paint_only_here import AREAS, selection_bounds, wants_area, write_mask
from .qt_compat import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTimer, QVBoxLayout, QWidget

FREEHAND, MAGNETIC = 'KisToolSelectOutline', 'KisToolSelectMagnetic'
CHIP = 'Painting only inside: %s'
HINT = 'Draw around the area, then press Paint only here again. The Magnetic Selection tool snaps to edges.'


class PaintOnlyBar(QWidget):
    def __init__(self, panel, areas=AREAS):
        super().__init__()
        self.panel, self.areas = panel, areas
        self.pending = None                               # the area to send with the next message (no chat yet, or an answer)
        self.awaiting = None                              # 'set' or 'clear' sent, until a goal event shows it
        self.cards = []                                   # Use my selection buttons waiting for a selection
        column = QVBoxLayout(self); column.setContentsMargins(0, 0, 0, 0); column.setSpacing(3)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(1)
        self.button = QPushButton('◌  Paint only here'); self.button.setObjectName('contextChip')
        self.button.setAccessibleName('Paint only here')
        self.button.setToolTip('Select an area in Krita (Freehand, Magnetic or any selection tool), then press this: the agent paints '
                               'only inside it until you clear it.')
        self.button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.button.setMinimumWidth(0)
        self.button.clicked.connect(self.press); row.addWidget(self.button, 1)
        self.chip = QPushButton(''); self.chip.setObjectName('paintOnlyChip')
        self.chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.chip.setMinimumWidth(0)
        self.chip.setToolTip('Krita keeps the agent out of the rest of the painting. Select another area and press Paint only here '
                             'to replace it; ✕ to paint everywhere again.')
        self.chip.clicked.connect(self.press); row.addWidget(self.chip, 1)
        self.clear_button = QPushButton('✕'); self.clear_button.setObjectName('contextAction')
        self.clear_button.setAccessibleName('Paint everywhere again'); self.clear_button.setToolTip('Clear the area: paint everywhere again')
        self.clear_button.clicked.connect(self.clear); row.addWidget(self.clear_button)
        column.addLayout(row)
        self.hint = QLabel(''); self.hint.setObjectName('contextHint'); self.hint.setWordWrap(True); column.addWidget(self.hint)
        self.chip.hide(); self.clear_button.hide(); self.hint.hide()
        self.timer = QTimer(self); self.timer.setInterval(700); self.timer.timeout.connect(self.watch_selection)

    # ----- the document --------------------------------------------------------------------------------------------------
    def document(self):
        try:
            return self.panel.protection_document()
        except (AttributeError, RuntimeError, ReferenceError):
            return None

    def has_selection(self, doc=None):
        doc = doc if doc is not None else self.document()
        try:
            return doc is not None and selection_bounds(doc.selection(), doc) is not None
        except (AttributeError, RuntimeError, ReferenceError):
            return False

    def chat_document(self, doc):
        """Whether `doc` is the painting the chat paints (a restored area goes only there)."""
        target = (getattr(self.panel, 'painting_target', None) or {}).get('document_id')
        try:
            return not target or document_id(doc) == target
        except (AttributeError, RuntimeError, ReferenceError):
            return False

    @staticmethod
    def choose_tool(name):
        tool = Krita.instance().action(name)
        if tool is not None: tool.trigger()

    def say(self, text):
        self.panel.status.setText(text)

    # ----- the button, the chip and its ✕ -------------------------------------------------------------------------------
    def press(self):
        doc = self.document()
        if doc is None:
            self.say('Open your painting, select an area, then press Paint only here.'); return
        if not self.has_selection(doc):
            self.choose_tool(FREEHAND)
            self.hint.setText(HINT); self.hint.show(); self.say('Freehand Selection tool: draw around the area.'); return
        command = self.capture()
        if command: self.deliver(command)

    def capture(self, name=None):
        """The document's selection as the area, protected at once. Returns the companion's set command, or None."""
        doc = self.document()
        reason = self.panel.agent_writing_reason(doc)
        if reason is not None:
            self.say(reason); return None
        try:
            area = self.areas.capture(doc, doc.selection(), name)
            path = write_mask(area, os.path.join(self.panel.pasted_folder(), 'creative-paint-only-%s.png' % uuid.uuid4().hex))
        except (ValueError, OSError) as error:
            self.say(str(error)); return None
        self.show_area(area['name'])
        self.panel.refresh_features()
        return {'action': 'set', 'mask_path': path, 'bounds': area['bounds'], 'canvas': [doc.width(), doc.height()], 'name': area['name']}

    def set_pending(self, command):
        """The area waiting for the next message; a mask file it replaces is deleted."""
        old = (self.pending or {}).get('mask_path')
        if old and old != (command or {}).get('mask_path'):
            try: os.remove(old)
            except OSError: pass
        self.pending = command

    def deliver(self, command):
        if self.panel.study_active:
            self.awaiting = 'set'; self.panel.send(dict(command, type='paint_only_here'))
        else:
            self.set_pending(command)
        self.say(CHIP % (command['name'] or 'your selection') + ('' if self.panel.study_active else ' (from your next message)'))

    def clear(self):
        doc = self.document()
        reason = self.panel.agent_writing_reason(doc) if doc is not None else None
        if reason is not None:
            self.say(reason); return
        if doc is not None: self.areas.clear(doc)
        self.set_pending(None); self.hide_area()
        if self.panel.study_active:
            self.awaiting = 'clear'; self.panel.send({'type': 'paint_only_here', 'action': 'clear'})
        self.panel.refresh_features(); self.say('Painting everywhere again.')

    def show_area(self, name):
        """The chip for an area (None: the artist's selection, unnamed)."""
        self.chip.setText(CHIP % (name or 'your selection')); self.chip.setAccessibleName(self.chip.text())
        self.chip.show(); self.clear_button.show(); self.button.hide(); self.hint.hide()

    def hide_area(self):
        self.chip.hide(); self.clear_button.hide(); self.button.show()

    # ----- a message -----------------------------------------------------------------------------------------------------
    def for_message(self, text):
        """The area to send with a message: the typed phrase with a selection captures it; else an area waiting for a chat."""
        command = self.capture() if wants_area(text) and self.has_selection() else None
        if command: self.set_pending(None)                # the typed area replaces one waiting
        command, self.pending = command or self.pending, None
        if command: self.awaiting = 'set'                 # goal events before the message's own do not show it yet
        return command

    # ----- the chat ------------------------------------------------------------------------------------------------------
    def sync(self, goal):
        """A goal event: show the chat's area, and make the document follow it."""
        area = (goal or {}).get('paint_only_here')
        if self.awaiting == 'set' and not area or self.awaiting == 'clear' and area:
            return                                        # an older event crossing what was just sent
        self.awaiting = None
        doc = self.document()
        writing = doc is None or self.panel.agent_writing_reason(doc) is not None
        if area:
            if not writing and self.areas.area(doc) is None and self.chat_document(doc):
                try:
                    self.areas.restore(doc, area)                 # a resumed chat: the area back from the companion's mask
                except (OSError, ValueError, KeyError) as error:
                    self.say('Paint only here could not be restored: %s' % error)
            self.show_area(area.get('name'))
        elif self.pending is None:
            if not writing: self.areas.clear(doc)
            self.hide_area()

    def chat_ended(self):
        self.areas.clear_all()                            # every document the chat set an area on, not only the active one
        self.set_pending(None); self.awaiting = None; self.cards = []; self.timer.stop()
        self.hide_area(); self.hint.hide()

    def poll(self):
        """The canvas poll (with or without the companion): a resumed chat's area is put on its painting once it is open, and
        a protection no area holds goes. Never a re-add of a protection the document lost: the bridge does that right before
        an agent write."""
        doc = self.document()
        if doc is None or self.panel.agent_writing_reason(doc) is not None: return
        chat_area = (self.panel.goal or {}).get('paint_only_here')
        try:
            if self.areas.area(doc) is not None: return
            if chat_area and self.awaiting is None:
                if self.chat_document(doc): self.areas.restore(doc, chat_area)
            elif self.pending is None and self.awaiting is None: self.areas.drop_stale(doc)
        except (ValueError, RuntimeError, AttributeError, OSError, KeyError):
            pass

    def update_controls(self):
        self.button.setEnabled(self.panel.protection_editing is None)

    # ----- the painter's question ----------------------------------------------------------------------------------------
    def select_card(self, event):
        """ask_for_selection's question: Select with Freehand, Use my selection (once a selection exists), Paint everywhere."""
        part = (event.get('select_area') or {}).get('part') or 'the area'
        item = self.panel.transcript.add_message('A quick question', event['question'])
        item['card'].setObjectName('questionMessage')
        controls = []
        for text in event.get('options') or ():
            button = QPushButton(text); button.setObjectName('questionChoice')
            button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            if text == 'Select with Freehand':
                button.setToolTip('Choose Krita’s Freehand Selection tool and draw around %s. The Magnetic Selection tool snaps to edges.' % part)
                button.clicked.connect(lambda _checked=False, part=part: self.start_selecting(part))
            elif text == 'Use my selection':
                button.setToolTip('Paint only inside the area you selected')
                button.setEnabled(self.has_selection()); self.cards.append(button)
                button.clicked.connect(lambda _checked=False, part=part, all_=controls: self.use_selection(part, all_))
            else:
                button.clicked.connect(lambda _checked=False, value=text, all_=controls: self.answer(value, all_))
            item['layout'].addWidget(button); controls.append(button)
        note = QLabel('Or write your own answer below.'); note.setObjectName('muted'); item['layout'].addWidget(note)
        self.timer.start()
        return controls

    def start_selecting(self, part):
        self.choose_tool(FREEHAND)
        self.hint.setText('Draw around %s, then press Use my selection. The Magnetic Selection tool snaps to edges.' % part); self.hint.show()

    def watch_selection(self):
        """Use my selection is enabled once the document has a selection."""
        ready = self.has_selection()
        for button in self.cards: button.setEnabled(ready)
        if not self.cards: self.timer.stop()

    def use_selection(self, part, controls):
        command = self.capture(part)
        if command: self.answer('Use my selection', controls, command)

    def answer(self, text, controls, command=None):
        for button in controls: button.setEnabled(False)
        self.cards = [b for b in self.cards if b not in controls]
        self.hint.hide()
        self.set_pending(command)
        self.panel.prompt.setPlainText(text); self.panel.submit()
