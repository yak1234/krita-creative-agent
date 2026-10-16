"""Document-bound creative sessions on the existing native Krita painting engine."""
import hashlib
import json
import os
import re
import time
import uuid
from krita import Krita, Selection
from PyQt5.QtCore import Qt, QCoreApplication
from .creative_validation import fields, numeric, text, color, validate_pass
from .creative_document_identity import document_id, open_documents
from .layer_craft import LayerCraft
from .region_craft import RegionCraft
from .filters import FilterCraft
from .colorize import ColorizeCraft
from .transform_craft import TransformCraft
from .canvas_view import CanvasView
from .comic import ComicCraft
from .merge_craft import MergeCraft
from .journal_store import Journal
import importlib
import threading
# command_queue is not hot-reloaded: after a plugin-only reload into a Krita started with an older
# copy, the flag is missing until Krita restarts, and Stop works as before (between actions).
stop_requested = getattr(importlib.import_module('.command_queue', __package__), 'stop_requested', None) or threading.Event()

# During a stroke pass, Krita handles clicks this often (Stop, the window) instead of freezing for the whole pass.
RESPONSIVE_SECONDS = 0.2

# A full .kra save after every action dominated small actions. Painting actions save
# every CHECKPOINT_EVERY actions or CHECKPOINT_SECONDS, and always on `checkpoint`,
# `end` and pass review; in between they only re-read the canvas.
CHECKPOINT_EVERY = 8
# Pass kinds that add a new agent layer or mask.
NEW_CONTRIBUTIONS = ('paint_pass', 'create_layer', 'fill_region', 'apply_filter', 'colorize_flats', 'transform_layer', 'comic_page', 'letter', 'merge_passes')
CHECKPOINT_SECONDS = 300
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


class CreativeTools(LayerCraft, RegionCraft, FilterCraft, ColorizeCraft, TransformCraft, CanvasView, ComicCraft, MergeCraft):
    def cmd_creative(self, request):
        fields(request, ('operation', 'session_id', 'operation_id', 'params'), ('operation', 'params'))
        operation = request['operation']
        params = request['params']
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        if operation == 'health':
            return {'status': 'ok', 'creative_version': '1.0.0', 'protocol_version': 2, 'build': CREATIVE_BUILD, 'krita_version': Krita.instance().version(),
                    'capabilities': self._creative_adapter_capabilities(), 'native_paths': True, 'session_active': bool(getattr(self, '_creative_session', None))}
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
        if operation == 'model_image':
            from .creative_reference import model_image
            return model_image(params)
        if operation == 'jpeg_copy':
            from .creative_reference import jpeg_copy
            return jpeg_copy(params)
        if operation == 'begin':
            return self._creative_begin(request)
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
            fields(params, ('output_dir', 'document_id', 'region', 'refresh'), ('output_dir',))
            if not isinstance(params.get('refresh', True), bool):
                raise ValueError('refresh must be boolean')
            destination = self._creative_output(request)
            doc = self._creative_document(params.get('document_id'))
            if doc is None:
                return {'status': 'ok', 'state': 'none', 'message': 'No canvas is open.'}
            return self._creative_observe(doc, {'output': destination, 'layers': set(),
                'document_id': document_id(doc), 'projection_fresh': not params.get('refresh', True)}, params.get('region'))
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
            samples = []
            for x, y in points:
                pixel = projection.pixelColor(x, y)
                samples.append({'position': [x, y], 'hex': '#%02x%02x%02x' % (pixel.red(), pixel.green(), pixel.blue()),
                                'rgba': [pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()]})
            return {'status': 'ok', 'document_id': document_id(doc),
                    'revision': self._creative_revision(doc, projection), 'samples': samples,
                    'source': 'Rendered canvas projection, 8-bit RGBA. These are observed colours, not an invented palette.'}
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
            if session.get('unsaved_operations'):
                active = self.get_active_document()
                if active is not None and document_id(active) == session['document_id']:
                    try:
                        flushed = self._creative_checkpoint(active, session).get('checkpoint')
                    except Exception as error:
                        return {'error': 'Could not save the last actions: ' + str(error), 'error_code': 'checkpoint_failed'}
            if session.get('guides_prior') is not None:
                try:
                    self._guides_restore(self._creative_document(session['document_id']), session)
                except ValueError:
                    pass                                 # the painting was closed; its guides went with it
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
            return dict(self._creative_checkpoint(doc, session), status='ok')
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
            fields(params, ('region',))
            return self._creative_observe(doc, session, params.get('region'))
        if operation == 'select':
            # Saved to the study folder; not a canvas change, so no pass or checkpoint.
            return self._region_select(doc, session, params)
        if operation == 'guides':
            # A view aid, not paint: no pass or checkpoint; restored when the chat ends.
            return self._guides_set(doc, session, params)
        if operation == 'list_brushes':
            fields(params, ('filter',))
            # The whole library: the companion adds a measured card to every preset (brush-catalog.json).
            result = self.cmd_list_brushes({'filter': params.get('filter', ''), 'limit': 500})
            return result
        if operation == 'capabilities':
            return self._craft_capabilities(doc, params)
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
        if operation not in ('paint_pass', 'adjust_layer', 'painting_toolbox', 'review_pass', 'create_layer', 'set_layer', 'fill_region', 'apply_filter', 'colorize_flats', 'transform_layer', 'comic_page', 'letter', 'merge_passes'):
            raise ValueError('Unsupported creative operation')
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
        # Validate the whole pass before any layer or brush changes.
        if operation == 'paint_pass':
            validate_pass(params, doc.width(), doc.height(), Krita.instance().resources('preset'))
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
        else:
            return self._creative_review(doc, session, params, operation_id, fingerprint)
        if operation in ('paint_pass', 'create_layer', 'fill_region', 'apply_filter'):
            self._comic_validate_scope(doc, session, operation, params)
        # A continuation batch starts where the last one on its layer ended: reuse that image
        # instead of re-rendering the whole canvas (reference jobs send hundreds of batches).
        continued = operation == 'paint_pass' and params.get('continue_layer_id')
        before = ({'image_path': next((e.get('after_path') for e in reversed(session['passes'])
                                       if e.get('layer_id') == params['continue_layer_id']), None)}
                  if continued else self._creative_observe(doc, session))
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
        smudge_restore = False
        session['operation_id'] = operation_id
        self._view_message(doc, params.get('name') or params.get('filter') or operation.replace('_', ' '))
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
            elif operation == 'paint_pass':
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
                    smudge_restore = True
                if params.get('continue_layer_id'):
                    node = self._creative_node(doc, params['continue_layer_id'])
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
                # The stage mask clips the complete brush footprint, not only
                # its path center. Restore the artist's selection afterwards.
                selection = doc.selection()
                if params.get('region'):
                    mask = Selection()
                    mask.select(*params['region'], 255)
                    doc.setSelection(mask)
                else:
                    doc.setSelection(None)
                try:
                    strokes, node, responded, interrupted = params['strokes'], doc.activeNode(), time.monotonic(), None
                    for index, stroke in enumerate(strokes):
                        # Stop ends the pass cleanly after the current stroke: a definite, shorter pass, not an uncertain one.
                        if interrupted or stop_requested.is_set():
                            result.update(stopped=interrupted or 'Stopped by the artist.', stopped_after_strokes=index, strokes_total=len(strokes))
                            break
                        self._creative_progress(session, 'painting', 'Painting stroke %d of %d' % (index + 1, len(strokes)))
                        # Krita renders each stroke; waiting and recompositing the whole canvas
                        # after every stroke made a pass dozens of times slower, so it happens once.
                        painted = self.cmd_curve_stroke(stroke, settle=False)
                        if painted.get('error'):
                            raise RuntimeError(painted['error'])
                        if time.monotonic() - responded >= RESPONSIVE_SECONDS:
                            interrupted, responded = self._creative_let_krita_respond(doc, node), time.monotonic()
                finally:
                    doc.waitForDone()                    # every stroke done before the selection changes back
                    doc.setSelection(selection)
                doc.refreshProjection()
                session['projection_fresh'] = True       # the observation after this skips a second recomposite
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
            if smudge_restore:
                self.cmd_restore_brush({})           # the artist's preset never keeps overlay mode
            if prior_node is not None:
                doc.setActiveNode(prior_node)
        if operation == 'merge_passes' and result.get('status') == 'ok' and not result.get('merged_layers'):
            session['operations'][operation_id] = (fingerprint, result)     # nothing merged: no canvas change, no checkpoint
            self._creative_store_operations(session, operation_id)
            return result
        if result.get('error_code') == 'validation_rejected':
            result['reconciled'] = True
            session['operations'][operation_id] = (fingerprint, result)
            self._creative_store_operations(session, operation_id)
            return result
        try:
            checkpoint = self._creative_commit_view(doc, session)
            result.update({key: value for key, value in checkpoint.items() if key != 'status'})
        except Exception as error:
            result.update(status='partial', error='Checkpoint failed: ' + str(error), error_code='checkpoint_failed')
        layer_id = result.get('layer_id', params.get('layer_id'))
        if result.get('contribution_removed'): layer_id = None
        try:
            if layer_id and operation in NEW_CONTRIBUTIONS:
                self._creative_settle_containers(doc, session, self._creative_node(doc, layer_id))
            if layer_id:
                state = self._creative_layer_state(self._creative_node(doc, layer_id), doc)
                entry = dict(id=operation_id, title=params.get('name') or {'fill_region': 'Region fill', 'apply_filter': params.get('filter'), 'colorize_flats': 'Colorized flats', 'transform_layer': 'Transform', 'comic_page': 'Comic page', 'letter': 'Lettering', 'merge_passes': 'Merged passes'}.get(operation) or 'Layer adjustment', kind=operation,
                             stage_id=params.get('stage_id'), region=params.get('region'), layer_id=layer_id,
                             continuation_of=params.get('continue_layer_id'),
                             group_id=result.get('group_id'),
                             projection_region=result.get('projection_region'),
                             projection_feather=result.get('projection_feather'),
                             before_path=before.get('image_path'), after_path=result.get('image_path'),
                             source_layer_id=result.get('source_layer_id'), source_prior=result.get('source_prior'),
                             source_after=result.get('source_after'),
                             clip=result.get('clip'), clip_group_id=result.get('clip_group_id'),
                             layer_type=result.get('layer_type'),
                             filter=result.get('filter'), filter_mode=result.get('mode'), target_id=result.get('target_id'),
                             comic=result.get('comic'), panel=params.get('panel'), merged_pass_ids=result.get('merged_pass_ids'),
                             prior=prior, after=state, strength=state['opacity'] / 255,
                             visible=state['visible'], rejected=False)
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
                                'Painting saved' if result['status'] == 'ok' else result.get('error', 'Painting paused'))
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
        self._creative_session = session
        try:
            if p['mode'] == 'resume':
                # Binding a conversation is an observation, never a native save.
                return dict(self._creative_observe(doc, session), status='ok', session_id=identifier,
                            passes=self._creative_passes(session), unresolved_operations=self._creative_unresolved(session),
                            committed_operation_count=self._creative_committed_count(session))
            return dict(self._creative_checkpoint(doc, session), status='ok', session_id=identifier)
        except Exception as error:
            if p['mode'] == 'resume':
                if session.get('journal'):
                    session['journal'].close()
                self._creative_session = None
                return {'error': 'Could not inspect this painting: ' + str(error),
                        'error_code': 'observation_failed', 'session_id': identifier}
            return {'error': 'The study was created but its checkpoint failed: ' + str(error),
                    'error_code': 'checkpoint_failed', 'session_id': identifier}

    def _creative_checkpoint(self, doc, session):
        self._creative_validate_save_target(doc, session)
        session['checkpoint'] += 1
        path = session.get('painting_path', os.path.join(session['output'], 'painting.kra'))
        # Follow a user-initiated Save As on this same bound document.
        current = doc.fileName() if hasattr(doc, 'fileName') else ''
        if session['checkpoint'] > 1 and current.lower().endswith('.kra'):
            path = os.path.realpath(current)
        session['painting_path'] = path
        self._creative_progress(session, 'saving', 'Saving ' + os.path.basename(path))
        doc.waitForDone()
        result = self.cmd_save_native({'path': path})
        if result.get('error'):
            raise RuntimeError(result['error'])
        session['saved_once'] = True
        session['unsaved_operations'] = 0
        session['last_saved_at'] = time.monotonic()
        self._creative_progress(session, 'observing', 'Reading the updated canvas')
        return dict(self._creative_observe(doc, session), checkpoint=path, save_number=session['checkpoint'])

    def _creative_commit_view(self, doc, session):
        # Save when due; otherwise only re-read the canvas and count the unsaved action.
        unsaved = session.get('unsaved_operations', 0) + 1
        due = (not session.get('saved_once') or unsaved >= CHECKPOINT_EVERY
               or time.monotonic() - session.get('last_saved_at', 0) >= CHECKPOINT_SECONDS)
        if due:
            return self._creative_checkpoint(doc, session)
        session['unsaved_operations'] = unsaved
        doc.waitForDone()
        return dict(self._creative_observe(doc, session), checkpoint_deferred=True, unsaved_operations=unsaved)

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
        top = children[-1] if children else None
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
        doc.refreshProjection(); doc.waitForDone()
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
        from PyQt5.QtCore import QPointF
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
                    if op == 'rotate': node.rotateNode(numeric(value.get('radians'), 'radians', -1000, 1000))
                    elif op == 'scale':
                        width = numeric(value.get('width'), 'width', 1, 100000)
                        height = numeric(value.get('height'), 'height', 1, 100000)
                        origin = value.get('origin', [0,0])
                        if not isinstance(origin,list) or len(origin)!=2: raise ValueError('origin must be [x,y]')
                        x,y = [numeric(v,'origin',-100000,100000) for v in origin]
                        strategy = value.get('strategy','Bicubic')
                        if strategy not in ('Bicubic','Bilinear','NearestNeighbor'): raise ValueError('Unknown scale strategy')
                        node.scaleNode(QPointF(x,y), int(width), int(height), strategy)
                    elif op == 'shear': node.shearNode(numeric(value.get('x',0),'x',-89,89), numeric(value.get('y',0),'y',-89,89))
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
        digest.update(projection.constBits().asstring(projection.byteCount()))
        manifest = [(n.uniqueId().toString(), n.name(), n.opacity(), n.visible(), n.locked(), depth)
                    for n, depth in self._creative_nodes(doc)]
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
                    entry['after_path'] = checkpoint['image_path']
                self._creative_store_passes(session)
        except Exception as error:
            result.update(status='partial', error='Checkpoint failed: ' + str(error), error_code='checkpoint_failed')
        result['affected_pass_ids'] = [entry['id'] for entry in affected]
        result['passes'] = self._creative_passes(session)
        session['operations'][operation_id] = (fingerprint, result)
        self._creative_store_operations(session, operation_id)
        self._creative_progress(session, 'saved' if result['status'] == 'ok' else 'error',
                                'Review saved' if result['status'] == 'ok' else result.get('error', 'Review paused'))
        return result

    def _creative_let_krita_respond(self, doc, node):
        """Let Krita's window and the panel (Stop) handle events during a stroke pass. Strokes go to
        the active layer of the active document, so a click elsewhere is undone or ends the pass."""
        QCoreApplication.processEvents()
        active = self.get_active_document()
        if active is None or document_id(active) != document_id(doc):
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

    def _creative_observe(self, doc, session, region=None):
        # A full recomposite reruns every filter mask; skip it right after a pass that just did one.
        if not session.pop('projection_fresh', False):
            doc.refreshProjection()
        doc.waitForDone()
        projection = doc.projection(0, 0, doc.width(), doc.height())
        if projection.isNull():
            raise RuntimeError('Could not read the canvas projection')
        revision = self._creative_revision(doc, projection)
        if region:
            self._creative_region(region, doc.width(), doc.height())
            image = projection.copy(*region)
        else:
            image = projection
        # A larger crop would be shrunk by the model API anyway, without the model knowing: shrink
        # it here and report the scale, so "actual pixels" is only claimed when it is true.
        if max(image.width(), image.height()) > VIEW_SIDE:
            image = image.scaled(VIEW_SIDE, VIEW_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scale = round(image.width() / (region[2] if region else doc.width()), 3)
        previews = os.path.join(session['output'], '.previews')
        os.makedirs(previews, exist_ok=True)
        # The whole-canvas view goes to the model after every action and stays in the chat log:
        # as a 1024-px PNG it was ~1.2 MB per action, as JPEG ~0.2 MB with no difference a model
        # can use. Zoomed crops (texture detail) and canvases with transparency stay PNG.
        jpeg = not region and not self._creative_has_transparency(image)
        filename = os.path.join(previews, 'view-' + uuid.uuid4().hex + ('.jpg' if jpeg else '.png'))
        if not image.save(filename, 'JPEG' if jpeg else 'PNG', VIEW_JPEG_QUALITY if jpeg else -1):
            raise RuntimeError('Could not save the canvas observation')
        layers = self._creative_layer_list(doc)
        with open(filename, 'rb') as stream:
            content_id = hashlib.sha256(stream.read()).hexdigest()
        captured_at = time.time()
        return {'status': 'ok', 'document_id': session['document_id'], 'name': doc.name(),
                'width': doc.width(), 'height': doc.height(), 'image_path': filename,
                'path': filename, 'revision': revision, 'content_id': content_id, 'captured_at': captured_at, 'region': region,
                'image_width': image.width(), 'image_height': image.height(), 'scale': scale,
                'layers': layers, 'filename': doc.fileName(), 'modified': doc.modified(),
                'observed_at': captured_at, 'artist_focus': self._view_artist_focus(doc), 'comic': self._comic_model(session)}

    def _creative_has_transparency(self, image):
        if not image.hasAlphaChannel():
            return False
        from PyQt5.QtGui import QImage
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        alphas = rgba.constBits().asstring(rgba.byteCount())[3::4]
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
