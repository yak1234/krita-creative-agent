# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto-approve (openspec auto-approve; the artist, 2026-10-25: "an auto approve mode, it's standard in agentic systems";
"when I record it I'd love the options automatically selected"). A card that waits for the artist is offered here with
its default answer; after the Auto-approve delay (the companion's setting: Off, Immediately, 10, 30 or 60 s) the answer
is taken by the same path its button takes, unless the artist acts first. The countdown shows on the card's own labels
and the status line, every second.

One card counts down at a time. `cancel` is any artist action (Undo, Redo, Stop, typing, sending, a card button, editing
the plan): the card then waits for the artist and is never offered again (`declined`). A card is answered at most twice
(a refused Met is offered once more, never a loop). `ready` holds the answer back (Met waits while the agent paints) and
`still` drops a card the companion closed meanwhile. The owner (the panel) is held weakly and passed to `act`, `ready` and
`still`, so no closure keeps the panel alive (a cycle between the panel and its widgets crashed UI tests at exit). The panel decides which cards are offered and with what; this
module never knows a card's meaning. The clock is a plain function, so tests advance it by hand and call `tick`."""
import math
import time
import weakref

from .qt_compat import sip, QTimer

DELAYS = (0, 10, 30, 60)
MAX_ANSWERS = 2


def delay_of(value):
    """The delay in seconds the setting's value means, or None (Off, or anything the setting never offers)."""
    return value if type(value) is int and value in DELAYS else None


def countdown_text(doing, hint, remaining):
    """The words on the card: "Auto-approve: Keeping in 42 s — Undo or type to stop"."""
    if remaining <= 0: return 'Auto-approve: %s now' % doing
    return 'Auto-approve: %s in %d s — %s' % (doing, math.ceil(remaining), hint)


class AutoApprove:
    def __init__(self, owner, clock=time.monotonic):
        """`owner` shows the countdown on its status line (show_auto_status(text)) and records each answer
        (auto_answered(card))."""
        self.owner = weakref.ref(owner); self.clock = clock; self.delay = None
        self.pending = None; self.declined = set(); self.answers = {}
        self.timer = QTimer(owner); self.timer.setInterval(250); self.timer.timeout.connect(self.tick)

    @property
    def on(self):
        return self.delay is not None

    def set_delay(self, value):
        """Off drops the countdown (the card waits); another delay counts from when the card was offered."""
        self.delay = delay_of(value)
        if not self.on: self.drop()
        else: self.tick(answer=False)

    def forget(self):
        """A new chat: nothing is pending, declined or answered any more."""
        self.drop(); self.declined.clear(); self.answers.clear()

    def offers(self, key):
        return self.on and key not in self.declined and self.answers.get(key, 0) < MAX_ANSWERS

    def show_status(self, text):
        owner = self.owner()
        if owner is not None: owner.show_auto_status(text)

    def offer(self, key, kind, answer, doing, hint, act, labels=(), ready=None, still=None, card=None):
        """Count down for card `key` ({kind, answer, card} is what the diagnostics record; `card` defaults to the key);
        `act(owner)` answers it as its button would. A card already counting keeps its countdown; another replaces it."""
        if not self.offers(key): return False
        if self.pending and self.pending['key'] == key: return True
        self.drop()
        self.pending = {'key': key, 'kind': kind, 'answer': answer, 'doing': doing, 'hint': hint, 'act': act, 'labels': list(labels),
                        'ready': ready or (lambda owner: True), 'still': still or (lambda owner: True), 'card': card or key, 'since': self.clock()}
        self.timer.start(); self.tick(answer=False)            # answered by the timer, never inside the panel's event
        return True

    def counting(self, key=None):
        return bool(self.pending) and (key is None or self.pending['key'] == key)

    def cancel(self):
        """The artist acted: the card waits for them, and is not offered again."""
        if not self.pending: return
        self.declined.add(self.pending['key']); self.drop()
        self.show_status('Auto-approve stopped for this card: it waits for you.')

    def drop(self):
        pending, self.pending = self.pending, None
        self.timer.stop()
        if pending: self.set_labels(pending, ''); self.show_status('')

    @staticmethod
    def set_labels(pending, text):
        for label in pending['labels']:
            if label is None or sip.isdeleted(label): continue
            label.setText(text); label.setVisible(bool(text))

    def tick(self, answer=True):
        pending, owner = self.pending, self.owner()
        if not pending or not self.on: return
        if owner is None or not pending['still'](owner):
            self.drop(); return
        remaining = pending['since'] + self.delay - self.clock()
        if remaining > 0 or not pending['ready'](owner) or not answer:
            text = (countdown_text(pending['doing'], pending['hint'], remaining) if remaining > 0 or pending['ready'](owner)
                    else 'Auto-approve: %s when the painting in progress ends' % pending['doing'])
            self.set_labels(pending, text); self.show_status(text)
            return
        self.drop()                                           # first: the answer's own hooks see nothing to cancel
        self.answers[pending['key']] = self.answers.get(pending['key'], 0) + 1
        owner.auto_answered({'kind': pending['kind'], 'answer': pending['answer'], 'delay': self.delay, 'card': pending['card']})
        pending['act'](owner)
