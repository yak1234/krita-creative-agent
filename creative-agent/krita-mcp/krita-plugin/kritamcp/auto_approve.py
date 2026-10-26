# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto-approve (openspec auto-approve; the artist, 2026-10-25: "an auto approve mode, it's standard in agentic systems";
"when I record it I'd love the options automatically selected"). A card that waits for the artist is offered here with
its default answer; after the Auto-approve delay (the companion's setting: Off, Immediately, 10, 30 or 60 s) the answer
is taken by the same path its button takes, unless the artist acts first. The countdown shows on the card's own labels
and the status line, every second.

One card counts down at a time, with one exception: a card of a kind in BESIDE (Keep on a custom effect build) counts in
its own lane beside it, so it never displaces a move's or a plan step's countdown nor is displaced by one (nothing waits
for it; the artist, custom-effects). The status line shows the main card's countdown while one counts. `cancel` is any
artist action (Undo, Redo, Stop, typing, sending, a card button, editing the plan): every counting card then waits for
the artist and is never offered again (`declined`). A card is answered at most twice
(a refused Met is offered once more, never a loop). `ready` holds the answer back (Met waits while the agent paints) and
`still` drops a card the companion closed meanwhile. The owner (the panel) is held weakly and passed to `act`, `ready` and
`still`, so no closure keeps the panel alive (a cycle between the panel and its widgets crashed UI tests at exit). The panel decides which cards are offered and with what; this
module never knows a card's meaning. The clock is a plain function, so tests advance it by hand and call `tick`."""
import math
import time
import weakref

from .qt_compat import sip, QTimer

DELAYS = (0, 10, 30, 60)
# Cards never answered here, whatever the delay: a canvas reference (canvas-reference.ts) is the artist's own choice of
# what the painting becomes (the companion's auto-approve.ts NEVER_AUTO_APPROVE keeps the same list).
NEVER = ('canvas_reference',)
# Cards answered no sooner than this many seconds, whatever the delay: Keep on a custom effect build adds to the artist's
# library (effects/policy.yaml auto_keep_min_seconds; the card's own auto_keep_seconds, when sent and longer, is used).
AT_LEAST = {'effect_build': 20}
# Cards that count in their own lane, beside the one main countdown (moves, plan steps, chat cards).
BESIDE = ('effect_build',)
LANES = ('main', 'beside')
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
        self.lanes = dict.fromkeys(LANES); self.declined = set(); self.answers = {}; self.answering = False
        self.timer = QTimer(owner); self.timer.setInterval(250); self.timer.timeout.connect(self.tick)

    @property
    def pending(self):
        """The main lane's card (moves, plan steps, chat cards), or None."""
        return self.lanes['main']

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

    def offer(self, key, kind, answer, doing, hint, act, labels=(), ready=None, still=None, card=None, at_least=None):
        """Count down for card `key` ({kind, answer, card} is what the diagnostics record; `card` defaults to the key);
        `act(owner)` answers it as its button would. A card already counting keeps its countdown; another replaces it.
        It is answered after the delay, or after max(AT_LEAST for its kind, `at_least`) seconds when that is longer. A
        BESIDE kind counts in its own lane and replaces only a card in that lane."""
        if kind in NEVER or not self.offers(key): return False
        lane = 'beside' if kind in BESIDE else 'main'
        current = self.lanes[lane]
        if current and current['key'] == key: return True
        self.drop(lane)
        self.lanes[lane] = {'key': key, 'kind': kind, 'answer': answer, 'doing': doing, 'hint': hint, 'act': act, 'labels': list(labels),
                        'ready': ready or (lambda owner: True), 'still': still or (lambda owner: True), 'card': card or key, 'since': self.clock(),
                        'at_least': max(AT_LEAST.get(kind, 0), at_least or 0)}
        self.timer.start(); self.tick(answer=False)            # answered by the timer, never inside the panel's event
        return True

    def counting(self, key=None, lane='main'):
        """Whether card `key` counts (in any lane), or with no key whether a card counts in `lane`."""
        if key is None: return bool(self.lanes[lane])
        return any(p and p['key'] == key for p in self.lanes.values())

    def cancel(self):
        """The artist acted: every counting card waits for them, and is not offered again. An answer Auto-approve gives
        goes through the same handlers as the artist's (a move's Keep), so it cancels nothing."""
        counting = [p for p in self.lanes.values() if p]
        if not counting or self.answering: return
        self.declined.update(p['key'] for p in counting); self.drop()
        self.show_status('Auto-approve stopped for this card: it waits for you.')

    def drop(self, lane=None):
        """The countdown in `lane` (every lane by default) taken away; the card waits."""
        dropped = []
        for name in (LANES if lane is None else (lane,)):
            if self.lanes[name]: dropped.append(self.lanes[name])
            self.lanes[name] = None
        if not any(self.lanes.values()): self.timer.stop()
        for pending in dropped: self.set_labels(pending, '')
        if dropped and not self.lanes['main']: self.show_status('')      # the status line shows the main card first

    @staticmethod
    def set_labels(pending, text):
        for label in pending['labels']:
            if label is None or sip.isdeleted(label): continue
            label.setText(text); label.setVisible(bool(text))

    def tick(self, answer=True):
        for lane in LANES:
            self.tick_lane(lane, answer)

    def tick_lane(self, lane, answer=True):
        pending, owner = self.lanes[lane], self.owner()
        if not pending or not self.on: return
        if owner is None or not pending['still'](owner):
            self.drop(lane); return
        remaining = pending['since'] + max(self.delay, pending['at_least']) - self.clock()
        if remaining > 0 or not pending['ready'](owner) or not answer:
            text = (countdown_text(pending['doing'], pending['hint'], remaining) if remaining > 0 or pending['ready'](owner)
                    else 'Auto-approve: %s when the painting in progress ends' % pending['doing'])
            self.set_labels(pending, text)
            if lane == 'main' or not self.lanes['main']: self.show_status(text)
            return
        self.drop(lane)                                       # first: the answer's own hooks see nothing to cancel
        self.answers[pending['key']] = self.answers.get(pending['key'], 0) + 1
        owner.auto_answered({'kind': pending['kind'], 'answer': pending['answer'], 'delay': self.delay, 'card': pending['card']})
        self.answering = True
        try: pending['act'](owner)
        finally: self.answering = False
