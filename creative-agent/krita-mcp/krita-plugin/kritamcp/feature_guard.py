# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin's use of the fork's features and protection (krita-fork 6.6).

In our Krita a painting has named features ("Sky", "Moon", "Buildings") and the artist can protect some of them: Krita
then keeps the agent's writes out. This module is the plugin's side of that:

  * `agent_writing(doc)` wraps a writing tool call in Document.setAgentActive(True) ... (False), so Krita knows the raw
    writes (setPixelData, filters, cut and paste) are the agent's and keeps them out of protected features;
  * `reject_privileged(params)` refuses, before anything runs, the options that only the artist may confirm
    (allowProtected, suspending protection, unprotecting, removing a feature): a model never reaches them;
  * `FeatureCraft` resolves feature names and expressions ("Sky - Moon") to selections through Document.selection(),
    pre-checks the node operations Krita refuses next to a protected feature, limits filter layers, filter masks and fill
    layers with Document.protectedSelection(), lists the features, and lets the artist's panel (never the model) protect
    and unprotect them.

Everything here needs our Krita and does nothing on a document without the fork's methods: there is no stock fallback.
"""
import contextlib
import json
import unicodedata

# Keys that lift or change protection. Compared without case, underscores and hyphens, at any depth of a call.
PRIVILEGED = ('allowprotected', 'setprotectionsuspended', 'protectionsuspended', 'setprotected', 'removefeature')
# Operations that change a feature or its protection: the artist's panel only, never a model's tool call.
PANEL_ONLY = ('feature_set_protected', 'feature_remove', 'feature_undo')
EXPRESSION_LIMIT = 2000
FORK_ONLY = 'Feature names need our Krita (the fork): this Krita has no features.'


def _plain(key):
    """A key as letters and digits only, lower case, Unicode-normalised: "allow.protected", "Allow-Protected", a non-breaking
    hyphen or a zero-width space inside it all become "allowprotected"."""
    return ''.join(c for c in unicodedata.normalize('NFKC', str(key)).lower() if c.isalnum())


def privileged_key(value, depth=0):
    """The first key anywhere in `value` (objects inside objects and lists, and JSON text inside strings, such as the
    toolbox's parameters_json) that lifts protection, or None."""
    if depth > 8:
        return None
    if isinstance(value, str):
        if value.lstrip()[:1] in ('{', '[') and len(value) < 1000000:
            try:
                return privileged_key(json.loads(value), depth + 1)
            except ValueError:
                return None
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if _plain(key) in PRIVILEGED:
                return key
            found = privileged_key(item, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = privileged_key(item, depth + 1)
            if found is not None:
                return found
    return None


def reject_privileged(params):
    key = privileged_key(params)
    if key is not None:
        raise ValueError("'%s' lifts or changes protection, which only the artist can confirm in the panel. Leave it out; "
                         "work around the protected feature or ask the artist." % key)


@contextlib.contextmanager
def agent_writing(doc):
    """Document.setAgentActive(True) for the block, off again after it, however it ends. A document without it (stock
    Krita, a test double) runs the block unchanged."""
    switch = getattr(doc, 'setAgentActive', None)
    if switch is None:
        yield
        return
    switch(True)
    try:
        yield
    finally:
        try:
            switch(False)
        except RuntimeError:
            pass                                     # the document was closed during the call


def merge_names(*lists):
    """Feature names from several records, each once, in the order first seen."""
    seen = []
    for names in lists:
        for name in names or ():
            if name not in seen:
                seen.append(str(name))
    return seen


def _quote_free(expression):
    return any(token in expression for token in (' + ', ' & ', ' - ', '(', '"'))


class FeatureCraft:
    # ----- availability ----------------------------------------------------------------------------------------------------
    @staticmethod
    def _feature_ready(doc):
        """True in our Krita: the document has features, queries and protection."""
        return all(hasattr(doc, name) for name in ('features', 'protectedSelection', 'protectionActive'))

    def _feature_names(self, doc):
        return [feature.name() for feature in doc.features()] if self._feature_ready(doc) else []

    def _feature_active(self, doc):
        """True when some feature is protected now (and protection is not suspended)."""
        return self._feature_ready(doc) and bool(doc.protectionActive())

    # ----- names and expressions -------------------------------------------------------------------------------------------
    def _feature_check_expression(self, doc, expression):
        """Validation: the document has features and the text could name some. Unknown names are found when it is used."""
        if not self._feature_ready(doc):
            raise ValueError(FORK_ONLY)
        if not isinstance(expression, str) or not expression.strip() or len(expression) > EXPRESSION_LIMIT:
            raise ValueError('A feature is a name or an expression such as "Sky - Moon" (1-%d characters).' % EXPRESSION_LIMIT)

    def _feature_selection(self, doc, expression):
        """A new Selection from features, through Document.selection(expression); a ValueError that names the features
        when Krita finds none (it answers None, with a warning)."""
        self._feature_check_expression(doc, expression)
        selection = doc.selection(expression)
        if selection is None:
            known = ', '.join(self._feature_names(doc)) or 'none'
            raise ValueError('No feature or feature expression matches "%s". Features: %s. Combine them with " + ", " & " and '
                             '" - " (spaces around each), and quote a name with a parenthesis in it.' % (expression, known))
        return selection

    # ----- reporting what Krita kept out -------------------------------------------------------------------------------------
    def _feature_kept_out(self, doc, *recorded):
        """The protected features Krita kept the call's writes out of, read while the call's agent move is still open.
        A move the call began is fresh (it starts again with each move), so its record is this call's. A move someone else
        holds open has a cumulative record: there only the last write's record is read (every write replaces it, even with
        nothing), so the caller must not read it for a call that wrote nothing. `recorded` are names the call already
        has, such as a stroke job's own keptOut()."""
        if not self._feature_ready(doc):
            return merge_names(*recorded)
        try:
            if self.__dict__.get('_feature_move_ours'):
                names = doc.agentMoveKeptOut() if hasattr(doc, 'agentMoveKeptOut') else []
            else:
                names = doc.lastKeptOut() if hasattr(doc, 'lastKeptOut') else []
        except RuntimeError:
            names = []                                   # the document was closed during the call
        return merge_names(names, *recorded)

    TOOLBOX_QUIET = ('set_brush', 'selection', 'modify_selection', 'eraser', 'blend_mode', 'layer_settings', 'brush_controls',
                     'configure_brush', 'restore_brush', 'set_color', 'set_brush_texture')

    @classmethod
    def _feature_call_writes(cls, operation, params):
        """False for a call that cannot write pixels (a toolbox call of settings only), whose kept_out must stay empty
        whatever the document's record says."""
        if operation == 'painting_toolbox':
            return any(isinstance(item, dict) and item.get('tool') not in cls.TOOLBOX_QUIET for item in params.get('commands') or [])
        return True

    def _feature_report(self, doc, result, *recorded):
        """Put `kept_out` (and why) in a tool result when protection kept a write out of features. Only what the call
        recorded while it ran (its result, the areas it left out, the names read inside its move): never the document's
        record now, which may be an earlier call's."""
        names = merge_names(result.get('kept_out'), self.__dict__.get('_feature_clipped'), *recorded)
        if names:
            result['kept_out'] = names
            # One vocabulary: a name reported as a feature is not also reported as a legacy protected area.
            legacy = [hit for hit in result.get('protected') or [] if (hit.get('name') if isinstance(hit, dict) else hit) not in names]
            if legacy:
                result['protected'] = legacy
            else:
                result.pop('protected', None)
            result.setdefault('kept_out_note', ('Krita kept part of this change out of the protected feature%s %s: the artist protected %s, '
                                       'so nothing there changes. Paint around %s, or ask the artist to lift the protection.'
                                       % ('s' if len(names) > 1 else '', ', '.join("'%s'" % n for n in names),
                                          'them' if len(names) > 1 else 'it', 'them' if len(names) > 1 else 'it')))      # a tool's own note (tool_craft) stays
        return result

    # ----- node operations Krita refuses next to a protected feature ------------------------------------------------------
    def _feature_protected_under(self, doc, node):
        """Names of the protected features the layer's pixels reach."""
        if not self._feature_active(doc):
            return []
        return [f.name() for f in doc.featuresOverlapping(node.bounds()) if f.isProtected()]

    def _feature_check_node(self, doc, node, what):
        """Krita refuses a transform, colour-space change or merge of a layer that reaches a protected feature: say so
        before it tries, naming the features."""
        names = self._feature_protected_under(doc, node)
        if names:
            raise ValueError("Cannot %s '%s': it reaches the protected %s %s, which the artist asked you to leave alone. Work on a "
                             "layer that stays clear of %s." % (what, node.name(), 'features' if len(names) > 1 else 'feature',
                                                                ', '.join("'%s'" % n for n in names), 'them' if len(names) > 1 else 'it'))

    def _feature_merge_down(self, doc, node):
        """node.mergeDown() with the refusal handled: Krita answers None (or false) and names the features."""
        merged = node.mergeDown()
        if not merged:
            names = self._feature_kept_out(doc)
            raise RuntimeError("Krita could not merge '%s'%s." % (node.name(), ': it reaches the protected ' + ', '.join(
                "'%s'" % n for n in names) if names else ''))
        return merged

    def _feature_transform(self, doc, node, what, call):
        """A node transform (rotate, scale, shear, crop): refused up front when the layer reaches a protected feature, and an
        answer of False from Krita (it refused) reported with the names."""
        self._feature_check_node(doc, node, what)
        if call() is False:
            names = self._feature_kept_out(doc)
            raise RuntimeError("Krita would not %s '%s'%s." % (what, node.name(), ': it reaches the protected ' + ', '.join(
                "'%s'" % n for n in names) if names else ''))

    def _feature_refuse_action(self, doc, entry):
        """A Krita action runs on the artist's selection and writes wherever it likes: no pixel action while a feature is
        protected. Selection actions only read."""
        if entry.get('kind', 'pixels') != 'selection' and self._feature_active(doc):
            raise ValueError("Krita action '%s' is not allowed while a feature is protected: actions are not kept out of it. "
                             "Use fill_region, a pass or a tool call instead, which Krita keeps out of the protected features."
                             % entry.get('id'))

    # ----- filter layers, filter masks and fill layers ----------------------------------------------------------------------
    def _feature_entirely_protected(self, doc, selection):
        """Names of the protected features when nothing of `selection` lies outside them (else empty): a change there
        would be clipped away whole."""
        if not self._feature_active(doc):
            return []
        hit = [f.name() for f in doc.featuresOverlapping(selection) if f.isProtected()]
        if not hit:
            return []
        rest = selection.duplicate()
        rest.subtract(doc.protectedSelection())
        return hit if rest.width() <= 0 or rest.height() <= 0 else []

    def _feature_limit_area(self, doc, area):
        """The area for a filter layer, filter mask or fill layer, without the protected features, so the new layer does not
        change how a protected feature looks (Krita does not clip these: they write no pixels). `area` is a fresh selection
        (changed in place) or None for the whole canvas. The features left out are recorded for the result's kept_out; an
        area that falls entirely inside protected features is an error."""
        if not self._feature_active(doc):
            return area
        if area is None:
            hit = [f.name() for f in doc.features() if f.isProtected()]
            limited = doc.protectedSelection(True)
        else:
            hit = [f.name() for f in doc.featuresOverlapping(area) if f.isProtected()]
            area.subtract(doc.protectedSelection())
            limited = area
        clipped = self.__dict__.setdefault('_feature_clipped', [])
        clipped.extend(name for name in hit if name not in clipped)
        if hit and (limited.width() <= 0 or limited.height() <= 0):
            raise ValueError("The area lies entirely inside the protected %s %s, so nothing would be left to change. Choose an area "
                             "outside %s." % ('features' if len(hit) > 1 else 'feature', ', '.join("'%s'" % n for n in hit),
                                              'them' if len(hit) > 1 else 'it'))
        return limited

    TOOLBOX_WRITES = ('stroke', 'curve_stroke', 'draw_shape', 'gradient', 'smart_patch', 'clear', 'fill', 'flood_fill')

    def _feature_protected_names(self, doc):
        return [f.name() for f in doc.features() if f.isProtected()] if self._feature_ready(doc) else []

    def _feature_refuse_toolbox(self, doc, commands):
        """painting_toolbox draws through the view's brush and Krita's shape and fill paths, which protection does not clip:
        while a feature is protected those commands are refused, with the tools that are kept out of protected features."""
        if not self._feature_active(doc):
            return
        writing = [item.get('tool') for item in commands if isinstance(item, dict) and item.get('tool') in self.TOOLBOX_WRITES]
        if writing:
            names = ', '.join("'%s'" % n for n in self._feature_protected_names(doc))
            raise ValueError("painting_toolbox cannot run %s while %s protected: its strokes, shapes and fills are not kept out of "
                             "protected features. Use paint_pass, fill_region, bucket_fill, krita_gradient or smart_patch, which "
                             "Krita keeps out of them." % (', '.join(sorted(set(writing))),
                                                           'the feature ' + names + ' is' if names.count("'") == 2 else 'the features ' + names + ' are'))

    # ----- the features list --------------------------------------------------------------------------------------------------
    def _feature_list(self, doc):
        """Every feature: name, kind, protected, author and state. Empty without the fork."""
        if not self._feature_ready(doc):
            return []
        return [{'name': f.name(), 'kind': f.kind(), 'protected': bool(f.isProtected()), 'author': f.author(), 'state': f.state()}
                for f in doc.features()]

    OBSERVED_FEATURES = 24

    def _feature_observation(self, doc, observation):
        """Looks carry the features so the model knows the names it may use: name and protected flag only, protected first,
        at most OBSERVED_FEATURES (the rest counted). `features_list` gives everything."""
        listed = self._feature_list(doc)
        if listed:
            listed.sort(key=lambda f: not f['protected'])
            observation['features'] = [{'name': f['name'], 'protected': f['protected']} for f in listed[:self.OBSERVED_FEATURES]]
            if len(listed) > self.OBSERVED_FEATURES:
                observation['features_more'] = len(listed) - self.OBSERVED_FEATURES
        return observation

    def _feature_set_protected(self, doc, name, value):
        """The artist's panel protects or unprotects a feature. Never reachable from a model's tool call. False when Krita
        did not do it (a refused call, or the document was closed)."""
        if not self._feature_ready(doc):
            raise ValueError(FORK_ONLY)
        feature = doc.feature(str(name).strip())
        if feature is None:
            raise ValueError("No feature called '%s'. Features: %s." % (name, ', '.join(self._feature_names(doc)) or 'none'))
        try:
            return bool(feature.setProtected(bool(value)))
        except RuntimeError:
            return False

    def _feature_add_protected(self, doc, name, selection):
        """The artist's selection becomes a protected feature (author artist, kept): "Buildings". Panel only."""
        if not self._feature_ready(doc):
            raise ValueError(FORK_ONLY)
        name = str(name).strip()
        if not name or len(name) > 60:
            raise ValueError('Give the feature a name of 1-60 characters.')
        if doc.addFeature(name, 'region', selection, 'artist', 'kept', True) is None:
            raise ValueError("Could not add a feature called '%s': the name is empty or already used. Features: %s."
                             % (name, ', '.join(self._feature_names(doc)) or 'none'))
        return True
