"""What the artist is doing in Krita's window, and light-touch help shown there.

* Follow the artist: the layers they have selected and their current colours go into
  every observation, so "the layer I selected" and "this colour" mean what they see.
* Composition guides: thirds, centre lines or a horizon as Krita guides. They are a
  view setting, not paint: no pass or checkpoint. The artist's own guides come back
  when the chat ends.
* Progress in the status bar: a short message when an operation starts (never floating over the
  painting: the artist, 2026-10-25, it blocked the view).

Everything here is best effort. A missing window or an older Krita never stops painting.
"""
from krita import Krita
from .creative_document_identity import document_id
from .creative_validation import fields, numeric

GUIDE_FIELDS = ('preset', 'horizon', 'horizontal', 'vertical', 'clear')
PRESETS = ('thirds', 'center', 'horizon')
MESSAGE_MS = 2500


class CanvasView:
    def _view_for(self, doc):
        """The view showing `doc`, preferring the active one, or None."""
        try:
            app = Krita.instance()
            wanted = document_id(doc)
            active = app.activeWindow().activeView() if app.activeWindow() else None
            views = ([active] if active else []) + [view for window in app.windows() for view in window.views()]
            return next((view for view in views if view is not None and view.document() is not None
                         and document_id(view.document()) == wanted), None)
        except Exception:
            return None

    def _view_artist_focus(self, doc):
        """The artist's selected layers and colours in the view of `doc`, or None."""
        view = self._view_for(doc)
        if view is None:
            return None
        try:
            focus = {'selected_layers': [{'id': node.uniqueId().toString(), 'name': node.name()} for node in view.selectedNodes()]}
            canvas = view.canvas()
            for key, getter in (('foreground', view.foregroundColor), ('background', view.backgroundColor)):
                colour = getter()
                if colour is not None:
                    focus[key] = colour.colorForCanvas(canvas).name()
            return focus
        except Exception:
            return None

    def _view_message(self, doc, message):
        view = self._view_for(doc)
        if view is None:
            return
        try:
            view.window().qwindow().statusBar().showMessage('Creative Agent · ' + message[:90], MESSAGE_MS)
        except Exception:
            pass

    # ----- composition guides ---------------------------------------------------
    def _guides_validate(self, doc, params):
        fields(params, GUIDE_FIELDS)
        if params.get('clear') is True:
            if len(params) > 1:
                raise ValueError('clear takes no other settings.')
            return
        if 'preset' in params and params['preset'] not in PRESETS:
            raise ValueError('preset must be thirds, center or horizon')
        if params.get('preset') == 'horizon' and 'horizon' not in params:
            raise ValueError('The horizon preset needs horizon: the y position in pixels.')
        if 'horizon' in params:
            numeric(params['horizon'], 'horizon', 0, doc.height())
        for key, limit in (('horizontal', doc.height()), ('vertical', doc.width())):
            if key in params:
                if not isinstance(params[key], list) or len(params[key]) > 16:
                    raise ValueError(key + ' must be a list of up to 16 positions in pixels')
                for value in params[key]:
                    numeric(value, key, 0, limit)
        if not any(key in params for key in ('preset', 'horizon', 'horizontal', 'vertical')):
            raise ValueError('Give a preset, horizon, horizontal or vertical guides, or clear.')

    def _guides_positions(self, doc, params):
        width, height = doc.width(), doc.height()
        horizontal, vertical = list(params.get('horizontal', [])), list(params.get('vertical', []))
        preset = params.get('preset')
        if preset == 'thirds':
            horizontal += [height / 3, height * 2 / 3]; vertical += [width / 3, width * 2 / 3]
        elif preset == 'center':
            horizontal.append(height / 2); vertical.append(width / 2)
        if 'horizon' in params:
            horizontal.append(params['horizon'])
        return sorted(set(float(v) for v in horizontal)), sorted(set(float(v) for v in vertical))

    def _guides_set(self, doc, session, params):
        """Show composition guides; the artist's guides are kept to restore when the chat ends."""
        self._guides_validate(doc, params)
        config = doc.guidesConfig()
        session.setdefault('guides_prior', config.toXml())
        if params.get('clear'):
            config.removeAllGuides()
            horizontal, vertical = [], []
        else:
            horizontal, vertical = self._guides_positions(doc, params)
            config.setHorizontalGuides(horizontal)
            config.setVerticalGuides(vertical)
            config.setVisible(True)
        doc.setGuidesConfig(config)
        return {'status': 'ok', 'horizontal': horizontal, 'vertical': vertical,
                'note': 'Guides are a view aid, not paint; the artist’s own guides return when the chat ends.'}

    def _guides_restore(self, doc, session):
        prior = session.pop('guides_prior', None)
        if prior is None or doc is None:
            return
        try:
            config = doc.guidesConfig()
            config.fromXml(prior)
            doc.setGuidesConfig(config)
        except Exception:
            pass
