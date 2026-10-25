"""Merge accepted stroke passes into one layer: fewer layers once the artist no longer needs per-pass undo.

whole (layer-plan goal 4, Met merges): the stage's own groups merge whole, each into one paint layer in its place, named
(and locked with lock, for the kept underpainting: goal 1). A group merges whole when it shows as it would on its own:
visible, unlocked, normal blend, not pass-through, no clipping, holding only the agent's layers (a Finish or accents
group's own layers count as the agent's) and never the guides. Its hidden leftovers (rejected passes, replaced
originals) go with it (goal 5), and every pass inside points to the merged layer. On the fork Krita merges the group as it
renders it (Document.mergeGroups); elsewhere the group's projection is copied to a new layer. A group that cannot merge
whole falls back to the runs below.

Runs inside the creative operation journal (creative_tools.py). Called when the artist keeps an
Agent move and when an Autopilot review passes. Only adjacent plain stroke layers in the same
group merge, so the picture looks the same: normal blend, no clipping, no masks, unlocked,
visible and unchanged since the agent painted them. Craft layers (fills, clipped shadow, light
and texture, filters) stay separate. One call merges one run of layers into a new layer below
it and records one pass; the merged passes point to it (`merged_into`) and leave the history.
"""
from .creative_validation import fields, text

MERGE_FIELDS = ('stage_id', 'name', 'whole', 'lock', 'expected_revision')


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
        for key in ('whole', 'lock'):
            if not isinstance(params.get(key, False), bool):
                raise ValueError('%s must be true or false' % key)
        self._craft_check_rgba(doc, 'Merging passes')

    def _merge_whole_groups(self, doc, session):
        """The stage's groups that merge whole (see the module docstring), oldest first, each with its nodes inside."""
        stage = session['merge_stage']
        entries = [e for e in session.get('passes', []) if e.get('stage_id') == stage and not e.get('merged_into')]
        recorded = {e['layer_id'] for e in session.get('passes', []) if e.get('layer_id')}
        owned = set(session.get('layers', ())) | recorded
        guides = self._guide_group(doc)
        found, seen = [], set()
        for entry in entries:
            identifier = entry.get('group_id')
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            try:
                group = self._creative_node(doc, identifier)
            except ValueError:
                continue
            if (group.type() != 'grouplayer' or not group.visible() or group.locked() or group.blendingMode() != 'normal'
                    or group.inheritAlpha() or not group.childNodes() or self._guide_holds(group, guides)
                    or (hasattr(group, 'passThroughMode') and group.passThroughMode())):
                continue
            inside, mine = [], True
            def walk(node, agent):
                nonlocal mine
                for child in node.childNodes():
                    key = child.uniqueId().toString()
                    # A pass's own layer (a Finish or accents group) holds only what that operation made.
                    if not (agent or key in owned) or self._guide_is_group(child, doc):
                        mine = False
                    inside.append(child)
                    walk(child, agent or key in recorded)
            walk(group, False)
            if mine:
                found.append((group, inside))
        return found

    def _merge_group(self, doc, session, params, group, inside, remaining):
        """One group into one paint layer in its place."""
        name = params.get('name') or 'Merged passes'
        parent = group.parentNode()
        doc.waitForDone()
        if hasattr(doc, 'mergeGroups'):
            merged = doc.mergeGroups([group])
            if merged is None:
                raise RuntimeError('Krita could not merge "%s".' % group.name())
        else:
            rect = group.bounds()
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            merged = doc.createNode(name, 'paintlayer')
            if merged is None:
                raise RuntimeError('Could not create the merged layer.')
            if w > 0 and h > 0 and merged.setPixelData(group.projectionPixelData(x, y, w, h), x, y, w, h) is False:
                raise RuntimeError('Krita rejected the merged layer pixels.')
            merged.setOpacity(group.opacity())
            if not parent.addChildNode(merged, group):
                raise RuntimeError('Could not add the merged layer.')
            group.remove()
        doc.waitForDone()
        merged.setName(name)
        if params.get('lock'):
            merged.setLocked(True)
        doc.refreshProjection()
        old = {node.uniqueId().toString() for node in inside} | {group.uniqueId().toString()}
        identifier = merged.uniqueId().toString()
        session['layers'] -= old
        session.get('clip_groups', set()).difference_update(old)
        session['layers'].add(identifier)
        operation = session.get('operation_id')
        merged_ids = []
        for entry in session.get('passes', []):
            if (entry.get('layer_id') in old or entry.get('group_id') in old) and not entry.get('merged_into'):
                entry['merged_into'] = operation
                merged_ids.append(entry['id'])
        return {'layer_id': identifier, 'layer_type': 'merged', 'merged_layers': len(old), 'merged_pass_ids': merged_ids,
                'remaining_runs': remaining, 'whole': True, 'locked': bool(params.get('lock'))}

    def _merge_apply(self, doc, session, params):
        session['merge_stage'] = params['stage_id']
        try:
            groups = self._merge_whole_groups(doc, session) if params.get('whole') else []
            runs = [] if groups else self._merge_runs(doc, session)
        finally:
            session.pop('merge_stage', None)
        if groups:
            group, inside = groups[0]
            return self._merge_group(doc, session, params, group, inside, len(groups) - 1)
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
