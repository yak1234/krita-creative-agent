"""Load an installed build into the running Krita, so most updates need no restart.

`reload` re-imports the creative operation modules from the installed plugin folder
and copies their fresh methods onto the live plugin object's classes, then restarts
the companion so it runs the newly installed release. Not reloaded: the HTTP bridge
(`__init__.py`), the panel (`creative_docker.py`) and this module's caller; a change
to those still needs a Krita restart, and `restart_required` says so.

The companion restart ends the companion's process, which ends its chat, so it is
deferred while a painting session is active; the plugin code reloads either way.
"""
import importlib
import os
import re
import sys

PACKAGE = __name__.rsplit('.', 1)[0]
# The bridge, the panel and process-wide state (crash hooks, the managed Node, the command queue, document identities).
NOT_RELOADED = ('__init__', 'creative_docker', 'command_queue', 'creative_document_identity', 'crash_diagnostics', 'node_runtime')
IMPORT = re.compile(r'^\s*from \.(\w*) import ([\w, ()]+)', re.M)


def modules(folder=None):
    """Every plugin module this reload may refresh, each after the modules it imports from: read from the files,
    so a new module (a new mixin, a helper) is never left behind by a hand-written list."""
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    names = sorted(f[:-3] for f in os.listdir(folder) if f.endswith('.py'))
    names = [n for n in names if n not in NOT_RELOADED and n != __name__.rsplit('.', 1)[-1]]
    imports = {}
    for name in names:
        with open(os.path.join(folder, name + '.py'), encoding='utf-8') as stream:
            found = set()
            for module, imported in IMPORT.findall(stream.read()):
                found.update([module] if module else [part.strip(' ()') for part in imported.split(',')])
            imports[name] = sorted(found & set(names))
    ordered, visiting = [], set()
    def visit(name):
        if name in ordered or name in visiting:
            return
        visiting.add(name)
        for dependency in imports[name]:
            visit(dependency)
        visiting.discard(name)
        ordered.append(name)
    for name in names:
        visit(name)
    return tuple(ordered)


def _fresh_attributes(fresh):
    """Every attribute `fresh` resolves from this package's classes, subclasses last so they win."""
    merged = {}
    for cls in reversed(fresh.__mro__):
        if cls.__module__.startswith(PACKAGE + '.') or cls.__module__ == PACKAGE:
            merged.update({k: v for k, v in vars(cls).items() if not (k.startswith('__') and k.endswith('__'))})
    return merged


def _rebind(instance, reloaded):
    """Copy fresh methods onto the live classes. Mixins added since start come along too."""
    swapped = 0
    for cls in type(instance).__mro__:
        short = cls.__module__.rsplit('.', 1)[-1]
        if short not in reloaded:
            continue
        fresh = getattr(sys.modules[cls.__module__], cls.__name__, None)
        if fresh is None or fresh is cls:
            continue
        for name, value in _fresh_attributes(fresh).items():
            setattr(cls, name, value)
            swapped += 1
    return swapped


def _restart_companion(instance):
    from krita import Krita
    from .qt_compat import QProcess, QTimer
    from .creative_docker import CreativeAgentDocker
    if getattr(instance, '_creative_session', None):
        return 'deferred: a painting session is active; start a new conversation, then reload again'
    states = []
    for dock in Krita.instance().dockers():
        if not isinstance(dock, CreativeAgentDocker):
            continue
        process = dock.process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            states.append('not running')
            continue
        if dock.busy or dock.study_active:
            states.append('deferred: the panel is busy')
            continue
        process.finished.connect(lambda *_args, panel=dock: QTimer.singleShot(300, panel.start_companion))
        dock.send({'type': 'shutdown'})
        states.append('restarting')
    return ', '.join(states) or 'no panel open'


def reload(instance, companion=True):
    """Reload this module first, so a new module list or rebind rule applies at once."""
    fresh = importlib.reload(sys.modules[__name__])
    return fresh._reload(instance, companion)


def _reload(instance, companion):
    reloaded = []
    importlib.invalidate_caches()                # new module files, such as a new mixin, are found
    for short in modules():
        module = sys.modules.get(PACKAGE + '.' + short)
        if module is not None:
            importlib.reload(module)
            reloaded.append(short)
    swapped = _rebind(instance, set(reloaded))
    instance._craft_manifest_cache = None        # the manifest format may have changed
    build = getattr(sys.modules.get(PACKAGE + '.creative_tools'), 'CREATIVE_BUILD', {})
    return {'status': 'ok', 'reloaded': reloaded, 'methods': swapped, 'build_id': build.get('build_id'),
            'companion': _restart_companion(instance) if companion else 'not requested',
            'restart_required': 'only when __init__.py or creative_docker.py changed (%s)' % ', '.join(NOT_RELOADED)}
