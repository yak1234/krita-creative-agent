"""Document-bound creative sessions on the existing native Krita painting engine.

A paint pass paints, on the fork (our Krita), as one libkis stroke job: Node.paintStrokes(strokes, options, selection)
-> StrokeJob, clipped by the region's stage mask, with full pen input, polled on the GUI thread so Krita keeps
responding, Stop as job.cancel() (_creative_stroke_job). On stock Krita 5.3.3 (frozen) it paints through the native
helper's paint_strokes when Krita loaded it, else stroke by stroke through the Python API (_creative_stock_strokes).
"""
import contextlib
import hashlib
import json
import os
import re
import time
import uuid
import krita as krita_module
from krita import Krita, Selection
from .qt_compat import Qt, QCoreApplication
from .creative_validation import fields, numeric, text, color, validate_pass, painted_share, PEN_INPUTS
from .creative_document_identity import document_id, open_documents
from .layer_craft import LayerCraft
from .region_craft import RegionCraft
from .filters import FilterCraft
from .colorize import ColorizeCraft
from .transform_craft import TransformCraft
from .canvas_view import CanvasView
from .comic import ComicCraft
from .merge_craft import MergeCraft
from .native_craft import NativeCraft, compact_actions
from .protection import ProtectionCraft, PANEL_ONLY as PROTECTION_PANEL_ONLY
from .script_steps import one_step
from .feature_guard import EXPRESSION_LIMIT, FeatureCraft, PANEL_ONLY as FEATURE_PANEL_ONLY, agent_writing, reject_privileged
from .material_stamp import MaterialCraft, RESOURCE_PREFIX as STAMP_RESOURCE_PREFIX
from .guide_craft import GuideCraft
from .tool_craft import ToolCraft, OPERATIONS as TOOL_OPERATIONS, PASS_TITLES as TOOL_TITLES, tool_functions_available
from .journal_store import Journal
from . import painting_weight
from . import canvas_projection
from . import vendor
import importlib
import threading
# command_queue is not hot-reloaded: after a plugin-only reload into a Krita started with an older
# copy, the flag is missing until Krita restarts, and Stop works as before (between actions).
stop_requested = getattr(importlib.import_module('.command_queue', __package__), 'stop_requested', None) or threading.Event()

# During a stroke pass, Krita handles clicks this often (Stop, the window) instead of freezing for the whole pass.
RESPONSIVE_SECONDS = 0.2
# The fork's stroke job (Node.paintStrokes): each wait on Krita's GUI thread lasts at most this long (it returns as soon
# as the job ends), with Qt's events run between waits. A job still painting after JOB_DEADLINE_SECONDS (well past the
# companion's own wait for a pass, so only a stuck job) is cancelled, and one that then does not end is an error.
JOB_POLL_MS = 10
# paint_pass has the bridge's default 120 s (not in LONG_OPERATIONS), so a job is cancelled at 100 s of job time: the result
# is then a definite "stopped after N strokes", not a lost one. After the cancel the job gets CANCEL_GRACE_SECONDS to end.
JOB_DEADLINE_SECONDS = 100
CANCEL_GRACE_SECONDS = 15
# After the artist's Undo ended a job, Krita carries the undo out later, from its event loop once the image is idle: the pass
# waits (running events) this long for it before it records anything.
UNDO_WAIT_SECONDS = 5
_FORK = None


def on_fork():
    """True in our Krita: the Node class has paintStrokes (asked once; a plugin reload starts over)."""
    global _FORK
    if _FORK is None:
        _FORK = hasattr(getattr(krita_module, 'Node', None), 'paintStrokes')
    return _FORK
# Krita refuses a save while it is already saving (its autosave of a large painting can take minutes): wait this long
# between tries, letting Krita run, before a checkpoint fails.
SAVE_RETRY_SECONDS = (10, 20, 30)


def wait_for_krita(seconds):
    """Let Krita run its own events (a save in progress) for `seconds`, without returning to the caller."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)

# A full .kra save after every action dominated small actions. Painting actions save every CHECKPOINT_SECONDS of
# painting, and always on `checkpoint`, `end` and pass review (the artist's Keep and Undo); in between they only
# re-read the canvas. Saving every 8 actions too cost 26% of all time in runs 5-8 on merged New Moscow (12 saves of
# 5-6.5 s, every 8 reference chunks), so a crash now loses at most CHECKPOINT_SECONDS of the agent's painting.
# With the native helper (protocol 6) a checkpoint saves in the background (agent_accel.save_in_background): Krita copies
# the image and writes the copy off its main thread, so the next action need not wait. Its result reports the job and
# claims no save (`save_job` running, `checkpoint_deferred`); the next checkpoint waits for it and confirms it, as do
# later results and `save_status`. Actions after the copy stay unsaved. Without the helper, before the painting is its
# own file, and at the end of a chat, the save is synchronous as before.
# Pass kinds that add a new agent layer or mask.
NEW_CONTRIBUTIONS = ('paint_pass', 'guide', 'create_layer', 'fill_region', 'apply_filter', 'colorize_flats', 'transform_layer', 'comic_page', 'letter', 'merge_passes', 'krita_action', 'clone_layer', 'split_by_color', 'stamp') + TOOL_OPERATIONS
CHECKPOINT_SECONDS = 180
# Operations that paint as one fork stroke job: waited on by the job itself, never by Document.waitForDone.
STROKE_JOBS = ('paint_pass', 'draw_guide')
# A painting copy a test or tool-choice run made: benchmark-runs/<stamp>-tool-choice[-no-guards]/<scenario>-<run>/…/<painting>.kra
# (or an image copy: .png, .jpg),
# the copy itself or a file a session saved deeper in that run folder (close_benchmark_copy, test_keep_protection).
BENCHMARK_COPY = re.compile(r'[/\\]benchmark-runs[/\\]\d{12}-tool-choice(-no-guards)?[/\\][a-z0-9-]+-\d+[/\\](?:[^/\\]+[/\\])*[^/\\]+\.(?:kra|png|jpe?g)$')
VIEW_JPEG_QUALITY = 90
# Long side of every image the models see: Claude and GPT downscale larger images to about this,
# so it is the most detail a view can carry. 1024 showed a 6000 px canvas at 1/6 scale, too small
# to see the dab texture the painter was meant to fix.
VIEW_SIDE = 1568

try:
    with open(os.path.join(os.path.dirname(__file__), 'build-info.json')) as _build_stream:
        CREATIVE_BUILD = json.load(_build_stream)
except (OSError, ValueError):
    CREATIVE_BUILD = {'build_id': 'development-unverified'}


def merge_pass_record_error(result, error):
    """Append a pass-record failure to an existing error instead of replacing it."""
    note = 'Pass record could not be saved: ' + str(error)
    return {'status': 'partial', 'error_code': result.get('error_code') or 'partial_change',
            'error': result['error'] + ' (' + note + ')' if result.get('error') else note}


class CreativeTools(LayerCraft, RegionCraft, FilterCraft, ColorizeCraft, TransformCraft, CanvasView, ComicCraft, MergeCraft, ProtectionCraft, FeatureCraft, NativeCraft, MaterialCraft, ToolCraft, GuideCraft):
    def cmd_creative(self, request):
        fields(request, ('operation', 'session_id', 'operation_id', 'params'), ('operation', 'params'))
        operation = request['operation']
        params = request['params']
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        # Protection is the artist's: no model-supplied option lifts it, and the panel's feature calls are not operations.
        reject_privileged(params)
        if operation in FEATURE_PANEL_ONLY:
            raise ValueError('Only the artist can change a feature or its protection in the panel.')
        if operation == 'health':
            return {'status': 'ok', 'creative_version': '1.0.0', 'protocol_version': 2, 'build': CREATIVE_BUILD, 'krita_version': Krita.instance().version(),
                    'capabilities': self._creative_adapter_capabilities(), 'native_paths': True, 'session_active': bool(getattr(self, '_creative_session', None)),
                    'krita_actions': len(self._native_actions(Krita.instance().version())), 'python_packages': vendor.versions(),
                    'fork_tools': tool_functions_available(), 'guides_view': True}
        if operation == 'context':
            fields(params, ('document_id',))
            doc = self._creative_document(params.get('document_id'))
            active = self.get_active_document()
            app = Krita.instance()
            documents = open_documents()
            return dict(self._creative_metadata(doc), status='ok',
                        active_document_id=document_id(active) if active else None,
                        documents=[self._creative_metadata(d) for d in documents])
        if operation == 'decode_reference':
            from .creative_reference import decode_reference
            return decode_reference(params)
        if operation == 'trace_reference':
            # Guided trace's own reduced decode (from_reference); decode_reference keeps the reference tools' limits.
            from .creative_reference import trace_reference
            return trace_reference(params)
        if operation == 'model_image':
            from .creative_reference import model_image
            return model_image(params)
        if operation == 'jpeg_copy':
            from .creative_reference import jpeg_copy
            return jpeg_copy(params)
        if operation == 'begin':
            return self._creative_begin(request)
        if operation == 'tidy_painting':
            # Ad hoc: remove the agent's hidden leftovers from the open painting (native_craft.py). Never during a chat.
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before tidying the painting.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open the painting to tidy in Krita first.')
            return self._native_tidy(doc, params)
        if operation == 'merge_agent_work':
            # Ad hoc: merge the agent's kept groups in the open painting into a few layers (native_craft.py). Never during a chat.
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before merging the painting.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open the painting to merge in Krita first.')
            return self._native_merge_agent(doc, params)
        if operation == 'close_benchmark_copy':
            # Development (scripts/evaluate-tool-choice.ts): close, unsaved, the painting copy a tool-choice run
            # opened. Never during a chat, and only a file inside a "-tool-choice" run folder.
            fields(params, ('path',), ('path',))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before closing the benchmark copy.')
            path = os.path.realpath(text(params['path'], 'path', 2000))
            if not BENCHMARK_COPY.search(path):
                raise ValueError('Only a painting copy inside a -tool-choice benchmark run folder can be closed.')
            for doc in open_documents():
                if doc.fileName() and os.path.realpath(doc.fileName()) == path:
                    doc.setModified(False)
                    return {'status': 'ok', 'closed': bool(doc.close())}
            return {'status': 'ok', 'closed': False}
        if operation == 'accel_probe':
            # Development: time the full recomposite against the native helper's area recomposite (agent_accel.py)
            # on the open painting. Never during a chat.
            fields(params, ('rect',), ('rect',))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            rect = params['rect']
            if not isinstance(rect, list) or len(rect) != 4:
                raise ValueError('rect is [x, y, w, h].')
            from . import agent_accel
            return dict(agent_accel.probe(doc, [int(numeric(v, 'rect', -100000, 100000)) for v in rect]), status='ok')
        if operation == 'observe_probe':
            # Development: one observation of the open painting with its parts timed, as a canvas step reports them.
            # Never during a chat; its preview goes to a temporary folder that is removed.
            fields(params, ('layers',))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            import shutil, tempfile
            folder = tempfile.mkdtemp(prefix='creative-observe-probe-')
            # `layers` painted layers, as a chat adds one per pass, removed after: what grows with a session.
            added = []
            for index in range(int(numeric(params.get('layers', 0), 'layers', 0, 500))):
                node = doc.createNode('Creative Agent · probe %d' % index, 'paintlayer')
                node.setPixelData(bytes([40, 80, 160, 255]) * (200 * 200), (index * 97) % max(1, doc.width() - 200), (index * 53) % max(1, doc.height() - 200), 200, 200)
                doc.rootNode().addChildNode(node, None); added.append(node)
            doc.waitForDone()
            try:
                session = {'output': folder, 'document_id': 'probe', 'passes': [], 'layers': set()}
                started = time.monotonic()
                self._creative_observe(doc, session)
                return {'status': 'ok', 'ms': dict(session.get('observe_ms', {}), total=int((time.monotonic() - started) * 1000)),
                        'canvas': [doc.width(), doc.height()]}
            finally:
                for node in added:
                    node.remove()
                shutil.rmtree(folder, ignore_errors=True)
        if operation == 'stroke_probe':
            # Development: where a chunk of strokes spends its time today (agent_accel.stroke_probe), on a temporary
            # layer of the open painting that is removed after. Never during a chat.
            fields(params, ('count', 'size', 'compare', 'preset'))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            from . import agent_accel
            count, size = int(numeric(params.get('count', 256), 'count', 1, 2000)), float(numeric(params.get('size', 40), 'size', 1, 1000))
            if params.get('compare'):
                return dict(agent_accel.stroke_compare(doc, self.get_active_view(), self, count, size, params.get('preset')), status='ok')
            return dict(agent_accel.stroke_probe(doc, self.get_active_view(), self, count, size), status='ok')
        if operation == 'select_probe':
            # Development: the same seed or colour steps through the Python path and the native helper
            # (agent_accel.select_compare) on the open painting: time and pixel agreement. Changes nothing. Never during a chat.
            # full: the whole select instead, built in one native call where the steps allow it (native "whole", the
            # default) or a selection per step (native "steps"), to compare the two.
            fields(params, ('steps', 'count', 'tolerance', 'full', 'native'))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            native = params.get('native', 'whole')
            if native not in ('whole', 'steps') or ('native' in params and not params.get('full')):
                raise ValueError('native is "whole" or "steps", with full: true.')
            if params.get('full'):
                # The whole select call as a chat runs it (build, bounds, save, edges), saved to a temporary folder.
                import shutil, tempfile
                from . import agent_accel
                folder = tempfile.mkdtemp(prefix='creative-select-probe-')
                try:
                    started = time.monotonic()
                    done = self._region_select(doc, {'output': folder}, {'name': 'probe', 'steps': params['steps']}, native == 'whole')
                    result = {'status': 'ok', 'timings_ms': dict(done['timings_ms'], total=int((time.monotonic() - started) * 1000)),
                              'selected_pixels': done['selected_pixels'], 'bounds': done['bounds'], 'built_with': self._region_built_with}
                    if self._region_built_with == 'whole':
                        result['native_ms'] = agent_accel.build_timings()  # the one call's phases inside the helper
                    return result
                finally:
                    shutil.rmtree(folder, ignore_errors=True)
            steps = params.get('steps')
            if steps is not None:
                if not isinstance(steps, list) or any(not isinstance(step, dict) or ('seed' in step) == ('color' in step)
                                                      or set(step) - {'seed', 'color', 'tolerance', 'bounds'} for step in steps):
                    raise ValueError('steps are seed or color steps: {seed or color, tolerance?, bounds?}.')
                self._region_validate_steps(doc, {}, steps)
            from . import agent_accel
            return dict(agent_accel.select_compare(doc, self, steps, int(numeric(params.get('count', 8), 'count', 1, 64)),
                                                   int(numeric(params.get('tolerance', 24), 'tolerance', 0, 255))), status='ok')
        if operation == 'pressure_probe':
            # Development: one stroke through the native helper at full pressure and tapered (agent_accel.pressure_compare),
            # on temporary layers of the open painting that are removed after. Never during a chat.
            fields(params, ('preset', 'size', 'image'))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            from . import agent_accel
            return dict(agent_accel.pressure_compare(doc, self, params.get('preset'), float(numeric(params.get('size', 60), 'size', 1, 1000)),
                                                     params.get('image')), status='ok')
        if operation == 'pen_probe':
            # Development: one stroke through the native helper without a pen input and one with it changing along the
            # stroke (agent_accel.pen_compare: input pressure, tilt, rotation, speed or time_ms, with a preset that reads
            # it by default), on temporary layers of the open painting that are removed after. Never during a chat.
            fields(params, ('input', 'preset', 'size', 'image'), ('input',))
            if params['input'] not in PEN_INPUTS:
                raise ValueError('input is one of: ' + ', '.join(PEN_INPUTS))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            from . import agent_accel
            return dict(agent_accel.pen_compare(doc, self, params['input'], params.get('preset'),
                                                float(numeric(params.get('size', 60), 'size', 1, 1000)), params.get('image')), status='ok')
        if operation == 'save_probe':
            # Development: the checkpoint's synchronous save against the native helper's background save of the open
            # painting to its own file (agent_accel.save_compare), each timed, with a timer on Krita's main thread
            # measuring how long each held it. Rewrites the painting's file with its current state. Never during a chat.
            fields(params, ('rounds', 'tick_ms'))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before probing.')
            doc = self.get_active_document()
            if doc is None:
                raise ValueError('Open a painting to probe in Krita first.')
            rounds = numeric(params.get('rounds', 1), 'rounds', 1, 5)
            tick_ms = numeric(params.get('tick_ms', 10), 'tick_ms', 1, 1000)
            from . import agent_accel
            return dict(agent_accel.save_compare(doc, self, int(rounds), int(tick_ms)), status='ok')
        if operation == 'close_document':
            # Ad hoc: close a saved painting so Krita frees its undo history (after a merge), to reopen it with
            # open_file. Never during a chat, and never a document with unsaved changes.
            fields(params, ('path',), ('path',))
            if getattr(self, '_creative_session', None):
                raise ValueError('A painting session is open: end it before closing a document.')
            path = os.path.realpath(text(params['path'], 'path', 2000))
            for doc in open_documents():
                if doc.fileName() and os.path.realpath(doc.fileName()) == path:
                    if doc.modified():
                        raise ValueError('This document has unsaved changes: save it in Krita before closing it.')
                    return {'status': 'ok', 'closed': bool(doc.close())}
            return {'status': 'ok', 'closed': False}
        if operation == 'test_keep_protection':
            # Development (the test driver's creative_test_protect): keep a proposed protected area, as the artist's
            # panel click would. Test copies only: the panel stays the only way to protect areas of a real painting.
            fields(params, ('name',), ('name',))
            name = text(params['name'], 'name', 60).strip()
            doc = self.get_active_document()
            path = os.path.realpath(doc.fileName()) if doc is not None and doc.fileName() else ''
            if not BENCHMARK_COPY.search(path):
                raise ValueError('Only test copies in benchmark-runs/ can be kept from a test.')
            pending = [a for a in self._protect_list(doc) if a.get('name') == name and a.get('state') == 'pending']
            if not pending:
                raise ValueError("No proposed area named '%s'." % name)
            for area in pending:
                self._protect_set_state(doc, area['id'], 'active')
            return {'status': 'ok', 'kept': len(pending)}
        if operation == 'krita_actions_audit':
            # Throwaway document, Krita's own undo stack: never while the agent holds a painting.
            if getattr(self, '_creative_session', None):
                raise ValueError('The action audit runs only with no painting session open.')
            return self._native_audit(params)
        if operation == 'import_journal':
            # One chat's JSON journal into its journal database, outside a painting session.
            fields(params, ('output_dir',), ('output_dir',))
            destination = self._creative_output(request)
            if getattr(self, '_creative_session', None) and self._creative_session.get('output') == destination:
                return {'status': 'ok', 'operations': len(self._creative_session['operations']), 'in_use': True}
            chat = {'output': destination, 'operations': {}}
            try:
                self._creative_load_operations(chat)
                self._creative_passes(chat)
                return {'status': 'ok', 'operations': len(chat['operations']), 'passes': len(chat['passes'])}
            finally:
                if chat.get('journal'):
                    chat['journal'].close()
        if operation == 'peek':
            # Ask/Plan may inspect the current canvas without creating, saving,
            # selecting, or taking ownership of a painting document.
            # refresh=False skips the full recomposite: for a close-up of a canvas just observed,
            # whose revision the caller compares, so a stale projection cannot pass unnoticed.
            fields(params, ('output_dir', 'document_id', 'region', 'refresh', 'guides'), ('output_dir',))
            if not isinstance(params.get('refresh', True), bool):
                raise ValueError('refresh must be boolean')
            guides = self._creative_guides_flag(params)
            destination = self._creative_output(request)
            doc = self._creative_document(params.get('document_id'))
            if doc is None:
                return {'status': 'ok', 'state': 'none', 'message': 'No canvas is open.'}
            return self._creative_observe(doc, {'output': destination, 'layers': set(),
                'document_id': document_id(doc), 'projection_fresh': not params.get('refresh', True)}, params.get('region'), **guides)
        if operation == 'sample_colors':
            fields(params, ('document_id', 'points'), ('points',))
            points = params['points']
            if not isinstance(points, list) or not 1 <= len(points) <= 16:
                raise ValueError('Choose 1–16 document pixel positions to sample.')
            doc = self._creative_document(params.get('document_id'))
            if doc is None:
                raise ValueError('Attach an open canvas before sampling its colours.')
            for point in points:
                if (not isinstance(point, list) or len(point) != 2 or
                        any(isinstance(n, bool) or not isinstance(n, int) for n in point) or
                        not 0 <= point[0] < doc.width() or not 0 <= point[1] < doc.height()):
                    raise ValueError('Sample positions must be integer pixels inside the canvas.')
            doc.refreshProjection(); doc.waitForDone()
            projection = doc.projection(0, 0, doc.width(), doc.height())
            if projection.isNull():
                raise RuntimeError('Could not read canvas colours.')
            # The paint, never a guide line over it (guide_craft.py): rebuilt around the sampled points only.
            sampled, guides_note = projection, None
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            near = [max(0, min(xs) - 8), max(0, min(ys) - 8)]
            near += [min(doc.width(), max(xs) + 9) - near[0], min(doc.height(), max(ys) + 9) - near[1]]
            owner = getattr(self, '_creative_session', None)
            try:
                clean, guides_note = self._guide_unguided(doc, projection, near, owner if owner and owner.get('document_id') == document_id(doc) else None)
                sampled = clean if clean is not None else projection
            except Exception as error:
                guides_note = 'The guide lines could not be left out of these samples: ' + str(error)
            samples = []
            for x, y in points:
                pixel = sampled.pixelColor(x, y)
                samples.append({'position': [x, y], 'hex': '#%02x%02x%02x' % (pixel.red(), pixel.green(), pixel.blue()),
                                'rgba': [pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()]})
            return {'status': 'ok', 'document_id': document_id(doc),
                    'revision': self._creative_revision(doc, projection), 'samples': samples,
                    'source': 'Rendered canvas projection, 8-bit RGBA. These are observed colours, not an invented palette.',
                    **({'guides_note': guides_note} if guides_note else {})}
        if operation == 'list_passes':
            fields(params, ('output_dir',))
            session = getattr(self, '_creative_session', None)
            if session and request.get('session_id') == session['id']:
                return {'status': 'ok', 'passes': self._creative_passes(session)}
            destination = self._creative_output(request)
            return {'status': 'ok', 'passes': self._creative_passes({'output': destination})}
        session = getattr(self, '_creative_session', None)
        if not session or request.get('session_id') != session['id']:
            raise ValueError('This painting session does not own the document')
        if operation == 'end':
            fields(params, ())
            # Deferred actions are saved before the study is released.
            flushed = None
            if session.get('unsaved_operations') or session.get('save_job'):
                active = self.get_active_document()
                if active is not None and document_id(active) == session['document_id']:
                    try:
                        # Waits for a background save, then saves what is left synchronously before releasing the study.
                        flushed = self._creative_checkpoint(active, session, changed=None, wait=True).get('checkpoint')
                    except Exception as error:
                        return {'error': 'Could not save the last actions: ' + str(error), 'error_code': 'checkpoint_failed'}
            if session.get('guides_prior') is not None:
                try:
                    self._guides_restore(self._creative_document(session['document_id']), session)
                except ValueError:
                    pass                                 # the painting was closed; its guides went with it
            if session.get('autosave_prior') is not None:
                try:
                    self._creative_document(session['document_id']).setAutosave(session['autosave_prior'])
                except (ValueError, AttributeError):
                    pass                                 # the painting was closed: a reopened one autosaves as usual
            if session.get('journal'):
                session['journal'].close()
            self._creative_session = None
            return {'status': 'ok', **({'checkpoint': flushed} if flushed else {})}
        doc = self.get_active_document()
        if doc is None or document_id(doc) != session['document_id']:
            return {'error': 'The active document changed. Return to this study before continuing.', 'error_code': 'document_changed'}
        if doc.width() != session['width'] or doc.height() != session['height']:
            return {'error': 'Canvas dimensions changed. Review the plan before continuing.', 'error_code': 'canvas_changed'}
        if operation == 'checkpoint':
            fields(params, ())
            return dict(self._creative_checkpoint(doc, session, changed=None), status='ok')
        if operation == 'save_status':
            # Confirm a background checkpoint without waiting: saved is true once no agent action is unsaved.
            fields(params, ())
            confirmed = self._creative_settle_save(session)
            pending = session.get('save_job')
            result = {'status': 'ok', 'saved': bool(session.get('saved_once')) and not pending and not session.get('unsaved_operations'),
                      'unsaved_operations': session.get('unsaved_operations', 0)}
            if pending or confirmed:
                result['save_job'] = {'job': pending['job'], 'state': 'running'} if pending else confirmed
            return result
        if operation == 'operation_status':
            fields(params, ('id',), ('id',))
            previous = session['operations'].get(text(params['id'], 'id', 100))
            counts = {}
            for entry in session.get('passes', []):
                key = entry.get('stage_id')
                counts[key] = counts.get(key, 0) + 1
            return {'status': 'ok', 'found': previous is not None,
                    'result': self._creative_replay(doc, session, previous[1]) if previous else None,
                    'committed_operation_count': self._creative_committed_count(session),
                    'committed_stage_counts': counts}
        if operation == 'observe':
            fields(params, ('region', 'guides'))
            # guides: false is the painting as Luna and the review judge it, without the agent's guide lines.
            observation = self._feature_observation(doc, self._creative_observe(doc, session, params.get('region'), **self._creative_guides_flag(params)))
            # Looks also list seams baked into the painting, found once a chat (on the whole canvas), as candidates for
            # the companion's Luna check (seams.py). Every look carries them: the studio looks before the painter does,
            # and a painter may only ever look at regions (run 15). The agent's own seams are select's open_edges.
            if 'seam_candidates' not in session:
                session['seam_candidates'] = self._creative_seam_candidates(doc, session)
            if session['seam_candidates']:
                observation['seam_candidates'] = session['seam_candidates']
            return observation
        if operation == 'features_list':
            # What the painting's features are called, and which the artist protected (read only).
            fields(params, ())
            return {'status': 'ok', 'features': self._feature_list(doc)}
        if operation == 'select':
            # Saved to the study folder; not a canvas change, so no pass or checkpoint.
            return self._region_select(doc, session, params)
        if operation == 'make_material':
            # Tips saved to the study folder (material_stamp.py); not a canvas change, like select.
            return self._material_make(doc, session, params)
        if operation == 'krita_action' and self._native_action_kind(params) == 'selection':
            # A selection action saves a named selection: no pass or checkpoint, like select.
            return self._native_select_action(doc, session, params)
        if operation == 'tidy_kept':
            # The kept stage's hidden leftovers go (native_craft.py): hidden, so not a canvas change and no pass.
            return self._native_tidy_kept(doc, session, params)
        if operation == 'split_by_color' and not params.get('as_layers'):
            # Saved selections only: no pass or checkpoint, like select.
            return self._native_split(doc, session, params)
        if operation in ('propose_protection', 'protection_list') + PROTECTION_PANEL_ONLY:
            # A mask in the painting, not paint: no pass or checkpoint. Keeping and removing are panel-only.
            return self._protect_operation(doc, session, operation, params)
        if operation == 'guides':
            # A view aid, not paint: no pass or checkpoint; restored when the chat ends.
            return self._guides_set(doc, session, params)
        if operation == 'finish_guide':
            # Hides an element's guide layers (guide_craft.py): not a pass; the guide passes follow their state.
            return self._guide_finish(doc, session, params)
        if operation == 'hide_guides':
            # Every guide hidden in one step: a finished run or the end of a chat leaves no guide in the painting.
            return self._guide_hide_all(doc, session, params)
        if operation == 'view_options':
            # While Luna checks the painting, every look also saves the view without guide lines (unguided_path).
            return self._guide_view_options(session, params)
        if operation == 'list_brushes':
            fields(params, ('filter',))
            # The whole library: the companion adds a measured card to every preset (brush-catalog.json).
            # The stamp's own tips and presets (stamp_names.py, one per variant) are hidden before the limit applies.
            result = self.cmd_list_brushes({'filter': params.get('filter', ''), 'limit': 500, 'exclude_prefix': STAMP_RESOURCE_PREFIX + ' '})
            return result
        if operation == 'capabilities':
            result = self._craft_capabilities(doc, params)
            result['capabilities']['krita_actions'] = compact_actions(self._native_actions(result['capabilities'].get('krita_version')))
            return result
        if operation == 'painting_tool_help':
            fields(params, ())
            return self._creative_tool_help()
        if operation == 'reconcile':
            fields(params, ('expected_revision',), ('expected_revision',))
            if params['expected_revision'] != self._creative_revision(doc):
                return {'error': 'Inspect the fresh canvas before acknowledging recovery.', 'error_code': 'canvas_changed'}
            for operation_key in self._creative_unresolved(session):
                session['operations'][operation_key][1]['reconciled'] = True
            self._creative_store_operations(session)
            return dict(self._creative_observe(doc, session), unresolved_operations=[],
                        committed_operation_count=self._creative_committed_count(session))
        if operation not in ('paint_pass', 'adjust_layer', 'painting_toolbox', 'review_pass', 'create_layer', 'set_layer', 'fill_region', 'apply_filter', 'colorize_flats', 'transform_layer', 'comic_page', 'letter', 'merge_passes', 'krita_action', 'clone_layer', 'split_by_color', 'stamp', 'draw_guide') + TOOL_OPERATIONS:
            raise ValueError('Unsupported creative operation')
        self._guide_refuse_target(doc, session, operation, params)
        operation_id = text(request.get('operation_id'), 'operation_id', 100)
        fingerprint = hashlib.sha256(json.dumps([operation, {k: v for k, v in params.items() if k != 'expected_revision'}], sort_keys=True).encode()).hexdigest()
        previous = session['operations'].get(operation_id)
        if previous:
            if previous[0] != fingerprint:
                raise ValueError('An operation ID cannot be reused with different painting instructions')
            return self._creative_replay(doc, session, previous[1])
        # The artist pressed Stop: nothing new starts, even if the companion has not heard yet.
        if stop_requested.is_set() and operation != 'review_pass':
            return {'status': 'stopped', 'error': 'Stopped by the artist before this action ran; nothing was painted.',
                    'error_code': 'stopped_by_artist'}
        unresolved = self._creative_unresolved(session)
        if unresolved:
            return {'error': 'An earlier operation has an uncertain result. Inspect the painting and acknowledge recovery before continuing.',
                    'error_code': 'outcome_unknown', 'unresolved_operations': unresolved}
        self._creative_validate_save_target(doc, session)
        expected = params.get('expected_revision')
        if expected and expected != self._creative_revision(doc):
            return {'error': 'The painting changed since the last observation. Inspect the fresh canvas before continuing.',
                    'error_code': 'canvas_changed'}
        # How long each step takes, in the result (not shown to the model): finds what is slow on a large painting.
        # A step that observed the canvas also reports the observation's parts, as step.part (outside the total).
        timings, clock = {}, [time.monotonic()]
        session.pop('observe_ms', None)
        def lap(step):
            now = time.monotonic(); timings[step] = int((now - clock[0]) * 1000); clock[0] = now
            for part, ms in session.pop('observe_ms', {}).items():
                timings[step + '.' + part] = ms
        # Validate the whole pass before any layer or brush changes.
        shape_limit = None                               # inside_shape's selection, decoded once: validated here, painted with below
        if operation == 'paint_pass':
            validate_pass(params, doc.width(), doc.height(), Krita.instance().resources('preset'))
            if 'inside_shape' in params:
                # An element's shape limits this one pass as the job's own selection (element-shapes 1.5).
                if not on_fork():
                    raise ValueError('A pass inside a shape needs our Krita (the fork).')
                if params.get('region') or 'selection' in params:
                    raise ValueError('Give a pass one limit: a region, a selection or a shape.')
                shape_limit = self._region_shape_selection(doc, session, params['inside_shape'])
            if 'selection' in params:
                if not on_fork():
                    raise ValueError('A pass limited to a selection or feature needs our Krita (the fork).')
                if params.get('region'):
                    raise ValueError('Give a pass a region or a selection (a saved name or feature), not both.')
                self._region_check_named(doc, session, text(params['selection'], 'selection', EXPRESSION_LIMIT))
            if params.get('smudge_overlay'):
                self._creative_validate_smudge_overlay(params['preset'], 'smudge_rate' in params)
            if params.get('continue_layer_id'):
                if params.get('blend_mode') or params.get('clip_to'):
                    raise ValueError('blend_mode and clip_to make a new layer; leave out continue_layer_id.')
                self._creative_validate_continuation(doc, session, params)
            elif params.get('blend_mode') or params.get('clip_to'):
                self._craft_validate_create(doc, session, self._creative_pass_layer(params))
        elif operation == 'adjust_layer':
            fields(params, ('layer_id', 'opacity', 'visible', 'expected_revision', 'stage_id', 'region'), ('layer_id',))
            if 'opacity' in params:
                numeric(params['opacity'], 'opacity', 0, 1)
            if 'visible' in params and not isinstance(params['visible'], bool):
                raise ValueError('visible must be boolean')
            if not any(key in params for key in ('opacity', 'visible')):
                raise ValueError('Supply opacity or visible')
            self._creative_validate_adjustment(doc, session, params)
        elif operation == 'painting_toolbox':
            self._creative_validate_toolbox(doc, params)
        elif operation == 'create_layer':
            self._craft_validate_create(doc, session, params)
        elif operation == 'set_layer':
            self._craft_validate_set(doc, session, params)
        elif operation == 'fill_region':
            self._region_validate_fill(doc, session, params)
        elif operation == 'apply_filter':
            self._filter_validate(doc, session, params)
        elif operation == 'colorize_flats':
            self._colorize_validate(doc, session, params)
        elif operation == 'transform_layer':
            self._transform_validate(doc, session, params)
        elif operation == 'comic_page':
            self._comic_validate_page(doc, session, params)
        elif operation == 'letter':
            self._comic_validate_letter(doc, session, params)
        elif operation == 'merge_passes':
            self._merge_validate(doc, session, params)
        elif operation == 'krita_action':
            self._native_validate_action(doc, session, params)
        elif operation == 'clone_layer':
            self._native_validate_clone(doc, session, params)
        elif operation == 'split_by_color':
            self._native_validate_split(doc, session, params)
        elif operation == 'stamp':
            self._stamp_validate(doc, session, params)
        elif operation == 'draw_guide':
            if not on_fork():
                raise ValueError('Guides need our Krita (the fork), which paints them on a layer of their own.')
            self._guide_validate(doc, session, params)
        elif operation in TOOL_OPERATIONS:
            self._tool_validate(doc, session, operation, params)
        else:
            return self._protect_review(doc, session, params, lambda: self._creative_review(doc, session, params, operation_id, fingerprint))
        if operation in ('paint_pass', 'create_layer', 'fill_region', 'apply_filter') + TOOL_OPERATIONS:
            self._comic_validate_scope(doc, session, operation, params)
        self._protect_refuse(doc, session, operation, params)
        lap('validate')
        # A continuation batch starts where the last one on its layer ended: reuse that image
        # instead of re-rendering the whole canvas (reference jobs send hundreds of batches).
        continued = operation == 'paint_pass' and params.get('continue_layer_id')
        before = ({'image_path': next((e.get('after_path') for e in reversed(session['passes'])
                                       if e.get('layer_id') == params['continue_layer_id']), None)}
                  if continued else self._creative_observe(doc, session))
        lap('before')
        protected = self._protect_capture(doc, session, operation, params)
        lap('protect_capture')
        prior_node = doc.activeNode() if hasattr(doc, 'activeNode') else None
        prior = None
        if operation == 'adjust_layer':
            prior = self._creative_layer_state(self._creative_node(doc, params['layer_id']), doc)
        # Persist intent before the first mutation. A crash leaves an uncertain
        # outcome that must be inspected, never an invitation to repeat strokes.
        session.pop('projection_fresh', None)
        session['operations'][operation_id] = (fingerprint, {
            'status': 'partial', 'error': 'This operation was interrupted. Inspect the current painting before continuing.',
            'error_code': 'outcome_unknown'})
        self._creative_store_operations(session, operation_id)
        result = {'status': 'ok'}
        smudge_restore, smudge_preset = False, None
        session['operation_id'] = operation_id
        self._view_message(doc, params.get('name') or params.get('filter') or operation.replace('_', ' '))
        # The call's writes are the agent's: Krita keeps the raw ones (pixel data, filters, paste) out of protected features.
        # Each writing call is one agent move too, so Krita's record of what it kept out starts fresh with the call.
        writing = contextlib.ExitStack()
        writing.enter_context(agent_writing(doc))
        self._feature_clipped, kept_names = [], []
        self._feature_move_ours = False
        if self._feature_ready(doc):
            fresh = not doc.agentMoveOpen()
            writing.enter_context(one_step(doc, params.get('name') or operation.replace('_', ' ')))
            self._feature_move_ours = fresh and doc.agentMoveOpen()      # a move this call began has a fresh record
        try:
            if operation == 'painting_toolbox':
                result.update(self._creative_toolbox(doc, session, params))
            elif operation == 'create_layer':
                result.update(self._craft_create(doc, session, params))
            elif operation == 'set_layer':
                prior = self._craft_set(doc, session, params)
            elif operation == 'fill_region':
                result.update(self._region_fill(doc, session, params))
            elif operation == 'apply_filter':
                result.update(self._filter_apply(doc, session, params))
            elif operation == 'colorize_flats':
                result.update(self._colorize_apply(doc, session, params))
            elif operation == 'transform_layer':
                result.update(self._transform_apply(doc, session, params))
            elif operation == 'comic_page':
                result.update(self._comic_page(doc, session, params))
            elif operation == 'letter':
                result.update(self._comic_letter(doc, session, params))
            elif operation == 'merge_passes':
                result.update(self._merge_apply(doc, session, params))
            elif operation == 'krita_action':
                result.update(self._native_action(doc, session, params))
            elif operation == 'clone_layer':
                result.update(self._native_clone(doc, session, params))
            elif operation == 'split_by_color':
                result.update(self._native_split(doc, session, params))
            elif operation == 'stamp':
                result.update(self._stamp_apply(doc, session, params, result))
            elif operation == 'draw_guide':
                result.update(self._guide_draw(doc, session, params, result))
            elif operation in TOOL_OPERATIONS:
                result.update(self._tool_apply(doc, session, operation, params, result))
            elif operation == 'paint_pass':
                # The fork paints a pass as one stroke job (Node.paintStrokes) that takes its preset by name, as saved, and
                # needs no view, so the artist's brush is left alone; smudge overlay mode goes to the job as
                # presetProperties (set on the job's own copy). Stock Krita paints with the view's brush, as before.
                stroke_job = on_fork()
                limit = self._region_load(session, params['selection'], doc) if params.get('selection') else None   # before any layer exists
                if shape_limit is not None:
                    # The job clips to the shape alone; the document's (the artist's) selection is never set, so there is
                    # nothing to restore and no undo step of its own: it lands with the pass.
                    limit = shape_limit
                if not stroke_job:
                    brush = self.cmd_set_brush({'preset': params['preset']})
                    if brush.get('error'):
                        raise RuntimeError(brush['error'])
                    if params.get('smudge_overlay'):
                        # Overlay mode smudges the merged image onto this pass's own empty layer;
                        # without it a smudge brush only mixes that empty layer and paints nothing.
                        # smudge_rate: how far a stroke carries paint (1 drags its first colour the whole way).
                        overlay = self.cmd_configure_brush({'properties': dict({'MergedPaint': True},
                            **({'SmudgeRateValue': params['smudge_rate']} if 'smudge_rate' in params else {}))})
                        if overlay.get('error'):
                            raise RuntimeError(overlay['error'])
                        smudge_restore, smudge_preset = True, overlay.get('preset')
                if params.get('continue_layer_id'):
                    node = self._creative_node(doc, params['continue_layer_id'])
                    if not stroke_job:
                        doc.setActiveNode(node)
                    layer = {'id': params['continue_layer_id']}
                    previous_pass = next(e for e in reversed(session['passes']) if e.get('layer_id') == layer['id'])
                    if previous_pass.get('group_id'):
                        layer['group_id'] = previous_pass['group_id']
                elif params.get('blend_mode') or params.get('clip_to'):
                    # Texture, shadow or light strokes on a craft layer: blended and clipped like create_layer.
                    created = self._craft_create(doc, session, self._creative_pass_layer(params))
                    layer = {'id': created['layer_id'], 'group_id': created.get('group_id')}
                    result['clip'] = created.get('clip')
                else:
                    layer = self._creative_new_layer(doc, session, params)
                if layer.get('error'):
                    raise RuntimeError(layer['error'])
                session['layers'].add(layer['id'])
                result['layer_id'] = layer['id']
                if layer.get('group_id'):
                    result['group_id'] = layer['group_id']
                if stroke_job:
                    # The job targets its node directly and needs no view: the artist's layer is active again as soon as it starts.
                    node = self._creative_node(doc, layer['id'])
                    if not hasattr(node, 'paintStrokes'):
                        raise RuntimeError('This Krita has Node.paintStrokes but this layer does not: nothing was painted.')
                    result.update(self._creative_stroke_job(doc, session, params, node, result, not params.get('continue_layer_id'),
                                                            lambda: prior_node is not None and doc.setActiveNode(prior_node), selection=limit))
                else:
                    self._creative_stock_strokes(doc, session, params, result)
                if result.get('error_code') != 'validation_rejected':
                    session['projection_fresh'] = True   # the observation after this skips a second recomposite
            else:
                selected = self.cmd_select_layer({'id': params['layer_id']})
                if selected.get('error'):
                    raise RuntimeError(selected['error'])
                adjusted = self.cmd_layer_settings({k: v for k, v in params.items() if k in ('opacity', 'visible')})
                if adjusted.get('error'):
                    raise RuntimeError(adjusted['error'])
        except Exception as error:
            result = dict(result, status='partial', error=str(error), error_code='partial_change')
        finally:
            try:
                if operation not in STROKE_JOBS or not on_fork():
                    doc.waitForDone()                      # a write inside the move lands after the call returns (a job has been waited on: never end the artist's strokes)
                if self._feature_call_writes(operation, params) and not (operation in STROKE_JOBS and on_fork()):
                    kept_names = self._feature_kept_out(doc)   # read before the move ends; a fork pass has its job's own names
            except RuntimeError:
                pass                                       # the document was closed during the call
            writing.close()
            if smudge_restore:
                # The artist's preset never keeps overlay mode: the preset the overlay was set on, by name (on the fork only
                # now that the job has ended, since it reads the view's live preset while it paints).
                restored = self.cmd_restore_brush({'preset': smudge_preset} if smudge_preset else {})
                if restored.get('error'):
                    result['brush_restore'] = 'failed: ' + str(restored['error'])
            if prior_node is not None:
                try:
                    doc.setActiveNode(prior_node)
                except RuntimeError:
                    pass                                   # the document was closed during the operation
        lap('apply')
        if operation == 'merge_passes' and result.get('status') == 'ok' and not result.get('merged_layers'):
            session['operations'][operation_id] = (fingerprint, result)     # nothing merged: no canvas change, no checkpoint
            self._creative_store_operations(session, operation_id)
            return result
        if result.get('error_code') == 'validation_rejected':
            result['reconciled'] = True
            session['operations'][operation_id] = (fingerprint, result)
            self._creative_store_operations(session, operation_id)
            return result
        # Nothing the agent does may change a visible pixel inside a protected area.
        result.update(self._protect_enforce(doc, session, operation, params, result, protected, prior))
        if operation not in ('set_layer', 'adjust_layer'):
            self._feature_report(doc, result, kept_names)   # which protected features Krita kept the call's writes out of
        lap('protect_enforce')
        try:
            checkpoint = self._creative_commit_view(doc, session)
            result.update({key: value for key, value in checkpoint.items() if key != 'status'})
        except Exception as error:
            result.update(status='partial', error='Checkpoint failed: ' + str(error), error_code='checkpoint_failed')
        lap('checkpoint')
        guide_record = result.pop('_guide', None)            # what a guide pass records (guide_craft.py), not for the painter
        layer_id = result.get('layer_id', params.get('layer_id'))
        if result.get('contribution_removed'): layer_id = None
        try:
            if layer_id and operation in NEW_CONTRIBUTIONS:
                self._creative_settle_containers(doc, session, self._creative_node(doc, layer_id))
            if layer_id:
                state = self._creative_layer_state(self._creative_node(doc, layer_id), doc)
                entry = dict(id=operation_id, title=params.get('name') or {'fill_region': 'Region fill', 'apply_filter': params.get('filter'), 'colorize_flats': 'Colorized flats', 'transform_layer': 'Transform', 'comic_page': 'Comic page', 'letter': 'Lettering', 'merge_passes': 'Merged passes', 'krita_action': result.get('action_label'), 'clone_layer': 'Clone', 'split_by_color': 'Split by colour', 'stamp': 'Stamp', **TOOL_TITLES}.get(operation) or 'Layer adjustment', kind=operation,
                             stage_id=params.get('stage_id'), region=params.get('region'), layer_id=layer_id,
                             continuation_of=params.get('continue_layer_id'),
                             group_id=result.get('group_id'),
                             projection_region=result.get('projection_region'),
                             projection_feather=result.get('projection_feather'),
                             # The painting's own images, without guide lines: what the pass history and Luna compare.
                             before_path=before.get('unguided_path') or before.get('image_path'),
                             after_path=result.get('unguided_path') or result.get('image_path'),
                             source_layer_id=result.get('source_layer_id'), source_prior=result.get('source_prior'),
                             source_after=result.get('source_after'),
                             clip=result.get('clip'), clip_group_id=result.get('clip_group_id'),
                             layer_type=result.get('layer_type'),
                             filter=result.get('filter'), filter_mode=result.get('mode'), target_id=result.get('target_id'),
                             comic=result.get('comic'), panel=params.get('panel'), merged_pass_ids=result.get('merged_pass_ids'),
                             prior=prior, after=state, strength=state['opacity'] / 255,
                             visible=state['visible'], rejected=False)
                if operation == 'draw_guide':
                    entry.update(kind='guide', element=result.get('element'), title='Guide · ' + str(result.get('element')), **(guide_record or {}))
                session.setdefault('passes', []).append(entry)
                self._creative_store_passes(session)
                result['passes'] = self._creative_passes(session)
        except Exception as error:
            result.update(merge_pass_record_error(result, error))
        # Store partial results too: retrying the same operation never paints twice.
        session['operations'][operation_id] = (fingerprint, self._creative_receipt(result))
        try:
            self._creative_store_operations(session, operation_id)
        except OSError as error:
            result.update(status='partial', error='The recovery record could not be saved: ' + str(error), error_code='partial_change')
        self._creative_progress(session, 'saved' if result['status'] == 'ok' else 'error',
                                self._creative_saved_message(result, 'Painting') if result['status'] == 'ok' else result.get('error', 'Painting paused'))
        lap('record')
        result['timings_ms'] = dict(timings, total=sum(v for k, v in timings.items() if '.' not in k))
        return result

    def _creative_begin(self, request):
        stop_requested.clear()           # a new session starts unstopped
        fields(request['params'], ('mode', 'name', 'width', 'height', 'background', 'output_dir', 'editable_layers', 'painting_path', 'source_document_id', 'expected_revision'),
               ('mode', 'name', 'output_dir'))
        identifier = request.get('session_id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9-]{36}', identifier):
            raise ValueError('Invalid session identifier')
        if getattr(self, '_creative_session', None):
            raise ValueError('Another creative session is active. End it before starting another.')
        p = request['params']
        name = text(p['name'], 'Study name')
        if p['mode'] not in ('new', 'copy', 'resume', 'current'):
            raise ValueError('Choose a new study or a copy of the current document')
        source = self.get_active_document()
        if p.get('source_document_id') and (source is None or document_id(source) != p['source_document_id']):
            raise ValueError('The active painting differs from the plan target. Return to the planned painting before starting.')
        if p.get('expected_revision') and (source is None or self._creative_revision(source) != p['expected_revision']):
            raise ValueError('The source painting changed since planning. Inspect it and review the plan before starting.')
        destination = os.path.realpath(os.path.expanduser(p['output_dir']))
        if not os.path.isdir(destination) or os.path.basename(destination) != identifier:
            raise ValueError('The companion must prepare a unique session output directory')
        painting_path = os.path.realpath(p.get('painting_path', os.path.join(destination, 'painting.kra')))
        if not painting_path.lower().endswith('.kra') or not os.path.isdir(os.path.dirname(painting_path)):
            raise ValueError('Choose a Krita file in an existing painting folder')
        if p['mode'] not in ('resume', 'current') and os.path.exists(painting_path):
            raise ValueError('That painting file already exists. Choose another filename.')
        if p['mode'] == 'new':
            width = numeric(p.get('width', 768), 'width', 128, 8192)
            height = numeric(p.get('height', 1024), 'height', 128, 8192)
            if int(width) != width or int(height) != height:
                raise ValueError('Canvas dimensions must be integers')
            color(p.get('background', '#ece3d4'))
            created = self.cmd_new_canvas({'width': width, 'height': height, 'name': name,
                                          'background': p.get('background', '#ece3d4')})
        elif p['mode'] == 'current':
            if source is None:
                raise ValueError('Open a canvas before starting Agent.')
            if os.path.exists(painting_path) and os.path.realpath(source.fileName()) != painting_path:
                raise ValueError('Choose a new filename for this unsaved canvas.')
            created = {'status': 'ok'}
        elif p['mode'] == 'copy':
            source = self.get_active_document()
            if source is None:
                raise ValueError('Open a document to make a working copy')
            if max(source.width(), source.height()) > 8192:
                raise ValueError('Use a working canvas up to 8192 pixels per side')
            created = self.cmd_duplicate_document({'name': name})
        else:
            source = self.get_active_document()
            if source is None or os.path.realpath(source.fileName()) != painting_path:
                raise ValueError('Open this saved painting in Krita before resuming its conversation.')
            if max(source.width(), source.height()) > 8192:
                raise ValueError('Use a working canvas up to 8192 pixels per side')
            editable = p.get('editable_layers', [])
            if not isinstance(editable, list) or any(not isinstance(item, str) for item in editable):
                raise ValueError('Invalid saved layer list')
            created = {'status': 'ok'}
        if created.get('error'):
            raise RuntimeError(created['error'])
        doc = self.get_active_document()
        if p['mode'] == 'copy' and (doc is None or document_id(doc) == document_id(source)):
            raise RuntimeError('The working copy is not active. No source artwork was changed; select the copy before continuing.')
        session = {'id': identifier, 'document_id': document_id(doc),
                   'output': destination, 'painting_path': painting_path, 'layers': set(), 'operations': {}, 'checkpoint': 0,
                   'width': doc.width(), 'height': doc.height(), 'operation_id': 'begin',
                   'saved_once': p['mode'] == 'resume'}
        self._creative_journal(session)
        if p['mode'] == 'resume':
            session['layers'] = set(p.get('editable_layers', []))
            self._creative_load_operations(session)
        self._creative_passes(session)
        session['layers'].update(e['layer_id'] for e in session['passes'] if e.get('layer_id'))
        # Clip groups the agent made stay live clip targets after a resume.
        session['clip_groups'] = {e['clip_group_id'] for e in session['passes'] if e.get('clip_group_id') and not e.get('rejected')}
        session['layers'].update(session['clip_groups'])
        # Krita's autosave of a large painting holds the image for minutes and stalls the agent, which saves its own
        # checkpoint after every operation: pause it on this painting only, and restore the artist's state at the end.
        if hasattr(doc, 'setAutosave'):
            session['autosave_prior'] = bool(doc.autosave())
            doc.setAutosave(False)
        self._creative_session = session
        try:
            if p['mode'] == 'resume':
                # Binding a conversation is an observation, never a native save.
                return dict(self._creative_observe(doc, session), status='ok', session_id=identifier,
                            passes=self._creative_passes(session), unresolved_operations=self._creative_unresolved(session),
                            committed_operation_count=self._creative_committed_count(session))
            return dict(self._creative_checkpoint(doc, session, changed=False), status='ok', session_id=identifier)
        except Exception as error:
            if p['mode'] == 'resume':
                if session.get('journal'):
                    session['journal'].close()
                if session.get('autosave_prior') is not None:
                    doc.setAutosave(session['autosave_prior'])     # no session: the artist's autosave comes back
                self._creative_session = None
                return {'error': 'Could not inspect this painting: ' + str(error),
                        'error_code': 'observation_failed', 'session_id': identifier}
            return {'error': 'The study was created but its checkpoint failed: ' + str(error),
                    'error_code': 'checkpoint_failed', 'session_id': identifier}

    def _creative_checkpoint(self, doc, session, changed=True, wait=False):
        """Save the painting to its working file and observe it. changed=False is a checkpoint that follows no agent
        change (starting a run): when Krita says the document is unmodified and it is already that file on disk, the
        save is skipped. changed=None (the `checkpoint` and `end` operations): changed when agent actions remain unsaved
        once a background save in progress is confirmed. changed=True: the action just done, not yet counted.
        A background save in progress is waited for and confirmed first: one save at a time. Then, with the native
        helper and the painting already its own file, the save starts in the background and its result claims nothing
        saved (`save_job` running); wait=True, or without the helper, saves synchronously (15-20 s on a large painting)."""
        self._creative_validate_save_target(doc, session)
        confirmed = self._creative_settle_save(session, wait=True)
        extra = 1 if changed is True else 0                # the caller's action, not yet in unsaved_operations
        if changed is None:
            changed = bool(session.get('unsaved_operations'))
        session['checkpoint'] += 1
        path = session.get('painting_path', os.path.join(session['output'], 'painting.kra'))
        # Follow a user-initiated Save As on this same bound document.
        current = doc.fileName() if hasattr(doc, 'fileName') else ''
        if session['checkpoint'] > 1 and current.lower().endswith('.kra'):
            path = os.path.realpath(current)
        session['painting_path'] = path
        report = {}
        if confirmed:
            report['save_job' if confirmed['state'] == 'done' else 'previous_save'] = confirmed
        skipped = not changed and not doc.modified() and current and os.path.realpath(current) == os.path.realpath(path) \
            and os.path.isfile(path)
        if skipped:
            path = os.path.realpath(path); session['painting_path'] = path
        else:
            self._creative_progress(session, 'saving', 'Saving ' + os.path.basename(path))
            doc.waitForDone()
            job = None if wait else self._creative_background_save(doc, path, report)
            if job is not None:
                if 'save_job' in report:
                    report['previous_save'] = report.pop('save_job')   # the confirmed one; save_job is the new one
                covered = session.get('unsaved_operations', 0) + extra
                session['save_job'] = {'job': job, 'operations': covered, 'saved_once': session.get('saved_once')}
                session['unsaved_operations'] = covered
                session['last_saved_at'] = time.monotonic()  # the timed save is this one, unless it fails
                self._creative_progress(session, 'observing', 'Reading the updated canvas')
                return dict(self._creative_observe(doc, session), **report, checkpoint_deferred=True,
                            unsaved_operations=covered, save_job={'job': job, 'state': 'running'},
                            save_number=session['checkpoint'])
            result = self.cmd_save_native({'path': path})
            for pause in SAVE_RETRY_SECONDS:
                if 'saveAs failed' not in str(result.get('error', '')):
                    break
                self._creative_progress(session, 'saving', 'Krita is still saving; trying again')
                wait_for_krita(pause)
                doc.waitForDone()
                result = self.cmd_save_native({'path': path})
            if result.get('error'):
                raise RuntimeError(result['error'])
        session['saved_once'] = True
        session['unsaved_operations'] = 0
        session['last_saved_at'] = time.monotonic()
        self._creative_progress(session, 'observing', 'Reading the updated canvas')
        return dict(self._creative_observe(doc, session), **report, checkpoint=path, save_number=session['checkpoint'],
                    **({'save_skipped': True} if skipped else {}))

    def _creative_background_save(self, doc, path, report):
        """Start the native helper's background save of the painting to `path`, its own file: the job id, or None to
        save synchronously (no protocol-6 helper, the painting is not yet that file, or the helper refused at once,
        which `report` notes: Krita was already saving it, and the synchronous save waits that out)."""
        current = doc.fileName() if hasattr(doc, 'fileName') else ''
        if not current or os.path.realpath(current) != os.path.realpath(path) or not os.path.isfile(path):
            return None
        try:
            from . import agent_accel
        except ImportError:
            return None
        job = agent_accel.save_in_background(current)
        if job is None:
            return None
        status = agent_accel.save_status(job) or {'state': 'failed', 'error': 'No answer from the native helper.'}
        if status.get('state') == 'failed':
            report['background_refused'] = status.get('error') or 'refused'
            return None
        return job

    def _creative_settle_save(self, session, wait=False):
        """Confirm the background save a checkpoint started, if it ended (wait=True: let Krita run until it does).
        Done: the actions it covered are saved; failed: they stay unsaved and the next action saves again. Returns
        {job, state, ms | error} once ended, else None."""
        pending = session.get('save_job')
        if not pending:
            return None
        try:
            from . import agent_accel
            status = agent_accel.wait_for_save(pending['job']) if wait else agent_accel.save_status(pending['job'])
        except ImportError:
            status = None
        status = status or {'state': 'failed', 'error': 'The native helper is no longer loaded.'}
        if status.get('state') == 'running':
            if wait:
                raise RuntimeError('The previous background save is still running.')
            return None
        del session['save_job']
        if status.get('state') == 'done':
            session['saved_once'] = True
            session['unsaved_operations'] = max(0, session.get('unsaved_operations', 0) - pending['operations'])
            return {'job': pending['job'], 'state': 'done', 'ms': status.get('ms')}
        session['saved_once'] = pending.get('saved_once')
        session['last_saved_at'] = 0                         # save again at the next action
        return {'job': pending['job'], 'state': 'failed', 'error': status.get('error') or 'The save failed.'}

    def _creative_commit_view(self, doc, session):
        # Save when due; otherwise only re-read the canvas and count the unsaved action. A background save in progress
        # is the timed save: its end is reported here when seen.
        confirmed = self._creative_settle_save(session)
        report = {('save_job' if confirmed['state'] == 'done' else 'previous_save'): confirmed} if confirmed else {}
        unsaved = session.get('unsaved_operations', 0) + 1
        due = (not session.get('saved_once') and not session.get('save_job')) or \
            (not session.get('save_job') and time.monotonic() - session.get('last_saved_at', 0) >= CHECKPOINT_SECONDS)
        if due:
            result = self._creative_checkpoint(doc, session)
            if confirmed:
                result.setdefault('previous_save' if 'save_job' in result else 'save_job', confirmed)
            return result
        session['unsaved_operations'] = unsaved
        doc.waitForDone()
        pending = session.get('save_job')
        if pending:
            report.setdefault('save_job', {'job': pending['job'], 'state': 'running'})
        return dict(self._creative_observe(doc, session), **report, checkpoint_deferred=True, unsaved_operations=unsaved)

    @staticmethod
    def _creative_saved_message(result, what):
        """The progress line after an action: saved only when its result says the file holds it."""
        if result.get('checkpoint') and not result.get('checkpoint_deferred'):
            return what + ' saved'
        if (result.get('save_job') or {}).get('state') == 'running':
            return what + ' updated; saving in the background'
        return what + ' updated'

    def _creative_validate_save_target(self, doc, session):
        if not session.get('saved_once'):
            return
        current = doc.fileName() if hasattr(doc, 'fileName') else ''
        path = os.path.realpath(current) if current.lower().endswith('.kra') else session.get('painting_path')
        if path and not os.path.isfile(path):
            raise ValueError('The painting file moved or disappeared. Locate the painting before continuing; its old path will not be recreated.')
        if path:
            session['painting_path'] = path

    def _creative_output(self, request):
        identifier = request.get('session_id', '')
        value = request['params'].get('output_dir', '')
        if not isinstance(value, str) or not isinstance(identifier, str):
            raise ValueError('Use the conversation observation directory')
        destination = os.path.realpath(value)
        if not re.fullmatch(r'[a-f0-9-]{36}', identifier) or not os.path.isdir(destination) or os.path.basename(destination) != identifier:
            raise ValueError('Use the conversation observation directory')
        return destination

    def _creative_document(self, identifier=None):
        active = self.get_active_document()
        if not identifier or (active and document_id(active) == identifier):
            return active
        app = Krita.instance()
        for doc in open_documents():
            if document_id(doc) == identifier:
                return doc
        raise ValueError('The selected canvas is no longer open. Attach an open canvas.')

    def _creative_metadata(self, doc):
        if doc is None:
            return {'document_id': None, 'state': 'none'}
        return {'document_id': document_id(doc), 'name': doc.name(),
                'filename': doc.fileName(), 'modified': doc.modified(), 'width': doc.width(), 'height': doc.height()}

    def _creative_nodes(self, doc):
        found = []
        def visit(node, depth=0):
            for child in node.childNodes():
                found.append((child, depth))
                visit(child, depth + 1)
        visit(doc.rootNode())
        return found

    def _creative_validate_smudge_overlay(self, preset_name, rate=False):
        # Overlay mode (MergedPaint) exists only in the Color Smudge engine, and Krita ignores it in Lightness mode.
        from krita import Preset
        import xml.etree.ElementTree as ET
        root = ET.fromstring(Preset(Krita.instance().resources('preset')[preset_name]).toXML())
        names = {e.get('name') for e in root.iter('param')}
        if root.get('paintopid') != 'colorsmudge' or 'MergedPaint' not in names or (rate and 'SmudgeRateValue' not in names):
            raise ValueError('smudge_overlay needs a Color Smudge blender preset such as k) Blender Basic.')

    def _creative_validate_continuation(self, doc, session, params):
        identifier = params['continue_layer_id']
        self._creative_passes(session)
        entries = [e for e in session['passes'] if e.get('layer_id') == identifier]
        if identifier not in session['layers'] or not entries:
            raise ValueError('Continuation requires an existing agent-owned paint layer.')
        latest = entries[-1]
        if (latest['kind'] != 'paint_pass' or latest.get('rejected') or
                latest.get('stage_id') != params.get('stage_id') or
                latest.get('region') != params.get('region')):
            raise ValueError('Continuation must retain its original stage and region.')
        node = self._creative_node(doc, identifier)
        state = self._creative_layer_state(node, doc)
        if state != latest['after'] or state['locked'] or not state['visible']:
            raise ValueError('The continuation layer changed; preserve the artist edits.')
        if node.childNodes():
            raise ValueError('A continuation cannot paint through added masks.')
        parent = node.parentNode() if hasattr(node, 'parentNode') else None
        if parent and (parent.childNodes()[-1] != node or parent.locked() or
                       not parent.visible() or parent.opacity() != 255 or
                       parent.blendingMode() != 'normal'):
            raise ValueError('The continuation layer container changed.')

    def _creative_pass_layer(self, params):
        """The create_layer settings for a stroke pass on a blended or clipped layer."""
        layer = {'name': params['name'], 'type': 'paint', 'opacity': params.get('layer_opacity', 1)}
        layer.update({key: params[key] for key in ('blend_mode', 'clip_to', 'stage_id', 'panel') if key in params})
        return layer

    def _creative_new_layer(self, doc, session, params):
        """Keep new stage paint together without moving existing artwork."""
        stage_id = params.get('stage_id')
        panel = self._comic_container(doc, session, params)
        if not stage_id and panel is None:
            return self.cmd_new_layer({'name': params['name'], 'opacity': params.get('layer_opacity', 1)})
        node = doc.createNode(params['name'], 'paintlayer')
        if node is None:
            raise RuntimeError('Could not create the painting layer')
        node.setOpacity(round(params.get('layer_opacity', 1) * 255))
        group = self._creative_stage_group(doc, session, stage_id, panel) if stage_id else panel
        existing = group.childNodes()
        if not group.addChildNode(node, existing[-1] if existing else None):
            raise RuntimeError('Could not add paint to the stage group')
        doc.setActiveNode(node)
        doc.refreshProjection()
        return {'status': 'ok', 'id': node.uniqueId().toString(), 'group_id': group.uniqueId().toString()}

    def _creative_stage_group(self, doc, session, stage_id, parent=None):
        """The stage's group at the top of `parent` (the painting, or a comic panel), reused while unchanged, else a new one."""
        root = parent if parent is not None else doc.rootNode()
        children = root.childNodes()
        group = None
        # Reuse only a journal-owned group that remains at the top, visible,
        # unlocked and unaffected by extra artist layers or masks. A changed
        # container remains untouched; new paint gets a new stage container.
        identifiers = {entry.get('group_id') for entry in session.get('passes', [])
                       if entry.get('stage_id') == stage_id and entry.get('group_id')}
        # The guides group stays at the top of the painting (guide_craft.py): new paint goes under it.
        top = next((child for child in reversed(children) if not (parent is None and self._guide_is_group(child, doc))), None)
        if top and top.uniqueId().toString() in identifiers:
            if (top.type() == 'grouplayer' and top.visible() and not top.locked() and
                    top.opacity() == 255 and top.blendingMode() == 'normal' and
                    all(child.uniqueId().toString() in session['layers'] for child in top.childNodes())):
                group = top
        if group is None:
            match = re.fullmatch(r'stage-\d+-(\d+)', stage_id)
            label = 'Stage ' + str(int(match.group(1)) + 1) if match else stage_id
            group = doc.createNode('Creative Agent · ' + label + (' (continued)' if identifiers else ''), 'grouplayer')
            if group is None or not root.addChildNode(group, top):
                raise RuntimeError('Could not create the stage group')
            group.setBlendingMode('normal')
        return group

    def _creative_node(self, doc, identifier):
        for node, _depth in self._creative_nodes(doc):
            if node.uniqueId().toString() == identifier:
                return node
        raise ValueError('That layer is no longer in this painting.')

    def _creative_layer_state(self, node, doc):
        digest = hashlib.sha256()
        # Tile reads avoid a second full-canvas allocation for large paint layers.
        for y in range(0, doc.height(), 256):
            digest.update(bytes(node.pixelData(0, y, doc.width(), min(256, doc.height() - y))))
        # A mask, moved parent, blend mode or off-canvas content is also artist
        # work. Do not treat an unchanged central pixel rectangle as ownership.
        structure = []
        def visit(child):
            bounds = child.bounds() if hasattr(child, 'bounds') else None
            record = {'id': child.uniqueId().toString(),
                      'blend': child.blendingMode() if hasattr(child, 'blendingMode') else 'normal',
                      'opacity': child.opacity(), 'visible': child.visible(), 'locked': child.locked(),
                      'bounds': [bounds.x(), bounds.y(), bounds.width(), bounds.height()] if bounds else None}
            if bounds and not bounds.isEmpty():
                if max(bounds.width(), bounds.height()) > 32768:
                    raise ValueError('This layer has extensive off-canvas content. Review it directly in Layers.')
                for y in range(bounds.y(), bounds.y() + bounds.height(), 256):
                    digest.update(bytes(child.pixelData(bounds.x(), y, bounds.width(), min(256, bounds.y() + bounds.height() - y))))
            structure.append(record)
            for descendant in child.childNodes():
                visit(descendant)
        visit(node)
        # Properties changed by the review controls are stored separately.
        structure[0].pop('opacity'); structure[0].pop('visible'); structure[0].pop('locked')
        parent = node.parentNode() if hasattr(node, 'parentNode') else None
        parent_id = parent.uniqueId().toString() if parent else None
        digest.update(json.dumps([parent_id, structure], sort_keys=True).encode())
        return {'opacity': node.opacity(), 'visible': node.visible(), 'pixels': digest.hexdigest(), 'locked': node.locked()}

    def _creative_adapter_capabilities(self):
        from .creative_native_adapters import capabilities
        return capabilities()

    def _creative_tool_help(self):
        result=self._creative_legacy_tool_help()
        result['capabilities']={name:{'available':True,'parameters':description,'selection':'See parameter description and transaction behavior','prerequisites':['Agent execution','bound target','valid contribution']} for name,description in result['tools'].items()}
        result['source_modes']={'new_layer':'No source layer or projection_region',
            'paint_layer_copy':'source_layer_id is an observed paint-layer ID',
            'visible_region_copy':'projection_region [x,y,width,height] and optional projection_feather 0..64; requires RGBA/U8 and opaque visible pixels under the mask; preserves existing layers'}
        result['native_adapters']=self._creative_adapter_capabilities()
        result['native_adapters']['gradient']['parameters']={'shape':['linear','radial'],'start':'[x,y]','end':'[x,y]','foreground':'#RRGGBB','background':'#RRGGBB','opacity':'0..1'}
        result['native_adapters']['smart_patch']['parameters']={'paths':'array of paths of [x,y]','diameter':'1..512','accuracy':'integer 0..100','patch_radius':'integer 1..50'}
        result['native_adapters']['smart_patch']['prerequisites'].append('preceding selection command in the same contribution')
        for name, metadata in result['native_adapters'].items():
            result['tools'][name]=json.dumps(metadata)
        result['capabilities'].update(result['native_adapters'])
        return result

    def _creative_legacy_tool_help(self):
        return {'status': 'ok', 'tools': {
            'set_color': 'color #RRGGBB; set foreground colour',
            'fill': 'x,y,radius,color,opacity; fill a circular area',
            'flood_fill': 'x,y,color,tolerance,connectivity,sample_merged,max_pixels; contiguous RGB flood fill',
            'clear': 'color #RRGGBB; replace the entire contribution with a solid colour; ignores selections',
            'set_brush_texture': 'path to an imported Krita pattern image, scale 0.01..10, strength 0..1',
            'set_brush': 'preset (exact installed name), size 0.01..10000 px, opacity/flow 0..1, rotation degrees; all optional',
            'stroke': 'points [[x,y,pressure],...], size, opacity, flow, color #RRGGBB; native brush engine',
            'curve_stroke': 'start [x,y], segments [[c1x,c1y,c2x,c2y,endx,endy],...], size, opacity, flow, color',
            'draw_shape': 'shape rectangle/ellipse/line/polygon; x,y,width,height or x,y,x2,y2 or points; color,fill,stroke,size,opacity. Filled shapes write solid pixels and ignore selections; use only without a selection.',
            'selection': 'shape rectangle/ellipse/polygon; bounds [x,y,width,height] or points; mode replace/add/subtract/intersect/clear; feather 0..128',
            'modify_selection': 'operation grow/shrink/feather/smooth, radius 1..128 (omit for smooth)',
            'eraser': 'enabled boolean; applies to subsequent native strokes',
            'move_layer': 'dx,dy integer canvas pixel offsets; moves the entire contribution',
            'transform_layer': 'operation rotate with radians; or scale with width,height,origin [x,y],strategy Bicubic/Bilinear/NearestNeighbor; or shear with x,y angles',
            'blend_mode': 'mode Krita blend identifier, e.g. normal,multiply,screen,overlay',
            'layer_settings': 'opacity 0..1, visible boolean, alpha_locked boolean',
            'brush_controls': 'controls {pigment:0..1,blend:0..1,scatter:0..1,pigment_dynamics:bool,blend_dynamics:bool}',
            'configure_brush': 'properties object of existing preset properties; inspect current_brush below first',
            'restore_brush': 'empty object; restores original in-memory preset settings'},
            'current_brush': self.cmd_brush_settings({}),
            'behavior': 'Commands run on a new layer, a copy of source_layer_id, or a masked visible-projection copy from projection_region. Source modes are exclusive. Locked source layers can be copied; original pixels stay intact. Selection and eraser state are restored afterwards. Explicit stage regions still apply. One call is one saved contribution.'}

    def _creative_validate_toolbox(self, doc, params):
        fields(params, ('name','source_layer_id','projection_region','projection_feather','commands','expected_revision','stage_id','region'), ('name','commands'))
        text(params['name'], 'name')
        commands = params['commands']
        if not isinstance(commands, list) or not 1 <= len(commands) <= 256:
            raise ValueError('Use 1–256 commands per contribution; observe before the next contribution.')
        self._feature_refuse_toolbox(doc, commands)
        allowed = {'set_brush','stroke','curve_stroke','draw_shape','selection','modify_selection',
                   'eraser','move_layer','transform_layer','blend_mode','layer_settings',
                   'brush_controls','configure_brush','restore_brush','set_color','fill','flood_fill','clear','set_brush_texture','gradient','smart_patch'}
        if params.get('region'):
            self._creative_region(params['region'], doc.width(), doc.height())
        if params.get('source_layer_id'):
            source = self._creative_node(doc, params['source_layer_id'])
            if source.type() != 'paintlayer':
                raise ValueError('Choose a paint layer to edit, or omit source_layer_id for a new layer.')
        if params.get('projection_region'):
            if params.get('source_layer_id'):
                raise ValueError('Choose either source_layer_id or projection_region, not both.')
            self._creative_region(params['projection_region'], doc.width(), doc.height())
            if doc.colorModel() != 'RGBA' or doc.colorDepth() != 'U8':
                raise ValueError('Visible-region retouch requires an RGBA/U8 document.')
            feather = params.get('projection_feather', 0)
            if isinstance(feather, bool) or not isinstance(feather, int) or not 0 <= feather <= 64:
                raise ValueError('projection_feather must be an integer from 0 to 64.')
            x,y,w,h = params['projection_region']
            if w*h > 2000000:
                raise ValueError('Visible-region retouch is limited to two million pixels per contribution.')
            if params.get('region'):
                sx,sy,sw,sh = params['region']
                if x < sx or y < sy or x+w > sx+sw or y+h > sy+sh:
                    raise ValueError('The projection region must remain inside the protected stage region.')
            if any(item['tool'] in ('move_layer','transform_layer','draw_shape','blend_mode','layer_settings','clear','fill','flood_fill') for item in commands):
                raise ValueError('Visible-region retouch supports selection-aware strokes, gradient, Smart Patch and brush controls only.')
        elif 'projection_feather' in params:
            raise ValueError('projection_feather requires projection_region.')
        for item in commands:
            fields(item, ('tool','parameters_json'), ('tool','parameters_json'))
            if item['tool'] not in allowed:
                raise ValueError('Unknown painting tool. Call painting_tool_help for available tools.')
            value = json.loads(item['parameters_json'])
            if not isinstance(value, dict):
                raise ValueError('parameters_json must encode an object')
            if item['tool'] in ('gradient','smart_patch'):
                from .creative_native_adapters import validated_parameters, NativeToolAdapter
                validated_parameters(item['tool'],value,doc.width(),doc.height())
                if not self._creative_adapter_capabilities()[item['tool']]['available']:
                    raise ValueError('Native adapter has not passed live acceptance for this Krita version')
                with NativeToolAdapter(self,doc,item['tool']) as adapter:
                    adapter.preflight(value)
                if item['tool']=='smart_patch':
                    if not (params.get('source_layer_id') or params.get('projection_region')): raise ValueError('Smart Patch requires a source paint layer or visible-region copy')
                    preceding=commands[:commands.index(item)]
                    selections=[json.loads(c['parameters_json']) for c in preceding if c['tool']=='selection']
                    if not selections or selections[-1].get('mode')=='clear': raise ValueError('Smart Patch requires an explicit preceding repair selection')
            if item['tool'] == 'stroke' and value.get('engine', 'native') != 'native':
                raise ValueError('Use native brush strokes for this contribution.')
            if item['tool'] == 'layer_settings':
                fields(value, ('opacity','visible','alpha_locked'))
            if item['tool'] == 'eraser':
                fields(value, ('enabled',), ('enabled',))
                if not isinstance(value['enabled'], bool): raise ValueError('enabled must be boolean')
            if params.get('region') and params['region'] != [0, 0, doc.width(), doc.height()] and item['tool'] in ('move_layer','transform_layer','draw_shape','blend_mode','layer_settings','clear'):
                raise ValueError('This plan explicitly protects pixels outside its region. Use region-clipped strokes, or revise that user constraint before whole-layer operations.')

    def _creative_projection_snapshot(self, doc, params):
        """Read only the bounded visible pixels and a feathered, selection-clipped mask."""
        x,y,w,h = params['projection_region']
        mask = Selection()
        mask.select(x,y,w,h,255)
        feather = params.get('projection_feather', 0)
        if feather:
            mask.feather(feather)
            hard = Selection(); hard.select(x,y,w,h,255)
            mask.intersect(hard)
        if doc.selection() is not None:
            mask.intersect(doc.selection())
        coverage = bytes(mask.pixelData(x,y,w,h))
        if len(coverage) != w*h or not any(coverage):
            raise ValueError('The visible-region mask is empty or has an unsupported format.')
        canvas_projection.refresh(doc, [x, y, w, h]); doc.waitForDone()   # only the area read next
        source = bytes(doc.rootNode().projectionPixelData(x,y,w,h))
        if len(source) != w*h*4:
            raise ValueError('The visible projection is not BGRA/U8 pixel data.')
        if any(source[index*4+3] != 255 for index,alpha in enumerate(coverage) if alpha):
            raise ValueError('Visible-region retouch currently requires opaque pixels under its mask.')
        pixels = bytearray(source)
        for index,alpha in enumerate(coverage):
            pixels[index*4+3] = alpha
        return mask, bytes(pixels), coverage

    def _creative_new_projection_layer(self, doc, name):
        root = doc.rootNode()
        children = root.childNodes()
        node = doc.createNode(name, 'paintlayer')
        if node is None or not root.addChildNode(node, children[-1] if children else None):
            raise RuntimeError('Could not create the visible-region working layer.')
        doc.setActiveNode(node)
        return {'status':'ok', 'id':node.uniqueId().toString()}

    def _creative_toolbox(self, doc, session, params):
        from .qt_compat import QPointF
        view = self.get_active_view()
        selection, eraser = doc.selection(), view.eraserMode()
        result = {'status': 'ok'}
        source = None
        node = None
        revision_before = self._creative_revision(doc)
        try:
            projection = self._creative_projection_snapshot(doc, params) if params.get('projection_region') else None
            if params.get('source_layer_id'):
                source = self._creative_node(doc, params['source_layer_id'])
                result.update(source_layer_id=params['source_layer_id'], source_prior=self._creative_layer_state(source, doc))
                doc.setActiveNode(source)
                layer = self.cmd_duplicate_layer({'name': params['name']})
            elif projection:
                layer = self._creative_new_projection_layer(doc, params['name'])
            else:
                layer = self._creative_new_layer(doc, session, params)
            if layer.get('error'): raise RuntimeError(layer['error'])
            result['layer_id'] = layer['id']
            if layer.get('group_id'): result['group_id'] = layer['group_id']
            session['layers'].add(layer['id'])
            node = doc.activeNode()
            node.setVisible(True)
            node.setLocked(False)
            if projection:
                x,y,w,h = params['projection_region']
                written = node.setPixelData(projection[1],x,y,w,h)
                if written is False:
                    raise RuntimeError('Krita rejected visible-region pixel data.')
                result['projection_region'] = params['projection_region']
                result['projection_feather'] = params.get('projection_feather',0)
            if source: source.setVisible(False)
            doc.setSelection(projection[0] if projection else None)
            view.setEraserMode(False)
            for index, item in enumerate(params['commands']):
                name, value = item['tool'], json.loads(item['parameters_json'])
                self._creative_progress(session, 'painting', '%s · command %d of %d' % (name.replace('_',' '), index+1, len(params['commands'])))
                if projection or params.get('region') and params['region'] != [0, 0, doc.width(), doc.height()]:
                    mask = Selection()
                    if projection:
                        x,y,w,h = params['projection_region']
                        written = mask.setPixelData(projection[2],x,y,w,h)
                        if written is False: raise RuntimeError('Could not restore the visible-region mask.')
                    else: mask.select(*params['region'], 255)
                    if doc.selection():
                        mask.intersect(doc.selection())
                    doc.setSelection(mask)
                if name in ('gradient','smart_patch'):
                    from .creative_native_adapters import execute
                    centers = []
                    if name == 'smart_patch':
                        for path in value['paths']:
                            xs=[point[0] for point in path]; ys=[point[1] for point in path]
                            centers.append((round((min(xs)+max(xs))/2),round((min(ys)+max(ys))/2)))
                    center_before = [bytes(node.pixelData(x,y,1,1)) for x,y in centers]
                    execute(self,doc,name,value)
                    if any(before == bytes(node.pixelData(x,y,1,1)) for (x,y),before in zip(centers,center_before)):
                        raise RuntimeError('Smart Patch left a repair-mask center unchanged; use a selection that covers the full defect and retry.')
                elif name == 'eraser': view.setEraserMode(value['enabled'])
                elif name == 'blend_mode': node.setBlendingMode(text(value.get('mode'), 'mode'))
                elif name == 'transform_layer':
                    op = value.get('operation')
                    if op == 'rotate': self._feature_transform(doc, node, 'rotate', lambda: node.rotateNode(numeric(value.get('radians'), 'radians', -1000, 1000)))
                    elif op == 'scale':
                        width = numeric(value.get('width'), 'width', 1, 100000)
                        height = numeric(value.get('height'), 'height', 1, 100000)
                        origin = value.get('origin', [0,0])
                        if not isinstance(origin,list) or len(origin)!=2: raise ValueError('origin must be [x,y]')
                        x,y = [numeric(v,'origin',-100000,100000) for v in origin]
                        strategy = value.get('strategy','Bicubic')
                        if strategy not in ('Bicubic','Bilinear','NearestNeighbor'): raise ValueError('Unknown scale strategy')
                        self._feature_transform(doc, node, 'scale', lambda: node.scaleNode(QPointF(x,y), int(width), int(height), strategy))
                    elif op == 'shear': self._feature_transform(doc, node, 'shear', lambda: node.shearNode(numeric(value.get('x',0),'x',-89,89), numeric(value.get('y',0),'y',-89,89)))
                    else: raise ValueError('Use rotate, scale, or shear')
                else:
                    if (name == 'clear' or name == 'draw_shape' and value.get('fill', True)) and doc.selection():
                        raise ValueError('Filled shapes do not honor selections. Clear the selection first, or use a native brush stroke.')
                    # Scripted Node painting reads the preset's composite op,
                    # not View's eraser toggle. Override only for this stroke.
                    previous_erase = None
                    if name in ('stroke','curve_stroke') and view.eraserMode():
                        properties = self.cmd_brush_settings({})['properties']
                        previous_erase = {key: properties[key] for key in ('CompositeOp','EraserMode') if key in properties}
                        configured = self.cmd_configure_brush({'properties': {'CompositeOp':'erase','EraserMode':True}})
                        if configured.get('error'): raise RuntimeError(configured['error'])
                    try:
                        response = getattr(self, 'cmd_'+name)(value)
                        if response.get('error'): raise RuntimeError(response['error'])
                    finally:
                        if previous_erase:
                            restored = self.cmd_configure_brush({'properties':previous_erase})
                            if restored.get('error'): raise RuntimeError(restored['error'])
                            view.setEraserMode(True)
                doc.waitForDone()
        except Exception as error:
            result.update(status='partial', error=str(error), error_code='partial_change')
            try:
                if node is not None:
                    if not node.remove(): raise RuntimeError('Could not remove unsuccessful contribution')
                    session['layers'].discard(result['layer_id'])
                    # The contribution layer no longer exists: never record or reference it.
                    result.pop('layer_id', None); result.pop('group_id', None)
                    result['contribution_removed'] = True
                if source: source.setVisible(result['source_prior']['visible'])
                doc.refreshProjection(); doc.waitForDone()
                if self._creative_revision(doc) == revision_before:
                    result.update(status='rejected', error_code='validation_rejected')
                    result.pop('layer_id', None)
            except Exception:
                pass
        finally:
            doc.setSelection(selection)
            view.setEraserMode(eraser)
            if source:
                result['source_after'] = self._creative_settle(doc, session, source)
            doc.refreshProjection(); doc.waitForDone()
        return result

    def _creative_unresolved(self, session):
        return [key for key, (_fingerprint, result) in session['operations'].items()
                if (result.get('error') or result.get('status') == 'partial') and not result.get('reconciled')]

    def _creative_committed_count(self, session):
        return len(session.get('passes', []))

    def _creative_validate_adjustment(self, doc, session, params):
        entries = [entry for entry in self._creative_passes(session) if entry.get('layer_id') == params['layer_id']]
        state = self._creative_layer_state(self._creative_node(doc, params['layer_id']), doc)
        if state['locked']:
            raise ValueError('This layer is locked. Choose an unlocked layer.')
        # The caller supplies a fresh document revision. Capture a new baseline
        # for existing artwork, including edits made since an earlier session.
        region = params.get('region')
        if region and region != [0, 0, doc.width(), doc.height()]:
            self._creative_region(region, doc.width(), doc.height())
            origin = next((entry for entry in entries if entry['kind'] == 'paint_pass'), None)
            bounds = origin.get('region') if origin else None
            if not bounds or not (region[0] <= bounds[0] and region[1] <= bounds[1] and
                    bounds[0] + bounds[2] <= region[0] + region[2] and bounds[1] + bounds[3] <= region[1] + region[3]):
                raise ValueError('That layer extends beyond the current stage region. Protected areas cannot be adjusted.')

    def _creative_revision(self, doc, projection=None):
        if projection is None:
            doc.refreshProjection()
            doc.waitForDone()
            projection = doc.projection(0, 0, doc.width(), doc.height())
        digest = hashlib.sha256()
        digest.update(projection.constBits().asstring(projection.sizeInBytes()))
        # Protected areas (selection masks in their own group) never render: proposing, keeping or removing one is
        # not a canvas change, so it must not refuse the painter's next pass as "the painting changed".
        manifest, skip = [], None
        for n, depth in self._creative_nodes(doc):
            if skip is not None and depth > skip:
                continue
            skip = depth if n.name() == self.PROTECTION_GROUP else None
            if skip is None:
                manifest.append((n.uniqueId().toString(), n.name(), n.opacity(), n.visible(), n.locked(), depth))
        digest.update(json.dumps([doc.width(), doc.height(), manifest]).encode())
        selection = doc.selection()
        if selection is not None:
            digest.update(bytes(selection.pixelData(0, 0, doc.width(), doc.height())))
        return digest.hexdigest()

    def _creative_passes(self, session):
        if 'passes' not in session:
            journal = self._creative_journal(session)
            session['passes'] = journal.passes() if journal else []
            legacy = os.path.join(session.get('output') or '', '.passes.json')
            if not session['passes'] and journal and os.path.exists(legacy):   # a chat from before the journal database
                try:
                    with open(legacy) as stream:
                        session['passes'] = json.load(stream)
                except (OSError, ValueError):
                    session['passes'] = []
                self._creative_store_passes(session)
                os.remove(legacy)
        # Stage rows are presentation records, never native operation records.
        session['passes'] = [entry for entry in session['passes'] if entry.get('kind') != 'stage']
        result = []
        latest = {entry['layer_id']: entry for entry in session['passes'] if entry.get('layer_id')}
        stages = {}
        for entry in session['passes']:
            if entry.get('merged_into'):
                continue                                   # shown through the pass that merged it
            item = dict(entry)
            for key in ('before_path', 'after_path'):
                if item.get(key) and not os.path.isabs(item[key]):
                    item[key] = os.path.join(session['output'], item[key])
            current = latest.get(item.get('layer_id'), {}).get('after', {})
            if current:
                item.update(strength=current['opacity'] / 255, visible=current['visible'])
            previous_row = next((r for r in reversed(result) if r.get('layer_id') == item.get('layer_id') and r.get('kind') == 'paint_pass'), None)
            if item.get('continuation_of') and previous_row is not None:
                previous_row.update(after_path=item.get('after_path'), after=item.get('after'),
                                    strength=item['strength'], visible=item['visible'],
                                    continuation_chunks=previous_row.get('continuation_chunks', 1) + 1)
            else:
                result.append(item)
            if item.get('stage_id'):
                stages.setdefault(item['stage_id'], []).append(item)
        for stage_id, entries in stages.items():
            origins = {}
            for entry in entries:
                origins.setdefault(entry['layer_id'], entry)
            owned = all(self._creative_new_contribution(entry) for entry in origins.values())
            match = re.fullmatch(r'stage-\d+-(\d+)', stage_id)
            move = re.fullmatch(r'move-(\d+)', stage_id)          # one collaborative Agent move
            title = 'Stage ' + str(int(match.group(1)) + 1) if match else 'Move ' + move.group(1) if move else stage_id
            later = self._creative_review_dependents(session, entries)
            member_ids = {entry['id'] for entry in entries}
            extra = sum(1 for entry in later if entry['id'] not in member_ids and not entry.get('rejected'))
            warning = ('Rejecting this stage also rejects %d later agent adjustments on its layers.' % extra) if extra else 'Compare or reject this stage together; other layers are preserved.'
            if not owned:
                warning += ' This stage adjusts existing layers; use individual passes for strength and visibility.'
            group = {'id': 'stage:' + stage_id, 'kind': 'stage', 'stage_id': stage_id,
                     'title': title + ' · %d changes' % len(entries), 'pass_ids': [entry['id'] for entry in entries],
                     'before_path': entries[0].get('before_path'), 'after_path': entries[-1].get('after_path'),
                     'strength': entries[0].get('stage_strength', 1),
                     'visible': any(entry.get('visible', True) for entry in entries),
                     'rejected': all(entry.get('rejected', False) for entry in entries), 'warning': warning,
                     'review_actions': ['strength', 'visibility', 'reject'] if owned else ['reject']}
            result.append(group)
        return result

    def _creative_settle(self, doc, session, node):
        """The agent changed `node` as part of another pass: its own newest pass now ends in this state."""
        state = self._creative_layer_state(node, doc)
        identifier = node.uniqueId().toString()
        for entry in reversed(session.get('passes', [])):
            if entry.get('layer_id') == identifier:
                entry['after'] = state
                break
        return state

    def _creative_settle_containers(self, doc, session, node):
        """A new mask or layer changes the state of the agent layers around it; they are not artist edits.

        Walks up through the agent's own containers (stage groups, comic panels) to every recorded
        agent layer above, such as a comic page, and stops at the first layer the agent does not own.
        """
        passes = session.get('passes', [])
        recorded = {entry.get('layer_id') for entry in passes}
        own = recorded | set(session.get('layers', ())) | {entry.get('group_id') for entry in passes}
        parent = node.parentNode() if hasattr(node, 'parentNode') else None
        while parent is not None and parent.uniqueId().toString() in own:
            if parent.uniqueId().toString() in recorded:
                self._creative_settle(doc, session, parent)
            parent = parent.parentNode()

    def _creative_new_contribution(self, entry):
        """A pass that made a new agent layer or mask (not a copy), so a stage can fade or hide it as a whole."""
        return entry['kind'] in NEW_CONTRIBUTIONS and not entry.get('source_layer_id')

    def _creative_review_dependents(self, session, entries):
        """Find each selected operation and subsequent work on the same layer."""
        selected = {entry['id'] for entry in entries}
        active_layers = set()
        result = []
        for entry in session['passes']:
            if entry['id'] in selected:
                active_layers.add(entry['layer_id'])
            if entry.get('source_layer_id') in active_layers:
                active_layers.add(entry['layer_id'])
            if entry.get('layer_id') in active_layers:
                result.append(entry)
        return result

    def _creative_review_targets(self, doc, session, entries):
        """Validate every affected layer before the first group mutation."""
        targets = {}
        for entry in entries:
            identifier = entry['layer_id']
            if identifier in targets:
                continue
            node = self._creative_node(doc, identifier)
            latest = next(item for item in reversed(session['passes']) if item.get('layer_id') == identifier)
            state = self._creative_layer_state(node, doc)
            if state['locked'] or any(state[key] != latest['after'][key] for key in ('pixels', 'opacity', 'visible')):
                raise ValueError('This layer has newer artist changes. They are preserved; review it in Layers instead.')
            if entry.get('source_layer_id'):
                source = self._creative_node(doc, entry['source_layer_id'])
                if self._creative_layer_state(source, doc) != entry['source_after']:
                    raise ValueError('The original layer has newer edits. Preserve them and review this contribution in Layers.')
            targets[identifier] = {'node': node, 'latest': latest, 'state': state}
        return targets

    def _creative_store_passes(self, session):
        journal = self._creative_journal(session)
        if not journal:
            return
        entries = []
        for entry in session.get('passes', []):
            item = dict(entry)
            for key in ('before_path', 'after_path'):
                if item.get(key):
                    item[key] = os.path.relpath(item[key], session['output']) if os.path.isabs(item[key]) else item[key]
            entries.append(item)
        journal.sync_passes(entries)                       # only the rows that changed

    def _creative_receipt(self, result):
        """What the journal keeps of a result: everything but the layer list and pass history.

        Both are re-read on replay. Keeping them made every receipt ~30-120 KB, and the whole
        journal is rewritten twice per action (97 MB after one long reference job)."""
        return {k: v for k, v in result.items() if k not in ('layers', 'passes')}

    def _creative_replay(self, doc, session, stored):
        result = dict(stored, replayed=True)
        if stored.get('image_path') and 'layers' not in stored:
            result['layers'] = self._creative_layer_list(doc)
        return result

    def _creative_load_operations(self, session):
        """The journal's operations, importing a chat's .operations.json from before the database once."""
        destination = session['output']
        session['operations'] = self._creative_operation_paths(self._creative_journal(session).operations(), destination, False)
        legacy = os.path.join(destination, '.operations.json')
        if not session['operations'] and os.path.exists(legacy):
            with open(legacy) as stream:
                session['operations'] = self._creative_operation_paths(json.load(stream), destination, False)
            self._creative_store_operations(session)
            os.remove(legacy)

    def _creative_journal(self, session):
        """The chat's journal, opened on first use for any session with an output folder."""
        if not session.get('journal') and session.get('output') and os.path.isdir(session['output']):
            session['journal'] = Journal(session['output'])
        return session.get('journal')

    def _creative_store_operations(self, session, operation_id=None):
        """Commit one operation's intent or receipt (or all, for a reconcile) to the journal."""
        journal = self._creative_journal(session)
        if not journal:
            return
        keys = [operation_id] if operation_id else list(session['operations'])
        items = {key: (session['operations'][key][0], self._creative_operation_paths(
            self._creative_receipt(session['operations'][key][1]), session['output'], True)) for key in keys}
        if operation_id:
            fingerprint, receipt = items[operation_id]
            journal.put_operation(operation_id, fingerprint, receipt, time.time())
        else:
            journal.put_operations(items, time.time())

    def _creative_operation_paths(self, value, directory, encode, key=''):
        if isinstance(value, dict):
            return {k: self._creative_operation_paths(v, directory, encode, k) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._creative_operation_paths(v, directory, encode) for v in value]
        if isinstance(value, str) and value and key in ('path', 'image_path', 'before_path', 'after_path', 'checkpoint', 'filename'):
            if encode and os.path.isabs(value):
                return os.path.relpath(value, directory)
            if not encode and not os.path.isabs(value):
                return os.path.realpath(os.path.join(directory, value))
        return value

    def _creative_review(self, doc, session, params, operation_id, fingerprint):
        fields(params, ('pass_id', 'action', 'value', 'expected_revision'), ('pass_id', 'action'))
        action = params['action']
        if action not in ('strength', 'visibility', 'reject'):
            raise ValueError('Choose strength, visibility or reject')
        if action == 'strength':
            numeric(params.get('value'), 'strength', 0, 1)
        if action == 'visibility' and not isinstance(params.get('value'), bool):
            raise ValueError('Visibility must be true or false')
        self._creative_passes(session)
        identifier = text(params['pass_id'], 'pass_id', 200)
        group = identifier.startswith('stage:')
        entries = [entry for entry in session['passes'] if
                   (entry.get('stage_id') == identifier[6:] if group else entry['id'] == identifier)]
        if not group and entries and entries[0].get('merged_into'):
            raise ValueError('This pass was merged with others into one layer; review the merged pass instead.')
        entries = [entry for entry in entries if not entry.get('merged_into')]
        if not entries:
            raise ValueError('Unknown agent pass or stage')
        if all(entry.get('rejected') for entry in entries):
            raise ValueError('This contribution has already been rejected.')
        affected = self._creative_review_dependents(session, entries) if action == 'reject' else entries
        if action == 'reject':
            self._comic_reject_guard(doc, session, affected)
        targets = self._creative_review_targets(doc, session, affected)
        origins = {}
        for entry in entries:
            origins.setdefault(entry['layer_id'], entry)
        if group and action != 'reject' and not all(self._creative_new_contribution(entry) for entry in origins.values()):
            raise ValueError('This stage adjusts existing layers. Review individual changes or reject the whole stage.')
        session['operation_id'] = operation_id
        session['operations'][operation_id] = (fingerprint, {
            'status': 'partial', 'error': 'The review operation was interrupted. Inspect the painting before continuing.',
            'error_code': 'outcome_unknown', 'affected_pass_ids': [entry['id'] for entry in affected]})
        self._creative_store_operations(session, operation_id)
        result = {'status': 'ok'}
        try:
            if action == 'reject':
                for entry in reversed(affected):
                    if entry.get('rejected'):
                        continue
                    node = targets[entry['layer_id']]['node']
                    if entry['kind'] == 'adjust_layer':
                        node.setOpacity(entry['prior']['opacity'])
                        node.setVisible(entry['prior']['visible'])
                    elif entry['kind'] == 'set_layer':
                        self._craft_restore(node, entry['prior'])
                    else:
                        node.setVisible(False)
                        if entry.get('source_layer_id'):
                            self._creative_node(doc, entry['source_layer_id']).setVisible(entry['source_prior']['visible'])
                        self._guide_restore_replaced(doc, session, entry)   # a tightened guide's rough one shows again
                    entry['rejected'] = True
            else:
                for layer_id, target in targets.items():
                    node = target['node']
                    if action == 'strength':
                        if group:
                            origin = origins[layer_id]
                            origin.setdefault('stage_base_opacity', target['state']['opacity'])
                            node.setOpacity(round(origin['stage_base_opacity'] * params['value']))
                        else:
                            node.setOpacity(round(params['value'] * 255))
                        # Krita ignores a filter mask's opacity; its pixels carry the strength.
                        # Keyed on the mask's saved coverage, not its newest pass (set_layer may follow).
                        self._filter_fade(session, node, node.opacity() / 255)
                    else:
                        node.setVisible(params['value'])
                if group and action == 'strength':
                    for entry in entries:
                        entry['stage_strength'] = params['value']
            doc.refreshProjection()
            doc.waitForDone()
            for target in targets.values():
                self._creative_settle_containers(doc, session, target['node'])     # a hidden mask changes its layer
            for target in targets.values():
                state = self._creative_layer_state(target['node'], doc)
                target['latest'].update(after=state, strength=state['opacity'] / 255, visible=state['visible'])
            self._creative_store_passes(session)
        except Exception as error:
            result = {'status': 'partial', 'error': str(error), 'error_code': 'partial_change'}
        try:
            checkpoint = self._creative_checkpoint(doc, session)
            result.update({key: value for key, value in checkpoint.items() if key != 'status'})
            if checkpoint.get('image_path'):
                for entry in affected:
                    entry['after_path'] = checkpoint.get('unguided_path') or checkpoint['image_path']
                self._creative_store_passes(session)
        except Exception as error:
            result.update(status='partial', error='Checkpoint failed: ' + str(error), error_code='checkpoint_failed')
        result['affected_pass_ids'] = [entry['id'] for entry in affected]
        result['passes'] = self._creative_passes(session)
        session['operations'][operation_id] = (fingerprint, result)
        self._creative_store_operations(session, operation_id)
        self._creative_progress(session, 'saved' if result['status'] == 'ok' else 'error',
                                self._creative_saved_message(result, 'Review') if result['status'] == 'ok' else result.get('error', 'Review paused'))
        return result

    def _creative_let_krita_respond(self, doc, node):
        """Let Krita's window and the panel (Stop) handle events during a stroke pass. Strokes go to
        the active layer of the active document, so a click elsewhere is undone or ends the pass."""
        QCoreApplication.processEvents()
        active = self.get_active_document()
        if active is None:
            # No active window: the screen slept or locked, not an artist's choice of another document.
            return ('Krita lost its active window (the screen may be asleep or locked); the pass stopped there. '
                    'Turn on Settings: Screen, "Keep the screen awake while painting", to paint unattended.')
        if document_id(active) != document_id(doc):
            return 'The artist switched to another document; the pass stopped there.'
        current = doc.activeNode()
        if node is not None and (current is None or current.uniqueId().toString() != node.uniqueId().toString()):
            doc.setActiveNode(node)
        return None

    def _creative_progress(self, session, phase, message):
        # The companion can read this while Krita's main thread paints or saves.
        if not session.get('output'):
            return
        path = os.path.join(session['output'], '.progress.json')
        try:
            with open(path + '.tmp', 'w') as stream:
                json.dump({'operation_id': session.get('operation_id'), 'phase': phase,
                           'message': message, 'at': time.time()}, stream)
            os.replace(path + '.tmp', path)
        except OSError:
            pass  # Reporting must never prevent saving the artwork.

    def _creative_weight(self, doc):
        """How heavy the painting is for Krita and why (painting_weight.py): layer metadata only, never pixels."""
        try:
            return painting_weight.weight(painting_weight.records(doc), doc.width(), doc.height())
        except Exception:
            return None                                  # a measure must never stop an observation

    def _creative_stroke_job(self, doc, session, params, node, result, new_layer=True, started=None, selection=None):
        """The fork: the whole pass as one Node.paintStrokes job (libkis StrokeJob, krita-fork task 2.4). The job paints in
        Krita's worker threads; this call stays synchronous to the bridge by polling it on the GUI thread with short
        bounded waits, running Qt's events between them: the job's feeder tops up its strokes from the event loop, which
        a GUI-thread wait never runs. So the window, the panel's Stop and the artist's own strokes respond while the pass
        paints, and the companion follows it through the progress file. `started` runs as soon as the job exists (the
        artist's layer becomes active again). `selection` is the job's own clip (the stamp's faded area), else the
        stage mask of params['region'], else none. Returns the result's fields: pen notes, `stroke_job`, and on a stop
        `stopped_after_strokes`. A job Krita ended on the artist's Undo is waited out until the undo has landed and then
        raised, so nothing is observed, saved or recorded as painted; a refused job painted nothing and is a rejected pass.
        The job's undo step is its own, named after the pass, or joins an open agent move by itself."""
        strokes, out = params['strokes'], {}
        options = {'name': params['name']}
        options['preset'] = params['preset']
        if params.get('smudge_overlay'):
            # Overlay mode on the job's own copy of the saved preset; the view's preset is never touched.
            options['presetProperties'] = dict({'MergedPaint': True},
                **({'SmudgeRateValue': params['smudge_rate']} if 'smudge_rate' in params else {}))
        if selection is None and params.get('region'):
            # The stage mask clips the whole brush footprint and fades in at inner edges (stage_mask.py); the job clips
            # to it alone, whatever the document selects, so the artist's selection is never swapped.
            from .stage_mask import mask as stage_mask
            x, y, w, h = params['region']
            selection = Selection()
            selection.setPixelData(stage_mask(params['region'], doc.width(), doc.height()).tobytes(), x, y, w, h)
        self._creative_progress(session, 'painting', 'Painting %d strokes' % len(strokes))
        history = hasattr(doc, 'undoIndex') and hasattr(doc, 'undoCount')
        start = (doc.undoIndex(), doc.undoCount() - doc.undoIndex()) if history else (0, 0)
        peak = start[0]
        # Pen input goes as the pass gives it: paintStrokes reads per-point pressure, tilt, rotation, speed and time_ms
        # lists in validate_pass's units and ranges, with validate_pass's margin (one brush size), well inside its caps.
        job = node.paintStrokes(strokes, options, selection)
        if started:
            started()
        for name in PEN_INPUTS:
            if any(name in stroke for stroke in strokes):
                # time_ms reached the brush engine but no preset has shown an effect yet (protocol 5 measurement).
                out[name] = 'applied (not yet confirmed visually)' if name == 'time_ms' else 'applied'
        cancelled, reported, told, deadline = False, -1, 0.0, time.monotonic() + JOB_DEADLINE_SECONDS
        while job.state() in ('queued', 'running'):
            QCoreApplication.processEvents()
            if history:
                peak = max(peak, doc.undoIndex())
            if not cancelled and (stop_requested.is_set() or time.monotonic() > deadline):
                job.cancel()                           # keeps the first strokesDone() strokes; the rest never paint
                cancelled, timed_out, deadline = True, not stop_requested.is_set(), time.monotonic() + CANCEL_GRACE_SECONDS
            elif cancelled and time.monotonic() > deadline:
                raise RuntimeError('The stroke job did not end after it was cancelled; inspect the painting.')
            if job.wait(JOB_POLL_MS):
                break
            done = job.strokesDone()
            if done != reported and time.monotonic() - told >= RESPONSIVE_SECONDS:
                reported, told = done, time.monotonic()
                self._creative_progress(session, 'painting', 'Painting stroke %d of %d' % (min(done + 1, len(strokes)), len(strokes)))
        state, done = job.state(), job.strokesDone()
        if history:
            peak = max(peak, doc.undoIndex())
        if state == 'failed':
            # The fork guarantees a refused job painted nothing: a new layer made for it is removed, and the pass is a
            # rejected one (nothing to inspect or retry), not a partial change.
            if new_layer:
                self._creative_discard_layer(doc, session, result, node)
            result.pop('layer_id', None); result.pop('group_id', None)
            result.update(status='rejected', error_code='validation_rejected',
                          error='Krita refused the strokes and painted nothing: ' + (job.errorString() or 'no reason given'))
            return out
        out['stroke_job'] = {'state': state, 'strokes': done, 'total': job.strokesTotal(), 'ms': job.elapsedMs()}
        kept = job.keptOut() if hasattr(job, 'keptOut') else []
        if kept:
            out['kept_out'] = list(kept)               # protected features the job's strokes were clipped out of
        if state == 'cancelled' and not cancelled:
            reason = job.cancelReason() if hasattr(job, 'cancelReason') else None
            if reason != 'script':
                self._creative_ended_by_krita(doc, session, result, node, new_layer, history, start, peak, reason)
        if state == 'cancelled':
            out.update(stopped=('The pass took too long and was stopped.' if cancelled and timed_out else 'Stopped by the artist.'),
                       stopped_after_strokes=done, strokes_total=len(strokes))
        # The job records what its strokes redrew on the layer: recomposite that, nothing more (empty: nothing).
        rect = job.changedRect()
        if rect.width() > 0 and rect.height() > 0:
            canvas_projection.refresh(doc, [rect.x(), rect.y(), rect.width(), rect.height()])
        return out

    def _creative_ended_by_krita(self, doc, session, result, node, new_layer, history, start, peak, reason):
        """Krita ended the job: the artist pressed Undo, or the document closed (the job's cancel reason says which, when
        the fork reports one). The fork stops the job, lets its step land, and carries the undo out later from its event
        loop, so the pass waits here, running events, until the undo has landed (the undo index fell, or a step can be
        redone that could not be before), and only then raises: the painting is observed, saved and recorded after the
        undo, never before it. With no strokes painted the undo took the step below the job (the pass layer's creation,
        or the artist's own action), which the message says. Always raised: the pass is not recorded as painted."""
        if reason == 'document_closed':
            raise RuntimeError('The document was closed during the pass; its strokes are gone. Inspect the painting.')
        landed = not history
        deadline = time.monotonic() + UNDO_WAIT_SECONDS
        while history and not landed and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            index, redo = doc.undoIndex(), doc.undoCount() - doc.undoIndex()
            landed = index < peak or index < start[0] or redo > start[1]
            if not landed:
                time.sleep(0.01)
        if not landed:
            raise RuntimeError('Krita ended the pass early (the artist pressed Undo, or the document closed), but no undo was '
                               'seen to land. Inspect the painting.')
        # The pass is not a painted pass: a layer made for it is dropped as a rejected pass's is, and a continuation's
        # layer keeps the earlier passes. Either way nothing is recorded for it.
        if new_layer:
            self._creative_discard_layer(doc, session, result, node)
        result.pop('layer_id', None); result.pop('group_id', None)
        result['contribution_removed'] = True
        raise RuntimeError('The artist pressed Undo during the pass; its strokes were undone. Inspect the painting.')

    def _creative_discard_layer(self, doc, session, result, node):
        """Remove the pass's new layer if it is still in the painting (an undo may have taken it already)."""
        identifier = result.get('layer_id')
        try:
            present = any(n is node or n.uniqueId().toString() == identifier for n, _depth in self._creative_nodes(doc))
        except Exception:
            present = False
        if present and not node.remove():
            raise RuntimeError('Could not remove the unsuccessful pass layer')
        session['layers'].discard(identifier)
        group_id = result.get('clip_group_id')            # a clip_base layer sits alone in a group made for it: the group goes too
        if group_id:
            try:
                self._creative_node(doc, group_id).remove()
            except ValueError:
                pass                                       # an undo may have taken it already
            session.get('clip_groups', set()).discard(group_id)
            session['layers'].discard(group_id)

    def _creative_stock_strokes(self, doc, session, params, result):
        """Stock Krita (frozen): the pass through the native helper when Krita loaded it, else stroke by stroke through
        the Python API, under the stage mask swapped in as the document selection; then the strokes' reach recomposited."""
        # The stage mask clips the complete brush footprint, not only
        # its path center. Restore the artist's selection afterwards.
        # Its inner edges fade in (stage_mask.py): a hard rectangle printed a straight band into open paint.
        selection = doc.selection()
        if params.get('region'):
            from .stage_mask import mask as stage_mask
            x, y, w, h = params['region']
            mask = Selection()
            mask.setPixelData(stage_mask(params['region'], doc.width(), doc.height()).tobytes(), x, y, w, h)
            doc.setSelection(mask)
        else:
            doc.setSelection(None)
        try:
            strokes, node, responded, interrupted = params['strokes'], doc.activeNode(), time.monotonic(), None
            # With the native helper loaded, the chunk is queued in a few calls with no view update per stroke
            # (agent_accel.paint_strokes); without it, stroke by stroke through the Python API as before.
            native = self._creative_native_strokes(doc, session, strokes, node)
            # Only the helper can paint the pen (pressure, tilt, rotation, speed, time); without it the pass paints
            # as a mouse at full pressure, and a helper before protocol 5 paints pressure alone. Each input says which.
            for name in PEN_INPUTS:
                if any(name in stroke for stroke in strokes):
                    result[name] = ('ignored: Krita has not loaded the native helper' if native is None else
                                    'ignored: the native helper predates tilt, rotation, speed and time (protocol 5)'
                                    if name in native.get('ignored', ()) else 'applied')
            if native is not None:
                result['native_strokes'] = native
                if 'stopped_after_strokes' in native:
                    result.update(stopped='Stopped by the artist.', stopped_after_strokes=native['stopped_after_strokes'], strokes_total=len(strokes))
                strokes = []
            for index, stroke in enumerate(strokes):
                # Stop ends the pass cleanly after the current stroke: a definite, shorter pass, not an uncertain one.
                if interrupted or stop_requested.is_set():
                    result.update(stopped=interrupted or 'Stopped by the artist.', stopped_after_strokes=index, strokes_total=len(strokes))
                    break
                self._creative_progress(session, 'painting', 'Painting stroke %d of %d' % (index + 1, len(strokes)))
                # Krita renders each stroke; waiting and recompositing the whole canvas
                # after every stroke made a pass dozens of times slower, so it happens once.
                # The Python API paints as a mouse (cmd_curve_stroke refuses pressure): the curve alone.
                painted = self.cmd_curve_stroke({k: v for k, v in stroke.items() if k not in PEN_INPUTS}, settle=False)
                if painted.get('error'):
                    raise RuntimeError(painted['error'])
                if time.monotonic() - responded >= RESPONSIVE_SECONDS:
                    interrupted, responded = self._creative_let_krita_respond(doc, node), time.monotonic()
        finally:
            doc.waitForDone()                    # every stroke done before the selection changes back
            doc.setSelection(selection)
        # Only the strokes' reach changed: the layer's settings were composited when it was made (a new layer,
        # create_layer for a blended or clipped one) or are unchanged (a continuation). Recomposite that area
        # (canvas_projection: the fork, else the helper on stock), else the whole image as before.
        canvas_projection.refresh(doc, self._creative_stroke_rect(params))

    def _creative_native_strokes(self, doc, session, strokes, node):
        """Paint the pass's strokes through the native helper, or None when Krita has not loaded it."""
        try:
            from . import agent_accel
        except ImportError:
            return None
        if not agent_accel.NATIVE_STROKES and not any(name in stroke for stroke in strokes for name in PEN_INPUTS):
            return None
        self._creative_progress(session, 'painting', 'Painting %d strokes' % len(strokes))
        return agent_accel.paint_strokes(doc.fileName() or '', node.uniqueId().toString(), strokes,
                                         {'size': getattr(self, 'current_brush_size', None), 'opacity': getattr(self, 'current_opacity', None)},
                                         stop=stop_requested.is_set)

    def _creative_observe(self, doc, session, region=None, guides=True):
        # Where an observation's time goes: Krita's recomposite (refresh) against the plugin's own work
        # on the full-size canvas (read, revision hash, view encode, details). The canvas operation reports it.
        # guides=False: the view is the painting without the agent's guide lines (guide_craft.py), for judging it;
        # the revision is still the painting's own. With guides showing, a look that keeps them also saves the view
        # without them (unguided_path), which the pass history and Luna compare.
        parts, clock = {}, [time.monotonic()]
        def lap(part):
            now = time.monotonic(); parts[part] = int((now - clock[0]) * 1000); clock[0] = now
        # A full recomposite reruns every filter mask; skip it right after a pass that just did one.
        if not session.pop('projection_fresh', False):
            doc.refreshProjection()
        doc.waitForDone()
        lap('refresh')
        projection = doc.projection(0, 0, doc.width(), doc.height())
        if projection.isNull():
            raise RuntimeError('Could not read the canvas projection')
        lap('read')
        revision = self._creative_revision(doc, projection)
        lap('revision')
        if region:
            self._creative_region(region, doc.width(), doc.height())
        unguided, guides_note = None, None
        if not guides or session.get('unguided_views'):   # the view without guides only for whoever judges it
            try:
                unguided, guides_note = self._guide_unguided(doc, projection, region, session)
            except Exception as error:                   # a look must never fail for its guides: they stay in it
                guides_note = 'The guide lines could not be left out of this view: ' + str(error)
        lap('guides')
        shown = unguided if unguided is not None and not guides else projection
        image = self._creative_view_image(doc, shown, region, scaled_read=shown is projection)
        lap('scale')
        scale = round(image.width() / (region[2] if region else doc.width()), 3)
        previews = os.path.join(session['output'], '.previews')
        os.makedirs(previews, exist_ok=True)
        filename = self._creative_save_view(previews, image, region)
        unguided_path = None
        if unguided is not None and guides:
            unguided_path = self._creative_save_view(previews, self._creative_view_image(doc, unguided, region, scaled_read=False), region)
        lap('view')
        # The details, each timed: on merged New Moscow they took 270 ms an observation together (runs 5-8).
        layers = self._creative_layer_list(doc); lap('layers')
        # Whole-canvas views say how much of the canvas is painted, so a blank document is not taken for a painting.
        painted = None if region else self._creative_painted_share(shown); lap('painted')
        with open(filename, 'rb') as stream:
            content_id = hashlib.sha256(stream.read()).hexdigest()
        lap('content')
        weight = self._creative_weight(doc); lap('weight')
        focus = self._view_artist_focus(doc); lap('focus')
        comic = self._comic_model(session); lap('comic')
        protected = self._protect_active(doc); lap('protected')
        captured_at = time.time()
        observation = {'status': 'ok', 'document_id': session['document_id'], 'name': doc.name(),
                'width': doc.width(), 'height': doc.height(), 'image_path': filename,
                'path': filename, 'revision': revision, 'content_id': content_id, 'captured_at': captured_at, 'region': region,
                'image_width': image.width(), 'image_height': image.height(), 'scale': scale,
                'layers': layers, 'weight': weight, 'filename': doc.fileName(), 'modified': doc.modified(),
                **({'painted_share': painted} if painted is not None else {}),
                'observed_at': captured_at, 'artist_focus': focus, 'comic': comic, 'protected_areas': protected}
        if unguided_path:
            observation['unguided_path'] = unguided_path
        if unguided is not None and not guides:
            observation['guides_hidden'] = True
        if guides_note:
            observation['guides_note'] = guides_note
        session['observe_ms'] = parts
        return observation

    def _creative_save_view(self, previews, image, region):
        """Save a view image in the previews folder: its path."""
        # The whole-canvas view goes to the model after every action and stays in the chat log:
        # as a 1024-px PNG it was ~1.2 MB per action, as JPEG ~0.2 MB with no difference a model
        # can use. Zoomed crops (texture detail) and canvases with transparency stay PNG.
        jpeg = not region and not self._creative_has_transparency(image)
        filename = os.path.join(previews, 'view-' + uuid.uuid4().hex + ('.jpg' if jpeg else '.png'))
        if not image.save(filename, 'JPEG' if jpeg else 'PNG', VIEW_JPEG_QUALITY if jpeg else -1):
            raise RuntimeError('Could not save the canvas observation')
        return filename

    @staticmethod
    def _creative_guides_flag(params):
        """An observe's or peek's guides flag as keyword arguments for _creative_observe ({} for the default, true)."""
        guides = params.get('guides', True)
        if not isinstance(guides, bool):
            raise ValueError('guides must be true or false')
        return {} if guides else {'guides': False}

    def _creative_view_image(self, doc, projection, region=None, scaled_read=True):
        """The view the model sees: the canvas, or `region` of it, shrunk to VIEW_SIDE when larger. A larger crop would
        be shrunk by the model API anyway, without the model knowing: shrink it here and report the scale, so "actual
        pixels" is only claimed when it is true. On the fork one scaled read of the area (canvas_projection.read_scaled,
        area-averaged as Qt's smooth scale); else the full-size projection already read for the revision, cropped and
        scaled with Qt. scaled_read=False: `projection` is an image the plugin made (the painting without guides), so it is
        always the one scaled."""
        area = list(region) if region else [0, 0, doc.width(), doc.height()]
        side = max(area[2], area[3])
        if side > VIEW_SIDE and scaled_read:
            image = canvas_projection.read_scaled(doc, area, VIEW_SIDE / side)
            if image is not None:
                return image
        image = projection.copy(*region) if region else projection
        if side > VIEW_SIDE:
            image = image.scaled(VIEW_SIDE, VIEW_SIDE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return image

    def _creative_stroke_rect(self, params):
        """[x, y, w, h] a paint pass's strokes can have changed: protection's reach (points widened well past the
        brush, cut to the pass's region), or None when unknown."""
        reach = self._protect_reach(params, 'paint_pass')
        return None if reach is None else [reach[0], reach[1], reach[2] - reach[0], reach[3] - reach[1]]

    def _creative_seam_candidates(self, doc, session):
        """Candidate seams of the visible painting with a close-up of each (seams.py), or [] when it cannot look."""
        try:
            import numpy as np
            from . import seams
            projection = doc.projection(0, 0, doc.width(), doc.height())
            try:
                clean, _note = self._guide_unguided(doc, projection, None, session)   # a guide line is never a seam
            except Exception:
                clean = None
            bgra = self._creative_image_bgra(clean if clean is not None else projection)
            started = time.monotonic()
            found = seams.close_ups(bgra, seams.candidates(bgra), os.path.join(session['output'], '.seams'))
            session.setdefault('observe_ms', {})['seams'] = int((time.monotonic() - started) * 1000)
            return found
        except Exception:
            return []                                    # a hint must never stop an observation

    @staticmethod
    def _creative_image_bgra(image):
        """An image's pixels as a numpy array (height x width x BGRA)."""
        import numpy as np
        from .qt_compat import QImage, image_bytes
        return np.frombuffer(image_bytes(image.convertToFormat(QImage.Format.Format_ARGB32)), np.uint8).reshape(image.height(), image.width(), 4)

    def _creative_painted_share(self, projection):
        from .qt_compat import QImage
        thumb = projection.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGBA8888)
        line, width = thumb.bytesPerLine(), thumb.width() * 4
        raw = thumb.constBits().asstring(thumb.sizeInBytes())
        return painted_share(b''.join(raw[row * line:row * line + width] for row in range(thumb.height())))

    def _creative_has_transparency(self, image):
        if not image.hasAlphaChannel():
            return False
        from .qt_compat import QImage
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        alphas = rgba.constBits().asstring(rgba.sizeInBytes())[3::4]
        return alphas.count(255) != len(alphas)

    def _creative_layer_list(self, doc):
        layers = []
        def visit(node, depth=0):
            for child in node.childNodes():
                key = child.uniqueId().toString()
                layers.append({'id': key, 'name': child.name(), 'depth': depth,
                               'opacity': child.opacity() / 255, 'visible': child.visible(),
                               'editable_by_agent': not child.locked(), 'type': child.type()})
                visit(child, depth + 1)
        visit(doc.rootNode())
        return layers

    def _creative_region(self, region, width, height):
        if not isinstance(region, list) or len(region) != 4:
            raise ValueError('Region must be [x,y,width,height]')
        x, y, w, h = region
        for value in region:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError('Region coordinates must be integers')
        if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
            raise ValueError('Region must fit the canvas')
