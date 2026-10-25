# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Folder tab's study (openspec folder-study, approved by the artist 2026-10-24): a vision model writes a short note per
project folder image, so the planner and painter read the notes as text and open an image only when they need it.

  * The study line under the element list: "Studying N images… k/N" with Stop while it runs, then how many are studied
    (the goal among them), how many are excluded, and how many failed (tried again when the agent opens them).
  * Each element row shows its state: a check mark when studied, nothing when not studied, a stop mark when excluded,
    and says so in its tooltip. The names stay the editable text they were.
  * The right-click menu on a row: Study (not studied), Exclude (never sent to any model), Include (an excluded one).
  * A folder of more than 20 images asks first: Study only what the plan uses (the default, with its estimate), Study all
    N (estimate), Let me pick… (the rows get checkboxes) or Don't study, then Continue.

The companion decides and remembers everything (folder-study-chat.ts); the panel shows its `study` status from the folder
event and sends folder_study commands. Nothing here reads an image.
"""
from .qt_compat import (QFrame, QHBoxLayout, QIcon, QLabel, QMenu, QPixmap, QPushButton, QRadioButton, QSizePolicy,
                        QStyle, Qt, QVBoxLayout, QWidget, QColor)

CHOICES = ('plan', 'all', 'pick', 'none')
IMAGE_WORDS = {'studied': 'Studied ✓: the agent reads its note', 'not_studied': 'Not studied',
               'studying': 'Being studied…', 'excluded': 'Excluded: never sent to any model'}


def cost_words(estimate):
    """'about $0.0132, 54 s' for an estimate {images, cost, seconds}."""
    estimate = estimate or {}
    seconds = int(estimate.get('seconds') or 0)
    time = '%d s' % seconds if seconds < 90 else 'about %d min' % round(seconds / 60.0)
    return 'about $%.4f, %s' % (float(estimate.get('cost') or 0), time)


class FolderStudyCard(QWidget):
    """The study line with Stop, and the choice card of a big folder; it marks the element rows of `elements` (the Folder
    tab's QListWidget, whose items hold the image's folder-relative name in their UserRole)."""

    def __init__(self, send, elements, parent=None):
        super().__init__(parent)
        self.send, self.elements, self.last, self.goal_name = send, elements, None, None
        self.ticked, self.changing = None, False          # the artist's ticks in Let me pick (kept across rebuilds); the card reopened
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(6)
        row = QHBoxLayout(); row.setSpacing(8)
        self.line = QLabel(''); self.line.setObjectName('muted'); self.line.setWordWrap(True); self.line.setTextFormat(Qt.TextFormat.PlainText)
        self.line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); row.addWidget(self.line, 1)
        self.stop = QPushButton('Stop'); self.stop.setObjectName('stepStop'); self.stop.setAccessibleName('Stop studying the folder images')
        self.stop.setToolTip('Stop the study: the notes written so far stay; the rest are studied when the agent opens them.')
        self.stop.clicked.connect(lambda: self.send({'type': 'folder_study', 'action': 'stop'})); row.addWidget(self.stop, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        self.choice = QFrame(); self.choice.setObjectName('planBar')
        choice = QVBoxLayout(self.choice); choice.setContentsMargins(10, 9, 10, 10); choice.setSpacing(5)
        self.question = QLabel(''); self.question.setWordWrap(True); self.question.setTextFormat(Qt.TextFormat.PlainText)
        self.question.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); choice.addWidget(self.question)
        self.options = {}
        for key in CHOICES:
            button = QRadioButton(''); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.toggled.connect(lambda _on=False: self.pick_mode())
            self.options[key] = button; choice.addWidget(button)
        self.options['plan'].setChecked(True)
        self.options['pick'].setToolTip('Tick the images to study in the list below, then press Continue. The choice is remembered for this folder.')
        self.change = QPushButton('Change what to study…'); self.change.setObjectName('footerAction')
        self.change.setToolTip('Choose again what a vision model studies in this folder.'); self.change.clicked.connect(self.reopen)
        row.addWidget(self.change, 0, Qt.AlignmentFlag.AlignTop)
        self.go = QPushButton('Continue'); self.go.setAccessibleName('Study the chosen folder images'); self.go.clicked.connect(self.chosen)
        choice.addWidget(self.go, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.choice)
        self.elements.itemChanged.connect(self.ticked_changed)
        self.clear()

    def clear(self):
        self.last = None; self.goal_name = None; self.ticked = None; self.changing = False
        self.line.setText(''); self.line.hide(); self.stop.hide(); self.change.hide(); self.choice.hide(); self.hide()

    def ticked_changed(self, item):
        if self.picking() and self.ticked is not None:
            name = item.data(Qt.ItemDataRole.UserRole)
            (self.ticked.add if item.checkState() == Qt.CheckState.Checked else self.ticked.discard)(name)

    def reopen(self):
        """Change what to study…: the card again, with the current choice."""
        self.changing = True
        current = (self.last or {}).get('choice')
        if current in self.options: self.options[current].setChecked(True)
        self.show_study(self.last, self.goal_name)

    def shows_states(self):
        """Whether the rows show study states (the study is on): the element list then stays after a plan."""
        return bool(self.last and self.last.get('enabled'))

    def state_of(self, name):
        return ((self.last or {}).get('images') or {}).get(name)

    @staticmethod
    def image_words(state):
        return IMAGE_WORDS.get(state, '')

    def words(self, study):
        """The study line, or '' when there is nothing to say."""
        images, count = study.get('images') or {}, int(study.get('count') or 0)
        states = list(images.values())
        studied, excluded, state = states.count('studied'), states.count('excluded'), study.get('state')
        plural = lambda n: '%d image%s' % (n, '' if n == 1 else 's')
        if state == 'waiting': return '%s to study when the chat starts.' % plural(count)
        if state == 'unavailable':
            return 'No connected model reads images: the folder is known by its file names. Connect a vision model (qwen3-vl through OpenRouter) to study it.'
        if state == 'running':
            total = int(study.get('total') or 0)
            return 'Studying %s… %d/%d' % (plural(total), int(study.get('done') or 0), total)
        if study.get('needs_choice'): return '%s: choose what to study below.' % plural(count)
        text = ('Study stopped: %d of %d images studied' if state == 'stopped' else '%d of %d images studied') % (studied, count)
        if state != 'stopped' and studied and studied == count - excluded: text += ' ✓'
        if self.goal_name and images.get(self.goal_name) == 'studied': text += ' · goal image studied ✓'
        if excluded: text += ' · %d excluded' % excluded
        failed = int(study.get('failed') or 0)
        if failed: text += ' · %d not studied (tried again when the agent opens them)' % failed
        return text + '.'

    def show_study(self, study, goal_name=None):
        """The folder event's study status (None: an older companion, or no folder): the line, Stop, the card, the rows."""
        self.last, self.goal_name = study, goal_name
        if not study or not study.get('enabled'):
            self.line.hide(); self.stop.hide(); self.choice.hide(); self.mark_rows(); self.setVisible(False); return
        self.setVisible(True)
        self.line.setText(self.words(study)); self.line.setVisible(bool(self.line.text()))
        self.stop.setVisible(study.get('state') == 'running'); self.stop.setEnabled(True)
        asking = bool(study.get('needs_choice')) or (self.changing and bool(study.get('big')))
        self.change.setVisible(bool(study.get('big')) and not asking)
        if asking:
            estimate, count = study.get('estimate') or {}, int(study.get('count') or 0)
            self.question.setText('This folder has %d images. What should a vision model study? Notes are kept with this chat; nothing is written into the folder.' % count)
            self.options['plan'].setText('Study only what the plan uses (the goal and the images its steps name; the rest when the agent opens them): %s' % cost_words(estimate.get('plan')))
            self.options['all'].setText('Study all %d: %s' % (count, cost_words(estimate.get('all'))))
            self.options['pick'].setText('Let me pick…'); self.options['none'].setText('Don\'t study')
        self.choice.setVisible(asking)
        self.mark_rows()

    def mark_rows(self):
        """Each row's mark and, in Let me pick, its checkbox (ticked when it was picked before)."""
        style, picking = self.style(), self.picking()
        blank = QPixmap(16, 16); blank.fill(QColor(0, 0, 0, 0))
        icons = {'studied': style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
                 'excluded': style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)}
        if picking and self.ticked is None: self.ticked = set((self.last or {}).get('picked') or [])
        if not picking: self.ticked = None
        self.elements.blockSignals(True)
        try:
            for i in range(self.elements.count()):
                item = self.elements.item(i)
                state = self.state_of(item.data(Qt.ItemDataRole.UserRole)) if self.shows_states() else None
                item.setIcon(icons.get(state, QIcon(blank)) if state else QIcon())
                if picking:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in self.ticked else Qt.CheckState.Unchecked)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable); item.setData(Qt.ItemDataRole.CheckStateRole, None)
        finally: self.elements.blockSignals(False)

    def picking(self):
        return not self.choice.isHidden() and self.options['pick'].isChecked()

    def pick_mode(self):
        if self.last is not None: self.mark_rows()

    def chosen(self):
        choice = next(key for key in CHOICES if self.options[key].isChecked())
        command = {'type': 'folder_study', 'action': 'choose', 'choice': choice}
        if choice == 'pick':
            ticked = self.ticked or set()
            command['picked'] = [self.elements.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.elements.count())
                                 if self.elements.item(i).data(Qt.ItemDataRole.UserRole) in ticked]
        self.changing = False
        self.send(command)

    def menu_for(self, item, parent=None):
        """The row's menu: Study when not studied, Exclude (never sent to any model), Include when excluded."""
        name, state = item.data(Qt.ItemDataRole.UserRole), self.state_of(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(parent or self)
        act = lambda label, action, tip: menu.addAction(label, lambda: self.send({'type': 'folder_study', 'action': action, 'name': name})).setToolTip(tip)
        if state == 'excluded':
            act('Include', 'include', 'Attach this image to the chat again; the study may read it.')
            return menu
        if state in (None, 'not_studied') and self.shows_states():
            act('Study', 'study', 'A vision model writes a short note on this image now.')
        act('Exclude', 'exclude', 'Never send this image to any model (painter, planner, Luna, study): it is no longer attached to the chat.')
        return menu
