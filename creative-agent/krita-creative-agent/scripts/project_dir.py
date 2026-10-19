"""The artwork project folder, independent of where this checkout lives (see project-dir.mjs)."""
import json
import os
from pathlib import Path

INSTALLED_CONFIG = Path.home() / 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json'


def project_dir():
    if os.environ.get('KRITA_PROJECT_DIR'):
        return Path(os.environ['KRITA_PROJECT_DIR']).expanduser().resolve()
    try:
        root = json.loads(INSTALLED_CONFIG.read_text()).get('project_root')
    except FileNotFoundError:
        root = None
    if not root:
        raise SystemExit('Set KRITA_PROJECT_DIR to your artwork folder, or install the plugin first.')
    return Path(root)
