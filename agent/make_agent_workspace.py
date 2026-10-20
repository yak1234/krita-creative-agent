#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate krita/data/workspaces/Photoshop_Agent.kws: the workspace a new KritaAgent install starts in (task 3.3).

A Krita workspace is a QMainWindow::saveState() blob keyed by dock object names. This script builds a stand-in window with
the real docker ids (a dock id is the docker factory id, see KoDockRegistry), arranges them, and saves the state with Qt 6.
Layout (Photoshop habit, agent beside the usual panels):

    toolbox | canvas | colour+tool options (tabs) / brush presets+overview+history (tabs) / layers | Creative Agent

The three stock toolbars share one row at the top. Run with Qt 6:

    QT_QPA_PLATFORM=offscreen uv run --with pyqt6 python agent/make_agent_workspace.py

Re-run it only to change the layout; creative-agent/krita-creative-agent/tests/test_new_install_defaults.py checks the
committed file (and that this script reproduces it).
"""
import base64
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'krita/data/workspaces/Photoshop_Agent.kws'
KRITARC = ROOT / 'krita/data/kritarc'
DEFAULT = ROOT / 'krita/data/workspaces/Default.kws'
NAME = 'Photoshop Agent'
AGENT = 'krita_creative_agent'
# Dockers a new install keeps hidden. Qt restoreState() leaves a docker that is not in the state where it was created (visible,
# right area), so every docker id Krita ships is listed: the stock Default workspace's ids and the ids kritarc knows.
def hidden_dockers():
    names = {n for n in state_names(state_of(DEFAULT)) if n not in TOOLBARS}
    names |= set(re.findall(r'^\[(?:krita|MainWindow)\]\[DockWidget (.+)\]$', KRITARC.read_text(), re.M))
    return sorted(names | set(python_docker_ids()))


def python_docker_ids():
    """Every docker id the bundled Python plugins register (plugins/python, DockWidgetFactory("id", ...) or a DOCKER_ID constant)."""
    ids = set()
    for path in (ROOT / 'plugins/python').rglob('*.py'):
        text = path.read_text(errors='replace')
        if 'DockWidgetFactory(' not in text:
            continue
        ids |= set(re.findall(r'DockWidgetFactory\(\s*["\']([^"\'{}]+)["\']', text))
        if re.search(r'DockWidgetFactory\(\s*DOCKER_ID', text):
            ids |= set(re.findall(r'^DOCKER_ID\s*=\s*["\']([^"\'{}]+)["\']', text, re.M))
    return sorted(ids)


_APP = None
TOOLBARS = ('mainToolBar', 'editToolBar', 'BrushesAndStuff')


def state_names(blob):
    """Object names stored in a QMainWindow state (QString: uint32 byte length, then UTF-16BE)."""
    names = []
    for match in re.finditer(rb'(?:\x00[\x20-\x7e])+', blob):
        run = match.group(0)
        for skip in range(len(run) // 2):
            sub, at = run[2 * skip:], match.start() + 2 * skip
            if at >= 4 and struct.unpack('>I', blob[at - 4:at])[0] == len(sub):
                names.append(sub.replace(b'\x00', b'').decode())
                break
    return names


def state_of(path):
    text = Path(path).read_text()
    return base64.b64decode(re.search(r'<state><!\[CDATA\[(.*?)\]\]', text, re.S).group(1))


def build_state():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QToolBar
    global _APP
    _APP = app = QApplication.instance() or QApplication([])   # kept alive: other tests in one process may need it
    window = QMainWindow()
    window.resize(1700, 1000)
    window.setCentralWidget(QLabel('canvas'))
    for name in TOOLBARS:                            # one row, as in the stock layout
        bar = QToolBar(name)
        bar.setObjectName(name)
        window.addToolBar(bar)
    docks = {}
    shown = ('ToolBox', 'ColorSelectorNg', 'sharedtooldocker', 'PaletteDocker', 'PresetDocker', 'OverviewDocker', 'History',
             'KisLayerBox', AGENT)
    for name, title in (('ToolBox', 'Toolbox'), ('ColorSelectorNg', 'Advanced Color Selector'),
                        ('sharedtooldocker', 'Tool Options'), ('PaletteDocker', 'Palette'), ('PresetDocker', 'Brush Presets'),
                        ('OverviewDocker', 'Overview'), ('History', 'Undo History'), ('KisLayerBox', 'Layers'),
                        (AGENT, 'Creative Agent')):
        dock = QDockWidget(title)
        dock.setObjectName(name)
        dock.setWidget(QLabel(name))
        docks[name] = dock

    right, left = Qt.DockWidgetArea.RightDockWidgetArea, Qt.DockWidgetArea.LeftDockWidgetArea
    horizontal, vertical = Qt.Orientation.Horizontal, Qt.Orientation.Vertical
    d = docks
    window.addDockWidget(left, d['ToolBox'])
    # Right area: [panels column | agent column]. One item first, so the area adopts the horizontal split.
    window.addDockWidget(right, d['ColorSelectorNg'])
    window.splitDockWidget(d['ColorSelectorNg'], d[AGENT], horizontal)
    window.splitDockWidget(d['ColorSelectorNg'], d['PresetDocker'], vertical)
    window.splitDockWidget(d['PresetDocker'], d['KisLayerBox'], vertical)
    window.tabifyDockWidget(d['ColorSelectorNg'], d['sharedtooldocker'])
    window.tabifyDockWidget(d['ColorSelectorNg'], d['PaletteDocker'])
    window.tabifyDockWidget(d['PresetDocker'], d['OverviewDocker'])
    window.tabifyDockWidget(d['PresetDocker'], d['History'])
    for name in hidden_dockers():
        if name not in d:
            dock = QDockWidget(name)
            dock.setObjectName(name)
            dock.setWidget(QLabel(name))
            window.addDockWidget(right, dock)
            dock.hide()
            d[name] = dock
    for name in shown:
        d[name].show()
    d['ColorSelectorNg'].raise_()
    d['PresetDocker'].raise_()
    window.show()
    app.processEvents()
    window.resizeDocks([d['ColorSelectorNg'], d['PresetDocker'], d['KisLayerBox']], [300, 280, 400], vertical)
    window.resizeDocks([d['ColorSelectorNg'], d[AGENT]], [300, 440], horizontal)
    app.processEvents()
    blob = bytes(window.saveState())
    window.close()
    return blob


def main():
    blob = build_state()
    if '--check' in sys.argv:                       # reproducibility: the committed blob is what this script builds
        same = blob == state_of(OUT) and base64.b64encode(blob).decode() in KRITARC.read_text()
        print('same' if same else 'DIFFERENT: run agent/make_agent_workspace.py')
        sys.exit(0 if same else 1)
    head = '<Workspace version="1" name="%s">\n    <state><![CDATA[%s]]></state>\n</Workspace>\n'
    OUT.write_text(head % (NAME, base64.b64encode(blob).decode()))
    text = KRITARC.read_text()
    state_line = 'State=' + base64.b64encode(blob).decode()
    text, count = re.subn(r'(?m)^(\[MainWindow\]\n)State=.*$', lambda m: m.group(1) + state_line, text)
    if count != 1:
        sys.exit('kritarc has no single [MainWindow] State line')
    KRITARC.write_text(text)
    print('wrote', OUT, len(blob), 'bytes;', sorted(state_names(blob)))


if __name__ == '__main__':
    main()
