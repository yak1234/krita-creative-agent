# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's plan list: per step, plain-word buttons coloured by meaning (plan-step-controls, the artist's mockup B; no
checkboxes or ticks to confuse with the features' boxes).

- before painting: Skip (grey); a skipped step is greyed and struck through, with Restore;
- the step that is painting: "✓ Good enough → next step" (green);
- a step whose move finished on its own: "✓ Met" (green) and "↺ Redo" (amber), Redo asking what to change (optional).

The companion decides each step's state (plan-steps.ts sends it as the goal event's plan_steps); this list shows it and
sends {'type': 'plan_step', 'id', 'action', 'step_key', 'text'?}. Every widget of the list is made here, so a restyle
touches this file only; the panel adds `PlanStepsList` to its plan bar and `plan_steps_stylesheet` to its stylesheet.
"""
import uuid
import weakref

from .qt_compat import sip

from .qt_compat import Qt, QTimer, QFrame, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy

# (action, label, object name for the colour, tooltip)
ACTIONS = {
    'open': [('skip', 'Skip', 'stepNeutral', 'Leave this step out: it is not painted. Restore brings it back.')],
    'skipped': [('restore', 'Restore', 'stepNeutral', 'Paint this step again when its turn comes.')],
    'painting': [('good_enough', '✓ Good enough → next step', 'stepMet',
                  'The batch in progress finishes, then nothing more is painted for this step and the next step starts.')],
    'finished': [('met', '✓ Met', 'stepMet', "Keep this step's move and go on to the next step."),
                 ('redo', '↺ Redo', 'stepRedo', "Undo this step's move and paint it again; you can say what to change.")],
}
SPOKEN = {'skip': 'Skip', 'restore': 'Restore', 'good_enough': 'Good enough, go to the next step after', 'met': 'Met:', 'redo': 'Redo'}
# (text, object name) shown on the step's second line
STATUS = {'painting': ('Painting', 'stepPainting'), 'finishing': ('Finishing the batch in progress…', 'stepPainting'),
          'finished': ('Finished', 'muted'), 'met': ('✓ Met', 'stepMetText'), 'good_enough': ('✓ Good enough', 'stepMetText'),
          'done': ('✓ Done', 'stepMetText'), 'skipped': ('Skipped', 'muted'), 'open': ('', 'muted')}
BUSY_ONLY = {'good_enough'}                 # only while the agent paints
IDLE_ONLY = {'met', 'redo'}                 # only once the move has ended


def sip_deleted(widget):
    try:
        return sip.isdeleted(widget)
    except Exception:
        return False


def step_actions(state):
    """The buttons a step in `state` offers: [(action, label, object name, tooltip)]."""
    return list(ACTIONS.get(state, []))


def plan_step_command(action, key, text=None):
    """The command for the companion, with a fresh id; text (Redo only) trimmed, and left out when blank."""
    command = {'type': 'plan_step', 'id': uuid.uuid4().hex, 'action': action, 'step_key': key}
    words = ' '.join(str(text or '').split())[:1000]
    if action == 'redo' and words:
        command['text'] = words
    return command


def step_colors(colors, dark):
    """Green (met, good enough) and amber (redo) for the theme: a button fill with its text, and a label colour for text
    on the panel's surface. All keep 4.5:1 contrast (tests/ui_panel_plan_steps.py)."""
    if dark:
        return {'met': '#2f7a4c', 'metText': '#ffffff', 'metHover': '#378d59', 'redo': '#9a5a12', 'redoText': '#ffffff', 'redoHover': '#ad6616',
                'metLabel': '#7fd19b', 'redoLabel': '#e8a54b'}
    return {'met': '#2a6e45', 'metText': '#ffffff', 'metHover': '#235d3a', 'redo': '#8a4f0e', 'redoText': '#ffffff', 'redoHover': '#74420c',
            'metLabel': '#256b3f', 'redoLabel': '#8a4f0e'}


def plan_steps_stylesheet(colors, dark):
    """The list's rules, appended to the panel's stylesheet (its font sizes are scaled with the rest)."""
    c = dict(colors, **step_colors(colors, dark))
    return '''
            QWidget#planStepsList { background: transparent; }
            QFrame#planStepRow { background: transparent; border: none; border-top: 1px solid %(border)s; }
            QLabel#stepTitle { font-size: 12px; }
            QLabel#stepSkipped { color: %(muted)s; font-size: 12px; }
            QLabel#stepNumber { color: %(muted)s; font-size: 11px; }
            QLabel#stepMetText { color: %(metLabel)s; font-size: 11px; font-weight: 600; }
            QLabel#stepRedoText { color: %(redoLabel)s; font-size: 11px; }
            QLabel#stepPainting { color: %(accent)s; font-size: 11px; }
            QPushButton#stepNeutral { background: %(raised)s; color: %(text)s; padding: 3px 9px; }
            QPushButton#stepMet { background: %(met)s; color: %(metText)s; font-weight: 600; padding: 3px 9px; }
            QPushButton#stepMet:hover { background: %(metHover)s; }
            QPushButton#stepRedo { background: %(redo)s; color: %(redoText)s; font-weight: 600; padding: 3px 9px; }
            QPushButton#stepRedo:hover { background: %(redoHover)s; }
            QPushButton#stepMet:disabled, QPushButton#stepRedo:disabled, QPushButton#stepNeutral:disabled { background: transparent; color: %(muted)s; border: 1px solid %(border)s; }
            QLabel#planStepsTitle { font-size: 12px; font-weight: 600; }
    ''' % c


class PlanStepsList:
    """The plan's steps, one row each: the number and title, then the state and its buttons. `show_steps` takes the goal
    event's plan_steps; `set_busy` follows the panel's busy flag (Good enough only while painting, Met / Redo after).
    It owns a plain QFrame (`widget`) and holds the panel's send weakly: a reference cycle between the panel and a list
    of Qt widgets was collected while Qt tore the panel down, and crashed the UI tests at exit."""

    def __init__(self, send):
        self.widget = QFrame(); self.widget.setObjectName('planSteps')
        self.widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.send = weakref.WeakMethod(send) if hasattr(send, '__self__') else (lambda: send)   # no cycle with the panel
        self.rows = []; self.busy = False; self.structure = None; self.builds = 0
        layout = QVBoxLayout(self.widget); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(2)
        header = QHBoxLayout(); header.setSpacing(6)
        self.title = QLabel('Steps'); self.title.setObjectName('planStepsTitle'); header.addWidget(self.title)
        self.summary = QLabel(''); self.summary.setObjectName('muted'); header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.list = QWidget(); self.list.setObjectName('planStepsList')
        self.list_layout = QVBoxLayout(self.list); self.list_layout.setContentsMargins(0, 0, 6, 0); self.list_layout.setSpacing(0)
        self.list_layout.addStretch(1)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(self.list); self.scroll.setMaximumHeight(280)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False); self.list.setAutoFillBackground(False)
        layout.addWidget(self.scroll)
        # The height is fitted once Qt has shown new rows: a timer the list's own frame owns, so it dies with the panel. A
        # QTimer.singleShot to this object's method could fire after the panel was gone and crashed the UI tests at exit.
        self.fit_timer = QTimer(self.widget); self.fit_timer.setSingleShot(True); self.fit_timer.setInterval(0)
        self.fit_timer.timeout.connect(self.fit_height)
        self.widget.hide()

    def isVisible(self):
        return self.widget.isVisible()


    @staticmethod
    def structure_of(rows):
        return tuple((str(r.get('key')), str(r.get('title')), str(r.get('state')), int(r.get('redone') or 0)) for r in rows)

    def show_steps(self, rows, busy=False):
        """Show the steps ({'index', 'key', 'title', 'state', 'redone'?}); rebuilt only when one changed, so an open Redo
        field keeps what the artist is typing while the companion publishes."""
        rows = [r for r in rows or [] if isinstance(r, dict) and r.get('key')]
        self.busy = bool(busy)
        if self.structure_of(rows) != self.structure: self.build(rows)
        else: self.set_busy(self.busy)
        self.widget.setVisible(bool(rows))

    def build(self, rows):
        self.builds += 1; self.structure = self.structure_of(rows)
        for row in self.rows:
            row['widget'].hide(); row['widget'].deleteLater()          # deleteLater: a button may be mid-click
        self.rows = []
        for entry in rows:
            self.rows.append(self.make_row(entry))
            self.list_layout.insertWidget(self.list_layout.count() - 1, self.rows[-1]['widget'])
        counts = {}
        for entry in rows: counts[entry.get('state')] = counts.get(entry.get('state'), 0) + 1
        met = sum(counts.get(s, 0) for s in ('met', 'good_enough', 'done'))
        parts = ['%d of %d met' % (met, len(rows))] + (['%d skipped' % counts['skipped']] if counts.get('skipped') else [])
        self.summary.setText(' · '.join(parts) if rows else '')
        self.set_busy(self.busy)
        self.fit_timer.start()                                  # once the new rows are shown (Qt shows them queued)

    MAX_HEIGHT = 280

    def fit_height(self):
        """A short list takes its rows' height at the panel's width; a longer one scrolls. The panel calls it when it is
        resized."""
        if sip_deleted(self.widget) or sip_deleted(self.scroll): return
        width = max(1, self.scroll.viewport().width())
        layout = self.list.layout()
        height = layout.heightForWidth(width) if layout.hasHeightForWidth() else -1
        if height < 0: height = self.list.sizeHint().height()
        self.scroll.setFixedHeight(max(24, min(self.MAX_HEIGHT, height + 2)))


    def make_row(self, entry):
        number, key, title, state = int(entry.get('index', 0)) + 1, str(entry['key']), str(entry.get('title') or ''), str(entry.get('state'))
        widget = QFrame(); widget.setObjectName('planStepRow')
        rows = QVBoxLayout(widget); rows.setContentsMargins(0, 5, 0, 5); rows.setSpacing(3)
        top = QHBoxLayout(); top.setSpacing(5)
        label = QLabel('%d.' % number); label.setObjectName('stepNumber'); label.setContentsMargins(0, 4, 0, 0); top.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(title); name.setTextFormat(Qt.TextFormat.PlainText); name.setWordWrap(True)
        name.setObjectName('stepSkipped' if state == 'skipped' else 'stepTitle')
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); name.setMinimumWidth(0)
        font = name.font(); font.setStrikeOut(state == 'skipped'); name.setFont(font)
        name.setContentsMargins(0, 3, 0, 0); top.addWidget(name, 1, Qt.AlignmentFlag.AlignTop); rows.addLayout(top)
        line = QHBoxLayout(); line.setSpacing(5)
        text, style = STATUS.get(state, ('', 'muted'))
        if entry.get('redone'):
            text = (text + ' · ' if text else '') + '↺ redone %d×' % int(entry['redone'])
            if style == 'muted': style = 'stepRedoText'
        status = QLabel(text, widget); status.setObjectName(style); status.setTextFormat(Qt.TextFormat.PlainText); status.setWordWrap(True)
        status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); status.setMinimumWidth(0)
        line.addWidget(status, 1)
        # Skip and Restore sit beside the title (struck through says skipped): one line per step that waits.
        compact = state in ('open', 'skipped') and not entry.get('redone')
        if compact: status.hide()
        row = {'key': key, 'state': state, 'widget': widget, 'title': name, 'status': status, 'buttons': [], 'editor': None, 'redo': None}
        for action, text, style, tip in step_actions(state):
            button = QPushButton(text); button.setObjectName(style); button.setToolTip(tip)
            button.setAccessibleName('%s step %d: %s' % (SPOKEN[action], number, title))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, a=action, r=row: self.press(r, a))
            (top if compact else line).addWidget(button, 0, Qt.AlignmentFlag.AlignTop); row['buttons'].append((action, button))
            if action == 'redo': row['redo'] = button
        if not compact: rows.addLayout(line)
        if row['redo']:
            row['editor'] = self.redo_editor(row, number); rows.addWidget(row['editor'])
        return row

    def redo_editor(self, row, number):
        editor = QWidget(); layout = QVBoxLayout(editor); layout.setContentsMargins(0, 2, 0, 0); layout.setSpacing(4)
        field = QLineEdit(); field.setPlaceholderText('What to change (optional)'); field.setMaxLength(1000)
        field.setAccessibleName('What to change in step %d (optional)' % number); layout.addWidget(field)
        buttons = QHBoxLayout(); buttons.setSpacing(5); buttons.addStretch(1)
        cancel = QPushButton('Cancel'); cancel.setObjectName('stepNeutral'); cancel.setAccessibleName('Cancel the redo of step %d' % number)
        confirm = QPushButton('↺ Redo step'); confirm.setObjectName('stepRedo'); confirm.setAccessibleName('Redo step %d now' % number)
        confirm.setToolTip("Undo this step's move and paint it again, with what you typed.")
        cancel.clicked.connect(lambda: (editor.hide(), field.clear(), self.fit_height()))
        confirm.clicked.connect(lambda: self.send_command(row, 'redo', field.text()))
        field.returnPressed.connect(lambda: self.send_command(row, 'redo', field.text()))
        buttons.addWidget(cancel); buttons.addWidget(confirm); layout.addLayout(buttons)
        editor.hide(); row['confirm'] = confirm
        return editor

    def press(self, row, action):
        if action == 'redo':                                    # first: what to change
            row['editor'].show(); row['editor'].findChild(QLineEdit).setFocus(); self.fit_height(); return
        self.send_command(row, action)

    def send_command(self, row, action, text=None):
        for _, button in row['buttons']: button.setEnabled(False)
        if row.get('confirm'): row['confirm'].setEnabled(False)
        if row['editor']: row['editor'].hide(); self.fit_height()
        send = self.send()
        if send: send(plan_step_command(action, row['key'], text))

    def set_busy(self, busy):
        """Good enough waits for painting; Met and Redo for the move to end; Skip and Restore any time. Also gives back the
        buttons a refused command left disabled."""
        self.busy = bool(busy)
        for row in self.rows:
            for action, button in row['buttons']:
                button.setEnabled(self.busy if action in BUSY_ONLY else not self.busy if action in IDLE_ONLY else True)
            if row.get('confirm'): row['confirm'].setEnabled(not self.busy)
