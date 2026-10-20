"""Merge accepted stroke passes into one layer: fewer layers once the artist no longer needs per-pass undo.

Runs inside the creative operation journal (creative_tools.py). Called when the artist keeps an
Agent move and when an Autopilot review passes. Only adjacent plain stroke layers in the same
group merge, so the picture looks the same: normal blend, no clipping, no masks, unlocked,
visible and unchanged since the agent painted them. Craft layers (fills, clipped shadow, light
and texture, filters) stay separate. One call merges one run of layers into a new layer below
it and records one pass; the merged passes point to it (`merged_into`) and leave the history.
"""
from .creative_validation import fields, text

MERGE_FIELDS = ('stage_id', 'name', 'expected_revision')


class MergeCraft:
    def _merge_runs(self, doc, session):
        """Runs (bottom to top) of adjacent mergeable stroke layers for the stage, with their passes."""
        stage = session['merge_stage']
        passes = [e for e in session.get('passes', []) if e.get('layer_id') and not e.get('merged_into')]
        latest = {e['layer_id']: e for e in passes}
        mine = {e['layer_id'] for e in passes if e.get('stage_id') == stage}
        eligible = {}
        for identifier in mine:
            entry = latest[identifier]
            if entry.get('rejected') or entry['kind'] not in ('paint_pass', 'merge_passes') or entry.get('clip') or entry.get('source_layer_id'):
                continue
            try:
                node = self._creative_node(doc, identifier)
            except ValueError:
                continue
            if (node.type() != 'paintlayer' or node.blendingMode() != 'normal' or node.inheritAlpha() or node.childNodes()
                    or node.locked() or not node.visible() or self._guide_in_group(node)):    # guides are never merged
                continue
            state = self._creative_layer_state(node, doc)
            if any(state[key] != entry['after'][key] for key in ('pixels', 'opacity', 'visible')):
                continue                                   # the artist changed it: leave it as it is
            eligible[identifier] = node
        runs, seen = [], set()
        for node in eligible.values():
            parent = node.parentNode()
            key = parent.uniqueId().toString()
            if key in seen:
                continue
            seen.add(key)
            run = []
            for child in parent.childNodes() + [None]:
                if child is not None and child.uniqueId().toString() in eligible:
                    run.append(child)
                    continue
                if len(run) >= 2:
                    runs.append(run)
                run = []
        return runs

    def _merge_validate(self, doc, session, params):
        fields(params, MERGE_FIELDS, ('stage_id',))
        text(params['stage_id'], 'stage_id', 100)
        if 'name' in params:
            text(params['name'], 'name', 120)
        self._craft_check_rgba(doc, 'Merging passes')

    def _merge_apply(self, doc, session, params):
        session['merge_stage'] = params['stage_id']
        try:
            runs = self._merge_runs(doc, session)
        finally:
            session.pop('merge_stage', None)
        if not runs:
            return {'merged_layers': 0, 'remaining_runs': 0}
        run = max(runs, key=len)
        parent = run[0].parentNode()
        base = doc.createNode(params.get('name') or 'Merged passes', 'paintlayer')
        if base is None or not self._craft_insert_below(doc, run[0], base):
            raise RuntimeError('Could not create the merged layer.')
        current = base
        for node in run:                                   # bottom to top, each onto the merged layer below it
            ids = lambda: [child.uniqueId().toString() for child in parent.childNodes()]
            position = ids().index(current.uniqueId().toString())
            doc.waitForDone()
            self._feature_merge_down(doc, node)
            doc.waitForDone()
            # Krita replaces both layers with a new one in the lower one's place; find it there.
            if node.uniqueId().toString() in ids():
                raise RuntimeError('Krita could not merge "%s".' % node.name())
            current = parent.childNodes()[position]
        current.setName(params.get('name') or 'Merged passes')
        doc.refreshProjection()
        old = {node.uniqueId().toString() for node in run}
        identifier = current.uniqueId().toString()
        session['layers'] -= old
        session['layers'].add(identifier)
        operation = session.get('operation_id')
        merged_ids = []
        for entry in session.get('passes', []):
            if entry.get('layer_id') in old and not entry.get('merged_into'):
                entry['merged_into'] = operation
                merged_ids.append(entry['id'])
        return {'layer_id': identifier, 'layer_type': 'merged', 'merged_layers': len(run),
                'merged_pass_ids': merged_ids, 'remaining_runs': len(runs) - 1}
