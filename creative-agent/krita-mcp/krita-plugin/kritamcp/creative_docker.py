"""Native Qt panel; model traffic and Pi dependencies run in a companion process."""
import json
import os
import html
import re
import time
import threading
import uuid
from .qt_compat import sip, enum_value
from .product_name import product_name
from .crash_diagnostics import record as record_error
from .panel_theme import panel_colors
from .plan_steps import PlanStepsList, plan_steps_stylesheet, thumbnail
from .auto_approve import AutoApprove, delay_of
from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita, Selection
from .creative_document_identity import document_id, open_documents
from . import node_runtime
from . import bundled_release
from .bridge_config import bridge_port
from .command_queue import stop_requested, command_executing
try:
    from .command_queue import artist_editing
except ImportError:                                       # command_queue is not hot-reloaded: an older copy has no flag
    artist_editing = threading.Event()
from .protection import ProtectionCraft
from .feature_guard import FeatureCraft
from .paint_only_panel import PaintOnlyBar
from .folder_study_panel import FolderStudyCard
from .reference_parts import part_image, crop_image, opaque_bounds
from .qt_compat import Qt, QProcess, QProcessEnvironment, QUrl, QTimer, pyqtSignal, QEvent, QSize, QRectF, scoped, QCoreApplication, QStandardPaths
from .qt_compat import QToolTip
from .qt_compat import QDesktopServices, QPixmap, QTextCursor, QTextDocument, QTextBlockFormat, QTextCharFormat, QFont, QIcon, QKeySequence, QPalette, QColor, QPainter, QPen
from .qt_compat import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QInputDialog,
                            QComboBox, QLineEdit, QPlainTextEdit, QTextBrowser,
                            QFileDialog, QSpinBox, QFormLayout, QDialog, QDialogButtonBox,
                            QCheckBox, QGroupBox, QFrame, QScrollArea, QSizePolicy, QLayout,
                            QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
                            QApplication, QShortcut, QListWidget, QListWidgetItem, QSlider, QToolButton, QSplitter, QStylePainter, QStyleOptionComboBox, QStyle, QStyledItemDelegate, QGridLayout,
                            QMessageBox, QProgressBar)


def disconnect_companion_callbacks(process):
    """Called by dock destruction before Qt deletes its child widgets/process."""
    if sip.isdeleted(process):
        return
    for signal in (process.readyReadStandardOutput, process.readyReadStandardError,
                   process.finished, process.errorOccurred):
        try:
            signal.disconnect()
        except TypeError:
            pass  # No remaining Python receivers.


def canvas_name(canvas):
    """Saved filenames are the identity artists can find in Finder."""
    return os.path.basename(canvas.get('filename') or '') or canvas.get('name') or 'Untitled'


def canvas_details(canvas):
    details = canvas.get('filename') or canvas_name(canvas)
    if canvas.get('name') and canvas['name'] != canvas_name(canvas):
        details += '\nDocument title: ' + canvas['name']
    return details


# The painter pre-selected when the artist has chosen none yet and it is connected.
DEFAULT_PAINTER = ('deepseek', 'deepseek-flash')

def provider_name(identifier):
    return {'openrouter': 'OpenRouter', 'opencode-go': 'OpenCode Go', 'opencode': 'OpenCode',
            'openai-codex': 'OpenAI Codex', 'openai': 'OpenAI', 'deepseek': 'DeepSeek',
            'anthropic': 'Anthropic', 'google': 'Google', 'google-gemini-cli': 'Gemini CLI',
            'google-antigravity': 'Google Antigravity', 'xai': 'xAI', 'cerebras': 'Cerebras',
            'meta': 'Meta'}.get(identifier, identifier.replace('-', ' ').title())


def painting_name_from(prompt, default='Creative painting'):
    """A file-friendly painting name from the artist's first words ("a winter street in Moscow" -> "A winter street in Moscow")."""
    words = re.sub(r'[^\w\s-]', ' ', prompt or '').split()
    name = ' '.join(words[:8])[:60].strip()
    return (name[0].upper() + name[1:]) if name else default


class ProviderDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Connect a model')
        layout = QFormLayout(self)
        self.provider = QComboBox()
        self.provider.addItems(['DeepSeek', 'OpenRouter', 'Custom'])
        self.endpoint = QLineEdit('https://api.deepseek.com')
        self.model = QLineEdit('deepseek-flash')
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.capability = QCheckBox('This model accepts images and tool calls')
        layout.addRow('Provider', self.provider)
        layout.addRow('API endpoint', self.endpoint)
        layout.addRow('Model ID', self.model)
        layout.addRow('API key', self.key)
        layout.addRow(self.capability)
        note = QLabel('Uses an OpenAI-compatible API. The key stays in memory for this session.\n'
                      'Models already connected in Pi are available in the main panel.')
        note.setWordWrap(True)
        layout.addRow(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Connect')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)
        self.provider.currentTextChanged.connect(self.select_provider)

    def select_provider(self, name):
        defaults = {'DeepSeek': ('https://api.deepseek.com', 'deepseek-flash'),
                    'OpenRouter': ('https://openrouter.ai/api/v1', 'deepseek/deepseek-v4.1-flash'),
                    'Custom': ('', '')}
        endpoint, model = defaults[name]
        self.endpoint.setText(endpoint)
        self.model.setText(model)
        self.capability.setChecked(False)

    def accept(self):
        if not all((self.endpoint.text().strip(), self.model.text().strip(), self.key.text().strip(), self.capability.isChecked())):
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Complete all fields first')
            return
        super().accept()

    def command(self):
        return {'type': 'configure_provider', 'provider': 'creative-' + self.provider.currentText().lower(),
                'base_url': self.endpoint.text().strip(), 'model': self.model.text().strip(),
                'api_key': self.key.text().strip()}



class ElidedComboBox(QComboBox):
    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox(); self.initStyleOption(option)
        text_rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(option.currentText, Qt.TextElideMode.ElideRight, max(20, text_rect.width() - 5))
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class ModelComboBox(ElidedComboBox):
    """A searchable, explicit-choice model picker; browsing cannot change a route."""
    modelChosen = pyqtSignal()

    def showPopup(self, initial_query=''):
        dialog = QDialog(self)
        dialog.setWindowTitle('Choose a model')
        dialog.setMinimumSize(390, 390)
        layout = QVBoxLayout(dialog)
        search = QLineEdit(dialog)
        search.setAccessibleName('Search models by name or ID')
        search.setPlaceholderText('Search models by name or ID…')
        listing = QListWidget(dialog)
        listing.setAccessibleName('Available models')
        for index in range(self.count()):
            item = QListWidgetItem(self.itemText(index), listing)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(self.itemData(index, Qt.ItemDataRole.ToolTipRole) or '')
            if not self.model().item(index).isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            if index == self.currentIndex(): listing.setCurrentItem(item)
        def filter_items(query):
            query = query.casefold().strip()
            for index in range(listing.count()):
                item = listing.item(index)
                item.setHidden(query not in (item.text() + ' ' + (item.toolTip() or '')).casefold())
            visible = next((listing.item(i) for i in range(listing.count())
                            if not listing.item(i).isHidden() and listing.item(i).flags() & Qt.ItemFlag.ItemIsEnabled), None)
            if visible: listing.setCurrentItem(visible)
        def choose(item=None):
            item = item or listing.currentItem()
            if item and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                dialog.accept()
        search.textChanged.connect(filter_items)
        search.returnPressed.connect(choose)
        listing.itemActivated.connect(choose)
        listing.itemClicked.connect(choose)
        layout.addWidget(search)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        buttons.accepted.connect(choose)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        search.setText(initial_query)
        search.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item = listing.currentItem()
            self.setCurrentIndex(item.data(Qt.ItemDataRole.UserRole))
            self.modelChosen.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                           Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.showPopup(); event.accept()
        elif event.text() and event.text().isprintable() and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.AltModifier):
            self.showPopup(event.text()); event.accept()
        else:
            super().keyPressEvent(event)


class ChatInput(QPlainTextEdit):
    submitted = pyqtSignal()
    filesAttached = pyqtSignal(list)
    imageAttached = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setTabChangesFocus(True)
        self.slash_menu = None

    def keyPressEvent(self, event):
        # The slash menu (commands) takes Up/Down to move, Tab/Return to choose, Escape to close.
        menu = self.slash_menu
        if menu is not None and menu.isVisible():
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = menu.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
                menu.setCurrentRow(max(0, min(menu.count() - 1, row))); event.accept(); return
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter) and menu.currentItem() is not None:
                menu.itemActivated.emit(menu.currentItem()); event.accept(); return
            if event.key() == Qt.Key.Key_Escape:
                menu.hide(); event.accept(); return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.submitted.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def canInsertFromMimeData(self, source):
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            files = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
            if files:
                self.filesAttached.emit(files)
                return
        if source.hasImage():
            self.imageAttached.emit(source.imageData())
            return
        super().insertFromMimeData(source)


class MessageBody(QTextBrowser):
    """One selectable rich-text document; only the streaming reply is updated."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('QTextBrowser { border: none; padding: 0; background: transparent; }')
        self.document().setDocumentMargin(0)

    def set_rendered(self, markup):
        cursor = self.textCursor()
        selection = cursor.selectedText()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        self.setHtml(markup)
        if selection:
            # setHtml resets the cursor. Recover the user's actual selection,
            # even when newly completed Markdown changes earlier character offsets.
            plain = self.toPlainText()
            normalized = selection.replace('\u2029', '\n')
            encoded = plain.encode('utf-16-le')
            same = encoded[start * 2:end * 2].decode('utf-16-le', errors='replace') == normalized
            python_match = plain.find(normalized)
            match = start if same else len(plain[:python_match].encode('utf-16-le')) // 2 if python_match >= 0 else -1
            if match >= 0:
                cursor = self.textCursor()
                cursor.setPosition(match)
                cursor.setPosition(match + len(normalized.encode('utf-16-le')) // 2, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor)
        self.fit_height()

    def fit_height(self):
        self.document().setTextWidth(max(40, self.viewport().width()))
        self.setFixedHeight(max(1, int(self.document().size().height()) + 3))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()


class ImagePreview(QDialog):
    def __init__(self, parent, canvas, title='Canvas snapshot'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 720)
        layout = QVBoxLayout(self)
        self.picture = QLabel(); self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(100, 100)
        self.picture.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.pixmap = QPixmap(canvas.get('path') or '')
        self.crop_pixmap = self.pixmap
        self.overview_pixmap = QPixmap(canvas.get('overview_path') or '')
        self.region_bounds = canvas.get('bounds') or canvas.get('region')
        self.canvas_width = canvas.get('width'); self.canvas_height = canvas.get('height')
        self.show_location = False
        if self.region_bounds and not self.overview_pixmap.isNull():
            self.location_button = QPushButton('Show location on canvas'); self.location_button.setCheckable(True)
            self.location_button.toggled.connect(self.toggle_location); layout.addWidget(self.location_button)
        self.image_scroll = QScrollArea(); self.image_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter); self.image_scroll.setWidgetResizable(True); self.image_scroll.setWidget(self.picture)
        layout.addWidget(self.image_scroll, 1)
        self.actual_pixels = False
        zoom_row = QHBoxLayout(); zoom_row.addStretch()
        self.zoom_button = QPushButton('100% snapshot'); self.zoom_button.setCheckable(True)
        self.zoom_button.setToolTip('Inspect one image pixel per display pixel. The overview may be reduced; region crops retain document pixels.')
        self.zoom_button.toggled.connect(self.toggle_zoom); zoom_row.addWidget(self.zoom_button); layout.addLayout(zoom_row)
        name = (canvas.get('name') or 'Selection bounds') if self.region_bounds else canvas_name(canvas)
        details = name
        if canvas.get('width'): details += ' · %s × %s' % (canvas['width'], canvas.get('height', '?'))
        if not self.region_bounds and canvas.get('name') and canvas['name'] != name:
            details += '\nDocument title: ' + canvas['name']
        if self.region_bounds: details += '\nRectangular crop · x %s, y %s · %s × %s px' % tuple(self.region_bounds)
        if canvas.get('captured_at'):
            captured = canvas['captured_at']
            if isinstance(captured, (int, float)): captured = time.strftime('%H:%M:%S', time.localtime(captured / 1000 if captured > 10**11 else captured))
            details += '\nCaptured ' + str(captured)
        if canvas.get('modified'): details += ' · includes unsaved changes'
        if canvas.get('purpose'): details += '\nUse for: ' + dict(REFERENCE_PURPOSES).get(canvas['purpose'], canvas['purpose'])
        if canvas.get('notes'): details += '\n' + canvas['notes']
        label = QLabel(details); label.setWordWrap(True); label.setObjectName('muted')
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def toggle_zoom(self, checked):
        self.actual_pixels = checked
        self.zoom_button.setText('Fit in window' if checked else '100% snapshot')
        self.render_image()

    def toggle_location(self, checked):
        self.show_location = checked
        self.location_button.setText('Show crop detail' if checked else 'Show location on canvas')
        self.render_image()

    def render_image(self):
        source = self.overview_pixmap if self.show_location else self.crop_pixmap
        if source.isNull():
            self.picture.setText('Preview is unavailable. Refresh the canvas to capture it again.'); return
        self.image_scroll.setWidgetResizable(not self.actual_pixels)
        if self.actual_pixels:
            self.picture.setFixedSize(source.size()); rendered = source
        else:
            self.picture.setMinimumSize(100, 100); self.picture.setMaximumSize(16777215, 16777215)
            rendered = source.scaled(self.image_scroll.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if self.show_location and self.region_bounds and self.canvas_width and self.canvas_height:
            rendered = rendered.copy()
            painter = QPainter(rendered); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor('#79a9ff'), 2))
            x, y, width, height = self.region_bounds
            painter.drawRect(QRectF(x * rendered.width() / self.canvas_width, y * rendered.height() / self.canvas_height,
                                    width * rendered.width() / self.canvas_width, height * rendered.height() / self.canvas_height))
            painter.end()
        self.picture.setPixmap(rendered)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_image()


REFERENCE_PURPOSES = [('general', 'Overall direction'), ('likeness', 'Character likeness'), ('composition', 'Composition'), ('palette', 'Palette'), ('material', 'Material & texture')]
REFERENCE_CAPTIONS = {'general': 'General', 'likeness': 'Likeness', 'composition': 'Composition', 'palette': 'Palette', 'material': 'Material'}


class ReferencePreview(ImagePreview):
    def __init__(self, parent, reference, readonly=False):
        super().__init__(parent, dict(reference, purpose=None, notes=None), 'Reference · ' + (reference.get('name') or os.path.basename(reference['path'])))
        self.setMinimumWidth(380)
        form = QFormLayout()
        self.purpose = QComboBox(); self.purpose.setAccessibleName('Reference purpose')
        for value, label in REFERENCE_PURPOSES: self.purpose.addItem(label, value)
        self.purpose.setCurrentIndex(max(0, self.purpose.findData(reference.get('purpose') or 'general')))
        self.notes = QPlainTextEdit(reference.get('notes') or '')
        self.notes.setAccessibleName('How to use this reference')
        self.notes.setPlaceholderText('For example: follow the pose, but keep our character’s outfit.')
        self.notes.setMaximumHeight(75)
        form.addRow('Use for', self.purpose); form.addRow('Your direction', self.notes)
        self.layout().insertLayout(self.layout().count() - 1, form)
        note = QLabel('This changes how the reference guides future messages. Earlier messages keep their original reference details.'); note.setWordWrap(True); note.setObjectName('muted')
        self.layout().insertWidget(self.layout().count() - 1, note)
        # A part or a crop of this reference, made with Krita's selection tools: the agent follows only that.
        parts = QHBoxLayout(); self.part_buttons = []
        for text, kind in (('Select a part in %s…' % product_name(), 'part'), ('Crop in %s…' % product_name(), 'crop')):
            button = QPushButton(text); button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setToolTip('Opens a copy in %s; select with any selection tool, then Use this part.' % product_name())
            button.clicked.connect(lambda _checked=False, value=kind: (self.reject(), parent.start_part(reference, value)))
            parts.addWidget(button); self.part_buttons.append(button)
        self.layout().insertLayout(self.layout().count() - 1, parts)
        buttons = self.findChild(QDialogButtonBox)
        if readonly:
            self.purpose.setEnabled(False); self.notes.setEnabled(False)
            for button in self.part_buttons: button.setEnabled(False); button.setToolTip('Pause the agent to select a part')
            note.setText('Pause the agent to change this reference’s purpose. You can still inspect the image.')
        else:
            buttons.setStandardButtons(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.accept)

    def accept(self):
        if len(self.notes.toPlainText()) > 2000:
            self.setWindowTitle('Keep reference directions under 2,000 characters.'); return
        super().accept()


class ProtectionDialog(QDialog):
    """Protected areas: what the agent must never change. One row per area, with Show and Remove; locked layers are
    listed and changed in Krita. Three ways to add one, easiest first."""
    DETAILS = {'agent': 'made by the agent · you approved', 'artist': 'made by you'}

    def __init__(self, panel, areas, features=()):
        super().__init__(panel)
        self.setWindowTitle('Protected areas'); self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        intro = QLabel('The agent never changes these. Anything it paints into them is removed, and it tells you.')
        intro.setWordWrap(True); intro.setObjectName('muted'); layout.addWidget(intro)
        self.rows = []
        # Our Krita's protected features: listed here too; the panel's Protected section protects and unprotects them.
        for feature in sorted((f for f in features if f.get('protected')), key=lambda f: f['name'].casefold()):
            row = QHBoxLayout()
            swatch = QLabel('◆'); swatch.setStyleSheet('color:#e5484d'); row.addWidget(swatch)
            detail = '%s · untick it in the Protected list to let the agent change it' % (feature.get('kind') or 'feature')
            label = QLabel('%s\n%s' % (feature['name'], detail)); label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True); row.addWidget(label, 1)
            layout.addLayout(row)
            self.rows.append({'name': feature['name'], 'detail': detail, 'show': None, 'remove': None})
        areas = list(areas)
        for area in areas:
            row = QHBoxLayout()
            swatch = QLabel('◆'); swatch.setStyleSheet('color:#e5484d'); row.addWidget(swatch)
            automatic = area.get('by') == 'automatic'
            # A lock keeps a layer's own pixels and settings; the agent may still paint on new layers above it.
            detail = ('%d layers · never edited by the agent, but it may paint over them' % area.get('count', 0)) if automatic else self.DETAILS.get(area.get('by'), '')
            if area.get('state') == 'pending': detail = 'proposed by the agent · it keeps out; Keep to make it yours'
            label = QLabel('%s\n%s' % (area['name'], detail)); label.setTextFormat(Qt.TextFormat.PlainText); label.setWordWrap(True); row.addWidget(label, 1)
            show = remove = None
            if not automatic:
                show = QPushButton('👁'); show.setCheckable(True); show.setAccessibleName('Show %s in red' % area['name'])
                show.toggled.connect(lambda on, entry=area: panel.show_protection(entry, on)); row.addWidget(show)
                remove = QPushButton('✕'); remove.setAccessibleName('Remove protection %s' % area['name'])
                remove.clicked.connect(lambda _checked=False, entry=area: (panel.remove_protection(entry), self.close())); row.addWidget(remove)
            layout.addLayout(row)
            self.rows.append({'name': area['name'], 'detail': detail, 'show': show, 'remove': remove})
        if not self.rows:
            empty = QLabel('Nothing is protected yet.'); empty.setObjectName('muted'); layout.addWidget(empty)
        actions = QHBoxLayout(); self.actions = []
        for text, slot, tip in (('Ask the agent…', panel.ask_to_protect, 'Describe what to protect; the agent marks it for you to keep.'),
                                ('Paint over it', panel.paint_protection, 'Paint red over what to protect; the eraser takes it away.'),
                                ('Use my selection', panel.protect_selection, 'Protect what is selected in %s now.' % product_name())):
            button = QPushButton(text); button.setToolTip(tip); button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, act=slot: (self.close(), act())); actions.addWidget(button); self.actions.append(button)
        layout.addLayout(actions)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(self.close); layout.addWidget(close)

    def closeEvent(self, event):
        for row in self.rows:
            if row['show'] is not None and row['show'].isChecked(): row['show'].setChecked(False)
        super().closeEvent(event)


class MassBar(QWidget):
    """A whole-picture reference's big masses as a flat bar of their own colours, each as wide as its part of the
    picture (mass-map.ts: mass_map.colours), with the companion's plain sentence (mass_map.overview) as its tooltip.
    Flat colours only: outlines over the reference looked like the tracing the artist removed."""

    def __init__(self, height=10):
        super().__init__()
        self.setObjectName('massMap'); self.colours = []
        self.setFixedHeight(height); self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(120, self.height())

    def set_mass_map(self, found, name=''):
        """Show a mass map ({'colours': [{'colour', 'share'}], 'overview'}); False (and nothing shown) without colours."""
        colours = [c for c in (found or {}).get('colours') or [] if isinstance(c, dict) and QColor(str(c.get('colour'))).isValid() and float(c.get('share') or 0) > 0]
        self.colours = [(QColor(str(c['colour'])), float(c['share'])) for c in colours]
        overview = str((found or {}).get('overview') or '').strip()
        self.setToolTip(CreativeAgentDocker.text_tip(['Big colour masses' + (' of ' + name if name else '') + (': ' + overview if overview else '')]) if self.colours else '')
        self.setAccessibleName(('Colour masses of ' + (name or 'the reference')) if self.colours else '')
        self.setAccessibleDescription(overview if self.colours else '')
        self.update()
        return bool(self.colours)

    def clear(self):
        self.set_mass_map(None)

    def paintEvent(self, _event):
        if not self.colours: return
        painter = QPainter(self); total = sum(share for _, share in self.colours) or 1; x = 0.0
        for color, share in self.colours:
            width = self.width() * share / total
            painter.fillRect(QRectF(x, 0, width + 0.5, self.height()), color); x += width
        painter.end()


class FeaturesSection(QFrame):
    """The panel's Protected section (krita-fork 6.6): the painting's features, protected first and by name, each with a
    box the artist ticks to protect it. Every widget of the section is made here, so a restyle touches this class only.
    It shows what it is given (`show_rows`); the panel reads the document and changes protection."""
    EMPTY = 'No features yet: select an area and use the shield to protect it'

    def __init__(self, on_toggle):
        super().__init__(); self.setObjectName('featuresSection')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)            # its own height; the chat takes the rest
        self.on_toggle = on_toggle; self.rows = []; self.pending_rows = []; self.builds = 0; self.locked = False; self.structure = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(2)
        header = QHBoxLayout(); header.setSpacing(6)
        self.toggle = QToolButton(); self.toggle.setObjectName('featuresToggle'); self.toggle.setText('Protected')
        self.toggle.setCheckable(True); self.toggle.setChecked(True); self.toggle.setAccessibleName('Show or hide the protected features')
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.toggled.connect(self.expand); header.addWidget(self.toggle)
        self.summary = QLabel(''); self.summary.setObjectName('muted'); header.addWidget(self.summary, 1)
        layout.addLayout(header)
        self.body = QWidget(); body = QVBoxLayout(self.body); body.setContentsMargins(4, 0, 0, 0); body.setSpacing(0)
        self.empty = QLabel(self.EMPTY); self.empty.setObjectName('muted'); self.empty.setWordWrap(True); body.addWidget(self.empty)
        self.list = QWidget(); self.list_layout = QVBoxLayout(self.list); self.list_layout.setContentsMargins(0, 0, 6, 0); self.list_layout.setSpacing(0)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(self.list); self.scroll.setMaximumHeight(132)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); body.addWidget(self.scroll)
        self.list.setObjectName('featuresList'); self.list.setAutoFillBackground(False); self.scroll.viewport().setAutoFillBackground(False)
        layout.addWidget(self.body)

    def expand(self, on):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow); self.body.setVisible(on)

    @staticmethod
    def structure_of(rows, pending=()):
        return (tuple(sorted((str(r['name']), str(r.get('kind') or '')) for r in rows)),
                tuple(sorted((str(a['id']), str(a['name']), str(a.get('state'))) for a in pending)))

    def present(self, rows, pending=()):
        """Show the rows: rebuilt and sorted when names or kinds changed, else only the boxes change, in place, so a row
        never jumps under the pointer and the clicked box keeps the focus. `pending`: areas the agent proposed that the
        artist has not kept yet (protection.py), listed below the features without a box: the artist answers them in
        the chat (Keep, Adjust, Discard)."""
        if self.structure_of(rows, pending) != self.structure: self.show_rows(rows, pending)
        else: self.set_flags(rows)
        self.show()

    def set_flags(self, rows):
        flags = {str(r['name']): bool(r['protected']) for r in rows}
        for row in self.rows:
            check = row['check']
            if check.isChecked() != flags.get(row['name'], check.isChecked()):
                check.blockSignals(True); check.setChecked(flags[row['name']]); check.blockSignals(False)
        self.summary.setText('%d of %d' % (sum(flags.values()), len(flags)) if flags else '')
        self.set_locked(self.locked)

    def show_rows(self, rows, pending=()):
        """Rebuild the list from feature rows ({'name', 'kind', 'protected'}) and pending areas ({'id', 'name'}); the
        order is the section's own."""
        self.builds += 1; self.structure = self.structure_of(rows, pending)
        for row in self.rows + self.pending_rows:
            row['widget'].hide(); row['widget'].deleteLater()          # deleteLater: a box may be mid-click
        self.rows = []; self.pending_rows = []
        ordered = sorted(rows, key=lambda r: (not r['protected'], r['name'].casefold(), r['name']))
        for entry in ordered:
            widget = QWidget(); line = QHBoxLayout(widget); line.setContentsMargins(0, 1, 0, 1); line.setSpacing(6)
            check = QCheckBox(entry['name'].replace('&', '&&')); check.setChecked(bool(entry['protected'])); check.setAccessibleName('Protect %s' % entry['name'])
            check.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); check.setMinimumWidth(0)
            check.toggled.connect(lambda on, name=entry['name']: self.on_toggle(name, on)); line.addWidget(check, 1)
            kind = QLabel(entry.get('kind') or ''); kind.setTextFormat(Qt.TextFormat.PlainText); kind.setObjectName('muted'); line.addWidget(kind)
            self.list_layout.addWidget(widget)
            self.rows.append({'name': entry['name'], 'check': check, 'kind': kind, 'widget': widget})
        for area in sorted(pending, key=lambda a: (a['name'].casefold(), a['name'])):
            widget = QWidget(); line = QHBoxLayout(widget); line.setContentsMargins(0, 1, 0, 1); line.setSpacing(6)
            label = QLabel(area['name']); label.setTextFormat(Qt.TextFormat.PlainText); label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            label.setToolTip('The agent proposed this area, shown in red; keep, adjust or discard it in the chat.' if area.get('state') == 'pending'
                             else 'A protected area: the agent never changes it. Remove it with the shield.')
            line.addWidget(label, 1)
            kind = QLabel('proposed, waiting for you' if area.get('state') == 'pending' else 'protected'); kind.setObjectName('muted'); line.addWidget(kind)
            self.list_layout.addWidget(widget)
            self.pending_rows.append({'name': area['name'], 'id': area['id'], 'label': label, 'kind': kind, 'widget': widget})
        listed = bool(self.rows or self.pending_rows)
        self.empty.setVisible(not listed); self.scroll.setVisible(listed)
        protected = sum(1 for r in ordered if r['protected'])
        self.summary.setText('%d of %d' % (protected, len(ordered)) if ordered else '')
        self.set_locked(self.locked)

    def set_locked(self, locked):
        """While the agent paints the boxes wait, like the shield: a change inside its move would join its undo step."""
        self.locked = locked
        for row in self.rows:
            row['check'].setEnabled(not locked)
            row['check'].setToolTip('Pause to change protection' if locked else
                                    ('Protected: the agent never changes it. Untick to let it.' if row['check'].isChecked() else
                                     'Tick to protect it: the agent then never changes it.'))


class CharacterDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        return QPlainTextEdit(parent) if index.column() == 1 else super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QPlainTextEdit): editor.setPlainText(index.data(Qt.ItemDataRole.EditRole) or '')
        else: super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QPlainTextEdit): model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)
        else: super().setModelData(editor, model, index)


# The AI image allowance choices for the open chat; -1 is no limit (null for the companion).
AI_IMAGE_CHOICES = ((0, 'No AI images'), (1, '1 AI image'), (3, '3 AI images'), (5, '5 AI images'), (-1, 'AI images: no limit'))


def material_words(m):
    """One planned material as the plan card shows it (the companion's plan-materials.ts materialsLine): "walls: red brick",
    "walls (Kremlin towers): old red castle brick" for a part's own (Luna's pick), " (unsure)" when Luna was not confident."""
    return '%s%s: %s%s' % (m.get('aspect', ''), ' (%s)' % m['part'] if m.get('part') else '', m.get('material') or m.get('id', ''),
                           ' (unsure)' if m.get('unsure') else '')


def materials_line(materials):
    """A step's planned materials in plain words: "walls: old red castle brick; roofs: rusty green metal"."""
    return '; '.join(material_words(m) for m in materials if isinstance(m, dict))


def edited_materials(text, before):
    """The materials the artist's words name: an entry written as it was shown keeps its id and hints; a new one goes as
    {aspect, id: the words}, which the companion resolves against the library (an id or a material's name) or drops."""
    shown = {material_words(m): m for m in before if isinstance(m, dict)}
    out = []
    for entry in (part.strip() for part in text.split(';')):
        if not entry:
            continue
        if entry in shown:
            out.append(shown[entry]); continue
        aspect, _, name = entry.partition(':')
        if aspect.strip() and name.strip():
            out.append({'aspect': aspect.strip().lower(), 'id': name.strip()})
    return out


class PlanDialog(QDialog):
    """The durable brief is editable without asking the model to rewrite it."""
    def __init__(self, parent, goal):
        super().__init__(parent)
        self.setWindowTitle('Painting plan')
        self.resize(680, 740)
        self.goal_record = json.loads(json.dumps(goal))
        self.export_references = list(getattr(parent, 'attached_references', [])) + list(getattr(parent, 'pending_references', []))
        self.export_target = dict(getattr(parent, 'painting_target', {}) or {})
        self.original_brief = json.loads(json.dumps(goal['brief']))
        # Steps are a painting order; retired stage controls are dropped on save.
        # id: a reworded step keeps its marks; materials: an architectural refine step's texture (architecture-texture goal 7)
        self.stage_metadata = [{key: step[key] for key in ('title', 'done_when', 'scope', 'id', 'materials') if key in step} for step in goal['brief']['steps']]
        self.stage_index = -1
        layout = QVBoxLayout(self)
        self.title = QLineEdit(goal['brief']['title']); self.title.setAccessibleName('Plan title')
        self.title.setStyleSheet('font-size: 20px; font-weight: 600; padding: 8px;')
        layout.addWidget(self.title)
        tabs = QTabWidget(); layout.addWidget(tabs, 1)
        overview = QTextBrowser(); overview.setOpenLinks(False); overview.setOpenExternalLinks(False)
        brief = goal['brief']
        overview.setHtml(parent.transcript.render('## ' + brief['title'] + '\n\n' + brief['objective'] + '\n\n### Keep intact\n' +
            '\n'.join('- ' + rule for rule in brief['requirements']) + '\n\n### Painting order\n' +
            '\n\n'.join('**%d. %s**\n\n%s' % (i + 1, step['title'], step['done_when']) + ('\n\nMaterials: ' + materials_line(step['materials']) if step.get('materials') else '')
                         for i, step in enumerate(brief['steps'])) +
            '\n\n### Finished when\n' + '\n'.join('- ' + check for check in brief['completion'])))
        tabs.addTab(overview, 'Overview')
        if self.export_references:
            references_view = QTextBrowser(); references_view.setOpenLinks(False); references_view.setOpenExternalLinks(False)
            reference_text = '## References\n\n' + '\n\n'.join('**' + (reference.get('name') or os.path.basename(reference.get('path', 'Reference'))) + '** · ' +
                dict(REFERENCE_PURPOSES).get(reference.get('purpose') or 'general', 'Overall direction') +
                ('\n\n' + reference['notes'] if reference.get('notes') else '') for reference in self.export_references)
            references_view.setHtml(parent.transcript.render(reference_text))
            tabs.addTab(references_view, 'References')
        brief_tab = QWidget(); form = QVBoxLayout(brief_tab)
        form.addWidget(QLabel('What we are making'))
        self.objective = QPlainTextEdit(goal['brief']['objective']); self.objective.setMaximumHeight(90)
        self.objective.setAccessibleName('Painting objective'); form.addWidget(self.objective)
        form.addWidget(QLabel('Requirements to preserve · one per line'))
        self.rules = QPlainTextEdit('\n'.join(goal['brief']['requirements'])); self.rules.setAccessibleName('Requirements to preserve')
        form.addWidget(self.rules, 1)
        form.addWidget(QLabel('Where the agent can choose'))
        self.freedom = QPlainTextEdit('\n'.join(goal['brief']['freedom'])); self.freedom.setMaximumHeight(90)
        self.freedom.setAccessibleName('Creative freedom'); form.addWidget(self.freedom)
        tabs.addTab(brief_tab, 'Brief')
        characters_tab = QWidget(); character_layout = QVBoxLayout(characters_tab)
        character_note = QLabel('Keep each character’s identity, appearance and relationships consistent. Add one requirement per line.'); character_note.setWordWrap(True)
        character_layout.addWidget(character_note)
        records = goal['brief'].get('characters', [])
        self.characters = QTableWidget(len(records), 2); self.characters.setHorizontalHeaderLabels(['Character', 'Details to preserve'])
        self.characters.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.characters.verticalHeader().setDefaultSectionSize(88)
        self.characters.setItemDelegate(CharacterDelegate(self.characters)); self.characters.setAccessibleName('Character requirements')
        for row, character in enumerate(records):
            self.characters.setItem(row, 0, QTableWidgetItem(character['name']))
            self.characters.setItem(row, 1, QTableWidgetItem('\n'.join(character.get('requirements', []))))
        character_layout.addWidget(self.characters, 1)
        character_actions = QHBoxLayout()
        add_character = QPushButton('Add character'); add_character.clicked.connect(lambda: self.characters.insertRow(self.characters.rowCount()))
        remove_character = QPushButton('Remove selected'); remove_character.clicked.connect(lambda: self.characters.removeRow(self.characters.currentRow()))
        character_actions.addWidget(add_character); character_actions.addWidget(remove_character); character_actions.addStretch(); character_layout.addLayout(character_actions)
        tabs.addTab(characters_tab, 'Characters')
        steps_tab = QWidget(); steps_layout = QVBoxLayout(steps_tab)
        self.steps = QTableWidget(len(goal['brief']['steps']), 2)
        self.steps.setHorizontalHeaderLabels(['Step', 'What it achieves'])
        self.steps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.steps.verticalHeader().setDefaultSectionSize(64)
        self.steps.setAccessibleName('Painting order')
        for index, step in enumerate(goal['brief']['steps']):
            self.steps.setItem(index, 0, QTableWidgetItem(step['title']))
            self.steps.setItem(index, 1, QTableWidgetItem(step['done_when']))
        steps_layout.addWidget(self.steps, 1)
        controls = QHBoxLayout()
        add = QPushButton('Add step'); add.clicked.connect(lambda: self.add_stage())
        remove = QPushButton('Remove selected'); remove.clicked.connect(lambda: self.remove_stage())
        controls.addWidget(add); controls.addWidget(remove); controls.addStretch(); steps_layout.addLayout(controls)
        self.stage_scope = QLineEdit(); self.stage_scope.setPlaceholderText('What this step focuses on (optional)'); self.stage_scope.setAccessibleName('Step scope')
        self.stage_materials = QLineEdit(); self.stage_materials.setPlaceholderText('Texture, e.g. walls: old red castle brick; roofs: rusty green metal')
        self.stage_materials.setAccessibleName('Step materials')
        stage_form = QFormLayout(); stage_form.addRow('Step focus', self.stage_scope); stage_form.addRow('Materials', self.stage_materials); steps_layout.addLayout(stage_form)
        order_note = QLabel('Steps are a suggested painting order. The Agent paints without stopping between them; one final review checks the finished painting.')
        order_note.setWordWrap(True); steps_layout.addWidget(order_note)
        self.steps.currentCellChanged.connect(lambda row, *_: self.select_stage(row))
        if self.steps.rowCount(): self.steps.setCurrentCell(0, 0)
        steps_layout.addWidget(QLabel('Final visual checks · one per line'))
        self.completion = QPlainTextEdit('\n'.join(goal['brief']['completion'])); self.completion.setMaximumHeight(130)
        self.completion.setAccessibleName('Completion checks'); steps_layout.addWidget(self.completion)
        tabs.addTab(steps_tab, 'Painting order')
        review_tab = QWidget(); review_layout = QVBoxLayout(review_tab)
        review = QTextBrowser(); review.setOpenLinks(False); review.setOpenExternalLinks(False)
        latest = (goal.get('reviews') or [None])[-1]
        if latest:
            review.setPlainText(latest['summary'] + '\n\n' + '\n\n'.join(('✓ ' if c['met'] else '○ ') + c['evidence'] for c in latest['checks']) +
                                ('\n\nStill to resolve:\n' + '\n'.join(latest['issues']) if latest['issues'] else ''))
        else:
            review.setPlainText('During Agent mode, a separate visual review compares the actual canvas with your reference and every requirement. Findings will appear here.')
        review_layout.addWidget(review); tabs.addTab(review_tab, 'Review')
        allowance = QHBoxLayout()
        allowance.addWidget(QLabel('Painting allowance'))
        self.minutes = QSpinBox(); self.minutes.setRange(0, 120); self.minutes.setSpecialValueText('No time limit'); self.minutes.setValue(goal['limits']['minutes']); self.minutes.setSuffix(' min')
        self.passes = QSpinBox(); self.passes.setRange(0, 150); self.passes.setSpecialValueText('No pass limit'); self.passes.setValue(goal['limits']['passes']); self.passes.setSuffix(' passes')
        self.minutes.setAccessibleName('Time allowance'); self.passes.setAccessibleName('Pass allowance')
        ai_images = goal['limits'].get('ai_images', 0)
        self.ai_images = QSpinBox(); self.ai_images.setRange(-1, 20); self.ai_images.setSpecialValueText('No AI image limit')
        self.ai_images.setSuffix(' AI images'); self.ai_images.setValue(-1 if ai_images is None else ai_images)
        self.ai_images.setAccessibleName('AI image allowance')
        self.ai_images.setToolTip('How many AI-generated images the painter may use in this chat. 0 paints everything by hand.')
        allowance.addWidget(self.minutes); allowance.addWidget(self.passes); allowance.addWidget(self.ai_images); allowance.addStretch(); layout.addLayout(allowance)
        used = QLabel('%d passes · %.1f minutes · %d AI images used. Paused time does not count.' % (goal.get('passes', 0), goal.get('used_ms', 0) / 60000, goal.get('ai_images_used', 0)))
        layout.addWidget(used)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        export = buttons.addButton('Export plan…', QDialogButtonBox.ButtonRole.ActionRole); export.clicked.connect(self.export_plan)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def add_stage(self):
        if self.steps.rowCount() >= 16: return
        self.save_stage(); self.stage_metadata.append({})
        self.steps.insertRow(self.steps.rowCount()); self.steps.setCurrentCell(self.steps.rowCount() - 1, 0)

    def remove_stage(self):
        row = self.steps.currentRow()
        if row < 0 or self.steps.rowCount() <= 1: return
        self.stage_index = -1
        if row < len(self.stage_metadata): self.stage_metadata.pop(row)
        self.steps.removeRow(row); self.steps.setCurrentCell(min(row, self.steps.rowCount() - 1), 0)
        self.select_stage(self.steps.currentRow())

    def save_stage(self):
        if self.stage_index < 0: return
        while len(self.stage_metadata) <= self.stage_index: self.stage_metadata.append({})
        step = self.stage_metadata[self.stage_index]
        if self.stage_scope.text().strip(): step['scope'] = self.stage_scope.text().strip()
        else: step.pop('scope', None)
        materials = edited_materials(self.stage_materials.text(), step.get('materials') or [])
        if materials: step['materials'] = materials
        else: step.pop('materials', None)

    def select_stage(self, index):
        self.save_stage(); self.stage_index = index
        step = self.stage_metadata[index] if 0 <= index < len(self.stage_metadata) else {}
        self.stage_scope.setText(step.get('scope', ''))
        self.stage_materials.setText(materials_line(step.get('materials') or []))

    def markdown(self):
        brief = self.brief()
        lines = ['# ' + brief['title'], '', brief['objective'], '', 'Plan revision: ' + str(self.goal_record.get('revision', 1))]
        target = self.export_target
        if target:
            filename = os.path.basename(target.get('filename') or '')
            name = filename or target.get('name') or ('Working copy' if target.get('mode') == 'copy' else 'New painting')
            lines += ['', '## Painting target', '', name]
        shape = self.goal_record.get('plan_target') or {}
        if shape.get('width') and shape.get('height'): lines += ['', 'Canvas: %s × %s px' % (shape['width'], shape['height'])]
        if self.export_references:
            lines += ['', '## References', '']
            for reference in self.export_references:
                purpose = dict(REFERENCE_PURPOSES).get(reference.get('purpose') or 'general', 'Overall direction')
                if reference.get('role') == 'construction-map': purpose = 'Construction map · ' + purpose
                lines.append('- ' + (reference.get('name') or os.path.basename(reference.get('path', 'Reference'))) + ' — ' + purpose)
                if reference.get('notes'): lines.append('  ' + reference['notes'].replace('\n', '\n  '))
        lines += ['', '## Requirements to preserve', ''] + ['- ' + rule for rule in brief['requirements']]
        if brief.get('characters'):
            lines += ['', '## Characters', '']
            for character in brief['characters']:
                lines += ['### ' + character['name'], ''] + ['- ' + rule for rule in character['requirements']] + ['']
        if brief['freedom']: lines += ['', '## Creative freedom', ''] + ['- ' + choice for choice in brief['freedom']]
        lines += ['', '## Painting order', '', 'A suggested order. The Agent paints without stopping between steps.', '']
        for index, step in enumerate(brief['steps']):
            lines += ['### %d. %s' % (index + 1, step['title']), '']
            if step.get('scope'): lines += ['Focus: ' + step['scope'], '']
            lines += ['Achieves: ' + step['done_when'], '']
            if step.get('materials'): lines += ['Materials: ' + materials_line(step['materials']), '']
        lines += ['## Final visual checks', ''] + ['- ' + check for check in brief['completion']]
        lines += ['', '## Allowance', '', ('%d minutes' % self.minutes.value() if self.minutes.value() else 'No time limit') + ' · ' + ('%d painting operations' % self.passes.value() if self.passes.value() else 'No pass limit'),
                  'Paused time does not count. This is a work allowance, not a monetary spending limit.']
        reviews = self.goal_record.get('reviews') or []
        if reviews:
            review = reviews[-1]
            lines += ['', '## Latest visual review', '', review.get('summary', '')]
            for check in review.get('checks', []): lines.append('- ' + ('Met: ' if check.get('met') else 'Still to resolve: ') + check.get('evidence', ''))
            if review.get('issues'): lines += ['', 'Remaining issues:'] + ['- ' + issue for issue in review['issues']]
        return '\n'.join(lines).rstrip() + '\n'

    def export_plan(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export painting plan', 'painting-plan.md', 'Markdown (*.md)')
        if not path: return
        try:
            with open(path, 'w', encoding='utf-8') as stream: stream.write(self.markdown())
        except OSError as error:
            self.setWindowTitle('Could not export plan: ' + str(error))

    def brief(self):
        split = lambda field: [line.strip() for line in field.toPlainText().splitlines() if line.strip()]
        self.save_stage()
        brief = dict(self.original_brief)
        brief.update({'title': self.title.text().strip(), 'objective': self.objective.toPlainText().strip(),
                'requirements': split(self.rules), 'freedom': split(self.freedom), 'completion': split(self.completion),
                'steps': [dict(self.stage_metadata[i] if i < len(self.stage_metadata) else {},
                           title=self.steps.item(i, 0).text().strip() if self.steps.item(i, 0) else '',
                           done_when=self.steps.item(i, 1).text().strip() if self.steps.item(i, 1) else '')
                          for i in range(self.steps.rowCount())]})
        characters = []
        for row in range(self.characters.rowCount()):
            name = self.characters.item(row, 0).text().strip() if self.characters.item(row, 0) else ''
            details = self.characters.item(row, 1).text() if self.characters.item(row, 1) else ''
            if name or details: characters.append({'name': name, 'requirements': [line.strip() for line in details.splitlines() if line.strip()]})
        if characters or 'characters' in brief: brief['characters'] = characters
        return brief

    def accept(self):
        brief = self.brief()
        if not brief['title'] or not brief['objective'] or not brief['completion'] or any(not s['title'] or not s['done_when'] for s in brief['steps']):
            self.setWindowTitle('Complete the objective, painting order, and final checks')
            return
        super().accept()


ASSISTANT = 'Creative Agent'                                     # the role of the agent's own messages


class ChatTranscript(QScrollArea):
    followChanged = pyqtSignal(bool)
    previewRequested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName('Conversation with Creative Agent')
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.rows.setContentsMargins(2, 16, 7, 12)
        self.rows.setSpacing(20)
        self.rows.addStretch()
        self.setWidget(self.body)
        self.messages = []
        self.reflow_timer = QTimer(self)
        self.reflow_timer.setSingleShot(True)
        self.reflow_timer.timeout.connect(self.reflow)
        self.setMinimumHeight(120)
        self.follow = True
        self.verticalScrollBar().sliderMoved.connect(self.track_scroll)
        self.verticalScrollBar().actionTriggered.connect(lambda _action: QTimer.singleShot(0, self.track_scroll))

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.track_scroll()

    def track_scroll(self):
        bar = self.verticalScrollBar()
        following = bar.maximum() - bar.value() < 30
        if following != self.follow:
            self.follow = following
            self.followChanged.emit(self.follow)

    def jump_to_latest(self):
        self.follow = True
        self.followChanged.emit(True)
        self.scroll_end()

    def render(self, text):
        # No model-generated HTML, external images, or automatic link loading.
        safe = html.escape(text, quote=False)
        safe = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'[Image: \1]', safe)
        safe = re.sub(r'!\[([^\]]*)\]\[[^\]]*\]', r'[Image: \1]', safe)
        document = QTextDocument()
        font = self.font(); base_size = getattr(self, 'body_text_size', 14); font.setPixelSize(base_size); document.setDefaultFont(font)
        document.setDefaultStyleSheet('body { line-height: 140%; } p { margin-top: 0; margin-bottom: 10px; } '
                                     'h1 { font-size: 19px; } h2 { font-size: 17px; } h3 { font-size: 15px; } '
                                     'li { margin-bottom: 5px; } pre { white-space: pre-wrap; }')
        document.setMarkdown(safe)
        block = document.begin()
        while block.isValid():
            cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setLineHeight(138, enum_value(QTextBlockFormat.LineHeightTypes.ProportionalHeight))
            block_format.setBottomMargin(3 if block.textList() else 9)
            if block_format.headingLevel():
                block_format.setTopMargin(4 if block.position() else 0)
                block_format.setBottomMargin(7)
                cursor.setPosition(block.position())
                cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
                char_format = QTextCharFormat(); heading_font = QFont(font)
                heading_font.setPixelSize(round({1: 20, 2: 18, 3: 16}.get(block_format.headingLevel(), 14) * base_size / 14))
                heading_font.setWeight(QFont.Weight.DemiBold); char_format.setFont(heading_font); cursor.mergeCharFormat(char_format)
            cursor.clearSelection(); cursor.setPosition(block.position())
            cursor.setBlockFormat(block_format)
            block = block.next()
        return document.toHtml()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'reflow_timer'): self.reflow_timer.start(0)

    def reflow(self):
        # Width changes reflow documents; deltas update only the current reply.
        for item in self.messages:
            item['label'].fit_height()
        self.scroll_end()

    def add_message(self, role, text, action=False, message_id=None):
        card = QFrame()
        card.setObjectName('userMessage' if role == 'You' else 'actionMessage' if action else 'assistantMessage')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12 if role == 'You' else 2, 10 if role == 'You' else 0, 12 if role == 'You' else 2, 10 if role == 'You' else 0)
        layout.setSpacing(7)
        label = QLabel(role)
        label.setObjectName('messageRole')
        body = MessageBody()
        body.setAccessibleDescription(role + ' message')
        title, _, details = text.partition('\n')
        details = details.strip()
        # An activity row: its first line is the row; the body opens on the details, never the title again.
        body.set_rendered(self.render(details if action and details else text))
        if action and not details:
            line = QLabel('·  ' + title[:200]); line.setObjectName('activityDisclosure'); line.setTextFormat(Qt.TextFormat.PlainText)
            line.setWordWrap(True); line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            body.hide(); layout.addWidget(line)
        elif action:
            toggle = QPushButton('›  ' + title[:90])
            toggle.setObjectName('activityDisclosure'); toggle.setCheckable(True)
            toggle.setAccessibleName('Expand ' + role.lower() + ' details'); toggle.setToolTip(title if len(title) > 90 else '')
            body.hide()
            toggle.toggled.connect(body.setVisible)
            toggle.toggled.connect(lambda checked: toggle.setText(('⌄  ' if checked else '›  ') + title[:90]))
            layout.addWidget(toggle)
        elif role != ASSISTANT:                                  # the agent's replies need no name over each one
            layout.addWidget(label)
        layout.addWidget(body)
        item = {'role': role, 'text': text, 'label': body, 'card': card, 'layout': layout, 'id': message_id, 'action': action}
        self.messages.append(item)
        self.rows.insertWidget(self.rows.count() - 1, card)
        self.reflow_timer.start(0)
        self.scroll_end()
        return item

    def append_to(self, item, text):
        old_position = self.verticalScrollBar().value()
        item['text'] += text
        item['label'].set_rendered(self.render(item['text']))
        if not self.follow:
            self.verticalScrollBar().setValue(old_position)
        self.scroll_end()

    def add_receipt(self, item, canvas):
        if item.get('receipt'): return
        name = canvas_name(canvas)
        button = QPushButton('▧  ' + name + ' · included')
        button.setObjectName('receipt')
        button.setToolTip('Open the exact canvas snapshot included in this message\n' + canvas_details(canvas))
        button.setAccessibleName('Preview included canvas ' + name)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda: self.previewRequested.emit(canvas))
        item['layout'].insertWidget(1, button)
        item['receipt'] = canvas

    def add_region_receipt(self, item, region, canvas=None):
        if item.get('region_receipt'): return
        snapshot = dict(region)
        if canvas and canvas.get('revision') == region.get('revision'): snapshot['overview_path'] = canvas.get('path')
        name = region.get('name') or 'Selection bounds'
        button = QPushButton('⌗  ' + name + ' · crop included'); button.setObjectName('receipt')
        button.setAccessibleName('Preview included rectangular crop')
        button.setToolTip('Open the exact rectangular crop included in this message')
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda: self.previewRequested.emit(snapshot))
        item['layout'].insertWidget(2 if item.get('receipt') else 1, button)
        item['region_receipt'] = snapshot

    def add_reference_receipts(self, item, references):
        if item.get('reference_receipts'): return
        snapshots = [dict(reference) for reference in references]
        for index, reference in enumerate(snapshots):
            name = reference.get('name') or os.path.basename(reference.get('path', 'Reference'))
            purpose = REFERENCE_CAPTIONS.get(reference.get('purpose') or 'general', 'General')
            button = QPushButton('▧  ' + name + ' · ' + purpose.lower()); button.setObjectName('receipt')
            button.setAccessibleName('Preview included reference ' + name)
            button.setToolTip('Included reference · ' + name + '\nPurpose when sent: ' + purpose)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, snapshot=reference: self.previewRequested.emit(snapshot))
            item['layout'].insertWidget(1 + index + bool(item.get('receipt')) + bool(item.get('region_receipt')), button)
        item['reference_receipts'] = snapshots

    def add_question(self, question, options, answer, image_path=None):
        item = self.add_message('A quick question', question)
        item['card'].setObjectName('questionMessage')
        # A picture the question is about (a close-up's place drawn on the goal image), scaled to the card.
        pixmap = QPixmap(image_path) if image_path else QPixmap()
        if not pixmap.isNull():
            picture = QLabel(); picture.setObjectName('questionImage')
            picture.setPixmap(pixmap.scaled(QSize(360, 270), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            item['layout'].addWidget(picture)
        choices = list(options)
        if not any(choice.casefold().strip(' .') == 'you decide' for choice in choices): choices.append('You decide')
        controls = []
        for option in choices:
            button = QPushButton(option)
            button.setObjectName('questionChoice')
            button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setToolTip(option)
            button.clicked.connect(lambda _checked=False, value=option: answer(value))
            item['layout'].addWidget(button); controls.append(button)
        note = QLabel('Or write your own answer below.'); note.setObjectName('muted')
        item['layout'].addWidget(note)
        return controls

    def scroll_end(self):
        if self.follow:
            QTimer.singleShot(0, self._finish_scroll)

    def _finish_scroll(self):
        # A user may scroll between scheduling and dispatching this callback.
        if self.follow:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear(self):
        for item in self.messages:
            self.rows.removeWidget(item['card'])
            item['card'].hide()
            item['card'].deleteLater()
        self.messages = []
        self.follow = True
        self.followChanged.emit(True)

    def toPlainText(self):
        return '\n\n'.join(item['role'] + '\n' + item['text'] for item in self.messages)


class LessonDialog(QDialog):
    """The latest Ask-mode lesson, for the artist only. Not modal, so it stays open while painting."""
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent
        self.setWindowTitle('Lesson'); self.resize(560, 680); self.setModal(False)
        layout = QVBoxLayout(self)
        self.body = QTextBrowser(); self.body.setOpenLinks(False); self.body.setOpenExternalLinks(False)
        self.body.setAccessibleName('Lesson'); layout.addWidget(self.body, 1)
        note = QLabel('For you to follow along. The painter does not read this lesson.'); note.setObjectName('muted'); note.setWordWrap(True)
        layout.addWidget(note)

    def show_lesson(self, lesson):
        self.setWindowTitle('Lesson · ' + lesson.get('title', ''))
        position = self.body.verticalScrollBar().value() if self.isVisible() else 0
        self.body.setHtml(self.panel.transcript.render(lesson.get('markdown', '')))
        self.body.verticalScrollBar().setValue(position)


class HistoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent
        self.setWindowTitle('Conversations'); self.resize(560, 580)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search paintings and conversations…'); self.search.setAccessibleName('Search conversations')
        layout.addWidget(self.search)
        self.list = QListWidget(); self.list.setAccessibleName('Saved conversations'); layout.addWidget(self.list, 1)
        self.note = QLabel('Loading conversations…'); self.note.setObjectName('muted'); self.note.setWordWrap(True); layout.addWidget(self.note)
        # Chat records: delete, and move chats between machines as one archive file (storage-layout E).
        manage = QHBoxLayout()
        self.delete_button = QPushButton('Delete…'); self.delete_button.setToolTip('Delete this chat and its records. Its painting is not touched.')
        self.delete_button.clicked.connect(self.delete_chat); manage.addWidget(self.delete_button)
        self.export_button = QPushButton('Export…'); self.export_button.setToolTip('Save the selected chat, or every chat when none is selected, as one archive file.')
        self.export_button.clicked.connect(self.export_chats); manage.addWidget(self.export_button)
        importer = QPushButton('Import…'); importer.setToolTip('Add chats from an archive file exported on this or another computer.')
        importer.clicked.connect(self.import_archive); manage.addWidget(importer)
        manage.addStretch(); layout.addLayout(manage)
        actions = QHBoxLayout()
        locate = QPushButton('Locate painting…'); locate.clicked.connect(self.relink); actions.addWidget(locate)
        actions.addStretch()
        restore = QPushButton('Open conversation'); restore.setObjectName('primaryAction'); restore.clicked.connect(self.restore); actions.addWidget(restore)
        layout.addLayout(actions)
        self.total_bytes = None; self.query = ''
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(lambda: parent.send({'type': 'history', 'query': self.search.text()}))
        self.search.textChanged.connect(lambda: self.timer.start(180)); self.list.itemDoubleClicked.connect(lambda _: self.restore())

    @staticmethod
    def size_text(size):
        return '%.1f GB' % (size / 1e9) if size >= 1e9 else '%d MB' % round(size / 1e6) if size >= 1e6 else '%d KB' % max(1, round(size / 1e3))

    def set_items(self, items, total_bytes=None, query=''):
        self.total_bytes, self.query = total_bytes, query
        self.list.clear()
        for entry in items:
            filename = entry.get('filename') or 'Draft · no painting yet'
            state = entry.get('status', 'paused').replace('_', ' ')
            size = ' · ' + self.size_text(entry['size_bytes']) if entry.get('size_bytes') else ''
            item = QListWidgetItem((entry.get('title') or 'Untitled conversation') + '\n' + os.path.basename(filename) + ' · ' + state + size)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(filename + '\n' + str(entry.get('updated_at', '')))
            if entry.get('thumbnail'): item.setIcon(QIcon(entry['thumbnail']))
            self.list.addItem(item)
        self.list.setIconSize(QSize(48, 48))
        total = (' Agent records: ' + self.size_text(total_bytes) + '.') if total_bytes else ''
        if items: self.note.setText('Restored conversations stay paused. Your other open paintings are preserved.' + total)
        elif query: self.note.setText('No matching conversations. Try another search or locate your painting.')
        else: self.note.setText('No chats in this project yet. Chats from another computer can be added with Import….')

    def selected_entry(self):
        selected = self.list.currentItem()
        return selected.data(Qt.ItemDataRole.UserRole) if selected else None

    # Dialog helpers, replaceable in tests.
    def confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def choose_save(self, title, name):
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(os.path.expanduser('~/Desktop'), name), 'Creative Agent archive (*.creative-agent-archive)')
        return path and (path if path.endswith('.creative-agent-archive') else path + '.creative-agent-archive')

    def choose_open(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, os.path.expanduser('~'), 'Creative Agent archive (*.creative-agent-archive)')
        return path

    def delete_chat(self):
        entry = self.selected_entry()
        if not entry:
            self.note.setText('Choose the chat to delete.'); return
        if entry.get('id') == getattr(self.panel, 'study_id', None):
            self.note.setText('Close this chat before deleting it.'); return
        if self.confirm('Delete chat', 'Delete "%s" and its records (%s)? Its painting is not touched. This cannot be undone.'
                        % (entry.get('title') or 'Untitled conversation', self.size_text(entry.get('size_bytes') or 0))):
            self.panel.send({'type': 'delete_chat', 'id': entry['id']})

    def export_chats(self):
        entry = self.selected_entry()
        name = re.sub(r'\s+', ' ', re.sub(r'[^\w .-]+', '', entry.get('title') or 'chat')).strip() or 'chat' if entry else 'All chats'
        path = self.choose_save('Export chat' if entry else 'Export every chat', name + '.creative-agent-archive')
        if path: self.panel.send({'type': 'export_archive', 'path': path, **({'id': entry['id']} if entry else {})})

    def import_archive(self):
        path = self.choose_open('Import chats')
        if path: self.panel.send({'type': 'import_archive', 'path': path})

    def restore(self):
        selected = self.list.currentItem()
        if selected:
            self.panel.request_restore({'type': 'resume', 'id': selected.data(Qt.ItemDataRole.UserRole)['id']}); self.hide()

    def relink(self):
        selected = self.list.currentItem()
        if not selected:
            self.note.setText('Choose the conversation whose painting has moved.'); return
        path, _ = QFileDialog.getOpenFileName(self, 'Locate this painting', getattr(self.panel, 'paintings_directory', ''), 'Krita paintings (*.kra)')
        if path: self.panel.send({'type': 'relink', 'id': selected.data(Qt.ItemDataRole.UserRole)['id'], 'path': path})


class PassReviewDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent; self.entries = []
        self.setWindowTitle('Review painting changes'); self.resize(760, 650)
        layout = QVBoxLayout(self)
        self.selector = QComboBox(); self.selector.setAccessibleName('Agent pass to review'); self.selector.currentIndexChanged.connect(self.show_pass); layout.addWidget(self.selector)
        views = QHBoxLayout()
        self.before = QLabel(); self.after = QLabel()
        for title, label in [('Before', self.before), ('After', self.after)]:
            column = QVBoxLayout(); heading = QLabel(title); heading.setObjectName('muted'); column.addWidget(heading)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setMinimumSize(80, 100); label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            column.addWidget(label, 1); views.addLayout(column, 1)
        layout.addLayout(views, 1)
        self.warning = QLabel(''); self.warning.setWordWrap(True); self.warning.setObjectName('muted'); layout.addWidget(self.warning)
        controls = QHBoxLayout()
        self.visible = QCheckBox('Show pass'); self.visible.toggled.connect(lambda checked: self.change('visibility', checked)); controls.addWidget(self.visible)
        controls.addWidget(QLabel('Strength'))
        self.strength = QSlider(Qt.Orientation.Horizontal); self.strength.setRange(0, 100); self.strength.setAccessibleName('Agent pass strength')
        self.strength.sliderReleased.connect(lambda: self.change('strength', self.strength.value() / 100)); controls.addWidget(self.strength, 1)
        self.percent = QLabel('100%'); self.strength.valueChanged.connect(lambda v: self.percent.setText(str(v) + '%')); controls.addWidget(self.percent)
        self.reject_pass = QPushButton('Reject pass'); self.reject_pass.clicked.connect(lambda: self.change('reject')); controls.addWidget(self.reject_pass)
        layout.addLayout(controls)
        note = QLabel('Changes apply only to recorded agent layers. If an artist has edited a layer, it is protected.'); note.setWordWrap(True); note.setObjectName('muted'); layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); self.buttons.rejected.connect(self.hide); layout.addWidget(self.buttons)

    def set_passes(self, entries):
        identifier = self.selector.currentData()
        self.entries = entries
        self.selector.blockSignals(True); self.selector.clear()
        for entry in entries: self.selector.addItem(entry.get('title') or entry.get('label') or 'Painting pass', entry['id'])
        index = self.selector.findData(identifier)
        self.selector.setCurrentIndex(index if index >= 0 else max(0, len(entries) - 1)); self.selector.blockSignals(False)
        self.show_pass()

    def show_pass(self, *_args):
        index = self.selector.currentIndex()
        entry = self.entries[index] if 0 <= index < len(self.entries) else None
        self.visible.blockSignals(True); self.strength.blockSignals(True)
        if entry:
            self.before_image = QPixmap(entry.get('before_path', '')); self.after_image = QPixmap(entry.get('after_path', ''))
            self.visible.setChecked(entry.get('visible', True)); self.strength.setValue(round(entry.get('strength', 1) * 100))
            self.percent.setText(str(self.strength.value()) + '%')
            self.warning.setText(entry.get('warning') or ('This pass has been rejected.' if entry.get('rejected') else 'Compare the captured before and after views.'))
        else:
            self.before_image = QPixmap(); self.after_image = QPixmap(); self.warning.setText('No recorded agent changes yet.')
        enabled = bool(entry and not entry.get('rejected') and not self.panel.busy)
        available = (entry or {}).get('review_actions', ['visibility', 'strength', 'reject'])
        self.visible.setText('Show step' if entry and entry.get('kind') == 'stage' else 'Show pass')
        self.reject_pass.setText('Reject step' if entry and entry.get('kind') == 'stage' else 'Reject pass')
        for action, widget in [('visibility', self.visible), ('strength', self.strength), ('reject', self.reject_pass)]: widget.setEnabled(enabled and action in available)
        self.visible.blockSignals(False); self.strength.blockSignals(False); self.render_images()

    def render_images(self):
        for label, image in [(self.before, getattr(self, 'before_image', QPixmap())), (self.after, getattr(self, 'after_image', QPixmap()))]:
            if image.isNull(): label.setText('No snapshot')
            else: label.setPixmap(image.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event); self.render_images()

    def change(self, action, value=None):
        if not self.selector.currentData(): return
        command = {'type': 'review_pass', 'action': action, 'pass_id': self.selector.currentData()}
        if value is not None: command['value'] = value
        self.panel.send(command)


class CreativeAgentDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Creative Agent')
        self.process = None
        self.buffer = b''
        self.models = []
        self.providers = []
        self.accepted_model = None
        self.pending_model_change = False
        self.reference = None
        self.construction_map = None
        self.study_active = False
        self.busy = False
        self.reply_open = False
        self.current_reply = None
        self.output_directory = None
        self.chat_directory = None                    # the chat's own folder (found outlines live in its .shapes); a save never moves it
        self.resume_on_ready = None
        self.pending_restore = None
        self.focus_after_restore = False
        self.study_id = None
        self.relink_id = None
        self.phase = 'idle'
        self.phase_started = time.monotonic()
        self.run_started = None
        self.saved_path = None
        self.saved_at = None
        self.painting_target = {}
        self.goal = None
        self.chat_mode = 'ask'
        self.pending_references = []
        self.attached_references = []
        self.canvas_context = {'selected': True, 'follow_active': True, 'state': 'none', 'canvas': None}
        self.question_id = None
        self.question_controls = []
        self.closeup_question_id = None
        self.closeup_controls = []
        self.streaming_text = ''
        self.last_user_item = None
        self.history_dialog = None
        self.pass_dialog = None
        self.versions = {}
        self.theme_mode = 'system'
        self.text_scale = 1.0
        self.document_signature = None
        self.had_document = False; self.mode_user_chosen = False; self.mode_auto = False
        self.uncertain_operations = []
        self.inspected_uncertain = False
        self.preview_after_refresh = False
        self.stream_timer = QTimer(self)
        self.stream_timer.setSingleShot(True)
        self.stream_timer.timeout.connect(self.flush_stream)
        self.context_timer = QTimer(self)
        self.context_timer.setSingleShot(True)
        self.context_timer.timeout.connect(lambda: self.context_command('inspect'))
        body = QWidget(); body.setObjectName('creativeChat')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)
        self.setMinimumWidth(320)
        self.setMinimumHeight(440)
        header = QHBoxLayout(); header.setSpacing(3)
        # The app's own name, once (the dock's title bar is Krita's): Toska in the fork, Krita in stock.
        self.title = QLabel(product_name()); self.title.setObjectName('chatTitle')
        header.addWidget(self.title, 1)
        self.end_button = QPushButton('＋'); self.end_button.setObjectName('headerAction')
        self.end_button.setAccessibleName('New chat')
        self.end_button.setToolTip('New chat · your painting stays open')
        self.end_button.clicked.connect(lambda: self.send({'type': 'end'}) if self.study_active else self.new_chat())
        header.addWidget(self.end_button)
        self.history_button = QPushButton('◷'); self.history_button.setObjectName('headerAction')
        self.history_button.setAccessibleName('Conversation history'); self.history_button.setToolTip('Conversation history')
        self.history_button.clicked.connect(self.show_history); header.addWidget(self.history_button)
        self.options_button = QPushButton('···'); self.options_button.setObjectName('headerAction')
        self.options_button.setAccessibleName('Settings'); self.options_button.setToolTip('Painting settings and connections')
        self.options_button.clicked.connect(lambda: self.show_settings())
        header.addWidget(self.options_button)
        layout.addLayout(header)
        self.workspace_label = QLabel('Your painting, in conversation'); self.workspace_label.setObjectName('muted')
        self.workspace_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        workspace_row = QHBoxLayout(); workspace_row.setSpacing(6)
        workspace_row.addWidget(self.workspace_label, 1)
        self.return_button = QPushButton('Return to painting'); self.return_button.setObjectName('footerAction')
        self.return_button.setAccessibleName('Return to the painting target')
        self.return_button.clicked.connect(lambda: self.return_to_painting())
        self.return_button.hide(); workspace_row.addWidget(self.return_button)
        layout.addLayout(workspace_row)
        self.use_canvas_button = QPushButton('Use this canvas as painting target')
        self.use_canvas_button.setObjectName('footerAction')
        self.use_canvas_button.setToolTip('Keep this conversation and plan, and work on the attached painting. Nothing paints until you Resume.')
        self.use_canvas_button.clicked.connect(lambda: self.send({'type': 'use_attached_canvas'}))
        self.use_canvas_button.hide(); layout.addWidget(self.use_canvas_button)
        # The artist's layout B (2026-10-23): under the header, the plan's progress strip and the Now painting card (and the
        # move card and activity line), pinned above the tabs so what paints is always on screen; then Chat · Plan · Folder.
        # The panel itself never scrolls: each tab has one scroll area (Chat its transcript, Plan and Folder their page).
        # Auto-approve (auto_approve.py): the card that waits counts down and takes its default answer unless the artist acts.
        self.auto_approve = AutoApprove(self); self.auto_last = 60; self.settings_unsent = False
        self.plan_steps = PlanStepsList(self.send_plan_step, self.request_stop, self.auto_approve.cancel)
        layout.addWidget(self.plan_steps.strip); layout.addWidget(self.plan_steps.now)
        # Start painting / Resume on the card when nothing paints, so it is reachable from every tab (the Plan tab's rule).
        self.card_start = QPushButton('Start painting'); self.card_start.setObjectName('primaryAction')
        self.card_start.setAccessibleName('Start painting the plan'); self.card_start.clicked.connect(lambda: self.start_plan())
        self.card_start.hide(); self.plan_steps.caption_row.addWidget(self.card_start, 0, Qt.AlignmentFlag.AlignTop)
        self.revealed_step = None
        self.card_reason = QLabel(''); self.card_reason.setObjectName('muted'); self.card_reason.setWordWrap(True)
        self.card_reason.setTextFormat(Qt.TextFormat.PlainText); self.card_reason.hide(); self.plan_steps.now_layout.addWidget(self.card_reason)
        self.now_auto = self.auto_label(); self.plan_steps.now_layout.addWidget(self.now_auto)
        self.plan_steps.strip.tapped.connect(self.show_step)
        # Sharpen goal (goal-sharpen.ts): its progress on the Now card while it runs, with Cancel.
        self.sharpen_row = QWidget(); sharpen_layout = QVBoxLayout(self.sharpen_row); sharpen_layout.setContentsMargins(0, 0, 0, 0); sharpen_layout.setSpacing(3)
        sharpen_top = QHBoxLayout(); sharpen_top.setSpacing(6)
        self.sharpen_text = QLabel(''); self.sharpen_text.setObjectName('muted'); self.sharpen_text.setWordWrap(True)
        self.sharpen_text.setTextFormat(Qt.TextFormat.PlainText); self.sharpen_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sharpen_top.addWidget(self.sharpen_text, 1)
        self.sharpen_cancel = QPushButton('Cancel'); self.sharpen_cancel.setObjectName('stepStop'); self.sharpen_cancel.setAccessibleName('Stop sharpening the goal image')
        self.sharpen_cancel.setToolTip('Stop sharpening: the original goal image is used.')
        self.sharpen_cancel.clicked.connect(lambda: (self.sharpen_cancel.setEnabled(False), self.send({'type': 'goal_sharpen', 'action': 'cancel'})))
        sharpen_top.addWidget(self.sharpen_cancel, 0, Qt.AlignmentFlag.AlignTop); sharpen_layout.addLayout(sharpen_top)
        self.sharpen_bar = QProgressBar(); self.sharpen_bar.setRange(0, 1000); self.sharpen_bar.setTextVisible(False); self.sharpen_bar.setFixedHeight(6)
        self.sharpen_bar.setAccessibleName('Sharpening progress'); sharpen_layout.addWidget(self.sharpen_bar)
        self.sharpen_row.hide(); self.plan_steps.now_layout.addWidget(self.sharpen_row)
        self.sharpen_controls = []; self.canvas_reference_controls = []
        top_area = QVBoxLayout(); top_area.setContentsMargins(0, 0, 0, 0); top_area.setSpacing(6); layout.addLayout(top_area)
        self.tabs = QTabWidget(); self.tabs.setObjectName('panelTabs'); self.tabs.setDocumentMode(True); self.tabs.setUsesScrollButtons(False)
        self.tabs.tabBar().setDrawBase(False); self.tabs.tabBar().setExpanding(False)
        self.tabs.setAccessibleName('Chat, plan and project folder')
        chat_page = QWidget(); chat_page.setObjectName('creativeChat'); chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 6, 0, 0); chat_layout.setSpacing(8)
        def scrolled_page(name):
            page = QWidget(); page.setObjectName('creativeChat'); page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 8, 2, 8); page_layout.setSpacing(8)
            scroll = QScrollArea(); scroll.setObjectName(name); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); scroll.setWidget(page)
            return scroll, page_layout
        self.plan_scroll, plan_page = scrolled_page('planPage')
        self.folder_scroll, folder_page = scrolled_page('folderPage')
        self.chat_tab = self.tabs.addTab(chat_page, 'Chat'); self.plan_tab = self.tabs.addTab(self.plan_scroll, 'Plan')
        self.folder_tab = self.tabs.addTab(self.folder_scroll, 'Folder')
        self.tabs.setTabVisible(self.plan_tab, False); self.tabs.setTabVisible(self.folder_tab, False)
        self.tabs.setTabToolTip(self.plan_tab, 'The plan, one step per element: skip, restore, keep or redo a step')
        self.tabs.setTabToolTip(self.folder_tab, 'The project folder: its goal image, element images and big colour masses')
        layout.addWidget(self.tabs, 1)
        # The current step is scrolled into view once Qt has laid the list out: a timer the panel owns, so it dies with it.
        self.reveal_timer = QTimer(self); self.reveal_timer.setSingleShot(True); self.reveal_timer.setInterval(0)
        self.reveal_timer.timeout.connect(self.reveal_current_step)
        self.tabs.currentChanged.connect(self.tab_changed)
        layout = chat_layout                                  # what follows goes into the Chat tab unless placed elsewhere

        self.model = ModelComboBox(); self.model.setMinimumWidth(70)
        self.model.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.model.setMinimumContentsLength(8)
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setAccessibleName('Model'); self.model.setToolTip('Choose the model receiving this conversation and attached images')
        self.model.modelChosen.connect(self.change_model)
        self.setup_box = QWidget(); self.setup_box.setObjectName('settingsBody'); self.setup_box.setMinimumWidth(0)
        settings_sections = QVBoxLayout(self.setup_box); settings_sections.setContentsMargins(6, 0, 10, 10); settings_sections.setSpacing(18)
        def settings_section(title):
            group = QGroupBox(title)
            rows = QFormLayout(group); rows.setContentsMargins(0, 10, 0, 0)
            rows.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            rows.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            rows.setVerticalSpacing(7); settings_sections.addWidget(group)
            return rows
        form = settings_section('Painting target')
        self.source = QComboBox(); self.source.addItem('Current canvas', 'current'); self.source.addItem('New painting', 'new'); self.source.addItem('Copy current painting', 'copy')
        # The dock often loads before any document opens. That is not an
        # instruction to create a painting when the artist later sends a message.
        self.source.setToolTip('Agent works on the current canvas by default. Choose a new painting or working copy only when you want one.')
        self.name = QLineEdit('Creative painting')
        size = QHBoxLayout(); size.setSpacing(8)
        self.canvas_width = QSpinBox(); self.canvas_width.setRange(128, 8192); self.canvas_width.setValue(768)
        self.canvas_height = QSpinBox(); self.canvas_height.setRange(128, 8192); self.canvas_height.setValue(1024)
        size_separator = QLabel('×'); size_separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        size.addWidget(self.canvas_width, 1); size.addWidget(size_separator); size.addWidget(self.canvas_height, 1)
        self.experiment = QComboBox(); self.experiment.addItem('Create freely', 'free')
        self.experiment.addItem('Follow a construction map', 'guided'); self.experiment.addItem('Plan from a reference', 'independent')
        form.addRow('Work on', self.source); form.addRow('Name', self.name); form.addRow('Size', size); form.addRow('Approach', self.experiment)
        self.map_button = QPushButton('Attach construction map…'); self.map_button.clicked.connect(lambda: self.attach('map')); form.addRow(self.map_button)
        appearance = settings_section('Appearance')
        self.theme_selector = QComboBox(); self.theme_selector.addItems(['Match %s' % product_name(), 'Dark', 'Light'])
        self.theme_selector.currentIndexChanged.connect(self.set_theme); appearance.addRow('Theme', self.theme_selector)
        self.text_size = QSpinBox(); self.text_size.setRange(13, 20); self.text_size.setValue(14); self.text_size.setSuffix(' px')
        self.text_size.setAccessibleName('Chat text size'); self.text_size.valueChanged.connect(self.set_text_size); appearance.addRow('Text size', self.text_size)
        execution = settings_section('Agent execution')
        self.reasoning_selector = QComboBox(); self.reasoning_selector.setAccessibleName('Reasoning level')
        for label, value in [('Auto', 'auto'), ('Off', 'off'), ('Minimal', 'minimal'), ('Low', 'low'), ('Medium', 'medium'), ('High', 'high'), ('Extra high', 'xhigh'), ('Maximum', 'max')]:
            self.reasoning_selector.addItem(label, value)
        execution.addRow('Reasoning', self.reasoning_selector)
        self.reasoning_note = QLabel('Auto adjusts reasoning to the task when the model supports it.'); self.reasoning_note.setWordWrap(True)
        self.reasoning_note.setObjectName('muted'); execution.addRow(self.reasoning_note)
        # Generic settings (move size, merging, image assets, decision checks…) are built from the companion's
        # declarations (settings_schema), so a new setting needs no code here.
        self.setting_widgets = {}; self.last_execution_settings = None
        self.generic_settings_host = QWidget(); self.generic_settings = QFormLayout(self.generic_settings_host)
        self.generic_settings.setContentsMargins(0, 0, 0, 0); self.generic_settings.setVerticalSpacing(7)
        self.generic_settings.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows); self.generic_settings.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        execution.addRow(self.generic_settings_host)
        craft_note = QLabel('The painter uses the full %s toolset: layers, selections, fills, filters, masks and gradients, then brush strokes.' % product_name())
        craft_note.setWordWrap(True); craft_note.setObjectName('muted'); execution.addRow(craft_note)
        # Decision endpoint and model: OpenRouter (live list), OpenAI, TypeSafe, or a custom System One endpoint.
        self.decision_endpoint = QComboBox(); self.decision_endpoint.setAccessibleName('Decision endpoint')
        self.decision_endpoint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.decision_endpoint.setMinimumContentsLength(8)
        self.decision_endpoint.currentIndexChanged.connect(lambda *_: self.decision_endpoint.currentData() and self.send({'type': 'decisions', 'action': 'list', 'endpoint': self.decision_endpoint.currentData()}))
        execution.addRow('Decision endpoint', self.decision_endpoint)
        self.decision_model = ElidedComboBox(); self.decision_model.setAccessibleName('Decision model')
        self.decision_model.activated.connect(lambda *_: self.decision_model.currentData() and self.send({'type': 'decisions', 'action': 'select',
            'endpoint': self.decision_endpoint.currentData(), 'model': self.decision_model.currentData()}))
        execution.addRow('Decision model', self.decision_model)
        decision_buttons = QHBoxLayout()
        self.decision_check = QPushButton('Check images'); self.decision_check.setToolTip('Send two control images that differ only in colour; the answer must change.')
        self.decision_check.clicked.connect(lambda: self.send({'type': 'decisions', 'action': 'check_images', 'endpoint': self.decision_endpoint.currentData(), 'model': self.decision_model.currentData()}))
        self.decision_key = QPushButton('Set key…'); self.decision_key.clicked.connect(self.set_decision_key)
        self.decision_add = QPushButton('Add endpoint…'); self.decision_add.clicked.connect(self.add_decision_endpoint)
        for button in (self.decision_check, self.decision_key): decision_buttons.addWidget(button)
        execution.addRow(decision_buttons); execution.addRow(self.decision_add)
        self.decision_note = QLabel(''); self.decision_note.setWordWrap(True); self.decision_note.setObjectName('muted'); execution.addRow(self.decision_note)
        self.reasoning_selector.currentIndexChanged.connect(self.change_execution_settings)
        connection = settings_section('Connections and history')
        self.provider_filter = ElidedComboBox()
        self.provider_filter.setAccessibleName('Model provider'); self.provider_filter.setToolTip('Choose a provider, then choose one of its models')
        self.provider_filter.currentIndexChanged.connect(self.change_provider)
        self.provider_note = QLabel('Choose a provider beside the composer, then select a model.'); self.provider_note.setObjectName('muted')
        self.provider_note.setWordWrap(True); self.provider_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); connection.addRow(self.provider_note)
        self.filter = QLineEdit(); self.filter.setPlaceholderText('Find a model…'); self.filter.textChanged.connect(self.filter_models)
        connection.addRow('Model search', self.filter)
        self.refresh_models_button = QPushButton('Refresh model catalog')
        self.refresh_models_button.setAccessibleName('Refresh model catalog')
        self.refresh_models_button.clicked.connect(lambda: self.send({'type': 'refresh_models', 'provider': self.provider_filter.currentData()}))
        connection.addRow(self.refresh_models_button)
        self.connect_button = QPushButton('Connect another API…'); self.connect_button.clicked.connect(self.connect_provider); connection.addRow(self.connect_button)
        self.restore_button = QPushButton('Locate a painting or plan…'); self.restore_button.clicked.connect(self.restore_conversation); connection.addRow(self.restore_button)
        self.connection_status = QLabel('Connecting…'); self.connection_status.setWordWrap(True)
        self.connection_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); connection.addRow(self.connection_status)
        self.diagnostics = QLabel(''); self.diagnostics.setWordWrap(True); self.diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diagnostics.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.diagnostics.setObjectName('muted'); connection.addRow(self.diagnostics)
        self.profile_notice = QLabel(''); self.profile_notice.setWordWrap(True); self.profile_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.profile_notice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); self.profile_notice.setAccessibleName('Plugin copy warning')
        self.profile_notice.setTextFormat(Qt.TextFormat.PlainText)      # paths in it are text, never markup
        self.profile_notice.hide(); connection.addRow(self.profile_notice)
        self.refresh_profile_notice()
        details_row = QHBoxLayout()
        self.diagnostics_toggle = QPushButton('Show diagnostics'); self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.setAccessibleName('Show connection diagnostics'); details_row.addWidget(self.diagnostics_toggle)
        self.copy_diagnostics = QPushButton('Copy'); self.copy_diagnostics.setAccessibleName('Copy connection diagnostics')
        self.copy_diagnostics.clicked.connect(lambda: QApplication.clipboard().setText(self.diagnostics_text.toPlainText()))
        details_row.addWidget(self.copy_diagnostics); connection.addRow(details_row)
        self.diagnostics_text = QPlainTextEdit(); self.diagnostics_text.setReadOnly(True); self.diagnostics_text.setAccessibleName('Connection diagnostics')
        self.diagnostics_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth); self.diagnostics_text.setMinimumWidth(0)
        self.diagnostics_text.setFixedHeight(180); self.diagnostics_text.hide(); connection.addRow(self.diagnostics_text)
        self.diagnostics_toggle.toggled.connect(self.toggle_diagnostics)
        self.export_diagnostics = QPushButton('Export troubleshooting report')
        self.export_diagnostics.setToolTip('Collect this conversation, plan, target and errors into one local file. No upload.')
        self.export_diagnostics.clicked.connect(lambda: self.send({'type': 'export_diagnostics', 'connection': self.diagnostics_text.toPlainText()}))
        connection.addRow(self.export_diagnostics)
        settings_sections.addStretch()
        for control in (self.source, self.experiment, self.theme_selector, self.provider_filter, self.name, self.filter):
            control.setMinimumWidth(0); control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.options_scroll = QScrollArea(); self.options_scroll.setWidgetResizable(True); self.options_scroll.setWidget(self.setup_box)
        self.options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.options_dialog = QDialog(self); self.options_dialog.setWindowTitle('Creative Agent settings'); self.options_dialog.resize(480, 620)
        self.options_dialog.setMinimumSize(360, 400)
        settings_layout = QVBoxLayout(self.options_dialog); settings_layout.addWidget(self.options_scroll)
        settings_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); settings_close.rejected.connect(self.options_dialog.hide); settings_layout.addWidget(settings_close)
        self.source.currentIndexChanged.connect(lambda: self.update_controls())
        self.experiment.currentIndexChanged.connect(lambda: self.update_controls())

        self.transcript = ChatTranscript(); self.transcript.body.setObjectName('conversationBody')
        self.transcript.previewRequested.connect(self.preview_canvas)
        layout.addWidget(self.transcript, 1)
        self.empty_state = QWidget(); empty = QVBoxLayout(self.empty_state); empty.setContentsMargins(8, 24, 8, 16); empty.setSpacing(12)
        welcome = QLabel('A little direction.\nRoom to create.'); welcome.setObjectName('emptyTitle'); welcome.setWordWrap(True); empty.addWidget(welcome)
        hint = QLabel('Explore your canvas, shape an idea, or paint together.'); hint.setWordWrap(True); hint.setObjectName('muted'); empty.addWidget(hint)
        self.no_document_label = QLabel('Start a painting: describe it, or open one.'); self.no_document_label.setWordWrap(True)
        self.no_document_label.setObjectName('muted'); self.no_document_label.hide(); empty.addWidget(self.no_document_label)
        self.starter_buttons = {}
        for label, mode, prompt in [('Discuss this painting', 'ask', 'What do you notice about this painting?'),
                                     ('Plan from a reference', 'plan', ''), ('Start a painting', 'autopilot', '')]:
            button = QPushButton(label + '  ↗'); button.setObjectName('emptyAction')
            button.clicked.connect(lambda _checked=False, m=mode, p=prompt: self.choose_starter(m, p)); empty.addWidget(button)
            self.starter_buttons[mode] = button
        self.transcript.rows.insertWidget(0, self.empty_state)
        jump_row = QHBoxLayout(); jump_row.addStretch()
        self.jump_button = QPushButton('↓  Latest'); self.jump_button.setObjectName('jumpLatest')
        self.jump_button.clicked.connect(self.transcript.jump_to_latest); self.jump_button.hide(); jump_row.addWidget(self.jump_button); jump_row.addStretch()
        self.transcript.followChanged.connect(lambda following: self.jump_button.setVisible(not following))
        layout.addLayout(jump_row)
        # Project folder: the folder the agent works from, its goal image and element images (the artist renames a guess in place).
        self.folder_card = QFrame(); self.folder_card.setObjectName('planBar')
        folder_layout = QVBoxLayout(self.folder_card); folder_layout.setContentsMargins(10, 9, 10, 10); folder_layout.setSpacing(6)
        folder_top = QHBoxLayout(); folder_top.setSpacing(10)
        self.folder_picture = QLabel(); self.folder_picture.setObjectName('folderGoal'); self.folder_picture.setFixedSize(96, 72)
        self.folder_picture.setAlignment(Qt.AlignmentFlag.AlignCenter); self.folder_picture.hide(); folder_top.addWidget(self.folder_picture, 0, Qt.AlignmentFlag.AlignTop)
        folder_words = QVBoxLayout(); folder_words.setSpacing(3)
        self.folder_title = QLabel(''); self.folder_title.setObjectName('planSummary'); self.folder_title.setWordWrap(True)
        self.folder_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); folder_words.addWidget(self.folder_title)
        # Goal picker: which folder image is the goal (the companion's goal reference); the default is final_goal.png.
        goal_row = QHBoxLayout(); goal_row.setSpacing(6)
        goal_caption = QLabel('Goal image:'); goal_caption.setObjectName('muted'); goal_row.addWidget(goal_caption)
        self.folder_goal_choice = QComboBox(); self.folder_goal_choice.setAccessibleName('Goal image')
        self.folder_goal_choice.setToolTip('The image the painting follows: its layout, colours and light. Any image of the folder can be the goal.')
        self.folder_goal_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.folder_goal_choice.setMinimumContentsLength(8)
        self.folder_goal_choice.currentIndexChanged.connect(self.folder_goal_chosen); goal_row.addWidget(self.folder_goal_choice, 1)
        folder_words.addLayout(goal_row)
        self.folder_goal = QLabel(''); self.folder_goal.setObjectName('muted'); self.folder_goal.setWordWrap(True)
        self.folder_goal.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder_goal.setTextFormat(Qt.TextFormat.PlainText); folder_words.addWidget(self.folder_goal)   # file names are text
        self.folder_footer = QLabel(''); self.folder_footer.setObjectName('muted'); self.folder_footer.setWordWrap(True)
        self.folder_footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder_footer.setTextFormat(Qt.TextFormat.PlainText); folder_words.addWidget(self.folder_footer)
        folder_top.addLayout(folder_words, 1); folder_layout.addLayout(folder_top)
        # The goal image's big masses (mass-map.ts), once found: a flat bar of their colours and one plain sentence.
        self.folder_masses = MassBar(12); self.folder_masses.hide(); folder_layout.addWidget(self.folder_masses)
        self.folder_mass_text = QLabel(''); self.folder_mass_text.setObjectName('muted'); self.folder_mass_text.setWordWrap(True)
        self.folder_mass_text.setTextFormat(Qt.TextFormat.PlainText); self.folder_mass_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder_mass_text.hide(); folder_layout.addWidget(self.folder_mass_text)
        # The element images, named as guessed, until the plan lists them (then the Plan tab shows them, once). Its rows
        # all show: it never scrolls inside the Folder tab.
        self.folder_elements = QListWidget(); self.folder_elements.setObjectName('folderElements')
        self.folder_elements.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.folder_elements.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.folder_elements.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.folder_elements.setAccessibleName('Element images of the project folder')
        self.folder_elements.setToolTip('The element images, painted in this order. Double-click a name to correct it.')
        self.folder_elements.itemChanged.connect(self.folder_guess_changed); folder_layout.addWidget(self.folder_elements)
        # Folder study (folder_study_panel.py): the study line, each row's state, the right-click menu, a big folder's choice.
        self.folder_study = FolderStudyCard(self.send, self.folder_elements); folder_layout.addWidget(self.folder_study)
        self.folder_elements.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_elements.customContextMenuRequested.connect(self.folder_element_context_menu)
        folder_page.addWidget(self.folder_card); folder_page.addStretch(1)
        self.folder_guesses = {}
        self.plan_bar = QFrame(); self.plan_bar.setObjectName('planBar')
        plan_layout = QVBoxLayout(self.plan_bar); plan_layout.setContentsMargins(10, 9, 10, 9); plan_layout.setSpacing(6)
        self.plan_summary = QLabel(''); self.plan_summary.setWordWrap(True); self.plan_summary.setObjectName('planSummary')
        self.plan_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); plan_layout.addWidget(self.plan_summary)
        # Plan step controls (plan_steps.py): Skip / Restore, Good enough → next step, Met / Redo, per step.
        plan_layout.addWidget(self.plan_steps.widget)
        plan_actions = QHBoxLayout(); plan_actions.setSpacing(5)
        self.plan_button = QPushButton('View plan'); self.plan_button.clicked.connect(self.edit_plan); plan_actions.addWidget(self.plan_button)
        self.compare_button = QPushButton('Review changes'); self.compare_button.clicked.connect(self.show_passes); plan_actions.addWidget(self.compare_button)
        plan_actions.addStretch()
        self.execute_button = QPushButton('Start painting'); self.execute_button.setObjectName('primaryAction')
        self.execute_button.clicked.connect(self.start_plan); plan_actions.addWidget(self.execute_button)
        plan_layout.addLayout(plan_actions); plan_page.addWidget(self.plan_bar); plan_page.addStretch(1); self.plan_bar.hide()
        # Agent mode: the painted move, to keep, undo or refine (refining is just the next message).
        self.move_bar = QFrame(); self.move_bar.setObjectName('planBar')
        move_layout = QVBoxLayout(self.move_bar); move_layout.setContentsMargins(10, 9, 10, 9); move_layout.setSpacing(6)
        self.move_summary = QLabel(''); self.move_summary.setWordWrap(True); self.move_summary.setObjectName('planSummary')
        self.move_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); move_layout.addWidget(self.move_summary)
        move_actions = QHBoxLayout(); move_actions.setSpacing(5)
        self.move_undo = QPushButton('Undo'); self.move_undo.setToolTip('Hide every pass of this move (reversible) and try a different approach')
        self.move_undo.clicked.connect(lambda: self.move_command('undo')); move_actions.addWidget(self.move_undo)
        move_actions.addStretch()
        self.move_keep = QPushButton('Keep'); self.move_keep.setObjectName('primaryAction'); self.move_keep.setToolTip('Keep this move and paint the next one')
        self.move_keep.clicked.connect(lambda: self.move_command('keep')); move_actions.addWidget(self.move_keep)
        self.move_auto = self.auto_label(); move_layout.addWidget(self.move_auto)
        move_layout.addLayout(move_actions); top_area.addWidget(self.move_bar); self.move_bar.hide(); self.current_move = None
        # Protected: the painting's features, each with a box the artist ticks to protect it (our Krita only).
        self.feature_changing = False
        self.features_section = FeaturesSection(self.toggle_feature); self.features_section.hide(); layout.addWidget(self.features_section)
        activity = QHBoxLayout(); activity.setSpacing(6)
        self.activity_dot = QLabel(''); self.activity_dot.setObjectName('activityDot'); activity.addWidget(self.activity_dot)
        self.status = QLabel('Connecting…'); self.status.setWordWrap(True); self.status.setObjectName('muted')
        self.status.setAccessibleDescription('Current activity'); self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        activity.addWidget(self.status, 1)
        self.recovery_button = QPushButton('Retry'); self.recovery_button.setObjectName('footerAction'); self.recovery_button.hide()
        self.recovery_action = None
        self.recovery_button.clicked.connect(lambda: self.recovery_action() if self.recovery_action else None)
        activity.addWidget(self.recovery_button)
        # Shown only while the companion keeps the screen awake for a painting run (Settings: Screen).
        self.awake_indicator = QLabel('☕ Screen awake'); self.awake_indicator.setObjectName('muted')
        self.awake_indicator.setAccessibleName('Keeping the screen awake while painting')
        self.awake_indicator.setToolTip('Keeping the screen awake while this run paints: %s can only paint while its window is active. '
                                        'It stops when the run pauses or ends. Turn it off in Settings: Screen.' % product_name())
        self.awake_indicator.hide(); activity.addWidget(self.awake_indicator)
        self.elapsed = QLabel(''); self.elapsed.setObjectName('muted'); self.elapsed.setAccessibleDescription('Activity elapsed time'); activity.addWidget(self.elapsed)
        # Auto-approve's quick switch, always on screen (the artist switches it on while recording); the delay is in Settings.
        self.auto_toggle = QCheckBox('Auto-approve'); self.auto_toggle.setAccessibleName('Auto-approve')
        self.auto_toggle.setToolTip('Cards that wait for you take their default answer after a countdown (Settings: Auto-approve sets the delay). '
                                    'Undo, Redo, Stop, typing or any button stops it. Start painting is never pressed for you.')
        self.auto_toggle.toggled.connect(self.toggle_auto_approve); activity.addWidget(self.auto_toggle)
        top_area.addLayout(activity)
        self.composer = QFrame(); self.composer.setObjectName('composer')
        compose = QVBoxLayout(self.composer); compose.setContentsMargins(10, 9, 10, 8); compose.setSpacing(7)
        self.canvas_row = QWidget(); canvas_layout = QHBoxLayout(self.canvas_row); canvas_layout.setContentsMargins(0, 0, 0, 0); canvas_layout.setSpacing(3)
        self.canvas_button = QPushButton('＋  Add current canvas'); self.canvas_button.setObjectName('contextChip')
        self.canvas_button.setMinimumWidth(0); self.canvas_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.canvas_button.setAccessibleName('Canvas context'); self.canvas_button.setIconSize(QSize(26, 26))
        self.canvas_button.clicked.connect(self.canvas_clicked); canvas_layout.addWidget(self.canvas_button, 1)
        self.canvas_refresh = QPushButton('↻'); self.canvas_refresh.setObjectName('contextAction'); self.canvas_refresh.setAccessibleName('Refresh canvas snapshot')
        self.canvas_refresh.setToolTip('Refresh canvas snapshot'); self.canvas_refresh.clicked.connect(lambda: self.context_command('refresh')); canvas_layout.addWidget(self.canvas_refresh)
        self.canvas_remove = QPushButton('×'); self.canvas_remove.setObjectName('contextAction'); self.canvas_remove.setAccessibleName('Detach canvas')
        self.canvas_remove.setToolTip('Exclude canvas from upcoming messages'); self.canvas_remove.clicked.connect(lambda: self.context_command('detach')); canvas_layout.addWidget(self.canvas_remove)
        compose.addWidget(self.canvas_row)
        self.context_hint = QLabel('The open canvas is included by default.'); self.context_hint.setObjectName('contextHint')
        self.context_hint.setWordWrap(True); compose.addWidget(self.context_hint)
        self.scope_tray = QWidget(); scope_layout = QHBoxLayout(self.scope_tray); scope_layout.setContentsMargins(0, 0, 0, 0); scope_layout.setSpacing(5)
        self.region_group = QWidget(); region_layout = QHBoxLayout(self.region_group); region_layout.setContentsMargins(0, 0, 0, 0); region_layout.setSpacing(1)
        self.region_button = QPushButton('⌗  Selection bounds'); self.region_button.setObjectName('contextChip')
        self.region_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.region_button.setMinimumWidth(0)
        self.region_button.setAccessibleName('Preview attached rectangular selection crop'); self.region_button.clicked.connect(self.preview_region)
        region_layout.addWidget(self.region_button, 1)
        self.region_remove = QPushButton('×'); self.region_remove.setObjectName('contextAction'); self.region_remove.setAccessibleName('Remove region attachment')
        self.region_remove.clicked.connect(lambda: self.send({'type': 'context', 'action': 'clear_region'})); region_layout.addWidget(self.region_remove)
        scope_layout.addWidget(self.region_group, 1)
        self.plan_context_button = QPushButton('Plan'); self.plan_context_button.setObjectName('contextChip')
        self.plan_context_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.plan_context_button.setMinimumWidth(0)
        self.plan_context_button.setAccessibleName('View the active plan included in this conversation'); self.plan_context_button.clicked.connect(self.edit_plan)
        scope_layout.addWidget(self.plan_context_button, 1)
        self.lesson_button = QPushButton('Lesson'); self.lesson_button.setObjectName('contextChip')
        self.lesson_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); self.lesson_button.setMinimumWidth(0)
        self.lesson_button.setAccessibleName('Open the lesson from Ask mode'); self.lesson_button.clicked.connect(self.open_lesson)
        scope_layout.addWidget(self.lesson_button, 1); compose.addWidget(self.scope_tray)
        self.lesson_dialog = None
        self.scope_tray.hide(); self.region_group.hide(); self.plan_context_button.hide(); self.lesson_button.hide()
        self.attachments = QWidget(); self.attachment_row = QHBoxLayout(self.attachments)
        self.attachment_row.setContentsMargins(0, 0, 0, 0); self.attachment_row.setSpacing(5)
        compose.addWidget(self.attachments); self.attachments.hide()
        self.protection_bar = QWidget(); bar = QHBoxLayout(self.protection_bar); bar.setContentsMargins(0, 0, 0, 0)
        self.protection_bar_label = QLabel('Painting protection'); bar.addWidget(self.protection_bar_label, 1)
        # Adjust (element-scoped-painting 2): Freehand Selection, with the Magnetic one (snaps to edges) a click away.
        self.protection_tool_button = QPushButton(''); self.protection_tool_button.clicked.connect(self.switch_protection_tool)
        bar.addWidget(self.protection_tool_button); self.protection_tool_button.hide()
        done = QPushButton('Done'); done.clicked.connect(lambda: self.finish_protection(True)); bar.addWidget(done)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(lambda: self.finish_protection(False)); bar.addWidget(cancel)
        compose.addWidget(self.protection_bar); self.protection_bar.hide()
        self.part_session = None
        self.part_bar = QWidget(); part_bar = QHBoxLayout(self.part_bar); part_bar.setContentsMargins(0, 0, 0, 0)
        self.part_bar_label = QLabel(''); self.part_bar_label.setWordWrap(True); part_bar.addWidget(self.part_bar_label, 1)
        use = QPushButton('Use this part'); use.clicked.connect(self.use_part); part_bar.addWidget(use)
        cancel_part = QPushButton('Cancel'); cancel_part.clicked.connect(self.close_part); part_bar.addWidget(cancel_part)
        compose.addWidget(self.part_bar); self.part_bar.hide()
        self.part_timer = QTimer(self); self.part_timer.setInterval(1000); self.part_timer.timeout.connect(self.check_part_session)
        # Paint only here (paint_only_panel.py): the artist's selection as the one area the agent may paint in.
        self.paint_only = PaintOnlyBar(self); compose.addWidget(self.paint_only)
        # Slash commands: typing "/" lists the companion's commands; choosing one inserts it.
        self.skills = []; self.slash_commands = []
        self.slash_menu = QListWidget(); self.slash_menu.setAccessibleName('Commands'); self.slash_menu.setMaximumHeight(150)
        self.slash_menu.itemActivated.connect(self.choose_skill); self.slash_menu.itemClicked.connect(self.choose_skill)
        compose.addWidget(self.slash_menu); self.slash_menu.hide()
        self.prompt = ChatInput(); self.prompt.setAccessibleName('Message Creative Agent'); self.prompt.slash_menu = self.slash_menu
        self.prompt.setPlaceholderText('Ask about your painting…'); self.prompt.setFixedHeight(62)
        self.prompt.textChanged.connect(self.resize_composer); self.prompt.textChanged.connect(self.update_slash_menu); self.prompt.submitted.connect(self.submit)
        self.prompt.textChanged.connect(lambda: self.auto_approve.cancel() if self.prompt.toPlainText().strip() else None)   # typing: the artist's turn
        self.prompt.filesAttached.connect(self.attach_paths); self.prompt.imageAttached.connect(self.attach_pasted_image)
        compose.addWidget(self.prompt)
        buttons = QHBoxLayout(); buttons.setSpacing(3)
        self.reference_button = QPushButton('＋'); self.reference_button.setObjectName('contextAction')
        self.reference_button.setAccessibleName('Attach context'); self.reference_button.setToolTip('Attach canvas or reference image')
        self.attach_menu = QMenu(self)
        self.attach_menu.addAction('Current canvas', lambda: self.context_command('attach'))
        self.attach_menu.addAction('Reference image…', lambda: self.attach('reference'))
        self.folder_action = self.attach_menu.addAction('Open project folder…', self.open_project_folder)
        self.folder_action.setToolTip('Point %s at a folder of references: a goal image and numbered element images, painted one element per move.' % product_name())
        self.selected_area_action = self.attach_menu.addAction('Selected area')
        self.selected_area_action.setToolTip('Attach a rectangular crop around the active selection. This does not authorize painting.')
        self.selected_area_action.triggered.connect(self.attach_selected_area)
        self.attach_menu.addSeparator()
        self.pin_canvas_action = self.attach_menu.addAction('Keep this canvas attached')
        self.pin_canvas_action.setCheckable(True); self.pin_canvas_action.triggered.connect(self.toggle_canvas_pin)
        self.document_menu = self.attach_menu.addMenu('Choose an open canvas')
        self.reference_button.setMenu(self.attach_menu); buttons.addWidget(self.reference_button)
        self.mode_selector = QComboBox(); self.mode_selector.setAccessibleName('Chat mode')
        self.mode_selector.addItem('Ask', 'ask'); self.mode_selector.addItem('Plan', 'plan'); self.mode_selector.addItem('Agent', 'agent'); self.mode_selector.addItem('Autopilot (experimental)', 'autopilot')
        self.mode_selector.setToolTip('Ask and Plan inspect your canvas. Agent paints one move at a time for you to keep, undo or refine. Autopilot (experimental) paints unattended until the review passes, for testing and long runs.')
        self.mode_selector.currentIndexChanged.connect(self.change_mode); buttons.addWidget(self.mode_selector)
        self.ai_images_selector = QComboBox(); self.ai_images_selector.setAccessibleName('AI images for this chat')
        for value, text in AI_IMAGE_CHOICES: self.ai_images_selector.addItem(text, value)
        self.ai_images_selector.setToolTip('How many AI-generated images the painter may use in this chat. 0 paints everything by hand.')
        self.ai_images_selector.currentIndexChanged.connect(self.change_ai_images); buttons.addWidget(self.ai_images_selector)
        self.ai_images_used = QLabel(''); self.ai_images_used.setAccessibleName('AI images used'); buttons.addWidget(self.ai_images_used)
        # Protected areas: what the agent must never change. The panel changes them here, in Krita's own process.
        self.protection = ProtectionCraft(); self.features = FeatureCraft(); self.protection_controls = []; self.protection_editing = None; self.protection_shown = None
        self.shapes_model_controls = []    # Download / Not now for the element-shapes model (shapes_model_needed)
        self.protect_button = QPushButton('🛡'); self.protect_button.setObjectName('contextAction')
        self.protect_button.setAccessibleName('Protected areas'); self.protect_button.setToolTip('Protected areas: what the agent must never change')
        self.protect_button.clicked.connect(lambda: self.open_protection()); buttons.addWidget(self.protect_button)
        buttons.addStretch(1)
        self.stop_button = QPushButton('■'); self.stop_button.setObjectName('stopAction')
        self.stop_button.setAccessibleName('Stop generating and pause agent'); self.stop_button.setToolTip('Stop · in-progress paint settles safely')
        self.stop_button.clicked.connect(self.request_stop); buttons.addWidget(self.stop_button)
        self.send_button = QPushButton('↑'); self.send_button.setObjectName('sendMessage'); self.send_button.setAccessibleName('Send message')
        self.send_button.clicked.connect(self.submit); buttons.addWidget(self.send_button)
        model_row = QHBoxLayout(); model_row.setSpacing(6)
        model_row.addWidget(self.provider_filter, 2); model_row.addWidget(self.model, 3)
        compose.addLayout(model_row); compose.addLayout(buttons); layout.addWidget(self.composer)
        saved = QHBoxLayout(); saved.setSpacing(4)
        self.save_status = QLabel('Ask · read only'); self.save_status.setObjectName('muted')
        self.save_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); saved.addWidget(self.save_status, 1)
        # This chat's Langfuse session (every chat is traced until New chat).
        self.trace_link = QLabel(''); self.trace_link.setObjectName('muted'); self.trace_link.setOpenExternalLinks(True)
        self.trace_link.setToolTip('Open this chat\'s traces in Langfuse'); self.trace_link.hide(); saved.addWidget(self.trace_link)
        self.folder_button = QPushButton('Show file'); self.folder_button.setObjectName('footerAction')
        self.folder_button.clicked.connect(self.open_output); saved.addWidget(self.folder_button); layout.addLayout(saved)
        self.start_button = QPushButton('Connect assistant'); self.start_button.clicked.connect(self.start_companion); layout.addWidget(self.start_button)
        self.preview = QLabel(); self.preview.hide()
        self.refresh_button = self.canvas_refresh
        self.clock = QTimer(self); self.clock.setInterval(1000); self.clock.timeout.connect(self.update_elapsed); self.clock.start()
        self.setWidget(body)
        # QDockWidget caches transient control widths as a window minimum. The
        # content layout already constrains its controls; let docking stay narrow.
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.apply_theme()
        self.shortcuts = []
        for key, callback in [('Ctrl+Alt+Shift+L', lambda: self.prompt.setFocus()), ('Ctrl+Alt+Shift+N', self.end_button.click), ('Escape', self.pause_if_busy)]:
            shortcut = QShortcut(QKeySequence(key), self); shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut); shortcut.activated.connect(callback); self.shortcuts.append(shortcut)
        self.update_controls()
        self.render_context()

    def set_text_size(self, value):
        self.text_scale = value / 14
        self.apply_theme(); self.resize_composer()

    def set_theme(self, index):
        self.theme_mode = ['system', 'dark', 'light'][index]
        self.apply_theme()

    def app_theme_name(self):
        """The app's saved colour theme ([theme] Theme), or '' when it cannot be read."""
        try:
            name = Krita.instance().readSetting('theme', 'Theme', '')
        except Exception:
            return ''
        return name if isinstance(name, str) else ''

    def apply_theme(self, dark=None):
        if dark is None:
            # Match: Toska's colours under a Toska theme, otherwise Dark or Light by the app's lightness (panel_theme.py)
            window = QApplication.palette().color(QPalette.ColorRole.Window) if self.theme_mode == 'system' else None
            c, dark = panel_colors(self.theme_mode, window.name() if window is not None else None,
                                   self.app_theme_name() if self.theme_mode == 'system' else None,
                                   window.lightness() if window is not None else None)
        else:
            c, dark = panel_colors('dark' if dark else 'light')
        self.theme_colors = c
        self.plan_steps.set_colors(c, dark)
        c['chevron'] = os.path.join(os.path.dirname(__file__), 'icons', 'chevron-dark.svg' if dark else 'chevron-light.svg').replace('\\', '\\\\').replace('"', '\\"')
        palette = QPalette(self.palette())
        for role, color in [(QPalette.ColorRole.Window, c['bg']), (QPalette.ColorRole.Base, c['surface']), (QPalette.ColorRole.Button, c['raised']),
                            (QPalette.ColorRole.WindowText, c['text']), (QPalette.ColorRole.Text, c['text']), (QPalette.ColorRole.ButtonText, c['text']),
                            (QPalette.ColorRole.Highlight, c['accent']), (QPalette.ColorRole.HighlightedText, c['bg'])]: palette.setColor(role, QColor(color))
        self.setPalette(palette)
        stylesheet = '''
            QWidget#creativeChat, QWidget#conversationBody, QWidget#settingsBody, QDialog { background: %(bg)s; color: %(text)s; }
            QLabel { color: %(text)s; background: transparent; font-size: 13px; }
            QLabel#chatTitle { font-size: 15px; font-weight: 600; }
            QLabel#emptyTitle { font-size: 25px; font-weight: 500; }
            QLabel#muted, QLabel#contextHint { color: %(muted)s; font-size: 11px; }
            QLabel#messageRole { color: %(muted)s; font-size: 11px; font-weight: 500; }
            QLabel#planSummary { font-size: 12px; }
            QLabel#autoApprove { font-size: 12px; font-weight: 600; }
            QLabel#activityDot { color: %(accent)s; font-size: 12px; }
            QFrame#userMessage { background: %(raised)s; border: none; border-radius: 10px; }
            QFrame#assistantMessage, QFrame#actionMessage { background: transparent; border: none; }
            QFrame#questionMessage { background: transparent; border: none; }
            QFrame#composer { background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; }
            QFrame#composer:focus-within { border-color: %(accent)s; }
            QFrame#planBar { background: %(surface)s; border: 1px solid %(border)s; border-radius: 9px; }
            QPlainTextEdit, QTextBrowser, QLineEdit, QTableWidget { color: %(text)s; selection-background-color: %(accent)s; selection-color: %(bg)s; font-size: 14px; }
            QPlainTextEdit, QTextBrowser { border: none; background: transparent; }
            QDialog QPlainTextEdit { background: %(surface)s; border: 1px solid %(border)s; border-radius: 6px; padding: 6px; }
            QDialog QComboBox { background: %(surface)s; border: 1px solid %(border)s; min-height: 24px; }
            QToolButton { background: %(surface)s; color: %(text)s; border: none; }
            QLineEdit, QSpinBox, QTableWidget { color: %(text)s; background: %(surface)s; border: 1px solid %(border)s; border-radius: 5px; padding: 5px; }
            QPushButton { color: %(text)s; background: %(raised)s; border: 1px solid transparent; border-radius: 6px; padding: 5px 8px; min-height: 20px; font-size: 11px; }
            QPushButton:hover { background: %(hover)s; }
            QPushButton:focus { border-color: %(accent)s; }
            QPushButton:disabled { color: %(muted)s; background: transparent; }
            QPushButton#headerAction { background: transparent; padding: 1px 4px; min-width: 22px; font-size: 20px; }
            QPushButton#headerAction:hover, QPushButton#contextAction:hover { background: %(raised)s; }
            QPushButton#emptyAction { background: transparent; border: 1px solid %(border)s; text-align: left; padding: 10px; font-size: 12px; }
            QPushButton#emptyAction:hover { background: %(raised)s; }
            QPushButton#contextChip { background: %(raised)s; text-align: left; font-size: 11px; min-height: 26px; padding: 3px 7px; }
            QPushButton#contextAction { background: transparent; padding: 2px 4px; font-size: 17px; min-width: 16px; }
            QPushButton#paintOnlyChip { background: %(raised)s; border: 1px solid %(accent)s; text-align: left; font-size: 11px; font-weight: 600; min-height: 26px; padding: 3px 7px; }
            QPushButton#contextAction::menu-indicator { image: none; width: 0; }
            QPushButton#sendMessage, QPushButton#stopAction { background: %(button)s; color: %(buttonText)s; font-size: 18px; font-weight: 500; min-width: 17px; min-height: 24px; padding: 2px 5px; border-radius: 7px; }
            QPushButton#sendMessage:disabled { background: %(raised)s; color: %(muted)s; }
            QPushButton#stopAction { font-size: 12px; }
            QPushButton#primaryAction { background: %(button)s; color: %(buttonText)s; }
            QPushButton#footerAction { background: transparent; color: %(muted)s; font-size: 10px; padding: 0 2px; min-height: 17px; }
            QPushButton#activityDisclosure { background: transparent; color: %(muted)s; text-align: left; padding: 0; font-size: 11px; border: none; }
            QPushButton#activityDisclosure:focus { color: %(text)s; }
            QLabel#activityDisclosure { color: %(muted)s; font-size: 11px; }
            QPushButton#referencePurpose { background: transparent; color: %(muted)s; padding: 0; min-height: 17px; font-size: 10px; }
            QPushButton#referenceRemove { background: %(raised)s; color: %(text)s; padding: 0; min-height: 12px; border-radius: 6px; font-size: 12px; }
            QPushButton#receipt { background: transparent; color: %(muted)s; text-align: left; padding: 0; font-size: 10px; }
            QPushButton#questionChoice { text-align: left; background: %(surface)s; border: 1px solid %(border)s; padding: 8px 10px; font-size: 12px; }
            QPushButton#questionChoice:hover { background: %(raised)s; }
            QComboBox { color: %(text)s; background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px 20px 4px 5px; min-height: 22px; font-size: 11px; }
            QComboBox:hover { background: %(raised)s; border-color: %(border)s; }
            QComboBox:focus { background: %(surface)s; border-color: %(accent)s; }
            QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; border: none; width: 18px; }
            QComboBox::down-arrow { image: url("%(chevron)s"); width: 12px; height: 8px; }
            QComboBox QAbstractItemView, QMenu { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; selection-background-color: %(raised)s; }
            QMenu::item { padding: 7px 16px; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical { background: %(border)s; min-height: 28px; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QGroupBox { border: none; padding-top: 20px; color: %(text)s; }
            QGroupBox::title { color: %(muted)s; }
            QListWidget { background: %(surface)s; color: %(text)s; border: none; }
            QListWidget::item { padding: 12px; border-bottom: 1px solid %(border)s; }
            QListWidget::item:selected { background: %(raised)s; }
            QListWidget#folderElements::item { padding: 5px 6px; }
            QLabel#folderGoal { background: %(raised)s; border-radius: 4px; }
            QTabWidget#panelTabs::pane { border: none; border-top: 1px solid %(border)s; }
            QTabWidget#panelTabs QTabBar::tab { padding: 7px 12px; font-size: 12px; }
            QTabWidget::pane { border: 1px solid %(border)s; border-radius: 5px; }
            QTabBar::tab { background: %(bg)s; color: %(muted)s; padding: 9px 10px; border: none; font-size: 11px; }
            QTabBar::tab:selected { color: %(text)s; background: %(surface)s; border-bottom: 2px solid %(accent)s; }
            QTabBar::tab:hover { background: %(raised)s; }
            QCheckBox { color: %(text)s; font-size: 12px; }
            QWidget#featuresList { background: transparent; }
            QToolButton#featuresToggle { background: transparent; color: %(text)s; font-size: 12px; font-weight: 500; padding: 0; }
            QHeaderView::section { background: %(raised)s; color: %(text)s; border: none; padding: 7px; font-size: 11px; }
            QTableCornerButton::section { background: %(raised)s; border: none; }
        ''' % c + plan_steps_stylesheet(c, dark)
        stylesheet = re.sub(r'font-size: (\d+)px', lambda match: 'font-size: %dpx' % round(int(match.group(1)) * self.text_scale), stylesheet)
        self.setStyleSheet(stylesheet)
        self.transcript.body_text_size = round(14 * self.text_scale)
        for item in self.transcript.messages:
            item['label'].set_rendered(self.transcript.render(item['text']))
        if hasattr(self, 'folder_elements'): self.fit_folder_elements()   # the rows' heights follow the font size

    def event(self, event):
        # Qt hands ApplicationPaletteChange to event(), never to changeEvent(); the panel sets its own palette, so it gets
        # no PaletteChange either. A theme change in the app reaches 'Match' here.
        handled = super().event(event)
        if event.type() == QEvent.Type.ApplicationPaletteChange and getattr(self, 'theme_mode', None) == 'system':
            self.apply_theme()
        return handled

    def toggle_diagnostics(self, expanded):
        self.diagnostics_text.setVisible(expanded)
        self.diagnostics_toggle.setText('Hide diagnostics' if expanded else 'Show diagnostics')
        if expanded:
            QTimer.singleShot(0, lambda: self.options_scroll.ensureWidgetVisible(self.diagnostics_text))

    def render_connection(self, ui_build, event):
        companion = event.get('build') or event.get('versions') or {}
        bridge = event.get('bridge') or {}
        bridge_build = bridge.get('build') or {}
        summaries = []
        for label, version, build in [('UI', ui_build.get('version'), ui_build),
                                       ('Companion', companion.get('version'), companion),
                                       ('Bridge', bridge.get('creative_version') or bridge_build.get('version') or bridge.get('version'), bridge_build)]:
            identifier = build.get('build_id')
            if identifier == 'development-unverified': identifier = None
            summaries.append(label + ' ' + (version or 'unavailable') + (' · ' + identifier[:12] if identifier else ''))
        self.diagnostics.setText('\n'.join(summaries))
        identifiers = [entry.get('build_id') for entry in (ui_build, companion, bridge_build)]
        verified = all(identifiers) and identifiers[0] != 'development-unverified' and len(set(identifiers)) == 1
        if bridge.get('error'): status = 'Bridge unavailable · ' + bridge['error']
        elif event.get('compatible') is False or (all(identifiers) and identifiers[0] != 'development-unverified' and len(set(identifiers)) != 1): status = 'Update required · plugin and companion differ'
        elif verified: status = 'Connected · matching build'
        else: status = 'Connected · build verification unavailable'
        self.connection_status.setText(status)
        # Deliberately include version metadata only, never model keys or config.
        report = {'status': status, 'compatible': event.get('compatible'), 'ui': ui_build, 'plugin_copy': self.profile_notice_lines(),
                  'companion': companion, 'bridge': {key: bridge[key] for key in ('version', 'creative_version', 'protocol_version', 'build', 'error') if key in bridge}}
        self.diagnostics_text.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))
        self.send({'type': 'diagnostic_ui', 'connection': report})

    def pause_if_busy(self):
        if self.busy: self.request_stop()

    def request_stop(self):
        self.auto_approve.cancel()
        # Krita stops starting painting actions at once, and a stroke pass ends after its current
        # stroke, without waiting for the companion: its next action often started before it heard.
        stop_requested.set()
        self.send({'type': 'stop'})

    def choose_starter(self, mode, prompt):
        self.mode_selector.setCurrentIndex(self.mode_selector.findData(mode))
        self.prompt.setPlainText(prompt)
        self.prompt.setFocus()
        if mode == 'plan' and not self.pending_references and not self.attached_references:
            self.attach('reference')

    def request_restore(self, command):
        if self.busy:
            self.status.setText('Pause the current painting before restoring another conversation.'); return
        if self.study_active:
            self.pending_restore = command
            self.send({'type': 'end'})
        else:
            self.focus_after_restore = True
            self.send(command)

    def locate_missing_painting(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Locate this painting', getattr(self, 'paintings_directory', ''), 'Krita paintings (*.kra)')
        if path and (self.relink_id or self.study_id):
            self.focus_after_restore = True
            self.send({'type': 'relink', 'id': self.relink_id or self.study_id, 'path': path})

    def set_recovery(self, label=None, action=None):
        self.recovery_action = action
        self.recovery_button.setVisible(bool(label))
        if label: self.recovery_button.setText(label)

    def context_command(self, action):
        if action == 'detach':
            self.canvas_context.update(selected=False, state='detached')
        elif action == 'attach':
            self.canvas_context.update(selected=True, follow_active=True, state='stale')
        self.render_context()
        if action in ('attach', 'refresh'):
            self.context_hint.setText('Capturing current canvas…')
        command = {'type': 'context', 'action': action}
        self.send(command)

    def attach_selected_area(self):
        try:
            document = Krita.instance().activeDocument()
            selection = document.selection() if document else None
            if selection is None or selection.width() <= 0 or selection.height() <= 0:
                self.status.setText('Select an area on the canvas first, then use ＋ → Selected area.'); return
            x = max(0, selection.x()); y = max(0, selection.y())
            right = min(document.width(), selection.x() + selection.width())
            bottom = min(document.height(), selection.y() + selection.height())
            if right <= x or bottom <= y:
                self.status.setText('The selection is outside this canvas. Choose an area within the painting.'); return
            region = {'document_id': document_id(document), 'bounds': [x, y, right - x, bottom - y], 'name': 'Selection bounds'}
            self.send({'type': 'context', 'action': 'region', 'region': region})
            self.status.setText('Attaching a rectangular crop around your selection…')
        except (AttributeError, RuntimeError):
            self.status.setText('The current selection could not be read. Try selecting the area again.')

    def preview_region(self):
        region = self.canvas_context.get('region') or {}
        if not region.get('path') or region.get('state') == 'unavailable':
            self.status.setText('This crop belongs to another canvas. Return to it or attach a new selected area.'); return
        snapshot = dict(region)
        canvas = self.canvas_context.get('canvas') or {}
        if canvas.get('revision') == region.get('revision'): snapshot['overview_path'] = canvas.get('path')
        self.preview_canvas(snapshot)

    def render_scope_tray(self):
        region = self.canvas_context.get('region') or {}
        brief = self.goal.get('brief') if self.goal else None
        lesson = self.goal.get('lesson') if self.goal else None
        self.region_group.setVisible(bool(region)); self.plan_context_button.setVisible(bool(brief)); self.lesson_button.setVisible(bool(lesson))
        self.scope_tray.setVisible(bool(region or brief or lesson))
        if lesson:
            self.lesson_button.setText('✎  Lesson')
            self.lesson_button.setToolTip(lesson.get('title', '') + '\nFrom Ask mode, for you to follow along. The painter does not read it.')
        if self.lesson_dialog is not None:
            if lesson: self.lesson_dialog.show_lesson(lesson)
            else: self.lesson_dialog.close()
        if region:
            unavailable = region.get('state') in ('unavailable', 'error')
            self.region_button.setText('⌗  Crop unavailable' if unavailable else '⌗  Region crop')
            bounds = region.get('bounds') or region.get('region')
            description = 'Rectangular crop; includes the bounding box, not an exact freehand mask. Attaching it does not authorize painting.'
            if bounds: description += '\nx %s, y %s · %s × %s px' % tuple(bounds)
            if unavailable: description += '\nReturn to its canvas or attach a new selected area.'
            self.region_button.setToolTip(description)
        if brief:
            self.plan_context_button.setText('☷  Plan · r' + str(self.goal.get('revision', 1)))
            self.plan_context_button.setToolTip(brief['title'] + '\nActive requirements and painting order are included in the conversation. Open to review or edit.')

    def render_target(self):
        target = self.painting_target
        canvas = self.canvas_context.get('canvas') or {}
        goal = self.goal or {}
        different = bool(canvas.get('document_id') and (target.get('document_id') != canvas['document_id'] or (target.get('mode') == 'new' and not target.get('bound'))))
        self.use_canvas_button.setVisible(bool(self.study_active and self.canvas_context.get('selected') and different and not goal.get('passes')))
        self.use_canvas_button.setEnabled(not self.busy)
        ready_plan = bool(goal.get('brief') and (goal.get('status') in ('ready', 'active', 'reviewing', 'paused', 'complete', 'limited') or goal.get('approved_revision') is not None))
        self.return_button.setVisible(bool(target.get('filename') or target.get('bound')))
        self.return_button.setEnabled(not self.busy)
        self.return_button.setText('Locate painting' if target.get('missing') else 'Return to painting')
        self.return_button.setToolTip('Open or focus this painting. The conversation stays paused.')
        if target and (target.get('bound') or ready_plan):
            name = os.path.basename(target.get('filename') or '') or target.get('name') or 'New painting'
            prefix = 'Painting target · ' if target.get('filename') or target.get('bound') else 'Target on start · '
            room = max(60, self.width() - self.return_button.sizeHint().width() - 34 - self.workspace_label.fontMetrics().horizontalAdvance(prefix))
            self.workspace_label.setText(prefix + self.workspace_label.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, room))   # the name, not the prefix, is cut
            details = target.get('filename') or name
            if not target.get('bound'): details += '\nThe conversation is not currently painting. Start Agent explicitly to work on this target.'
            if target.get('document_id') and canvas.get('document_id') != target['document_id']:
                details += '\nThe attached canvas is different from this painting target.'
            self.workspace_label.setToolTip(details)
        elif canvas and self.canvas_context.get('selected'):
            name = canvas_name(canvas)
            button_width = self.return_button.sizeHint().width() if target.get('filename') or target.get('bound') else 0
            self.workspace_label.setText(self.fontMetrics().elidedText('Canvas · ' + name, Qt.TextElideMode.ElideMiddle, max(100, self.width() - button_width - 34)))
            self.workspace_label.setToolTip(canvas_details(canvas) + '\nObservation context. No painting target has been started.')
        else:
            self.workspace_label.setText('No painting target started')
            self.workspace_label.setToolTip('Attach context or describe a painting. Ask and Plan do not change artwork.')

    def return_to_painting(self, restored=False):
        """Focus the recorded artwork without saving, closing, binding or starting Agent."""
        if self.busy: return False
        target = self.painting_target
        filename, identifier = target.get('filename'), target.get('document_id')
        if not (filename or identifier): return False
        try:
            instance = Krita.instance()
            documents = open_documents()
            identity = document_id
            canonical = lambda path: os.path.normcase(os.path.realpath(path)) if path else None
            document = next((doc for doc in documents if identifier and identity(doc) == identifier), None)
            if document is None and filename:
                document = next((doc for doc in documents if canonical(doc.fileName()) == canonical(filename)), None)
            if document is not None and document == instance.activeDocument():
                # Krita 5.3 can crash when showView re-enters setCurrentView for
                # the already-active document during a docker restore.
                self.context_command('inspect')
                return True
            if document is None and (not filename or not os.path.isfile(filename)):
                self.status.setText('This painting has moved. Locate it to reconnect the conversation.')
                self.set_recovery('Locate painting', self.locate_missing_painting)
                self.return_button.setText('Locate painting')
                if not restored: self.locate_missing_painting()
                return False
            window = instance.activeWindow()
            if not window: raise RuntimeError('Open a %s window before returning to the painting.' % product_name())
            if document is None:
                document = instance.openDocument(filename)
                if not document: raise RuntimeError('%s could not open this painting. Your other documents are still open.' % product_name())
            # Reuse a view in any window, including an unsaved in-memory target.
            views = instance.views()
            view = next((view for view in views if identity(view.document()) == identity(document) and view.window() == window), None)
            if view is None: view = next((view for view in views if identity(view.document()) == identity(document)), None)
            if view is not None: window = view.window()
            else: view = window.addView(document)
            if not view: raise RuntimeError('The painting opened, but %s could not show its view.' % product_name())
            window.showView(view); window.activate()
            self.context_command('inspect')
            self.status.setText('Painting opened · conversation paused' if restored else 'Painting focused. Use Start painting when you are ready.')
            return True
        except (AttributeError, RuntimeError, OSError) as error:
            self.status.setText('Could not show the painting: ' + str(error))
            return False

    def toggle_canvas_pin(self, pinned):
        canvas = self.canvas_context.get('canvas') or {}
        if not canvas.get('document_id'): return
        self.send({'type': 'context', 'action': 'attach', 'follow_active': not pinned, 'document_id': canvas['document_id']})

    def context_payload(self):
        payload = {key: self.canvas_context.get(key, default) for key, default in [('selected', True), ('follow_active', True)]}
        canvas = self.canvas_context.get('canvas') or {}
        if canvas.get('document_id'): payload['document_id'] = canvas['document_id']
        return payload

    def render_context(self):
        context = self.canvas_context
        canvas = context.get('canvas') or {}
        state = context.get('state', 'none')
        selected = context.get('selected', True)
        name = canvas_name(canvas)
        if selected and canvas:
            prefix = 'Canvas · '
            self.canvas_button.setText(prefix + self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, max(80, self.width() - 190)))
            self.canvas_button.setAccessibleName('Canvas context ' + name)
            pixmap = QPixmap(canvas.get('path', ''))
            self.canvas_button.setIcon(QIcon(pixmap) if not pixmap.isNull() else QIcon())
            self.canvas_button.setToolTip('Preview selected canvas\n' + canvas_details(canvas) + ('\nFollows the active canvas' if context.get('follow_active', True) else '\nPinned as observation context'))
            hints = {'fresh': 'Snapshot ready · latest canvas captured when you send', 'stale': 'Canvas selected · next message captures the latest view',
                     'error': context.get('error') or 'Canvas capture failed. Use refresh to retry.'}
            self.context_hint.setText(hints.get(state, 'Canvas selected · includes unsaved changes' if canvas.get('modified') else 'Canvas selected for the next message'))

        else:
            self.canvas_button.setIcon(QIcon())
            self.canvas_button.setText('＋  Add current canvas')
            self.canvas_button.setAccessibleName('Add current canvas')
            self.canvas_button.setToolTip('Attach the active %s document as visual context' % product_name())
            self.context_hint.setText('Canvas not included' if not selected else context.get('error') or 'No open canvas · attach a reference or start a painting')
        self.canvas_refresh.setVisible(selected and bool(canvas))
        self.canvas_remove.setVisible(selected and bool(canvas))
        self.pin_canvas_action.blockSignals(True); self.pin_canvas_action.setChecked(not context.get('follow_active', True)); self.pin_canvas_action.blockSignals(False)
        self.pin_canvas_action.setEnabled(selected and bool(canvas))
        self.document_menu.clear()
        for document in context.get('documents', []):
            title = canvas_name(document)
            action = self.document_menu.addAction(title, lambda checked=False, doc=document: self.send({'type': 'context', 'action': 'attach', 'document_id': doc['document_id'], 'follow_active': False}))
            action.setToolTip(canvas_details(document))
        self.document_menu.setEnabled(bool(context.get('documents')))
        self.render_scope_tray(); self.render_target()

    def canvas_clicked(self):
        if self.canvas_context.get('selected') and (self.canvas_context.get('canvas') or {}).get('path'):
            self.preview_canvas(self.canvas_context['canvas'])
        elif self.canvas_context.get('selected') and self.canvas_context.get('canvas'):
            self.preview_after_refresh = True; self.context_command('refresh')
        else: self.context_command('attach')

    def preview_canvas(self, canvas):
        dialog = ImagePreview(self, canvas)
        dialog.exec()

    def select_provider(self, provider):
        self.provider_filter.blockSignals(True)
        index = self.provider_filter.findData(provider)
        if index < 0:
            self.provider_filter.addItem(provider_name(provider), provider); index = self.provider_filter.count() - 1
        self.provider_filter.setCurrentIndex(index); self.provider_filter.blockSignals(False)

    def change_provider(self, *_args):
        self.filter.blockSignals(True); self.filter.clear(); self.filter.blockSignals(False)
        self.filter_models()

    def set_decision_key(self):
        endpoint = self.decision_endpoint.currentData()
        if not endpoint: return
        key, ok = QInputDialog.getText(self, 'Decision endpoint key', 'API key for %s (leave empty to remove):' % self.decision_endpoint.currentText(), QLineEdit.EchoMode.Password)
        if ok: self.send({'type': 'decisions', 'action': 'save_key', 'endpoint': endpoint, 'key': key.strip()})

    def add_decision_endpoint(self):
        url, ok = QInputDialog.getText(self, 'Add decision endpoint', 'System One endpoint URL (e.g. http://localhost:8888/v1/systemone):')
        if not ok or not url.strip(): return
        name, ok = QInputDialog.getText(self, 'Add decision endpoint', 'Short id (letters, digits, dashes):', text='local')
        if not ok or not name.strip(): return
        key, _ = QInputDialog.getText(self, 'Add decision endpoint', 'API key (optional):', QLineEdit.EchoMode.Password)
        self.send({'type': 'decisions', 'action': 'add_endpoint', 'id': name.strip().lower(), 'name': name.strip(), 'url': url.strip(), 'key': key.strip()})

    def show_decisions(self, event):
        self.decision_endpoint.blockSignals(True); self.decision_endpoint.clear()
        for endpoint in event.get('endpoints', []):
            self.decision_endpoint.addItem(endpoint['name'] + ('' if endpoint['key_configured'] or endpoint['custom'] else ' · needs key'), endpoint['id'])
        self.decision_endpoint.setCurrentIndex(max(0, self.decision_endpoint.findData(event.get('endpoint'))))
        self.decision_endpoint.blockSignals(False)
        selection = event.get('selection') or {}
        self.decision_model.clear()
        labels = {True: 'reads images', False: 'text only', None: 'image support unchecked'}
        for model in event.get('models', []):
            price = model.get('price_per_million_input')
            self.decision_model.addItem('%s · %s%s' % (model['id'], labels.get(model.get('images')), (' · $%.3f/M' % price) if price else ''), model['id'])
        if selection.get('endpoint') == event.get('endpoint'):
            self.decision_model.setCurrentIndex(max(0, self.decision_model.findData(selection.get('model'))))
        endpoint = next((e for e in event.get('endpoints', []) if e['id'] == event.get('endpoint')), {})
        self.decision_key.setEnabled(event.get('endpoint') != 'openrouter')
        note = event.get('error') or event.get('note') or ''
        if not note and not endpoint.get('key_configured') and not endpoint.get('custom'): note = endpoint.get('key_hint', '')
        if not note: note = 'Visual checks and pacing are on for this model.' if event.get('visual') is True else 'Visual checks need a model that passed the image check.'
        self.decision_note.setText(note)

    def build_generic_settings(self, fields):
        """One labelled combo box per declared setting (see the companion's settings-schema.mjs)."""
        while self.generic_settings.rowCount(): self.generic_settings.removeRow(0)
        self.setting_widgets = {}
        for field in fields:
            if field.get('control') == 'checkbox':
                # A boolean shown as one checkbox: options are [off, on] and the "on" label is its text.
                # The text is a wrapping label beside a bare box (a checkbox's own text cannot wrap at narrow widths).
                options = {option['value']: option['label'] for option in field.get('options', [])}
                box = QCheckBox(); box.setAccessibleName(field.get('accessible') or field['label'])
                text = QLabel(options.get(True, field['label'])); text.setWordWrap(True)
                text.mousePressEvent = lambda _event, box=box: box.toggle()
                row = QWidget(); row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0, 0, 0, 0); row_layout.setSpacing(6)
                row_layout.addWidget(box, 0, Qt.AlignmentFlag.AlignTop); row_layout.addWidget(text, 1)
                if field.get('tooltip'): box.setToolTip(field['tooltip']); text.setToolTip(field['tooltip'])
                box.toggled.connect(self.change_execution_settings)
                self.generic_settings.addRow(field['label'], row); self.setting_widgets[field['key']] = box
                continue
            combo = QComboBox(); combo.setAccessibleName(field.get('accessible') or field['label'])
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); combo.setMinimumContentsLength(8)
            for option in field.get('options', []): combo.addItem(option['label'], option['value'])
            if field.get('tooltip'): combo.setToolTip(field['tooltip'])
            combo.currentIndexChanged.connect(self.change_execution_settings)
            self.generic_settings.addRow(field['label'], combo); self.setting_widgets[field['key']] = combo
            if field.get('note'):
                note = QLabel(field['note']); note.setWordWrap(True); note.setObjectName('muted'); self.generic_settings.addRow(note)
        self.update_controls(); self.sync_auto_approve()

    def apply_execution_settings(self, settings):
        """Show saved settings without sending them back."""
        # A quick Auto-approve switch made while painting is saved at the next pause: until then it stays as the artist set it.
        controls = [(widget, settings.get(key)) for key, widget in self.setting_widgets.items() if not (key == 'auto_approve' and self.settings_unsent)]
        controls += [(self.reasoning_selector, settings.get('reasoning'))]
        for control, value in controls:
            if isinstance(control, QCheckBox):
                if isinstance(value, bool): control.blockSignals(True); control.setChecked(value); control.blockSignals(False)
                continue
            index = control.findData(value)
            if index >= 0: control.blockSignals(True); control.setCurrentIndex(index); control.blockSignals(False)
        self.sync_auto_approve()

    def change_execution_settings(self, *_args):
        self.sync_auto_approve()
        if self.busy: return
        settings = {key: widget.isChecked() if isinstance(widget, QCheckBox) else widget.currentData() for key, widget in self.setting_widgets.items()}
        settings.update({'reasoning': self.reasoning_selector.currentData(), 'native_craft': True})
        self.settings_unsent = False
        self.send({'type': 'set_execution_settings', 'settings': settings})

    # Auto-approve (auto_approve.py, openspec auto-approve): which cards count down, and with what answer.
    def auto_label(self):
        label = QLabel(''); label.setObjectName('autoApprove'); label.setWordWrap(True); label.setTextFormat(Qt.TextFormat.PlainText)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); label.setMinimumWidth(0); label.hide()
        return label

    def card_auto_label(self, button):
        """A countdown line on the chat card that holds `button`."""
        label = self.auto_label(); layout = button.parentWidget().layout() if button.parentWidget() else None
        if layout is not None: layout.addWidget(label)
        return label

    def sync_auto_approve(self):
        """Follow the Auto-approve setting: the delay, the quick switch, and a countdown for the card that waits."""
        combo = self.setting_widgets.get('auto_approve')
        if combo is None: return
        value = combo.currentData(); delay = delay_of(value)
        if delay is not None: self.auto_last = delay
        self.auto_toggle.blockSignals(True); self.auto_toggle.setChecked(delay is not None); self.auto_toggle.blockSignals(False)
        if delay != self.auto_approve.delay: self.auto_approve.set_delay(value)
        self.arm_auto_approve()

    def toggle_auto_approve(self, on):
        combo = self.setting_widgets.get('auto_approve')
        if combo is None:                                       # no settings yet: nothing to switch
            self.auto_toggle.blockSignals(True); self.auto_toggle.setChecked(False); self.auto_toggle.blockSignals(False); return
        combo.blockSignals(True); combo.setCurrentIndex(max(0, combo.findData(self.auto_last if on else 'off'))); combo.blockSignals(False)
        if self.busy: self.settings_unsent = True; self.sync_auto_approve()   # on at once; saved when the run pauses
        else: self.change_execution_settings()

    def show_auto_status(self, text):
        """The countdown on the status line; '' takes a countdown away."""
        if text: self.status.setText(text)
        elif self.status.text().startswith('Auto-approve:'): self.status.setText('Waiting for you.')

    def auto_answered(self, card):
        """Auto-approve took a card's default: recorded in the diagnostics and said in the chat."""
        self.send(dict(card, type='auto_approved'))
        delay = card['delay']
        self.status.setText('Auto-approve took %s%s.' % (card['answer'], ' after %d s' % delay if delay else ''))
        QTimer.singleShot(0, self.arm_auto_approve)            # the next card that waits, once this answer is sent

    def finished_step_row(self, key=None):
        """The finished step whose Met is pressable now (not while the agent paints, nor once pressed)."""
        return next((row for row in self.plan_steps.rows if row['state'] == 'finished' and (key is None or row['key'] == key)
                     and any(action == 'met' and button.isEnabled() for action, button in row['buttons'])), None)

    def ready_move_number(self):
        moves = [m for m in (self.goal or {}).get('moves') or [] if m.get('status') == 'ready']
        return moves[-1].get('number') if moves else (self.current_move or {}).get('number')

    def arm_auto_approve(self):
        """Count down for a finished plan step (Met) or a move outside a plan (Keep), unless a chat card counts already.
        A move that reached its size limit is the same card. Start painting is never offered."""
        auto = self.auto_approve
        if not auto.on or (auto.counting() and auto.pending['kind'] not in ('plan_step', 'move')): return
        move = self.current_move
        row = self.finished_step_row()
        if row is not None:
            key = row['key']
            def met(panel, key=key):
                found = panel.finished_step_row(key)
                if found is not None: panel.plan_steps.send_command(found, 'met')
            auto.offer('%s@%s' % (key, self.ready_move_number()), 'plan_step', 'met', 'Met', 'Redo or type to stop', met,
                       [self.now_auto] + ([self.move_auto] if move else []), ready=lambda panel: not panel.busy,
                       still=lambda panel, key=key: panel.finished_step_row(key) is not None, card=key)
        elif move and self.move_bar.isVisible():
            number = move.get('number')
            auto.offer('move:%s' % number, 'move', 'keep', 'Keeping', 'Undo or type to stop', lambda panel: panel.move_command('keep'),
                       [self.move_auto], ready=lambda panel: not panel.busy,
                       still=lambda panel, number=number: (panel.current_move or {}).get('number') == number)
        elif auto.counting():
            auto.drop()

    def offer_choice(self, key, kind, button, answer, doing, hint='press a button or type to stop', ready=None):
        """Count down for a chat card's button: pressed for the artist after the delay (the same path as their click)."""
        if not self.auto_approve.on: return
        self.auto_approve.offer(key, kind, answer, doing, hint, lambda panel: button.click(), [self.card_auto_label(button)],
                                ready=ready, still=lambda panel: not sip.isdeleted(button) and button.isEnabled())

    def offer_recommended(self, key, kind, controls, recommended, ready=None):
        """A question's recommended option (the companion marks it, auto-approve.ts), when the card shows it."""
        if not recommended: return
        wanted = str(recommended).casefold().strip(' .')
        button = next((b for b in controls or [] if b.text().casefold().strip(' .') == wanted), None)
        if button is not None: self.offer_choice(key, kind, button, button.text(), '“%s”' % button.text(), ready=ready)

    def change_model(self, *_args):
        selected = self.model.currentData()
        if selected:
            self.model.setToolTip(selected['provider'] + ' · ' + selected['id'] + '\nSelected images are sent to this provider.')
            if self.study_active and not self.busy and selected != self.accepted_model:
                self.pending_model_change = True
                self.send({'type': 'set_model', 'provider': selected['provider'], 'model': selected['id']})
                self.update_controls()

    def restore_accepted_model(self):
        if self.pending_model_change and self.accepted_model:
            self.select_provider(self.accepted_model['provider']); self.filter_models()
            self.model.blockSignals(True)
            for index in range(self.model.count()):
                if self.model.itemData(index) == self.accepted_model: self.model.setCurrentIndex(index); break
            self.model.blockSignals(False)
        self.pending_model_change = False
        self.update_controls()

    def show_move(self, move):
        self.current_move = move if move.get('status') == 'ready' else None
        if not self.current_move:
            self.move_bar.hide(); return
        detail = '%d action%s' % (move.get('actions', 0), '' if move.get('actions') == 1 else 's')
        if move.get('strokes'): detail += ' · %d strokes' % move['strokes']
        review = '<br><span>%s</span>' % html.escape(move['review_line']) if move.get('review_line') else ''   # Luna's verdict
        # How close the move left the canvas to the goal reference, and what the host undid (goal-likeness.ts)
        review += '<br><span>%s</span>' % html.escape(move['likeness_line']) if move.get('likeness_line') else ''
        self.move_summary.setText('<b>Move %d</b> · %s<br><span>%s. Keep it, undo it, or type a correction below.</span>%s'
                                  % (move['number'], html.escape(move.get('title') or 'Painting move'), detail, review))
        self.move_bar.show()

    def move_command(self, action):
        self.auto_approve.cancel()
        if not self.current_move or self.busy: return
        self.send({'type': 'move', 'action': action, 'move': self.current_move['number']})
        self.answered_move = self.current_move; self.move_bar.hide(); self.current_move = None

    def restore_answered_move(self):
        """A refused Keep, Undo, Met or Redo: the card comes back while its move is still ready, and the plan list's
        buttons are enabled again."""
        move, self.answered_move = getattr(self, 'answered_move', None), None
        self.plan_steps.set_busy(self.busy)
        if not move or self.current_move: return
        latest = next((m for m in (self.goal or {}).get('moves') or [] if m.get('number') == move.get('number')), move)
        if latest.get('status') == 'ready': self.show_move(latest)

    def send_plan_step(self, command):
        self.auto_approve.cancel()
        if command.get('action') in ('met', 'redo') and self.current_move:   # the step answers the move card: Met keeps, Redo undoes
            self.answered_move = self.current_move; self.move_bar.hide(); self.current_move = None
        self.send(command)

    def start_plan(self):
        self.auto_approve.cancel()
        if not self.goal or not self.goal.get('brief'): return
        # The plan is painted in Agent mode, one move per step for the artist to keep, undo or refine.
        self.mode_selector.setCurrentIndex(self.mode_selector.findData('agent'))
        self.submit(force_start=True)

    def show_history(self):
        if self.history_dialog is None:
            self.history_dialog = HistoryDialog(self)
        self.history_dialog.show(); self.history_dialog.raise_()
        self.send({'type': 'history', 'query': self.history_dialog.search.text()})

    def show_passes(self):
        if self.pass_dialog is None: self.pass_dialog = PassReviewDialog(self)
        self.pass_dialog.show(); self.pass_dialog.raise_()
        self.send({'type': 'review_pass', 'action': 'list'})

    def attach_paths(self, paths, role='reference'):
        for path in paths:
            if not path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                self.status.setText('Attach a PNG, JPEG or GIF reference image.'); continue
            if len(self.pending_references) + len([r for r in self.attached_references if r.get('source') != 'folder']) >= 4:
                self.status.setText('Use up to four references. Remove one to replace it.'); break
            if os.path.isfile(path) and not any(r['path'] == path for r in self.pending_references + self.attached_references):
                self.pending_references.append({'path': path, 'role': role, 'name': os.path.basename(path), 'purpose': 'composition' if role == 'construction-map' else 'general', 'notes': ''})
        self.show_references()

    @staticmethod
    def pasted_folder():
        """Where pasted references and reference parts wait until they are sent; files older than a day go."""
        import tempfile, time
        folder = os.path.join(tempfile.gettempdir(), 'creative-agent-pasted')
        os.makedirs(folder, exist_ok=True)
        for name in os.listdir(folder):
            try:
                if time.time() - os.path.getmtime(os.path.join(folder, name)) > 86400: os.remove(os.path.join(folder, name))
            except OSError: pass
        return folder

    def attach_pasted_image(self, image):
        # Temporary attachment only; runtime copies it into portable study state on send.
        # Pastes live in one folder, and any older than a day are removed here.
        from .qt_compat import QImage
        path = os.path.join(self.pasted_folder(), 'creative-reference-' + uuid.uuid4().hex + '.png')
        if QImage(image).save(path):
            self.attach_paths([path])
            for reference in self.pending_references:
                if reference['path'] == path: reference['name'] = 'Pasted reference'
            self.show_references()

    def update_slash_menu(self):
        # The companion's commands (its skills event: /colour, /refine, ... then /skill:<name>); an older companion sends
        # skills only, listed as /skill:<name>. Typing filters by a command or its aliases, or by a skill's bare name.
        text = self.prompt.toPlainText()
        typed = text.lower() if text.startswith('/') and ' ' not in text and '\n' not in text else None   # any case, as the companion matches
        def matches_typed(entry):
            names = [entry['command']] + list(entry.get('aliases') or [])
            if entry['command'].startswith('/skill:'): names.append('/' + entry['command'][7:])
            return any(name.startswith(typed) for name in names)
        matches = [c for c in self.slash_commands if typed is not None and matches_typed(c)]
        self.slash_menu.clear()
        for entry in matches:
            description = entry.get('description') or ''
            item = QListWidgetItem(entry['command'] + ' — ' + description[:90] + ('…' if len(description) > 90 else ''))
            item.setData(Qt.ItemDataRole.UserRole, entry['command']); item.setToolTip(description)
            self.slash_menu.addItem(item)
        if matches:
            self.slash_menu.setCurrentRow(0); self.slash_menu.show()
        else:
            self.slash_menu.hide()

    def choose_skill(self, item):
        self.prompt.setPlainText(item.data(Qt.ItemDataRole.UserRole) + ' ')
        cursor = self.prompt.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End); self.prompt.setTextCursor(cursor)
        self.slash_menu.hide(); self.prompt.setFocus()

    def resize_composer(self):
        height = int(self.prompt.document().size().height() * self.prompt.fontMetrics().lineSpacing()) + 10
        self.prompt.setFixedHeight(max(66, min(120, height)))

    def flush_stream(self):
        if self.streaming_text:
            self.empty_state.hide()
            if not self.reply_open:
                self.current_reply = self.transcript.add_message('Creative Agent', '')
                self.reply_open = True
            self.transcript.append_to(self.current_reply, self.streaming_text)
            self.streaming_text = ''

    def change_mode(self, *_args):
        self.chat_mode = self.mode_selector.currentData()
        if not getattr(self, 'setting_default_mode', False): self.mode_user_chosen = True; self.mode_auto = False
        placeholders = {'ask': 'Ask about your painting…', 'plan': 'Describe the result and what to preserve…', 'agent': 'Describe a move, e.g. paint the swirling night sky…', 'autopilot': 'Give a direction, or send to start the plan…'}
        self.prompt.setPlaceholderText(placeholders[self.chat_mode])
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.send({'type': 'set_mode', 'mode': self.chat_mode})
        self.update_controls(); self.render_context()

    def open_project_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Open project folder', getattr(self, 'folder_root', '') or '')
        if path: self.send({'type': 'open_folder', 'path': path})

    def show_folder(self, event):
        # Only the study changed (its progress, a note): the rows are updated in place, so a rename in progress, the
        # selection and the scroll stay (folder_study_panel.py).
        shown = json.dumps({k: v for k, v in event.items() if k not in ('type', 'study')}, sort_keys=True, default=str)
        if shown == getattr(self, 'folder_shown', None) and not self.folder_card.isHidden() and self.folder_elements.count():
            self.show_folder_study(event); return
        self.folder_shown = shown
        index = event.get('index') or {}
        self.folder_root = index.get('root', '')
        self.folder_title.setText('<b>%s</b>' % html.escape(index.get('name') or os.path.basename(self.folder_root)))
        self.folder_title.setToolTip(self.text_tip([self.folder_root]) if self.folder_root else '')
        goal = index.get('goal')
        choices = index.get('goal_choices') or ([goal['name']] if goal else []) + [e['name'] for e in index.get('elements') or []] + [o['name'] for o in index.get('others') or []]
        self.folder_goal_choice.blockSignals(True); self.folder_goal_choice.clear()
        for name in choices: self.folder_goal_choice.addItem(name, name)
        self.folder_goal_choice.setCurrentIndex(self.folder_goal_choice.findData(goal['name']) if goal else -1)
        self.folder_goal_choice.blockSignals(False); self.folder_goal_choice.setEnabled(bool(choices) and not self.busy)
        self.folder_goal.setText(self.goal_sharpen_words(event.get('goal_sharpen')) if goal else 'No goal image found: choose one above, or name it final_goal.png.')
        self.folder_goal.setVisible(bool(self.folder_goal.text()))
        self.clear_folder_masses(); self.show_folder_masses()          # never another folder's goal
        elements = index.get('elements') or []
        self.folder_guesses = {element['name']: element.get('guess') or element['name'] for element in elements}
        self.folder_elements.blockSignals(True); self.folder_elements.clear()
        for element in elements:
            item = QListWidgetItem(self.folder_guesses[element['name']])
            item.setData(Qt.ItemDataRole.UserRole, element['name'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole + 1, [element['name']] + ([element['prompt']] if element.get('prompt') else []))   # the tooltip's lines
            self.folder_elements.addItem(item)
        self.folder_elements.blockSignals(False)
        self.folder_goal_name = goal['name'] if goal else None
        self.show_folder_study(event)
        others, skipped = index.get('others') or [], index.get('skipped') or []
        plural = lambda n, word: '%d %s%s' % (n, word, '' if n == 1 else 's')
        limit = event.get('plan_limit')
        over = ' (the plan takes the first %d)' % limit if limit and len(elements) > limit else ''
        parts = [plural(len(elements), 'element image') + over] + ([plural(len(others), 'other image')] if others else []) + (['%d skipped' % len(skipped)] if skipped else [])
        self.folder_footer.setText(' · '.join(parts))
        tip = (['Other images (listed, not attached): ' + ', '.join(o['name'] for o in others)] if others else []) \
            + (['Skipped:'] + ['%s: %s' % (s['name'], s['reason']) for s in skipped] if skipped else [])
        self.folder_footer.setToolTip(self.text_tip(tip) if tip else '')
        self.folder_card.show(); self.tabs.setTabVisible(self.folder_tab, True)

    def show_folder_study(self, event):
        """The study's state on the Folder tab: the study line and each row's mark and tooltip, in place."""
        study = event.get('study')
        self.folder_elements.blockSignals(True)
        for i in range(self.folder_elements.count()):
            item = self.folder_elements.item(i)
            state = FolderStudyCard.image_words(((study or {}).get('images') or {}).get(item.data(Qt.ItemDataRole.UserRole))) if study else ''
            item.setToolTip(self.text_tip(list(item.data(Qt.ItemDataRole.UserRole + 1) or []) + ([state] if state else [])))
        self.folder_elements.blockSignals(False)
        self.folder_study.show_study(study, getattr(self, 'folder_goal_name', None)); self.fit_folder_elements()

    def folder_goal_chosen(self, _index=None):
        name = self.folder_goal_choice.currentData()
        if name: self.send({'type': 'folder_goal', 'name': name})

    @staticmethod
    def goal_sharpen_words(state):
        """The Folder card's line about sharpening the goal (goal-sharpen.ts status), or ''."""
        state = state or {}
        sharpened = state.get('sharpened')
        if state.get('state') == 'used' and sharpened:
            full = sharpened.get('full') or [0, 0]
            return 'Sharpened 4x on this computer (%d x %d); the painter reads it at %d x %d.' % (full[0], full[1], sharpened.get('width', 0), sharpened.get('height', 0))
        factor = state.get('factor')
        words = {'offered': 'is %.1fx smaller than the canvas: sharpening is offered in the chat.', 'running': 'is %.1fx smaller than the canvas: sharpening it…',
                 'review': 'is %.1fx smaller than the canvas: the sharpened copy waits for your answer in the chat.',
                 'kept': 'is %.1fx smaller than the canvas: used as it is.', 'failed': 'is %.1fx smaller than the canvas: sharpening failed, used as it is.',
                 'cancelled': 'is %.1fx smaller than the canvas: sharpening was stopped.'}.get(state.get('state'))
        return ('The goal image ' + words % factor) if words and factor else ''

    def choice_card(self, title, text, choices, answer, image_path=None, notes=()):
        """A card in the chat with a picture (optional), notes always shown under it, and one button per (label, value):
        answered once, then disabled."""
        self.flush_stream(); self.reply_open = False; self.empty_state.hide()
        item = self.transcript.add_message(title, text, True)
        pixmap = QPixmap(image_path) if image_path else QPixmap()
        if not pixmap.isNull():
            picture = QLabel(); picture.setObjectName('questionImage')
            picture.setPixmap(pixmap.scaled(QSize(400, 300), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            item['layout'].addWidget(picture)
        for note in notes:
            if not note.strip(): continue
            line = QLabel(note.strip()); line.setObjectName('muted'); line.setWordWrap(True); line.setTextFormat(Qt.TextFormat.PlainText)
            line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); item['layout'].addWidget(line)
        buttons = []
        for label, value in choices:
            button = QPushButton(label); button.setObjectName('questionChoice')
            button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, chosen=value: ([b.setEnabled(False) for b in buttons], self.auto_approve.cancel(), answer(chosen)))
            item['layout'].addWidget(button); buttons.append(button)
        return buttons

    def show_sharpen_progress(self, event):
        """The Now card's sharpening row: shown while it runs, hidden when it ends."""
        running = not event.get('finished')
        total = max(1, int(event.get('total') or 1))
        if running:
            self.sharpen_bar.setValue(int(1000 * min(1.0, float(event.get('done') or 0) / total)))
            self.sharpen_text.setText(event.get('message') or 'Sharpening the goal image…')
            if not self.sharpen_row.isVisible(): self.sharpen_cancel.setEnabled(True)
            self.status.setText(self.sharpen_text.text())
        self.sharpen_row.setVisible(running); self.plan_steps.set_side_task(running)

    def fit_folder_elements(self):
        """The element list shows every row (it never scrolls inside the Folder tab), and only until the plan lists them."""
        count = self.folder_elements.count()
        rows = sum(self.folder_elements.sizeHintForRow(i) for i in range(count))
        self.folder_elements.setFixedHeight(rows + 2 * self.folder_elements.frameWidth() + 2 if count else 0)
        self.folder_elements.setVisible(bool(count) and (not (self.goal or {}).get('brief') or self.folder_study.shows_states()))   # the study's states show there

    @staticmethod
    def text_tip(lines):
        """A tooltip of plain lines (file names may hold < or &): escaped inside rich text, so nothing is read as markup."""
        return '<p style="white-space:pre-wrap">%s</p>' % '<br>'.join(html.escape(str(line)) for line in lines)

    def folder_element_menu(self, item):
        """A row's study menu (folder_study_panel.py): Study, Exclude or Include."""
        return self.folder_study.menu_for(item, self)

    def folder_element_context_menu(self, position):
        item = self.folder_elements.itemAt(position)
        if item is not None: self.folder_element_menu(item).exec(self.folder_elements.viewport().mapToGlobal(position))

    def folder_guess_changed(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        guess = ' '.join(item.text().split())
        if not guess or guess == self.folder_guesses.get(name):
            self.folder_elements.blockSignals(True); item.setText(self.folder_guesses.get(name, '')); self.folder_elements.blockSignals(False)
            return
        self.folder_guesses[name] = guess
        if item.text() != guess:
            self.folder_elements.blockSignals(True); item.setText(guess); self.folder_elements.blockSignals(False)
        self.send({'type': 'folder_guess', 'name': name, 'guess': guess})

    def show_references(self):
        while self.attachment_row.count():
            item = self.attachment_row.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        self.reference_remove_buttons = []
        # The project folder's images show on its card; the tiles keep the artist's own references.
        references = [r for r in self.attached_references if r.get('source') != 'folder'] + self.pending_references
        for ref in references[:4]:
            tile = QFrame(); tile.setObjectName('referenceTile'); tile.setFixedWidth(72)
            column = QVBoxLayout(tile); column.setContentsMargins(0, 0, 0, 0); column.setSpacing(1)
            thumbnail = QWidget(); image_layout = QGridLayout(thumbnail); image_layout.setContentsMargins(0, 0, 0, 0)
            picture = QPushButton(); picture.setObjectName('contextChip'); picture.setFixedSize(72, 42)
            picture.setIcon(QIcon(ref['path'])); picture.setIconSize(QSize(56, 34))
            name = ref.get('name') or os.path.basename(ref['path'])
            picture.setToolTip(name + '\n' + dict(REFERENCE_PURPOSES).get(ref.get('purpose') or 'general', 'Overall direction'))
            picture.setAccessibleName('Preview and edit reference ' + name)
            picture.clicked.connect(lambda _checked=False, entry=ref: self.edit_reference(entry)); image_layout.addWidget(picture, 0, 0)
            remove = QPushButton('×'); remove.setObjectName('referenceRemove'); remove.setFixedSize(18, 18)
            remove.setAccessibleName('Remove reference ' + name); remove.setToolTip('Remove reference')
            remove.setEnabled(not self.busy)
            remove.clicked.connect(lambda _checked=False, entry=ref: self.remove_reference(entry)); image_layout.addWidget(remove, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            self.reference_remove_buttons.append(remove); column.addWidget(thumbnail)
            masses = self.mass_map_label(ref, 72)
            if masses: column.addWidget(masses)
            purpose = QPushButton(REFERENCE_CAPTIONS.get(ref.get('purpose') or 'general', 'General'))
            purpose.setObjectName('referencePurpose'); purpose.setFixedWidth(72)
            purpose.setAccessibleName('Change reference purpose for ' + name)
            purpose.setToolTip('Choose how this reference guides the painting')
            purpose.clicked.connect(lambda _checked=False, entry=ref: self.edit_reference(entry)); column.addWidget(purpose)
            self.attachment_row.addWidget(tile)
        self.attachment_row.addStretch()
        self.attachments.setVisible(bool(references))

    def mass_map_label(self, reference, width, height=6, bar=None):
        """The reference's big masses (found by the companion) as a flat bar of their colours, its tooltip the artist's
        sentence, or None when it has none (yet). The painter's own summary is not shown: it is coordinates for the model."""
        bar = bar or MassBar(height)
        if not bar.set_mass_map(reference.get('mass_map'), reference.get('name') or ''):
            return None
        if width: bar.setFixedWidth(width)
        return bar

    @staticmethod
    def picture_path(reference):
        """The file a reference's thumbnail is read from: a sharpened goal's own picture from before (goal-sharpen.ts), the
        same picture and small, so its tens of millions of pixels are never decoded on Krita's GUI thread for a thumbnail."""
        reference = reference or {}
        return ((reference.get('sharpened') or {}).get('from') or {}).get('path') or reference.get('path') or ''

    def folder_goal_reference(self):
        return next((r for r in self.attached_references if r.get('source') == 'folder' and r.get('role') == 'reference'), None)

    def show_folder_masses(self):
        goal = self.folder_goal_reference()
        shown = goal is not None and self.mass_map_label(goal, 0, bar=self.folder_masses) is not None
        if not shown:
            self.clear_folder_masses()
        self.folder_masses.setVisible(shown)
        overview = str(((goal or {}).get('mass_map') or {}).get('overview') or '') if shown else ''
        self.folder_mass_text.setText(('Big colour masses: ' + overview) if overview else ''); self.folder_mass_text.setVisible(bool(overview))
        path = self.picture_path(goal)
        if path != getattr(self, 'folder_picture_path', None):
            self.folder_picture_path = path
            picture = thumbnail(path, self.folder_picture.size(), self.devicePixelRatioF()) if path else QPixmap()
            self.folder_picture.setPixmap(picture); self.folder_picture.setVisible(not picture.isNull())
            self.folder_picture.setAccessibleName('Goal image ' + (goal or {}).get('name', '') if not picture.isNull() else '')

    def clear_folder_masses(self):
        self.folder_masses.clear(); self.folder_masses.hide()
        self.folder_mass_text.setText(''); self.folder_mass_text.hide()
        self.folder_picture.clear(); self.folder_picture.hide(); self.folder_picture_path = None

    def edit_reference(self, reference):
        dialog = ReferencePreview(self, reference, readonly=self.busy)
        if dialog.exec() == QDialog.DialogCode.Accepted and not self.busy:
            self.apply_reference_purpose(reference, dialog.purpose.currentData(), dialog.notes.toPlainText().strip())

    def apply_reference_purpose(self, reference, purpose, notes):
        if reference in self.pending_references:
            reference.update(purpose=purpose, notes=notes); self.show_references()
        else:
            command = {'type': 'set_reference_purpose', 'path': reference['path'], 'purpose': purpose, 'notes': notes}
            if reference.get('id'): command['id'] = reference['id']
            self.send(command)

    def remove_reference(self, reference):
        if reference in self.pending_references: self.pending_references.remove(reference)
        else:
            self.send({'type': 'remove_reference', 'path': reference['path']})
        self.show_references()

    def answer_question(self, text):
        self.auto_approve.cancel()
        for button in self.question_controls: button.setEnabled(False)
        self.prompt.setPlainText(text); self.submit()

    def edit_plan(self):
        self.auto_approve.cancel()
        if not self.goal or not self.goal.get('brief'): return
        dialog = PlanDialog(self, self.goal)
        if self.busy:
            dialog.setWindowTitle('Painting plan · pause to edit')
            for editor in dialog.findChildren(QWidget):
                if isinstance(editor, (QLineEdit, QPlainTextEdit, QTableWidget, QSpinBox, QCheckBox)): editor.setEnabled(False)
            for buttons in dialog.findChildren(QDialogButtonBox):
                save = buttons.button(QDialogButtonBox.StandardButton.Save)
                if save: save.setEnabled(False)
        if dialog.exec() == QDialog.DialogCode.Accepted and not self.busy:
            self.send({'type': 'edit_plan', 'brief': dialog.brief()})
            ai_images = dialog.ai_images.value()
            self.send({'type': 'set_limits', 'limits': {'minutes': dialog.minutes.value(), 'passes': dialog.passes.value(),
                                                        'ai_images': None if ai_images < 0 else ai_images}})

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_document_state()
        if not self.process and not os.environ.get('KRITA_CREATIVE_NO_AUTOSTART'):
            QTimer.singleShot(100, self.start_companion)

    def hideEvent(self, event):
        QToolTip.hideText()                                    # no tooltip or command list outlives the hidden panel
        menu = getattr(self, 'slash_menu', None)
        if menu is not None and not sip.isdeleted(menu): menu.hide()
        super().hideEvent(event)

    def update_elapsed(self):
        try:
            self.poll_canvas_metadata()
        except Exception:                                  # the clock and every status go on whatever the canvas poll meets
            if not getattr(self, 'poll_failed', False): record_error('the panel, polling the canvas')
            self.poll_failed = True
        else:
            self.poll_failed = False
        if not self.busy:
            self.elapsed.setText('')
            return
        seconds = int(time.monotonic() - self.phase_started)
        self.elapsed.setText('%d:%02d' % (seconds // 60, seconds % 60))
        if self.phase in ('waiting', 'thinking', 'planning') and seconds >= 30:
            self.status.setText('Waiting for the model… You can pause at any time.')

    def has_open_document(self):
        """True when Krita has an active document. A closed or deleted one (None, or a dead wrapper) counts as none."""
        try: return Krita.instance().activeDocument() is not None
        except (RuntimeError, ReferenceError): return False
        except AttributeError: pass
        # Only when Krita cannot be asked: the companion's last look at the canvas.
        canvas = self.canvas_context.get('canvas') or {}
        return bool(canvas.get('document_id') and self.canvas_context.get('selected') and self.canvas_context.get('state') != 'none')

    def invites_painting(self):
        return not self.has_open_document() and not (self.study_active or self.goal)

    def set_default_mode(self, mode):
        self.setting_default_mode = True
        try: self.mode_selector.setCurrentIndex(self.mode_selector.findData(mode))
        finally: self.setting_default_mode = False

    def refresh_document_state(self):
        """Follow documents opening and closing: the empty-state invitation, the automatic Agent mode, the size fields."""
        try:
            has = self.has_open_document()
            invite = self.invites_painting()
            self.no_document_label.setVisible(invite)
            if 'ask' in self.starter_buttons: self.starter_buttons['ask'].setVisible(not invite)
            if invite and not self.mode_user_chosen and self.chat_mode == 'ask':
                self.set_default_mode('agent'); self.mode_auto = True
            elif has and self.mode_auto and not (self.study_active or self.goal) and self.chat_mode == 'agent':
                self.set_default_mode('ask'); self.mode_auto = False
            if self.had_document and not has and (self.study_active or self.goal) and not self.busy:
                self.status.setText('The painting was closed in %s. Use Return to painting to open it again, or start a new chat.' % product_name())
            if has != self.had_document: self.had_document = has; self.update_controls()
        except (AttributeError, RuntimeError, ReferenceError):
            pass
        self.refresh_features()

    def poll_canvas_metadata(self):
        if not self.isVisible(): return
        self.refresh_document_state()
        self.paint_only.poll()                           # a leftover Paint only here protection goes, with or without the companion
        if not self.process: return
        try:
            doc = Krita.instance().activeDocument()
            signature = (document_id(doc), doc.fileName(), doc.modified()) if doc else None
            if signature != self.document_signature:
                self.document_signature = signature
                self.canvasChanged(None)
        except (AttributeError, RuntimeError):
            pass

    def open_lesson(self):
        lesson = self.goal.get('lesson') if self.goal else None
        if not lesson: return
        if self.lesson_dialog is None: self.lesson_dialog = LessonDialog(self)
        self.lesson_dialog.show_lesson(lesson)
        self.lesson_dialog.show(); self.lesson_dialog.raise_(); self.lesson_dialog.activateWindow()

    def new_chat(self):
        self.source.setCurrentIndex(self.source.findData('current'))
        self.flush_stream()
        self.transcript.clear()
        self.current_reply = None; self.reply_open = False
        self.folder_card.hide(); self.folder_guesses = {}; self.folder_elements.clear(); self.clear_folder_masses(); self.folder_study.clear(); self.folder_shown = None
        self.plan_steps.show_steps([]); self.tabs.setTabVisible(self.plan_tab, False); self.tabs.setTabVisible(self.folder_tab, False)
        self.tabs.setCurrentIndex(self.chat_tab)
        self.auto_approve.forget()
        self.goal = None; self.plan_bar.hide(); self.move_bar.hide(); self.current_move = None; self.question_id = None; self.question_controls = []; self.closeup_question_id = None; self.closeup_controls = []
        self.sharpen_controls = []; self.canvas_reference_controls = []; self.sharpen_row.hide(); self.plan_steps.set_side_task(False)
        self.pending_references = []; self.attached_references = []; self.show_references()
        self.paint_only.chat_ended()
        self.empty_state.show()
        self.last_user_item = None
        self.chat_mode = 'ask'; self.mode_selector.blockSignals(True); self.mode_selector.setCurrentIndex(0); self.mode_selector.blockSignals(False)
        self.mode_user_chosen = False; self.mode_auto = False; self.refresh_document_state()
        self.saved_path = None; self.saved_at = None; self.painting_target = {}; self.save_status.setText('Ask · no canvas changes')
        self.trace_link.hide(); self.trace_link.setText('')
        self.study_id = None
        self.render_scope_tray(); self.render_target()
        self.prompt.setPlaceholderText('Ask about your painting…')
        self.context_command('inspect')
        self.prompt.setFocus()

    def restore_conversation(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Restore a painting or saved plan', getattr(self, 'paintings_directory', self.output_directory) or '', 'Painting or saved plan (*.kra goal.json)')
        if path:
            if path.lower().endswith('.kra'): self.request_restore({'type': 'resume', 'path': path})
            else: self.request_restore({'type': 'resume', 'id': os.path.basename(os.path.dirname(path))})

    def canvasChanged(self, canvas):
        # Krita may emit this while constructing the dock. Observe only after
        # initialization; the host owns attachment state and target pinning.
        if hasattr(self, 'context_timer'):
            if not self.has_open_document() and self.canvas_context.get('canvas'):
                self.canvas_context.update(state='none', canvas=None); self.render_context()
            elif self.canvas_context.get('selected'):
                self.canvas_context['state'] = 'stale'
                self.render_context()
            self.context_timer.start(120)
            self.refresh_features()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'canvas_button'): self.render_context()

    def start_blocked_reason(self):
        """Why the plan cannot start now, in the artist's words (the card says it instead of showing no button)."""
        goal = self.goal or {}
        if self.painting_target.get('missing'): return 'Locate the painting to start: use Locate painting above.'
        if goal.get('question'): return 'Answer the question in the chat to start.'
        if goal.get('target_needs_review'): return 'The canvas changed: review the plan in the chat to start.'
        if self.uncertain_operations: return 'Check the unfinished painting operations first (see the activity line).'
        return ''

    def show_step(self, index):
        """A tap on the progress strip: that step in the Plan tab."""
        rows = self.plan_steps.list_rows
        if not 0 <= index < len(rows) or not self.tabs.isTabVisible(self.plan_tab): return
        self.tabs.setCurrentIndex(self.plan_tab)
        row = rows[index]
        if row.parentWidget() is self.plan_steps.done_box and not self.plan_steps.expanded: self.plan_steps.fold.setChecked(True)
        self.step_to_reveal = index; self.reveal_timer.start()

    def show_settings(self):
        """The settings, modeless, on the panel's own screen, raised and active (a dialog left off screen looked like a
        frozen app)."""
        dialog = self.options_dialog
        dialog.setModal(False)
        screen = (self.screen() if hasattr(self, 'screen') else None) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = QSize(16, 40)                                 # the title bar and borders, which geometry() leaves out
        size = dialog.size().boundedTo(area.size() - frame)
        dialog.resize(size); size = size + frame
        centre = self.mapToGlobal(self.rect().center()) if self.isVisible() else area.center()
        x = min(max(area.left(), centre.x() - size.width() // 2), area.right() - size.width())
        y = min(max(area.top(), centre.y() - size.height() // 2), area.bottom() - size.height())
        dialog.move(x, y)
        dialog.show(); dialog.raise_(); dialog.activateWindow()

    def tab_changed(self, index):
        QToolTip.hideText(); self.slash_menu.hide()          # nothing of another tab stays open over this one
        if index == self.plan_tab: self.reveal_timer.start()
        if index == self.folder_tab: self.fit_folder_elements()   # its rows' heights are known once it shows

    def reveal_current_step(self):
        """The Plan tab scrolled to the step that paints, or to the one tapped on the strip (QScrollArea.ensureWidgetVisible),
        once it is laid out."""
        index, self.step_to_reveal = getattr(self, 'step_to_reveal', None), None
        rows = self.plan_steps.list_rows
        row = rows[index] if index is not None and 0 <= index < len(rows) else self.plan_steps.current_list_row()
        if row is not None and not sip.isdeleted(row) and self.tabs.currentIndex() == self.plan_tab:
            self.plan_scroll.ensureWidgetVisible(row, 0, 40)


    def app_data(self):
        """~/Library/Application Support/KritaAgent in the fork (the app's settings folder), None in stock Krita."""
        return bundled_release.app_data_dir(QStandardPaths.writableLocation(scoped(QStandardPaths, 'StandardLocation', 'GenericDataLocation')),
                                            QCoreApplication.organizationName())

    def config_path(self):
        """The artist's or first-run config in <AppData> when there is one, else the one in the plugin folder."""
        return bundled_release.resolve_config(os.path.dirname(os.path.abspath(__file__)), self.app_data())

    def profile_notice_lines(self):
        """What the launcher and the first config did about an old plugin copy in the profile (bundled_release.shadow_notices), plus
        a line when this very plugin runs from the profile instead of the app. Plain text, no dialog."""
        app_data = self.app_data()
        if app_data is None:
            return []
        try:
            lines = bundled_release.shadow_notices(app_data)
            app_plugin = os.path.join(os.path.dirname(QCoreApplication.applicationDirPath()), 'Resources', 'krita', 'pykrita', 'kritamcp')
            running = bundled_release.profile_plugin_notice(os.path.dirname(os.path.abspath(__file__)), app_data, app_plugin)
            return ([running] if running else []) + lines
        except Exception:
            return []

    def refresh_profile_notice(self):
        lines = self.profile_notice_lines()
        self.profile_notice.setText('\n'.join(lines))
        self.profile_notice.setVisible(bool(lines))
        return lines

    def install_bundled_release(self):
        """In the packaged app: verify the companion inside it and copy it to <AppData> once (bundled_release.py)."""
        bundled = bundled_release.bundled_dir(os.path.dirname(os.path.abspath(__file__)))
        app_data = self.app_data()
        if bundled is None or app_data is None:
            return
        spec = json.loads((bundled / 'release-manifest.json').read_text()).get('node_runtime')
        runtimes = node_runtime.default_root()
        node = node_runtime.node_path(spec, runtimes) if spec else ''
        bundled_release.ensure_installed(bundled, app_data, runtimes, node, bridge_url='http://127.0.0.1:%d' % bridge_port('', QCoreApplication.organizationName()),
                                         cache_dir=os.path.join(os.path.expanduser('~/Library/Caches'), os.path.basename(str(app_data)), 'creative-agent'))
        self.refresh_profile_notice()                                         # the data copy may just have happened

    def fetch_node_runtime(self, config):
        if getattr(self, 'runtime_fetch', None) and self.runtime_fetch['thread'].is_alive():
            return
        spec = config['node_runtime']
        state = {'done': 0, 'total': 0, 'error': None, 'finished': False}
        def work():
            try: node_runtime.ensure(spec, config.get('node_runtimes'), progress=lambda done, total: state.update(done=done, total=total))
            except Exception as error: state['error'] = str(error)
            finally: state['finished'] = True
        self.runtime_fetch = {'thread': threading.Thread(target=work, daemon=True), 'state': state}
        self.runtime_fetch['thread'].start()
        self.start_button.setEnabled(False)
        self.status.setText('Downloading Node %s for Creative Agent (one time)…' % spec['version'])
        timer = QTimer(self); timer.setInterval(250)
        def poll():
            if not state['finished']:
                if state['total']: self.status.setText('Downloading Node %s for Creative Agent (one time)… %d%%' % (spec['version'], state['done'] * 100 // state['total']))
                elif state['done']: self.status.setText('Downloading Node %s for Creative Agent (one time)… %.0f MB' % (spec['version'], state['done'] / 1e6))
                return
            timer.stop(); timer.deleteLater()
            if state['error']:
                self.start_button.setEnabled(True)
                self.status.setText('Could not set up Node: %s Check your connection and press Start to retry.' % state['error'])
            else:
                self.start_companion()
        timer.timeout.connect(poll); timer.start()

    def start_companion(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            self.install_bundled_release()
            config = bundled_release.load_config(self.config_path())          # a clear message naming the file if it is damaged
            # A managed Node runtime is fetched once, in the background, then the companion starts.
            if config.get('node_runtime') and not os.environ.get(node_runtime.OVERRIDE) and not node_runtime.is_ready(config['node_runtime'], config.get('node_runtimes')):
                self.fetch_node_runtime(config); return
            # The runtime manager names this OS's node (bin/node, or node.exe on Windows); the installer's path is a hint.
            if config.get('node_runtime'): config['node'] = str(node_runtime.resolve(config['node_runtime'], config.get('node_runtimes')))
            if not os.path.isfile(config['companion']) or not os.path.isfile(config['node']):
                raise ValueError('The companion path is unavailable. Run the local setup and installer.')
            self.paintings_directory = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(config['companion'])), config.get('paintings_dir', 'output')))
        except Exception as error:
            self.status.setText(str(error))
            return
        self.buffer = b''
        self.process = QProcess(self)
        # QObject.destroyed precedes child deletion. Use a free callback: a
        # bound method on this dying dock is not a reliable signal receiver.
        self.destroyed.connect(lambda _object=None, process=self.process: disconnect_companion_callbacks(process))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('KRITA_CREATIVE_CONFIG', self.config_path())
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(os.path.dirname(config['companion']))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.process.start(config['node'], [config['companion']])
        self.start_button.setEnabled(False)
        self.status.setText('Connecting Agent Pi…')

    def process_ui_alive(self):
        return not sip.isdeleted(self) and not sip.isdeleted(self.status) and not sip.isdeleted(self.start_button)

    def process_error(self, _error):
        if self.process_ui_alive():
            self.status.setText('The companion could not start. Check its installation.')

    def process_finished(self, *_args):
        if not self.process_ui_alive():
            return
        self.busy = False; self.study_active = False; stop_requested.clear()
        self.start_button.setEnabled(True)
        self.start_button.setText('Reconnect assistant')
        self.start_button.show()
        self.status.setText('Assistant disconnected. Reconnect to continue.')
        self.update_controls()

    def send(self, command):
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            self.status.setText('Start the assistant first.')
            return
        self.process.write((json.dumps(command) + '\n').encode('utf-8'))

    def read_output(self):
        if not self.process_ui_alive():
            return
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            # One bad event must never stop the panel: an error escaping here left every later line (idle, busy false)
            # unread in the buffer until the companion wrote again, and the panel showed a run that had ended.
            try:
                self.handle_event(json.loads(line.decode('utf-8')))
            except Exception:
                record_error('the panel, handling a companion event')
                try: self.status.setText('An assistant message could not be displayed (details in the error log).')
                except Exception: pass

    def handle_event(self, event):
        kind = event['type']
        if kind == 'diagnostics_exported':
            self.diagnostics_text.setPlainText('Troubleshooting report saved locally:\n' + event['path'])
            self.diagnostics_toggle.setChecked(True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(event['path'])))
        elif kind == 'tracing':
            url = event.get('url', '')
            if url.startswith('https://') or url.startswith('http://'):
                self.trace_link.setText('<a href="%s">Trace</a>' % html.escape(url, quote=True)); self.trace_link.show()
        elif kind == 'context':
            self.canvas_context = {key: value for key, value in event.items() if key != 'type'}
            self.render_context(); self.update_controls(); self.refresh_document_state()
            if self.status.text().startswith('Attaching a rectangular crop') and (self.canvas_context.get('region') or {}).get('state') == 'fresh':
                self.status.setText('Rectangular crop attached')
            if self.preview_after_refresh and self.canvas_context.get('state') == 'fresh' and (self.canvas_context.get('canvas') or {}).get('path'):
                self.preview_after_refresh = False; self.preview_canvas(self.canvas_context['canvas'])
            if self.canvas_context.get('state') == 'error': self.set_recovery('Retry canvas', lambda: self.context_command('refresh'))
            elif self.recovery_button.text() == 'Retry canvas': self.set_recovery()
        elif kind == 'needs_relink':
            self.relink_id = event['id']; self.status.setText(event['message'])
            self.set_recovery('Locate painting', self.locate_missing_painting)
        elif kind == 'relinked':
            self.saved_path = event['path']; self.set_recovery(); self.status.setText('Painting location updated. Conversation remains paused.')
            self.painting_target.update(filename=event['path'], missing=False)
            self.render_target()
        elif kind == 'model_capability':
            capability = event.get('status')
            if capability in ('verifying', 'failed') or self.phase == 'checking_model': self.status.setText(event.get('message') or 'Checking model compatibility…')
            self.model.setToolTip(event.get('message') or 'Model route')
            if capability == 'failed': self.restore_accepted_model()
        elif kind == 'move':
            self.show_move(event['move']); self.arm_auto_approve()
        elif kind == 'decisions':
            self.show_decisions(event)
        elif kind == 'skills':
            self.skills = [s for s in event.get('skills', []) if s.get('name') and s.get('description')]
            commands = [c for c in event.get('commands') or [] if isinstance(c, dict) and str(c.get('command', '')).startswith('/')]
            self.slash_commands = commands or [{'command': '/skill:' + s['name'], 'description': s['description']} for s in self.skills]
            self.update_slash_menu()
        elif kind == 'settings_schema':
            self.build_generic_settings(event.get('fields', []))
            if self.last_execution_settings: self.apply_execution_settings(self.last_execution_settings)
        elif kind == 'execution_settings':
            settings = event['settings']; self.last_execution_settings = settings
            self.apply_execution_settings(settings)
            # Strokes only is no longer offered: a chat saved with it gets the full Krita toolset back.
            if settings.get('native_craft') is False and not self.busy: self.change_execution_settings()
            effective = event.get('effective_reasoning')
            available = event.get('available_reasoning') or []
            # The companion describes its Auto policy; an older companion sends none.
            auto = event.get('reasoning_note') if settings.get('reasoning') == 'auto' else None
            if effective is not None:
                self.reasoning_note.setText((auto + ' ' if auto else '') + 'Now: ' + effective + '. Supported levels: ' + ', '.join(available) + '. Your preference applies to the painter, the reviewer and preparation workers.')
            else:
                self.reasoning_note.setText('Applies when the conversation starts. ' + (auto or 'Auto uses low reasoning when supported.') + ' Other levels adapt to the selected model.')
        elif kind == 'model':
            value = event['model']; self.accepted_model = {'provider': value['provider'], 'id': value['id']}; self.pending_model_change = False
            self.select_provider(value['provider']); self.filter_models(); self.model.blockSignals(True)
            for index in range(self.model.count()):
                if self.model.itemData(index) == self.accepted_model: self.model.setCurrentIndex(index); break
            self.model.blockSignals(False); self.update_controls()
        elif kind == 'uncertain_operations':
            self.uncertain_operations = event.get('operations', [])
            self.inspected_uncertain = False
            self.status.setText(event.get('message') or 'Inspect the last operation before continuing.')
            if self.uncertain_operations: self.set_recovery('Inspect result', lambda: self.send({'type': 'inspect_result'}))
            else: self.set_recovery()
            self.update_controls()
        elif kind == 'inspected_result':
            self.inspected_uncertain = True
            canvas = event.get('canvas')
            if canvas: self.preview_canvas(canvas)
            self.status.setText('Check the canvas. Continue only after inspecting the result.')
            self.set_recovery('Continue after inspection', lambda: self.send({'type': 'reconcile'}))
        elif kind == 'reconciled':
            self.uncertain_operations = []; self.inspected_uncertain = False
            self.set_recovery(); self.status.setText('Result acknowledged. Painting remains paused.'); self.update_controls()
        elif kind == 'message_context':
            item = next((item for item in reversed(self.transcript.messages) if item.get('id') == event.get('message_id') and item['role'] == 'You'), self.last_user_item)
            if item and event.get('status') == 'included' and event.get('canvas'):
                self.transcript.add_receipt(item, event['canvas'])
            if item and event.get('status') == 'included' and event.get('region'):
                self.transcript.add_region_receipt(item, event['region'], event.get('canvas'))
            if item and event.get('status') == 'included' and event.get('references'):
                self.transcript.add_reference_receipts(item, event['references'])
        elif kind == 'conversations':
            if self.history_dialog: self.history_dialog.set_items(event.get('items', []), event.get('total_bytes'), event.get('query', ''))
        elif kind == 'passes':
            if self.pass_dialog: self.pass_dialog.set_passes(event.get('passes', []))
        elif kind in ('ready', 'models'):
            self.models = event['models']
            self.providers = event.get('providers') or []
            selected = self.accepted_model if self.study_active else event.get('selected') or self.model.currentData()
            # Nothing chosen yet (a fresh install): the default painter when it is connected (the artist, 2026-10-24).
            if not selected and not self.accepted_model:
                selected = next(({'provider': m['provider'], 'id': m['id']} for m in self.models if (m['provider'], m['id']) == DEFAULT_PAINTER
                                 and m.get('configured') and m.get('interactive', True)), None)
            provider = (selected or {}).get('provider') or self.provider_filter.currentData()
            if not provider:
                provider = next((m['provider'] for m in self.models if m.get('configured') and m.get('interactive', True)), None)
            self.provider_filter.blockSignals(True); self.provider_filter.clear()
            provider_records = {item['id']: item for item in self.providers}
            for identifier in sorted({item['provider'] for item in self.models} | set(provider_records), key=provider_name):
                configured = provider_records.get(identifier, {}).get('configured') or any(item.get('configured') for item in self.models if item['provider'] == identifier)
                oauth = provider_records.get(identifier, {}).get('auth') == 'oauth' or any(item.get('auth') == 'oauth' for item in self.models if item['provider'] == identifier)
                self.provider_filter.addItem(provider_name(identifier) + ('' if configured else ' · sign in' if oauth else ' · connect'), identifier)
            self.provider_filter.setCurrentIndex(max(0, self.provider_filter.findData(provider))); self.provider_filter.blockSignals(False)
            self.filter_models()
            self.model.blockSignals(True)
            if selected:
                for index in range(self.model.count()):
                    if self.model.itemData(index) == selected:
                        self.model.setCurrentIndex(index)
                        break
            self.model.blockSignals(False)
            if kind == 'ready':
                self.status.setText(event.get('bridge', {}).get('error') or 'Ready')
                self.versions = event.get('versions') or event.get('build') or {}
                try:
                    with open(os.path.join(os.path.dirname(__file__), 'build-info.json')) as stream: ui_build = json.load(stream)
                except (OSError, ValueError): ui_build = {'build_id': 'development-unverified', 'version': 'development'}
                self.render_connection(ui_build, event)
                self.bridge_compatible = event.get('compatible', True)
                if event.get('compatible') is False:
                    self.status.setText('A matching plugin build must be loaded before painting.')
                self.context_command('inspect')
            self.start_button.hide()
            self.update_controls()
            if kind == 'ready' and self.resume_on_ready:
                identifier = self.resume_on_ready; self.resume_on_ready = None
                self.focus_after_restore = not getattr(self, 'preserve_canvas_on_reload', False)
                self.send({'type': 'resume', 'id': identifier})
        elif kind == 'busy':
            self.busy = event['busy']
            self.plan_steps.set_busy(self.busy)
            self.folder_goal_choice.setEnabled(not self.busy and self.folder_goal_choice.count() > 0)
            if not self.busy: stop_requested.clear()      # the stopped run has ended
            self.run_started = time.monotonic() if self.busy else None
            self.activity_dot.setText('●' if self.busy else '')
            self.update_controls(); self.update_elapsed()
            self.return_button.setEnabled(not self.busy)
            if not self.busy and self.settings_unsent: self.change_execution_settings()   # a quick switch made while painting
            self.arm_auto_approve()
            if not self.busy and self.study_active and self.focus_after_restore:
                self.focus_after_restore = False
                self.return_to_painting(restored=True)
        elif kind == 'study':
            self.study_id = event['id']
            self.study_active = True; self.output_directory = self.chat_directory = event['directory']
            self.model.blockSignals(True)
            if event.get('model'):
                self.accepted_model = event['model']; self.pending_model_change = False
                self.select_provider(event['model']['provider']); self.filter_models(); self.model.blockSignals(True)
                for index in range(self.model.count()):
                    if self.model.itemData(index) == event['model']:
                        self.model.setCurrentIndex(index)
                        break
            self.model.blockSignals(False)
            self.empty_state.hide()
            self.options_button.setChecked(False)
            self.options_dialog.hide()
            self.update_controls()
        elif kind == 'ended':
            self.study_active = False; self.update_controls()
            self.new_chat()
            self.status.setText('Ready for a new conversation.')
            if self.pending_restore:
                command = self.pending_restore; self.pending_restore = None
                self.focus_after_restore = True
                self.send(command)
        elif kind == 'canvas':
            if event.get('checkpoint'):
                self.saved_path = event['checkpoint']
                self.saved_at = time.strftime('%H:%M:%S')
                self.output_directory = os.path.dirname(self.saved_path)
                self.folder_button.setEnabled(True)
                self.save_status.setText('Saved ' + time.strftime('%H:%M:%S') + ' · ' + os.path.basename(self.saved_path))
                self.save_status.setToolTip(self.saved_path)
                self.painting_target.update(filename=self.saved_path, document_id=event.get('document_id') or self.painting_target.get('document_id'), bound=True)
                self.render_target()
        elif kind == 'history':
            self.flush_stream(); self.transcript.clear(); self.current_reply = None; self.reply_open = False
            self.empty_state.setVisible(not bool(event['messages']))
            for message in event['messages']:
                item = self.transcript.add_message('You' if message['role'] == 'user' else 'Creative Agent', message['text'], message_id=message.get('id'))
                canvas = message.get('canvas') or message.get('context', {}).get('canvas')
                if canvas: self.transcript.add_receipt(item, canvas)
                if message.get('region'): self.transcript.add_region_receipt(item, message['region'], canvas)
                if message.get('references'): self.transcript.add_reference_receipts(item, message['references'])
                if message['role'] == 'user': self.last_user_item = item
        elif kind == 'keep_awake':
            self.awake_indicator.setVisible(bool(event.get('active') and event.get('display')))
        elif kind == 'goal':
            self.goal = event['goal']
            if 'painting_target' in event:
                self.painting_target = event['painting_target'] or {}
                if self.painting_target.get('filename'): self.saved_path = self.painting_target['filename']
            self.paint_only.sync(self.goal)
            self.render_scope_tray(); self.render_target()
            self.chat_mode = event['mode']
            self.mode_selector.blockSignals(True)
            self.mode_selector.setCurrentIndex(self.mode_selector.findData(self.chat_mode)); self.mode_selector.blockSignals(False)
            references = event.get('references', [])
            copied = {r.get('source_path') for r in references}
            self.pending_references = [r for r in self.pending_references if r['path'] not in copied]
            self.attached_references = references; self.show_references(); self.show_folder_masses()
            brief = self.goal.get('brief')
            self.render_ai_images()
            self.plan_bar.setVisible(bool(brief))
            step_rows = (event.get('plan_steps') or []) if brief else []
            goal_reference = self.folder_goal_reference()
            self.plan_steps.show_steps(step_rows, self.busy, root=getattr(self, 'folder_root', ''), goal_image=self.picture_path(goal_reference))
            self.tabs.setTabVisible(self.plan_tab, bool(brief))
            self.tabs.setTabText(self.plan_tab, 'Plan · %d' % len(brief['steps']) if brief and brief.get('steps') else 'Plan')
            current_step = self.plan_steps.current_index()
            if current_step is not None and current_step != self.revealed_step: self.reveal_timer.start()   # only when another step paints
            self.revealed_step = current_step
            self.fit_folder_elements()                         # the plan lists the elements from now on
            if self.current_move:                               # the card goes once its move is kept or undone, not before
                shown = next((m for m in self.goal.get('moves') or [] if m.get('number') == self.current_move.get('number')), None)
                if shown is not None and shown.get('status') != 'ready': self.move_bar.hide(); self.current_move = None
            if brief:
                states = {'draft': 'Plan draft', 'ready': 'Plan ready', 'active': 'Painting', 'paused': 'Paused', 'reviewing': 'Visual review',
                          'complete': 'Finished', 'limited': 'Allowance reached', 'needs_input': 'Needs your input', 'move_ready': 'Move ready'}
                step = max(0, min(self.goal.get('current_step', 0), len(brief['steps']) - 1))
                label = 'Canvas changed · review plan' if self.goal.get('target_needs_review') else 'Needs your answer' if self.goal.get('question') else states.get(self.goal['status'], self.goal['status'])
                current = brief['steps'][step] if brief['steps'] else {}
                # A project folder's plan: the step's element file (its scope) and how many steps are ticked.
                source = current.get('scope', '') if re.search(r'\.(png|jpe?g|gif)$', current.get('scope', ''), re.I) else ''
                done = len(self.goal.get('done_steps') or [])
                if step_rows:                                   # the steps say which step paints and how many are met
                    self.plan_summary.setText(label + ' · ' + brief['title'])
                else:
                    self.plan_summary.setText(label + ' · ' + brief['title'] + ('\nStep %d of %d · %s' % (step + 1, len(brief['steps']), current['title']) if brief['steps'] else '')
                                              + (' · from %s' % os.path.basename(source) if source else '') + (' · %d of %d done' % (done, len(brief['steps'])) if done else ''))
                self.plan_summary.setToolTip('%d painting passes · %d tokens used' % (self.goal.get('passes', 0), self.goal.get('tokens', 0)))
            if not self.goal.get('question'):
                for button in self.question_controls: button.setEnabled(False)
            self.update_controls(); self.arm_auto_approve()
        elif kind == 'folder':
            self.show_folder(event)
        elif kind == 'mode':
            self.mode_selector.blockSignals(True); self.mode_selector.setCurrentIndex(self.mode_selector.findData(event['mode'])); self.mode_selector.blockSignals(False)
            self.chat_mode = event['mode']; self.update_controls()
        elif kind == 'closeup_question':
            # Close-up references (closeups.ts): asked beside the run, answered by this question's id, never typed into the chat.
            if self.closeup_question_id != event['id']:
                self.closeup_question_id = event['id']
                question_id = event['id']
                def answer(value, question_id=question_id):
                    self.auto_approve.cancel()
                    for button in self.closeup_controls: button.setEnabled(False)
                    self.send({'type': 'closeup_answer', 'question_id': question_id, 'answer': value})
                self.closeup_controls = self.transcript.add_question(event['question'], event.get('options', []), answer, event.get('image_path'))
                self.offer_recommended(question_id, 'closeup', self.closeup_controls, event.get('recommended'))
        elif kind == 'question':
            self.flush_stream(); self.reply_open = False
            if self.question_id != event['id']:
                self.question_id = event['id']
                # The painter asks for a selection (ask_for_selection): Select with Freehand, Use my selection, Paint everywhere.
                self.question_controls = (self.paint_only.select_card(event) if event.get('select_area') else
                                          self.transcript.add_question(event['question'], event.get('options', []), self.answer_question, event.get('image_path')))
                self.offer_recommended(event['id'], 'question', self.question_controls, event.get('recommended'), ready=lambda panel: not panel.busy)
            self.prompt.setPlaceholderText('Answer here, or choose an option above…')
        elif kind == 'review':
            self.flush_stream(); self.reply_open = False
            review = event['review']
            text = review['summary']
            if review.get('issues'): text += '\n\n' + '\n'.join('- ' + issue for issue in review['issues'])
            self.empty_state.hide()
            self.transcript.add_message('Visual review', text, True)
        elif kind == 'protection_proposed':
            self.flush_stream(); self.reply_open = False; self.empty_state.hide()
            area = event['area']
            item = self.transcript.add_message('Protected area', "I marked '%s' in red. Keep this protection?" % area['name'], True)
            self.protection_controls = []
            for text, choice in (('Keep', 'keep'), ('Adjust', 'adjust'), ('Discard', 'discard')):
                button = QPushButton(text); button.setObjectName('questionChoice')
                button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                button.clicked.connect(lambda _checked=False, entry=area, value=choice: self.answer_protection(entry, value))
                item['layout'].addWidget(button); self.protection_controls.append(button)
            self.show_protection(area, True); self.refresh_features()
        elif kind == 'shapes_model_needed':
            # Element shapes (src/shapes/chat.ts): the one-time model download waits for the artist's answer.
            self.flush_stream(); self.reply_open = False; self.empty_state.hide()
            size = int(event.get('size_mb') or 0)
            item = self.transcript.add_message('Element shapes', event.get('message') or 'Finding shapes needs a one-time download (%d MB).' % size, True)
            self.shapes_model_controls = []
            for text, choice in (('Download (%d MB)' % size, 'accept'), ('Not now', 'decline')):
                button = QPushButton(text); button.setObjectName('questionChoice')
                button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                button.clicked.connect(lambda _checked=False, value=choice, where=item: self.answer_shapes_model(value, where))
                item['layout'].addWidget(button); self.shapes_model_controls.append(button)
        elif kind == 'goal_sharpen_offer':
            # Sharpen goal (goal-sharpen.ts): offered beside the chat, never a question the run waits for.
            question_id = event['id']
            answers = dict(zip(event.get('options') or ['Sharpen', 'Use as is'], ('sharpen', 'original')))
            self.sharpen_controls = self.choice_card('Goal image', event.get('message') or '', list(answers.items()),
                                                     lambda value, question_id=question_id: self.send({'type': 'goal_sharpen', 'id': question_id, 'action': value}))
            if self.sharpen_controls: self.offer_choice('sharpen:' + question_id, 'sharpen_offer', self.sharpen_controls[0], 'sharpen', self.sharpen_controls[0].text(), 'press a button to stop')
        elif kind == 'goal_sharpen_review':
            question_id = event['id']
            answers = dict(zip(event.get('options') or ['Use sharpened', 'Keep original'], ('use', 'keep')))
            self.sharpen_controls = self.choice_card('Goal image', event.get('question') or '', list(answers.items()),
                                                     lambda value, question_id=question_id: self.send({'type': 'goal_sharpen', 'id': question_id, 'action': value}),
                                                     event.get('image_path'))
            if self.sharpen_controls: self.offer_choice('sharpened:' + question_id, 'sharpen_review', self.sharpen_controls[0], 'use', self.sharpen_controls[0].text(), 'press a button to stop')
        elif kind == 'goal_sharpen_progress':
            self.show_sharpen_progress(event)
        elif kind == 'canvas_reference':
            # Canvas reference (canvas-reference.ts): the canvas and the reference side by side. Never offered to
            # Auto-approve (auto_approve.NEVER): what the painting becomes is the artist's choice.
            reference_id = event['id']; paragraphs = (event.get('message') or '').split('\n\n')
            choices = list(zip(event.get('options') or [], event.get('actions') or []))
            self.canvas_reference_controls = self.choice_card(event.get('title') or 'Canvas reference', paragraphs[0], choices,
                                                              lambda value, reference_id=reference_id: self.send({'type': 'canvas_reference', 'id': reference_id, 'action': value}),
                                                              event.get('image_path'), notes=paragraphs[1:])
        elif kind == 'shapes_model_ready':
            for button in self.shapes_model_controls: button.setEnabled(False)
            self.status.setText('The shape model is ready.')
        elif kind == 'found_area':
            # Find it for me (paint_only_panel.py): the outline becomes the document's selection, or the reason it did not.
            self.paint_only.found(event)
        elif kind == 'protection_hit':
            self.flush_stream(); self.reply_open = False; self.empty_state.hide()
            self.transcript.add_message('Protected area', event['message'], True)
        elif kind == 'visual_check':
            self.flush_stream(); self.reply_open = False; self.empty_state.hide()
            found = ', '.join('%s (%s, %d%%)' % (f['label'], (f.get('location') or 'location unknown').replace('_', ' '), round(f['probability'] * 100))
                              for f in event.get('findings', []))
            suffix = ' Recorded only.' if event.get('mode') == 'evaluate' else ' Given to the painter to verify.'
            self.transcript.add_message('Luna check', 'This pass may have introduced: ' + found + '.' + suffix, True)
        elif kind == 'review_progress':
            self.flush_stream(); self.reply_open = False; self.empty_state.hide()
            mean = event.get('mean', 0)
            verdict = 'no real improvement' if mean < 1 else 'slight improvement' if mean < 2 else 'clear improvement'
            self.transcript.add_message('Luna progress', 'Since the previous review, the failing checks show %s (%.1f of 3).' % (verdict, mean), True)
        elif kind == 'text':
            self.streaming_text += event['text']
            if not self.stream_timer.isActive(): self.stream_timer.start(35)
        elif kind == 'message_end':
            self.flush_stream()
            self.reply_open = False
        elif kind == 'action':
            self.flush_stream()
            self.reply_open = False
            self.empty_state.hide()
            self.transcript.add_message('Needs attention' if event.get('error') else 'Activity', event['message'], not event.get('error'))
        elif kind in ('status', 'error'):
            phase = event.get('phase', 'error' if kind == 'error' else self.phase)
            if phase != self.phase or event['message'] != self.status.text():
                self.phase_started = time.monotonic()
            self.phase = phase
            self.status.setText(event['message'])
            if kind == 'error':
                self.restore_answered_move()
                self.pending_restore = None
                self.focus_after_restore = False
                self.restore_accepted_model()
                self.flush_stream()
                self.reply_open = False
                self.empty_state.hide()
                self.transcript.add_message('Needs attention', event['message'])
            self.update_elapsed()

    def append_text(self, text):
        self.transcript.add_message('Creative Agent', text)

    def filter_models(self, *_args):
        selected = self.model.currentData()
        query = self.filter.text().casefold()
        provider = self.provider_filter.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        entries = [m for m in self.models if m['provider'] == provider and query in (provider_name(m['provider']) + ' ' + m['provider'] + ' ' + m['name'] + ' ' + m['id']).casefold()]
        current = next((m for m in self.models if {'provider': m['provider'], 'id': m['id']} == selected), None)
        if current and current['provider'] == provider and current not in entries: entries.insert(0, current)
        accepted = next((m for m in self.models if {'provider': m['provider'], 'id': m['id']} == self.accepted_model), None)
        if accepted and accepted['provider'] == provider and accepted not in entries: entries.insert(0, accepted)
        for item in entries:
            available = item.get('configured') and item.get('interactive', True)
            oauth = item.get('auth') == 'oauth'
            suffix = (' · sign in' if oauth else ' · connect') if not item.get('configured') else ' · batch' if not item.get('interactive', True) else ''
            self.model.addItem(item['name'] + suffix, {'provider': item['provider'], 'id': item['id']})
            row = self.model.model().item(self.model.count() - 1); row.setEnabled(bool(available))
            reason = ('Sign in to this provider in Pi (run pi, then /login).' if oauth else 'Connect this provider in Pi, or add an API connection below.') if not item.get('configured') else 'Batch models do not support interactive chat.' if not item.get('interactive', True) else item.get('capability_message') or 'Ready for interactive chat.'
            if oauth and item.get('configured'):
                reason += '\nSigned in through Pi. If the sign-in lapses, the run pauses until you sign in again.'
            row.setToolTip(provider_name(item['provider']) + '\n' + item['id'] + '\n' + reason)
        preferred = next((i for i in range(self.model.count()) if self.model.itemData(i) == selected), -1)
        if preferred < 0 and self.study_active and self.accepted_model and provider != self.accepted_model['provider']:
            preferred = -1
        elif preferred < 0:
            preferred = next((i for i in range(self.model.count()) if self.model.model().item(i).isEnabled() and 'deepseek-v4.1-flash' in self.model.itemData(i)['id']), -1)
        if preferred < 0 and (not self.study_active or not self.accepted_model or provider == self.accepted_model['provider']):
            preferred = next((i for i in range(self.model.count()) if self.model.model().item(i).isEnabled()), -1)
        self.model.setCurrentIndex(preferred)
        self.model.blockSignals(False)
        provider_models = [m for m in self.models if not provider or m['provider'] == provider]
        if provider and not provider_models:
            self.provider_note.setText('No models are registered for ' + provider_name(provider) + ' in Pi yet. Add a model in Pi or connect an API below.')
        elif provider and not any(m.get('configured') for m in provider_models):
            self.provider_note.setText('Connect ' + provider_name(provider) + ' in Pi, or add an API below. Choose a connected provider to send messages.')
        else:
            self.provider_note.setText('Choose a provider beside the composer. The next dropdown shows only that provider’s models.')
        self.update_controls()

    def connect_provider(self):
        dialog = ProviderDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.send(dialog.command())
            dialog.key.clear()

    def attach(self, role):
        paths, _filter = QFileDialog.getOpenFileNames(self, 'Attach reference images', '', 'Images (*.png *.jpg *.jpeg *.gif)')
        self.attach_paths(paths, 'construction-map' if role == 'map' else 'reference')

    def submit(self, _checked=False, force_start=False):
        self.auto_approve.cancel()
        if getattr(self, 'move_bar', None) is not None: self.move_bar.hide(); self.current_move = None   # a message after a move refines it
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            self.status.setText('Connect the assistant before sending.'); return
        prompt = self.prompt.toPlainText().strip()
        start_plan = bool(force_start and self.goal and self.goal.get('brief'))
        if not prompt:
            if start_plan: prompt = 'Start painting from this plan.'
            elif self.pending_references: prompt = 'Help me plan a painting from these references and our discussion.'
            else:
                self.status.setText('Write a message, attach a reference, or use Start painting.'); return
        selected = (self.accepted_model if self.study_active else None) or self.model.currentData()
        if not selected:
            self.status.setText('Choose or connect a model first.'); return
        self.empty_state.hide()
        self.transcript.jump_to_latest(); self.flush_stream()
        start_mode, start_name = self.source.currentData(), self.name.text()
        if not self.study_active and start_mode == 'current' and self.chat_mode == 'agent' and not self.has_open_document():
            # Nothing is open: the first message creates the painting, sized by the Size fields and named from the request.
            start_mode = 'new'
            if start_name.strip() in ('', 'Creative painting'): start_name = painting_name_from(prompt)
        message_id = uuid.uuid4().hex
        self.last_user_item = self.transcript.add_message('You', prompt, message_id=message_id)
        self.reply_open = False
        shared = {'chat_mode': self.chat_mode, 'start_plan': start_plan, 'references': self.pending_references,
                  'canvas': self.context_payload(), 'message_id': message_id}
        area = self.paint_only.for_message(prompt)              # Paint only here: the typed phrase, an answer, or an area set before the chat
        if area: shared['paint_only_here'] = area
        if self.study_active:
            self.send(dict(shared, type='prompt', text=prompt))
        else:
            self.send(dict(shared, type='start', prompt=prompt, provider=selected['provider'], model=selected['id'],
                           mode=start_mode, name=start_name, width=self.canvas_width.value(),
                           height=self.canvas_height.value(), experiment=self.experiment.currentData()))
        self.prompt.clear(); self.status.setText('Preparing your message…')

    def render_ai_images(self):
        """Show the open chat's AI image allowance (-1 in the selector is no limit) and how many it used."""
        goal = self.goal or {}
        value = (goal.get('limits') or {}).get('ai_images', 0)
        key = -1 if value is None else value
        selector = self.ai_images_selector
        selector.blockSignals(True)
        if selector.findData(key) < 0: selector.addItem('%d AI images' % key, key)
        selector.setCurrentIndex(selector.findData(key)); selector.blockSignals(False)
        used = goal.get('ai_images_used', 0)
        self.ai_images_used.setText('%d used' % used if used else '')
        self.ai_images_used.setToolTip('%d AI images made in this chat' % used)

    def change_ai_images(self, _index):
        if not self.goal or self.busy: return
        value = self.ai_images_selector.currentData()
        limits = self.goal.get('limits') or {}
        self.send({'type': 'set_limits', 'limits': {'minutes': limits.get('minutes', 0), 'passes': limits.get('passes', 0),
                                                    'ai_images': None if value < 0 else value}})

    # ----- reference parts -----------------------------------------------------------
    def start_part(self, reference, kind):
        """Open a copy of the reference in Krita for the artist to select a part (or a crop) with Krita's tools."""
        import shutil
        if self.part_session: return
        if len(self.pending_references) + len(self.attached_references) >= 4:
            self.status.setText('Remove a reference to add a part.'); return
        copy = os.path.join(self.pasted_folder(), 'creative-part-source-' + uuid.uuid4().hex + os.path.splitext(reference['path'])[1])
        shutil.copyfile(reference['path'], copy)
        app = Krita.instance(); window = app.activeWindow()
        previous = window.activeView() if window else None
        doc = app.openDocument(copy)
        if doc is None:
            os.remove(copy); self.status.setText('%s could not open this reference.' % product_name()); return
        if (doc.colorModel(), doc.colorDepth()) != ('RGBA', 'U8'):             # a part is cut from 8-bit RGBA pixels
            doc.setColorSpace('RGBA', 'U8', 'sRGB-elle-V2-srgbtrc.icc')
        if window: window.addView(doc)
        # A part is drawn around with the Freehand Selection Tool: a colour wand grabs look-alike pixels across the image.
        tool = app.action('KisToolSelectOutline' if kind == 'part' else 'KisToolSelectRectangular')
        if tool is not None: tool.trigger()
        name = reference.get('name') or os.path.basename(reference['path'])
        self.part_session = {'reference': reference, 'kind': kind, 'doc': doc, 'copy': copy, 'view': previous, 'window': window, 'name': name}
        self.part_bar_label.setText('Selecting a part of ' + name); self.part_bar.show(); self.part_timer.start()

    def part_name(self, default):
        name, ok = QInputDialog.getText(self, 'Name this part', 'Name', QLineEdit.EchoMode.Normal, default)
        return name.strip()[:60] if ok and name.strip() else None

    def use_part(self):
        session = self.part_session
        if not session: return
        doc, kind = session['doc'], session['kind']
        width, height = doc.width(), doc.height()
        selection = doc.selection()
        bounds = self.selection_bounds(selection, doc)
        if bounds is None:
            self.status.setText('Select the part first.'); return
        pixels = bytes(doc.pixelData(0, 0, width, height))
        if kind == 'part':
            image = part_image(pixels, bytes(selection.pixelData(0, 0, width, height)), width, height)
            bounds, size = opaque_bounds(image, width, height), (width, height)
            if bounds is None:
                self.status.setText('Select the part first.'); return
        else:
            image, bounds = crop_image(pixels, width, height, bounds); size = (bounds[2], bounds[3])
        name = self.part_name('Part of ' + session['name'])
        if not name: return
        from .qt_compat import QImage
        path = os.path.join(self.pasted_folder(), 'creative-reference-' + uuid.uuid4().hex + '.png')
        if not QImage(image, size[0], size[1], size[0] * 4, QImage.Format.Format_ARGB32).save(path):
            self.status.setText('Could not save the part.'); return
        original = session['reference']
        self.close_part()
        self.pending_references.append({'path': path, 'role': 'reference', 'name': '%s (%s)' % (name, kind), 'purpose': original.get('purpose') or 'general',
                                        'notes': '', 'part_of': original['path'], 'part_kind': kind, 'bounds': bounds})
        self.show_references(); self.status.setText("'%s (%s)' is attached. Ask the agent to paint from it." % (name, kind))

    def close_part(self, closed_by_artist=False):
        session, self.part_session = self.part_session, None
        self.part_timer.stop(); self.part_bar.hide()
        if not session: return
        if not closed_by_artist:
            session['doc'].setModified(False); session['doc'].close()
        if session['window'] is not None and session['view'] is not None: session['window'].showView(session['view'])
        try: os.remove(session['copy'])
        except OSError: pass

    def check_part_session(self):
        """The artist closed the temporary document themselves: as if Cancel was pressed."""
        if self.part_session and self.part_session['doc'] not in Krita.instance().documents():
            self.close_part(closed_by_artist=True)

    # ----- protected areas ---------------------------------------------------------
    def protection_document(self):
        return Krita.instance().activeDocument()

    def open_protection(self, modal=True):
        doc = self.protection_document()
        if doc is None:
            self.status.setText('Open your painting to protect parts of it.'); return None
        dialog = ProtectionDialog(self, self.protection._protect_list(doc), self.feature_rows())
        if modal: dialog.exec()
        else: dialog.show()
        return dialog

    def answer_shapes_model(self, choice, item=None):
        self.auto_approve.cancel()
        for button in self.shapes_model_controls: button.setEnabled(False)
        self.send({'type': 'shapes_model', 'action': choice})
        if choice == 'decline' and item is not None:
            # A decline lasts for the chat (the companion refuses shapes at once); this lets the artist allow them again.
            button = QPushButton('Ask again'); button.setObjectName('questionChoice')
            button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setToolTip('Allow the shape model download to be offered again in this chat.')
            button.clicked.connect(lambda _checked=False: (button.setEnabled(False), self.send({'type': 'shapes_model', 'action': 'enable'})))
            item['layout'].addWidget(button); self.shapes_allow_button = button

    def answer_protection(self, area, choice):
        self.auto_approve.cancel()
        for button in self.protection_controls: button.setEnabled(False)
        self.show_protection(area, False)
        doc = self.protection_document()
        if choice == 'keep':
            self.protection._protect_set_state(doc, area['id'], 'active'); self.status.setText("'%s' is protected." % area['name'])
        elif choice == 'discard' and self.agent_writing_reason(doc) is None:
            self.protection._protect_remove(doc, area['id'])
        elif choice == 'discard' or not self.adjust_protection(area):
            if choice == 'discard': self.status.setText(self.PAUSE_REASON)
            for button in self.protection_controls: button.setEnabled(True)       # refused for now: the artist can answer again
            self.show_protection(area, True)
        self.refresh_features()

    def feature_rows(self):
        """The painting's features for the Protected section (name, kind, protected); empty without our Krita, without a
        painting, or when the document is gone."""
        try:
            doc = self.protection_document()
            return self.features._feature_list(doc, brief=True) if doc is not None else []
        except (AttributeError, RuntimeError, ReferenceError):
            return []

    def pending_areas(self, doc):
        """The protected areas (protection.py) for the Protected section, besides the features: those the agent proposed
        and the artist has not answered yet, and those kept. Locked layers are not listed there."""
        try:
            return [a for a in self.protection._protect_list(doc) if a.get('by') != 'automatic' and a.get('state') in ('pending', 'active')]
        except (AttributeError, RuntimeError, ReferenceError, ValueError):
            return []

    def feature_wait_reason(self, doc=None):
        """Why the artist's protection controls must wait now, or None. Krita's own state decides, not only the panel's
        busy flag: Keep and Undo of a move, and any bridge command, write inside an agent move without a busy event, and
        a change made then would join the agent's undo step."""
        if self.busy or self.feature_changing or self.protection_editing is not None:
            return self.PAUSE_REASON
        return self.agent_writing_reason(doc)

    PAUSE_REASON = 'Pause to change protection: the agent is working on the painting.'

    def agent_writing_reason(self, doc=None):
        """The pause reason while the agent is writing right now (a bridge command, an open agent move), else None: a
        node removed or a selection set then would join the agent's undo step."""
        if command_executing.is_set():
            return self.PAUSE_REASON
        try:
            doc = doc if doc is not None else self.protection_document()
            if doc is not None and any(bool(getattr(doc, check)()) for check in ('agentMoveOpen', 'agentActive') if hasattr(doc, check)):
                return self.PAUSE_REASON
        except (AttributeError, RuntimeError, ReferenceError):
            pass
        return None

    def refresh_features(self):
        """Follow the painting's features in the Protected section: on every canvas poll, document change, new chat and
        protection change. One features() read of names, kinds and flags (no pixels); the rows are rebuilt only when names
        or kinds change, otherwise the boxes are set in place. Hidden with no painting and in stock Krita."""
        if not hasattr(self, 'features_section') or not hasattr(self, 'features'): return
        try:
            doc = self.protection_document()
            ready = doc is not None and self.features._feature_ready(doc)
            rows = self.features._feature_list(doc, brief=True) if ready else None
        except (AttributeError, RuntimeError, ReferenceError):
            rows = None                                   # a closed or deleted document
        if rows is None:
            self.features_section.structure = None; self.features_section.hide(); return
        self.features_section.present(rows, self.pending_areas(doc))
        self.features_section.set_locked(self.feature_wait_reason(doc) is not None)

    def toggle_feature(self, name, value):
        """The artist ticked or unticked a feature's box: the only caller of set_feature_protected. Refused while the agent
        works; the boxes are locked during the call, so a second click (or a nested event loop) cannot re-enter. The list
        then shows what Krita has: a refused change puts the box back."""
        reason = self.feature_wait_reason()
        if reason is not None:
            self.status.setText(reason); self.refresh_features(); return False
        focused = QApplication.focusWidget()              # locking disables the box, which drops its focus
        self.feature_changing = True; self.features_section.set_locked(True)
        try:
            done = self.set_feature_protected(name, value)
        finally:
            self.feature_changing = False
            self.refresh_features()
            if focused is not None and any(r['check'] is focused for r in self.features_section.rows) and focused.isEnabled():
                focused.setFocus()
        if done and any(r['name'] == name and r['protected'] != bool(value) for r in self.feature_rows()):
            self.status.setText("%s did not change the protection of '%s': it was busy. Please try again." % (product_name(), name))
            done = False
        return done

    def set_feature_protected(self, name, value):
        """The artist protects or unprotects a feature from the panel. Only the panel calls this: the companion has no
        operation for it (feature_guard.PANEL_ONLY), so a model cannot lift a protection."""
        doc = self.protection_document()
        if doc is None:
            self.status.setText('Open your painting to protect parts of it.'); return False
        try:
            done = self.features._feature_set_protected(doc, name, value)
        except ValueError as error:
            self.status.setText(str(error)); return False
        if not done:
            self.status.setText("%s did not change the protection of '%s': it was busy. Please try again." % (product_name(), name)); return False
        self.status.setText("'%s' is %s." % (name, 'protected' if value else 'no longer protected'))
        return True

    def remove_protection(self, area):
        self.protection._protect_remove(self.protection_document(), area['id'])
        self.status.setText("'%s' is no longer protected." % area['name'])

    def show_protection(self, area, on):
        """Krita shows the active selection mask's area over the painting; Show makes the area's mask active."""
        doc = self.protection_document()
        mask = doc is not None and hasattr(self.protection, '_protect_mask_node') and self.protection._protect_mask_node(doc, area['id'])
        if not mask: return
        if on:
            self.protection_shown = self.protection_shown or doc.activeNode(); doc.setActiveNode(mask)
        elif self.protection_shown is not None:
            doc.setActiveNode(self.protection_shown); self.protection_shown = None

    def ask_to_protect(self):
        if self.mode_selector.currentData() != 'agent':
            self.mode_selector.setCurrentIndex(self.mode_selector.findData('agent'))
        self.prompt.setPlainText('Protect '); self.prompt.moveCursor(QTextCursor.MoveOperation.End); self.prompt.setFocus()

    @staticmethod
    def selection_bounds(selection, doc):
        if selection is None: return None
        left, top = max(0, selection.x()), max(0, selection.y())
        right, bottom = min(doc.width(), selection.x() + selection.width()), min(doc.height(), selection.y() + selection.height())
        return None if right <= left or bottom <= top else [left, top, right - left, bottom - top]

    def protect_selection(self):
        doc = self.protection_document()
        reason = self.feature_wait_reason(doc)
        if reason is not None and doc is not None:
            self.status.setText(reason); return
        selection = doc.selection() if doc is not None else None
        bounds = self.selection_bounds(selection, doc) if doc is not None else None
        if bounds is None:
            self.status.setText('Select an area first.'); return
        count = len([a for a in self.protection._protect_list(doc) if a.get('by') != 'automatic']) + 1
        name, ok = QInputDialog.getText(self, 'Protect this area', 'Name', QLineEdit.EchoMode.Normal, 'Protected %d' % count)
        if not ok or not name.strip(): return
        if self.features._feature_ready(doc):
            # Our Krita: the selection becomes a protected feature ("Buildings"), which Krita itself keeps the agent out of.
            try:
                self.features._feature_add_protected(doc, name, selection)
            except ValueError as error:
                self.status.setText(str(error)); return
            self.refresh_features()
            self.status.setText("'%s' is protected." % name.strip()[:60]); return
        self.protection._protect_add(doc, selection.duplicate(), name.strip()[:60], 'artist', 'active', bounds)
        self.status.setText("'%s' is protected." % name.strip()[:60])

    def paint_protection(self, area=None):
        """Paint over it: the area's mask becomes the active node and the brush paints protection, the eraser
        removes it. Done keeps it; Cancel restores it (or drops a new one)."""
        doc = self.protection_document()
        if doc is None:
            self.status.setText('Open your painting to protect parts of it.'); return
        if area is None:
            count = len([a for a in self.protection._protect_list(doc) if a.get('by') != 'automatic']) + 1
            name, ok = QInputDialog.getText(self, 'Paint protection', 'Name', QLineEdit.EchoMode.Normal, 'Protected %d' % count)
            if not ok or not name.strip(): return
            area = self.protection._protect_add(doc, Selection(), name.strip()[:60], 'artist', 'active', [0, 0, 0, 0]); saved = None
        else:
            saved = self.protection._protect_mask_node(doc, area['id']).selection().duplicate()
        self.protection_editing = {'area': area, 'saved': saved, 'node': doc.activeNode()}
        self.protection._protect_editing(doc, True)              # Krita will not paint a mask in a locked group
        doc.setActiveNode(self.protection._protect_mask_node(doc, area['id']))
        brush = Krita.instance().action('KritaShape/KisToolBrush')
        if brush is not None: brush.trigger()
        self.protection_tool_button.hide()
        self.protection_bar_label.setText("Painting protection: '%s'" % area['name']); self.protection_bar.show(); self.update_controls()

    FREEHAND, MAGNETIC = 'KisToolSelectOutline', 'KisToolSelectMagnetic'

    def adjust_protection(self, area):
        """Adjust a proposed area with a selection tool, not the brush: the artist's own selection is set aside, the area
        becomes the document selection and the Freehand Selection Tool is chosen. Done writes the selection back into the
        area; Cancel leaves it. Never while the agent paints. Returns whether the adjustment started."""
        doc = self.protection_document()
        if doc is None:
            self.status.setText('Open your painting to protect parts of it.'); return False
        reason = self.feature_wait_reason(doc)
        if reason is not None:
            self.status.setText(reason); return False
        mask = self.protection._protect_mask_node(doc, area['id'])
        if not mask:
            self.status.setText('That protected area is no longer in this painting.'); return False
        earlier = doc.selection()
        self.protection_editing = {'area': area, 'mode': 'select', 'earlier': earlier.duplicate() if earlier is not None else None,
                                   'node': None, 'doc': doc}
        artist_editing.set()                                     # the bridge holds agent writes until Done or Cancel
        doc.setSelection(mask.selection().duplicate())
        self.protection_bar_label.setText("Adjusting '%s': change the selection, then Done" % area['name'])
        self.protection_tool_button.show(); self.choose_protection_tool(self.FREEHAND)
        self.protection_bar.show(); self.update_controls()
        return True

    def choose_protection_tool(self, name):
        self.protection_tool = name
        tool = Krita.instance().action(name)
        if tool is not None: tool.trigger()
        magnetic = name == self.MAGNETIC
        self.protection_tool_button.setText('Freehand' if magnetic else 'Magnetic')
        self.protection_tool_button.setToolTip('Back to the Freehand Selection Tool' if magnetic else
                                               'Magnetic Selection Tool: it snaps to edges, good for skylines')

    def switch_protection_tool(self):
        self.choose_protection_tool(self.FREEHAND if getattr(self, 'protection_tool', None) == self.MAGNETIC else self.MAGNETIC)

    def finish_protection(self, keep):
        editing = self.protection_editing
        if editing is not None and editing.get('mode') == 'select':
            return self.finish_adjusting(keep)
        self.protection_editing = None
        self.protection_bar.hide()
        if editing is None: return
        doc, area = self.protection_document(), editing['area']
        self.protection._protect_editing(doc, False)
        mask = self.protection._protect_mask_node(doc, area['id'])
        bounds = self.selection_bounds(mask.selection(), doc) if mask is not None and keep else None
        if keep and bounds:
            self.protection._protect_set_bounds(doc, area['id'], bounds)
            self.protection._protect_set_state(doc, area['id'], 'active'); self.status.setText("'%s' is protected." % area['name'])
        elif editing['saved'] is None or (keep and not bounds):
            self.protection._protect_remove(doc, area['id']); self.status.setText('Nothing was protected.')
        else:
            mask.setSelection(editing['saved'])
        if editing['node'] is not None: doc.setActiveNode(editing['node'])
        self.update_controls()

    def finish_adjusting(self, keep):
        """Done or Cancel of Adjust. Done with nothing selected keeps the bar open."""
        editing = self.protection_editing
        area, doc = editing['area'], self.adjusted_document(editing['doc'])
        if doc is None:                                          # the painting was closed: nothing to write back or restore
            self.end_adjusting(); return
        reason = self.agent_writing_reason(doc)
        if reason is not None:
            self.status.setText(reason); return
        if keep:
            selection = doc.selection()
            bounds = self.selection_bounds(selection, doc)
            if bounds is None:
                self.status.setText('Select an area first.'); return
            mask = self.protection._protect_mask_node(doc, area['id'])
            if mask:
                mask.setSelection(selection.duplicate())
                self.protection._protect_set_bounds(doc, area['id'], bounds)
                self.protection._protect_set_state(doc, area['id'], 'active'); self.status.setText("'%s' is protected." % area['name'])
            else:
                self.status.setText('That protected area is no longer in this painting.')
        doc.setSelection(editing['earlier'])                     # the artist's own selection back, or none
        self.end_adjusting()

    def end_adjusting(self):
        self.protection_editing = None; artist_editing.clear()
        self.protection_bar.hide(); self.protection_tool_button.hide()
        self.refresh_features(); self.update_controls()

    @staticmethod
    def adjusted_document(doc):
        """The painting the adjustment began on, if Krita still has it open (never whichever is active now)."""
        try:
            return next((open_doc for open_doc in Krita.instance().documents() if open_doc is doc or open_doc == doc), None)
        except (AttributeError, RuntimeError, ReferenceError):
            return None

    def update_controls(self):
        running = bool(self.process and self.process.state() == QProcess.ProcessState.Running)
        self.ai_images_selector.setVisible(bool(self.goal)); self.ai_images_used.setVisible(bool(self.goal))
        self.ai_images_selector.setEnabled(running and bool(self.goal) and not self.busy)
        self.ai_images_selector.setToolTip('Pause to change AI images for this chat.' if self.busy else
                                           'How many AI-generated images the painter may use in this chat. 0 paints everything by hand.')
        self.protect_button.setEnabled(not self.busy and self.protection_editing is None)
        self.protect_button.setToolTip('Pause to change protection' if self.busy else 'Protected areas: what the agent must never change')
        self.features_section.set_locked(self.feature_wait_reason() is not None)
        if hasattr(self, 'paint_only'): self.paint_only.update_controls()
        for control in (self.source, self.name, self.experiment): control.setEnabled(not self.study_active and not self.busy)
        self.model.setEnabled(not self.busy and not self.pending_model_change)
        self.provider_filter.setEnabled(not self.busy and not self.pending_model_change)
        self.reasoning_selector.setEnabled(running and not self.busy)
        for widget in self.setting_widgets.values(): widget.setEnabled(running and not self.busy)
        self.filter.setEnabled(not self.busy)
        self.connect_button.setEnabled(running and not self.busy)
        sizing = self.source.currentData() == 'new' or (self.source.currentData() == 'current' and self.chat_mode == 'agent' and not self.has_open_document())
        self.canvas_width.setEnabled(not self.study_active and sizing)
        self.canvas_height.setEnabled(not self.study_active and sizing)
        self.map_button.setVisible(self.experiment.currentData() == 'guided')
        self.send_button.setToolTip('Send direction · current brush action settles first' if self.busy else 'Send message · Enter')
        self.send_button.setEnabled(running and bool((self.accepted_model if self.study_active else None) or self.model.currentData()) and not self.pending_model_change and (not self.busy or self.study_active))
        self.stop_button.setEnabled(self.busy); self.stop_button.setVisible(self.busy)
        self.reference_button.setEnabled(running and not self.busy)
        self.plan_button.setEnabled(bool(self.goal))
        self.end_button.setEnabled(running and not self.busy)
        self.history_button.setEnabled(running and not self.busy)
        self.restore_button.setEnabled(running and not self.busy)
        self.canvas_refresh.setEnabled(running and not self.busy)
        self.canvas_remove.setEnabled(not self.busy)
        self.use_canvas_button.setEnabled(running and not self.busy)
        self.region_remove.setEnabled(not self.busy)
        for button in getattr(self, 'reference_remove_buttons', []): button.setEnabled(not self.busy)
        canvas_file = (self.canvas_context.get('canvas') or {}).get('filename')
        self.folder_button.setEnabled(bool(self.saved_path or canvas_file or getattr(self, 'paintings_directory', None)))
        self.folder_button.setText('Locate file' if self.painting_target.get('missing') else 'Show file' if self.saved_path or canvas_file else 'Show folder')
        self.folder_button.setToolTip('Reveal the painting in Finder' if self.saved_path or canvas_file else 'Open your painting folder')
        can_start = bool(not self.painting_target.get('missing') and not self.uncertain_operations and self.goal and not self.goal.get('target_needs_review') and not self.goal.get('question') and self.goal.get('brief') and self.goal.get('status') in ('draft', 'ready', 'paused', 'limited', 'needs_input'))
        self.execute_button.setVisible(can_start and not self.busy)
        self.execute_button.setEnabled(running and can_start and not self.busy and getattr(self, 'bridge_compatible', True))
        self.execute_button.setText('Resume' if self.goal and self.goal.get('status') == 'paused' else 'Start painting')
        idle_plan = bool(self.goal and self.goal.get('brief') and not self.busy and self.plan_steps.current_index() is None
                         and self.goal.get('status') in ('draft', 'ready', 'paused', 'limited', 'needs_input'))
        self.card_start.setVisible(can_start and idle_plan)
        reason = '' if can_start or not idle_plan else self.start_blocked_reason()
        self.card_reason.setText(reason); self.card_reason.setVisible(bool(reason))
        self.card_start.setEnabled(self.execute_button.isEnabled()); self.card_start.setText(self.execute_button.text())
        self.card_start.setAccessibleName('Resume painting the plan' if self.execute_button.text() == 'Resume' else 'Start painting the plan')
        self.compare_button.setVisible(bool(self.goal and self.goal.get('passes', 0)))
        placeholders = {'ask': 'Ask about your painting…', 'plan': 'Describe the result and what to preserve…', 'agent': 'Describe the next move, or type a correction to refine the last one…', 'autopilot': 'Give a direction for the next painting step…'}
        self.prompt.setPlaceholderText('Answer here, or choose an option above…' if self.goal and self.goal.get('question') else
                                       'Describe the painting you want, e.g. a winter street in Moscow at night…' if self.invites_painting() and self.chat_mode == 'agent' else placeholders[self.chat_mode])
        if self.chat_mode in ('ask', 'plan'): self.save_status.setText(self.chat_mode.capitalize() + ' · read only')
        elif self.saved_at and self.saved_path: self.save_status.setText('Saved ' + self.saved_at + ' · ' + os.path.basename(self.saved_path))
        elif self.saved_path: self.save_status.setText('Painting · ' + os.path.basename(self.saved_path))
        else: self.save_status.setText('Agent · ready')

    def open_output(self):
        if self.painting_target.get('missing') or (self.saved_path and not os.path.isfile(self.saved_path)):
            if self.relink_id: self.locate_missing_painting()
            else: self.status.setText('The painting has moved. Open History and use Locate painting to reconnect it.')
            return
        canvas_file = (self.canvas_context.get('canvas') or {}).get('filename')
        file_path = self.saved_path or canvas_file
        if file_path and os.path.isfile(file_path):
            QProcess.startDetached('/usr/bin/open', ['-R', file_path])
        elif getattr(self, 'paintings_directory', None):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.paintings_directory))



def register_creative_docker():
    Krita.instance().addDockWidgetFactory(DockWidgetFactory(
        'krita_creative_agent', scoped(DockWidgetFactoryBase, 'DockPosition', 'DockRight'), CreativeAgentDocker))
