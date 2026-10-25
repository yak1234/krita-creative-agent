# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's plan: per step, plain-word buttons coloured by meaning (plan-step-controls, the artist's mockup B; no
checkboxes or ticks to confuse with the features' boxes), in three places (the artist's panel layout B, 2026-10-23):

- `strip`: one segment per step under the panel's header (green met, grey skipped, purple painting, neutral open), the
  step's title on hover or tap;
- `now`: the Now painting card above the tabs, so the step that paints and its buttons are on screen whatever the list
  or the conversation shows: the step's number, title, element image and batch, with Good enough and Stop; Met and Redo
  once its move has finished; the next step when none paints;
- `widget`: the Plan tab's list, the current step highlighted, the met and passed skipped steps folded into one summary
  row that expands. It never scrolls itself: the tab scrolls (one scroll area per tab, no nested scroll bars).

The buttons, by the step's state:
- before painting: Skip (grey); a skipped step is greyed and struck through, with Restore;
- the step that is painting: "✓ Good enough → next step" (green), and Stop on the card;
- a step whose move finished on its own: "✓ Met" (green) and "↺ Redo" (amber), Redo asking what to change (optional).

The companion decides each step's state (plan-steps.ts sends it as the goal event's plan_steps); this list shows it and
sends {'type': 'plan_step', 'id', 'action', 'step_key', 'text'?}. Every widget of the list is made here, so a restyle
touches this file only; the panel places the three widgets and adds `plan_steps_stylesheet` to its stylesheet.
"""
import html
import os
import uuid
import weakref

from .qt_compat import (pyqtSignal, Qt, QEvent, QSize, QRect, QColor, QPainter, QImageReader, QPixmap, QToolTip, QFrame, QWidget, QLabel, QPushButton,
                        QLineEdit, QVBoxLayout, QHBoxLayout, QSizePolicy)

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
BUSY_ONLY = {'good_enough', 'stop'}         # only while the agent paints
IDLE_ONLY = {'met', 'redo'}                 # only once the move has ended
CURRENT = ('painting', 'finishing', 'finished')        # the step the Now painting card shows
DONE = ('met', 'good_enough', 'done')
# The card's first line, by state; and each state in words for the strip's tooltips.
CAPTION = {'painting': 'Now painting', 'finishing': 'Finishing', 'finished': 'Finished · keep it?', 'open': 'Up next'}
WORDS = {'open': 'to paint', 'skipped': 'skipped', 'painting': 'painting', 'finishing': 'finishing its batch',
         'finished': 'finished, waiting for Met or Redo', 'met': 'met', 'good_enough': 'good enough', 'done': 'done'}
THUMB = QSize(56, 42)


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
    # The strip's segments: met and painting keep 3:1 against the panel (graphics, WCAG 1.4.11); skipped and open are
    # the panel's own muted and raised greys, open outlined.
    if dark:
        return {'met': '#2f7a4c', 'metText': '#ffffff', 'metHover': '#378d59', 'redo': '#9a5a12', 'redoText': '#ffffff', 'redoHover': '#ad6616',
                'metLabel': '#7fd19b', 'redoLabel': '#e8a54b', 'paintingLabel': '#c3aef5',
                'segment_met': '#4fae74', 'segment_painting': '#a98be8', 'segment_skipped': colors['muted'], 'segment_open': colors['raised']}
    return {'met': '#2a6e45', 'metText': '#ffffff', 'metHover': '#235d3a', 'redo': '#8a4f0e', 'redoText': '#ffffff', 'redoHover': '#74420c',
            'metLabel': '#256b3f', 'redoLabel': '#8a4f0e', 'paintingLabel': '#5b3aa8',
            'segment_met': '#2a7a4a', 'segment_painting': '#6b46c1', 'segment_skipped': colors['muted'], 'segment_open': colors['raised']}


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
            QLabel#stepPainting { color: %(paintingLabel)s; font-size: 11px; font-weight: 600; }
            QFrame#nowCard { background: %(surface)s; border: 1px solid %(border)s; border-left: 3px solid %(segment_painting)s; border-radius: 8px; }
            QFrame#nowCard QWidget#nowBody, QFrame#nowCard QLabel { border: none; }
            QLabel#nowTitle { font-size: 13px; font-weight: 600; }
            QLabel#nowThumb { background: %(raised)s; border-radius: 4px; }
            QFrame#planStepCurrent { background: %(raised)s; border: none; border-left: 3px solid %(segment_painting)s; border-radius: 4px; }
            QPushButton#stepFold { background: transparent; color: %(muted)s; text-align: left; padding: 4px 0; font-size: 11px; border: none; }
            QPushButton#stepFold:hover { color: %(text)s; }
            QPushButton#stepStop { background: transparent; color: %(text)s; border: 1px solid %(border)s; padding: 2px 9px; }
            QPushButton#stepNeutral { background: %(raised)s; color: %(text)s; padding: 3px 9px; }
            QPushButton#stepMet { background: %(met)s; color: %(metText)s; font-weight: 600; padding: 3px 9px; }
            QPushButton#stepMet:hover { background: %(metHover)s; }
            QPushButton#stepRedo { background: %(redo)s; color: %(redoText)s; font-weight: 600; padding: 3px 9px; }
            QPushButton#stepRedo:hover { background: %(redoHover)s; }
            QPushButton#stepMet:disabled, QPushButton#stepRedo:disabled, QPushButton#stepNeutral:disabled { background: transparent; color: %(muted)s; border: 1px solid %(border)s; }
            QLabel#planStepsTitle { font-size: 12px; font-weight: 600; }
    ''' % c


def weak(callback):
    """A callable to the callback that keeps no reference to its object: a reference cycle between the panel and a list
    of Qt widgets was collected while Qt tore the panel down, and crashed the UI tests at exit."""
    if callback is None: return lambda: None
    return weakref.WeakMethod(callback) if hasattr(callback, '__self__') else (lambda: callback)


def text_tip(text):
    """A tooltip that is text: Qt reads one that looks like markup as rich text, and titles and file names may hold < or &."""
    return '<p style="white-space:pre-wrap">%s</p>' % html.escape(str(text)) if text else ''


def index_of(entry, default=0):
    """A step's 0-based index, or `default` when the companion sent none."""
    try:
        return int(entry.get('index'))
    except (TypeError, ValueError):
        return default


def file_name(path):
    return str(path or '').replace('\\', '/').rsplit('/', 1)[-1]


def thumbnail(path, size, ratio=1.0):
    """A small picture of an image file for a high-DPI screen (`ratio` device pixels per pixel), or a null pixmap. The
    reader decodes it at the small size, so a 6000 px element costs little."""
    reader = QImageReader(str(path or '')); reader.setAutoTransform(True)
    full = reader.size()
    if not full.isValid() or full.isEmpty(): return QPixmap()
    fitted = full.scaled(QSize(round(size.width() * ratio), round(size.height() * ratio)), Qt.AspectRatioMode.KeepAspectRatio)
    reader.setScaledSize(fitted)
    image = reader.read()
    if image.isNull(): return QPixmap()
    pixmap = QPixmap.fromImage(image); pixmap.setDevicePixelRatio(ratio)
    return pixmap


class StepStrip(QWidget):
    """One segment per plan step, coloured by its state. Each segment's title shows as its tooltip (Qt's help event); a
    tap emits `tapped(index)` (the panel opens that step in the Plan tab). A press never opens a tooltip window: one shown
    under a pressed button on macOS could keep the mouse. The whole strip has an accessible name that says the same as
    the colours."""
    tapped = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName('stepStrip')
        self.segments = []; self.colors = {}
        self.setFixedHeight(10); self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hide()

    def sizeHint(self):
        return QSize(120, 10)

    def set_steps(self, rows):
        self.segments = [{'state': str(r.get('state')), 'title': str(r.get('title') or ''), 'index': index_of(r, i)} for i, r in enumerate(rows)]
        met = sum(1 for s in self.segments if s['state'] in DONE); skipped = sum(1 for s in self.segments if s['state'] == 'skipped')
        parts = ['Plan progress: %d of %d met' % (met, len(self.segments))] + (['%d skipped' % skipped] if skipped else [])
        current = next((s for s in self.segments if s['state'] in CURRENT), None)
        if current: parts.append('step %d %s' % (current['index'] + 1, WORDS[current['state']].split(',')[0]))
        self.setAccessibleName(' · '.join(parts))
        self.setVisible(bool(self.segments)); self.update()

    def set_colors(self, colors):
        self.colors = dict(colors); self.update()

    def segment_rect(self, index):
        count = max(1, len(self.segments)); gap = 2 if count < 40 else 0
        width = (self.width() - gap * (count - 1)) / count
        return QRect(round(index * (width + gap)), 2, max(1, round(width)), self.height() - 4)

    def tip_at(self, point):
        for i, segment in enumerate(self.segments):
            if self.segment_rect(i).adjusted(-1, -4, 1, 4).contains(point):
                return text_tip('Step %d of %d · %s · %s' % (segment['index'] + 1, len(self.segments), segment['title'], WORDS.get(segment['state'], segment['state'])))
        return ''

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:               # a tooltip per segment (QToolTip: intercept the help event)
            tip = self.tip_at(event.pos())
            if tip: QToolTip.showText(event.globalPos(), tip, self)
            else: QToolTip.hideText(); event.ignore()
            return True
        return super().event(event)

    def index_at(self, point):
        return next((i for i in range(len(self.segments)) if self.segment_rect(i).adjusted(-1, -4, 1, 4).contains(point)), None)

    def mouseReleaseEvent(self, event):                       # a tap (pens and touch have no hover): that step, in the Plan tab
        QToolTip.hideText()
        point = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        index = self.index_at(point)
        if index is not None and event.button() == Qt.MouseButton.LeftButton: self.tapped.emit(self.segments[index]['index'])
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, segment in enumerate(self.segments):
            state = segment['state']
            key = 'segment_met' if state in DONE else 'segment_painting' if state in CURRENT else 'segment_skipped' if state == 'skipped' else 'segment_open'
            rect = self.segment_rect(i)
            painter.setPen(QColor(self.colors.get('border', '#808080')) if key == 'segment_open' else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.colors.get(key, '#808080')))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1) if key == 'segment_open' else rect, 2, 2)
        painter.end()


class PlanStepsList:
    """The plan's steps (see the module docstring for its three widgets). `show_steps` takes the goal event's
    plan_steps; `set_busy` follows the panel's busy flag (Good enough and Stop only while painting, Met / Redo after).
    `rows[i]` holds step i's controls: the Now painting card's body for the current step, its list row otherwise;
    `list_rows[i]` is step i's row in the Plan tab's list. It holds the panel's callbacks weakly (`weak`)."""

    def __init__(self, send, stop=None, pressed=None):
        # pressed: any button of the list was pressed by the artist (Auto-approve stops its countdown, auto_approve.py)
        self.send = weak(send); self.stop = weak(stop); self.pressed = weak(pressed)
        self.rows = []; self.list_rows = []; self.busy = False; self.structure = None; self.builds = 0
        self.expanded = False; self.root = ''; self.goal_image = ''; self.thumbs = {}
        self.strip = StepStrip()
        # The Now painting card: its caption row (with Stop) stays; its body is rebuilt with the steps.
        self.now = QFrame(); self.now.setObjectName('nowCard')
        self.now.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        card = QVBoxLayout(self.now); card.setContentsMargins(10, 7, 10, 8); card.setSpacing(4)
        top = QHBoxLayout(); top.setSpacing(6)
        self.caption = QLabel(''); self.caption.setObjectName('stepPainting'); self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); top.addWidget(self.caption, 1)
        self.stop_button = QPushButton('Stop'); self.stop_button.setObjectName('stepStop')
        self.stop_button.setAccessibleName('Stop painting'); self.stop_button.setToolTip('Stop: the stroke in progress settles safely, then the agent pauses.')
        self.stop_button.clicked.connect(lambda: self.stop() and self.stop()())
        top.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignTop); card.addLayout(top)
        self.caption_row = top                                  # the panel adds its Start painting / Resume here
        self.now_layout = card; self.now_body = None
        self.now.hide(); self.has_card = False; self.side_task = False
        # The Plan tab's list: a header, the folded steps, then the others.
        self.widget = QFrame(); self.widget.setObjectName('planSteps')
        self.widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self.widget); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(2)
        header = QHBoxLayout(); header.setSpacing(6)
        self.title = QLabel('Steps'); self.title.setObjectName('planStepsTitle'); header.addWidget(self.title)
        self.summary = QLabel(''); self.summary.setObjectName('muted'); header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.fold = QPushButton(''); self.fold.setObjectName('stepFold'); self.fold.setCheckable(True)
        self.fold.toggled.connect(self.set_expanded); layout.addWidget(self.fold); self.fold.hide()
        self.done_box = QWidget(); self.done_box.setObjectName('planStepsList'); self.done_layout = QVBoxLayout(self.done_box)
        self.done_layout.setContentsMargins(0, 0, 0, 0); self.done_layout.setSpacing(0); layout.addWidget(self.done_box); self.done_box.hide()
        self.list = QWidget(); self.list.setObjectName('planStepsList')
        self.list_layout = QVBoxLayout(self.list); self.list_layout.setContentsMargins(0, 0, 0, 0); self.list_layout.setSpacing(0)
        layout.addWidget(self.list)
        self.widget.hide()

    def isVisible(self):
        return self.widget.isVisible()

    def set_side_task(self, on):
        """Something the companion does beside the steps (sharpening the goal image) shows on the Now card while it runs."""
        self.side_task = bool(on)
        self.now.setVisible(self.has_card or self.side_task)

    def set_colors(self, colors, dark):
        self.strip.set_colors(dict(colors, **step_colors(colors, dark)))

    @staticmethod
    def structure_of(rows):
        return tuple((str(r.get('key')), str(r.get('title')), str(r.get('state')), int(r.get('redone') or 0), str(r.get('source') or '')) for r in rows)

    def show_steps(self, rows, busy=False, root=None, goal_image=None):
        """Show the steps ({'index', 'key', 'title', 'state', 'redone'?, 'source'?, 'batches'?}); rebuilt only when one
        changed, so an open Redo field keeps what the artist is typing while the companion publishes. `root` is the
        project folder (a step's source is relative to it) and `goal_image` the picture shown when a step has none."""
        rows = [r for r in rows or [] if isinstance(r, dict) and r.get('key')]
        self.busy = bool(busy)
        images = (str(root or ''), str(goal_image or ''))
        if self.structure_of(rows) != self.structure or images != (self.root, self.goal_image):
            self.root, self.goal_image = images; self.build(rows)
        else:                                                   # a new batch: its count changes in place, nothing is rebuilt
            self.set_busy(self.busy)
            for entry in rows:
                if entry.get('key') == getattr(self.now_body, 'key', None): self.set_detail(self.now_body.card, entry)
        self.widget.setVisible(bool(rows)); self.strip.set_steps(rows)

    def current_index(self):
        return next((i for i, row in enumerate(self.rows) if row['state'] in CURRENT), None)

    def current_list_row(self):
        index = self.current_index()
        return self.list_rows[index] if index is not None else None

    def build(self, rows):
        self.builds += 1; self.structure = self.structure_of(rows)
        for widget in self.list_rows + ([self.now_body] if self.now_body else []):
            widget.hide(); widget.deleteLater()                # deleteLater: a button may be mid-click
        self.rows = []; self.list_rows = []; self.now_body = None
        current = next((i for i, r in enumerate(rows) if r.get('state') in CURRENT), None)
        upcoming = next((i for i, r in enumerate(rows) if r.get('state') == 'open'), None)
        folded = [i for i, r in enumerate(rows) if r.get('state') in DONE or (r.get('state') == 'skipped' and current is not None and i < current)]
        for i, entry in enumerate(rows):
            if i == current:
                self.rows.append(self.now_row(entry, len(rows)))
                self.list_rows.append(self.make_row(entry, highlight=True)['widget'])
            else:
                row = self.make_row(entry); self.rows.append(row); self.list_rows.append(row['widget'])
            (self.done_layout if i in folded else self.list_layout).addWidget(self.list_rows[-1])
        if current is None and upcoming is not None:           # nothing paints: the card says what is next
            self.now_body = self.card_body(rows[upcoming], len(rows)); self.now_layout.addWidget(self.now_body)
        self.caption.setText('%s · step %d of %d' % (CAPTION.get(rows[current]['state'], ''), current + 1, len(rows)) if current is not None
                             else '%s · step %d of %d' % (CAPTION['open'], upcoming + 1, len(rows)) if upcoming is not None else '')
        self.stop_button.setVisible(current is not None and rows[current].get('state') in ('painting', 'finishing'))
        self.has_card = current is not None or upcoming is not None
        self.now.setVisible(self.has_card or self.side_task)
        counts = {}
        for entry in rows: counts[entry.get('state')] = counts.get(entry.get('state'), 0) + 1
        met = sum(counts.get(s, 0) for s in DONE)
        parts = ['%d of %d met' % (met, len(rows))] + (['%d skipped' % counts['skipped']] if counts.get('skipped') else [])
        self.summary.setText(' · '.join(parts) if rows else '')
        folded_met = sum(1 for i in folded if rows[i].get('state') in DONE); folded_skipped = len(folded) - folded_met
        self.fold_words = ' · '.join((['%d met' % folded_met] if folded_met else []) + (['%d skipped' % folded_skipped] if folded_skipped else []))
        self.fold.setAccessibleName('Show the %d steps met or skipped' % len(folded))
        self.fold.setVisible(bool(folded)); self.fold.blockSignals(True); self.fold.setChecked(self.expanded); self.fold.blockSignals(False)
        self.set_expanded(self.expanded)
        self.set_busy(self.busy)

    def set_expanded(self, on):
        self.expanded = bool(on)
        self.fold.setText(('▾  ' if self.expanded else '▸  ') + getattr(self, 'fold_words', ''))
        self.done_box.setVisible(self.expanded and self.fold.isVisibleTo(self.widget))

    def card_body(self, entry, total):
        """The card's picture and words for a step: its element image (else the goal image), title, source and batch."""
        body = QWidget(); body.setObjectName('nowBody')
        line = QHBoxLayout(body); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(8)
        source = str(entry.get('source') or '')
        path = os.path.join(self.root, source) if source and self.root else source
        picture = self.thumbnail(path if source else '') if source else QPixmap()
        if picture.isNull() and self.goal_image: picture = self.thumbnail(self.goal_image)
        if not picture.isNull():
            thumb = QLabel(); thumb.setObjectName('nowThumb'); thumb.setFixedSize(THUMB); thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setPixmap(picture); thumb.setAccessibleName('Picture of ' + (file_name(source) or 'the goal image'))
            line.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout(); words.setSpacing(2)
        title = QLabel(str(entry.get('title') or '')); title.setObjectName('nowTitle'); title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True); title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); title.setMinimumWidth(0)
        words.addWidget(title)
        detail = QLabel(''); detail.setObjectName('muted'); detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True); detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); detail.setMinimumWidth(0)
        detail.setToolTip(text_tip(source)); words.addWidget(detail)
        line.addLayout(words, 1)
        body.title_label = title; body.words = words; body.detail = detail; body.card = body; body.key = str(entry.get('key'))
        self.set_detail(body, entry)
        return body

    @staticmethod
    def set_detail(body, entry):
        """The card's source line: "from <file> · batch N"."""
        source = str(entry.get('source') or '')
        details = (['from ' + file_name(source)] if source else []) + (['batch %d' % int(entry['batches'])] if entry.get('batches') else [])
        body.detail.setText(' · '.join(details)); body.detail.setVisible(bool(details))

    def thumbnail(self, path):
        if not path: return QPixmap()
        ratio = self.now.devicePixelRatioF() if hasattr(self.now, 'devicePixelRatioF') else 1.0
        key = (path, ratio)
        if key not in self.thumbs: self.thumbs[key] = thumbnail(path, THUMB, ratio)
        return self.thumbs[key]

    def now_row(self, entry, total):
        """The current step on the card: its body, then its buttons and status."""
        number, key, title, state = index_of(entry) + 1, str(entry['key']), str(entry.get('title') or ''), str(entry.get('state'))
        widget = QWidget(); widget.setObjectName('nowStep')
        rows = QVBoxLayout(widget); rows.setContentsMargins(0, 0, 0, 0); rows.setSpacing(5)
        body = self.card_body(entry, total); rows.addWidget(body)
        text = {'finishing': STATUS['finishing'][0]}.get(state, '')
        if entry.get('redone'): text = (text + ' · ' if text else '') + '↺ redone %d×' % int(entry['redone'])
        status = QLabel(text); status.setObjectName('stepRedoText' if entry.get('redone') and state != 'finishing' else 'muted')
        status.setTextFormat(Qt.TextFormat.PlainText); status.setWordWrap(True); status.setVisible(bool(text))
        status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); status.setMinimumWidth(0)
        body.words.addWidget(status)
        line = QHBoxLayout(); line.setSpacing(5)
        row = {'key': key, 'state': state, 'widget': widget, 'title': body.title_label, 'status': status, 'buttons': [], 'editor': None, 'redo': None}
        self.add_buttons(row, line, state, number, title)
        line.addStretch(1); rows.addLayout(line)
        if row['redo']:
            row['editor'] = self.redo_editor(row, number); rows.addWidget(row['editor'])
        widget.card = body; widget.key = key
        self.now_body = widget; self.now_layout.addWidget(widget)
        return row

    def add_buttons(self, row, line, state, number, title):
        for action, text, style, tip in step_actions(state):
            button = QPushButton(text); button.setObjectName(style); button.setToolTip(tip)
            button.setAccessibleName('%s step %d: %s' % (SPOKEN[action], number, title))
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, a=action, r=row: self.press(r, a))
            line.addWidget(button, 0, Qt.AlignmentFlag.AlignTop); row['buttons'].append((action, button))
            if action == 'redo': row['redo'] = button

    def make_row(self, entry, highlight=False):
        number, key, title, state = index_of(entry) + 1, str(entry['key']), str(entry.get('title') or ''), str(entry.get('state'))
        widget = QFrame(); widget.setObjectName('planStepCurrent' if highlight else 'planStepRow')
        rows = QVBoxLayout(widget); rows.setContentsMargins(6 if highlight else 0, 5, 0, 5); rows.setSpacing(3)
        top = QHBoxLayout(); top.setSpacing(5)
        label = QLabel('%d.' % number); label.setObjectName('stepNumber'); label.setContentsMargins(0, 4, 0, 0); top.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(title); name.setTextFormat(Qt.TextFormat.PlainText); name.setWordWrap(True)
        name.setObjectName('stepSkipped' if state == 'skipped' else 'stepTitle')
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); name.setMinimumWidth(0)
        font = name.font(); font.setStrikeOut(state == 'skipped'); name.setFont(font)
        name.setContentsMargins(0, 3, 0, 0); top.addWidget(name, 1, Qt.AlignmentFlag.AlignTop); rows.addLayout(top)
        line = QHBoxLayout(); line.setSpacing(5)
        text, style = STATUS.get(state, ('', 'muted'))
        if highlight and state == 'finished': text = 'Finished · Met or Redo on the card above'
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
        if not highlight:                                        # the current step's buttons are on the card
            self.add_buttons(row, top if compact else line, state, number, title)
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
        cancel.clicked.connect(lambda: (editor.hide(), field.clear()))
        confirm.clicked.connect(lambda: self.send_command(row, 'redo', field.text()))
        field.returnPressed.connect(lambda: self.send_command(row, 'redo', field.text()))
        buttons.addWidget(cancel); buttons.addWidget(confirm); layout.addLayout(buttons)
        editor.hide(); row['confirm'] = confirm
        return editor

    def press(self, row, action):
        pressed = self.pressed()
        if pressed: pressed()
        if action == 'redo':                                    # first: what to change
            row['editor'].show(); row['editor'].findChild(QLineEdit).setFocus(); return
        self.send_command(row, action)

    def send_command(self, row, action, text=None):
        for _, button in row['buttons']: button.setEnabled(False)
        if row.get('confirm'): row['confirm'].setEnabled(False)
        if row['editor']: row['editor'].hide()
        send = self.send()
        if send: send(plan_step_command(action, row['key'], text))

    def set_busy(self, busy):
        """Good enough and Stop wait for painting; Met and Redo for the move to end; Skip and Restore any time. Also gives
        back the buttons a refused command left disabled."""
        self.busy = bool(busy)
        for row in self.rows:
            for action, button in row['buttons']:
                button.setEnabled(self.busy if action in BUSY_ONLY else not self.busy if action in IDLE_ONLY else True)
            if row.get('confirm'): row['confirm'].setEnabled(not self.busy)
        self.stop_button.setEnabled(self.busy)
