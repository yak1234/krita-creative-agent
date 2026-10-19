"""The Creative Agent's native helper (krita-native/agent-accel), when Krita loaded it: Krita internals the Python API
lacks, built against the exact Krita it runs in.

The helper puts one object on the application, named `creative-agent-accel`, with invokable methods taking plain
values; this module finds it and calls them through Qt's meta-object system, the same under PyQt5 and PyQt6. Without the
helper (stock install, another Krita version) every call returns None and the plugin keeps its Python path.

  refresh_rect(path, (x, y, w, h)) -> ms   recomposite only that area, where Document.refreshProjection() recomposites all
  refresh_region(path, (x, y, w, h)) -> {ms, rect, requested}   the same, grown by every effect that spreads a change
                                  outside it (filter masks, adjustment layers, layer styles, clones...), and the rect
                                  it recomposited (protocol 7; from 7 refresh_rect grows the area too)
  paint_strokes(path, layer_id, strokes, defaults) -> summary   a chunk of strokes in one call, without per-stroke view updates
  select_contiguous(path, seed, tolerance, bounds) -> (rect, mask)   a seed step (magic wand) on the visible image
  select_similar(path, colour, tolerance, bounds) -> (rect, mask)    a colour step on the visible image
  selection_outline(rect, mask) -> polygons                          a mask's outline, as Krita draws marching ants
  build_selection(path, steps) -> (rect, mask)    a whole select's seed and colour steps in one call (protocol 4)
  build_timings() -> phases                       where the last build_selection's time went, in the helper
  paint_strokes' points carry tilt, rotation, speed and time besides pressure (protocol 5)
  save_in_background(path) -> job                 Krita's background save of a document to its own file (protocol 6)
  save_status(job) -> {state, ms, startMs, error, file, clean}   running, done or failed; wait_for_save waits for the end
"""
import struct
from .qt_compat import QByteArray, QCoreApplication, QMetaObject, QObject, Qt, Q_ARG, Q_RETURN_ARG

OBJECT_NAME = 'creative-agent-accel'
PROTOCOL = 7                              # agent_accel.cpp AgentAccelService::version()
KNOWN = (3, 4, 5, 6, 7)                   # the protocols this module speaks: 4 is 3 with buildSelection added, 5 is 4 with
                                          # tilt, rotation, speed and time on paintStrokes' points, 6 is 5 with
                                          # saveInBackground and saveStatus, 7 is 6 with refreshRect growing its rect
                                          # by the effects that spread it and refreshRegion answering that rect
MASK_HEADER = struct.Struct('<4i')        # x, y, w, h of the mask that follows, w*h bytes (agent_accel.h)


def _call(service, method, result_type, *args):
    return QMetaObject.invokeMethod(service, method, Qt.ConnectionType.DirectConnection, Q_RETURN_ARG(result_type), *args)


def service(app=None, protocol=3):
    """The helper's service object, or None when Krita did not load it, it speaks a protocol this module does not know,
    or one older than `protocol` (what the caller's method needs)."""
    app = app or QCoreApplication.instance()
    found = app.findChild(QObject, OBJECT_NAME, Qt.FindChildOption.FindDirectChildrenOnly) if app is not None else None
    if found is None:
        return None
    try:
        version = _call(found, 'version', int)
    except Exception:                                    # an object of that name without the method
        return None
    return found if version in KNOWN and version >= protocol else None


def refresh_rect(path, rect, app=None):
    """Recomposite only rect [x, y, w, h] of the document saved at `path` ('' for the active one) and wait for it.
    Returns the helper's milliseconds, or None without the helper or the document. A helper older than protocol 7
    recomposites exactly the rect, leaving stale the halo a filter mask or layer style spreads around it: callers that
    need the picture right use refresh_region."""
    found = service(app)
    if found is None:
        return None
    x, y, w, h = (int(v) for v in rect)
    took = _call(found, 'refreshRect', int, Q_ARG(str, path or ''), Q_ARG(int, x), Q_ARG(int, y), Q_ARG(int, w), Q_ARG(int, h))
    return None if took is None or took < 0 else took


def refresh_region(path, rect, app=None):
    """Recomposite what changes when pixels changed inside rect [x, y, w, h] of the document saved at `path` ('' for
    the active one), and wait for it: the rect grown by every effect that spreads a change outside it (filter masks,
    adjustment layers, layer styles, transform masks, clones, through pass-through groups), cut to the image, so the
    picture is what a whole-image refresh gives. Returns {'ms', 'rect': (x, y, w, h) recomposited ((0, 0, 0, 0) when
    nothing of the rect is inside the image), 'requested': (x, y, w, h)}, or None without a protocol-7 helper or the
    document: then refresh the whole image."""
    import json
    found = service(app, 7)
    if found is None:
        return None
    x, y, w, h = (int(v) for v in rect)
    answer = json.loads(_call(found, 'refreshRegion', str, Q_ARG(str, path or ''), Q_ARG(int, x), Q_ARG(int, y),
                              Q_ARG(int, w), Q_ARG(int, h)) or '{}')
    if 'error' in answer or 'rect' not in answer:
        return None
    return {'ms': answer.get('ms'), 'rect': tuple(answer['rect']), 'requested': tuple(answer.get('requested', (x, y, w, h)))}


def _mask(answer):
    """The helper's selection answer as ((x, y, w, h), mask bytes), or None for a failure (an empty answer) or a
    malformed one. Nothing selected is a zero-size rect and no bytes."""
    data = bytes(answer) if answer is not None else b''
    if len(data) < MASK_HEADER.size:
        return None
    rect = MASK_HEADER.unpack_from(data)
    mask = data[MASK_HEADER.size:]
    return (rect, mask) if rect[2] >= 0 and rect[3] >= 0 and len(mask) == rect[2] * rect[3] else None


def select_contiguous(path, seed, tolerance, bounds, app=None):
    """region_craft's seed step in the helper: the pixels of the visible image within `tolerance` of the seed's colour
    on every 8-bit channel, opaque at all, and joined to the seed through edge neighbours inside `bounds` [x, y, w, h].
    Returns ((x, y, w, h), mask) for the selected pixels' bounding rect, 255 where selected, or None without the helper
    or the document: then the Python path runs."""
    found = service(app)
    if found is None:
        return None
    x, y = (int(v) for v in seed)
    bx, by, bw, bh = (int(v) for v in bounds)
    return _mask(_call(found, 'selectContiguous', QByteArray, Q_ARG(str, path or ''), Q_ARG(int, x), Q_ARG(int, y),
                       Q_ARG(int, int(tolerance)), Q_ARG(int, bx), Q_ARG(int, by), Q_ARG(int, bw), Q_ARG(int, bh)))


def select_similar(path, colour, tolerance, bounds, app=None):
    """region_craft's colour step in the helper: every pixel inside `bounds` within `tolerance` of `colour` ('#rrggbb')
    on every 8-bit channel and opaque at all, joined or not. Returns as select_contiguous does."""
    found = service(app)
    if found is None:
        return None
    bx, by, bw, bh = (int(v) for v in bounds)
    return _mask(_call(found, 'selectSimilar', QByteArray, Q_ARG(str, path or ''), Q_ARG(str, colour), Q_ARG(int, int(tolerance)),
                       Q_ARG(int, bx), Q_ARG(int, by), Q_ARG(int, bw), Q_ARG(int, bh)))


def selection_outline(rect, mask, app=None):
    """The outline of `mask` (w*h bytes at rect [x, y, w, h]) as Krita's own selection outline: a list of polygons,
    each a list of [x, y] canvas pixel corners ending where it started. None without the helper."""
    import json
    found = service(app)
    if found is None:
        return None
    x, y, w, h = (int(v) for v in rect)
    if w <= 0 or h <= 0:
        return []
    answer = json.loads(_call(found, 'selectionOutline', str, Q_ARG(QByteArray, QByteArray(MASK_HEADER.pack(x, y, w, h) + bytes(mask)))) or '{}')
    return answer.get('polygons')


BUILD_FIELDS = ('seed', 'color', 'tolerance', 'bounds', 'mode')


def build_selection(path, steps, app=None):
    """region_craft's seed and colour steps (validated) in one call: the helper reads the visible image once, searches
    every step in it as select_contiguous and select_similar do, and combines them in order as Selection.add, subtract,
    intersect and replace do (the first step replaces; later ones add unless their mode says otherwise). Refinements
    are not sent: the caller applies them. Returns ((x, y, w, h), mask) for the final selected pixels' bounding rect,
    or None without a protocol-4 helper, the document, or for a step the helper refuses: then build step by step."""
    import json
    found = service(app, 4)
    if found is None:
        return None
    sent = [{key: step[key] for key in BUILD_FIELDS if key in step} for step in steps]
    return _mask(_call(found, 'buildSelection', QByteArray, Q_ARG(str, path or ''), Q_ARG(str, json.dumps(sent))))


def build_timings(app=None):
    """The last build_selection's phases inside the helper, in milliseconds: {steps, area, wait, parse, read, fill,
    combine, pack, total}, or {error} when it failed; None without a protocol-4 helper."""
    import json
    found = service(app, 4)
    return None if found is None else json.loads(_call(found, 'buildTimings', str) or '{}')


def save_in_background(path, app=None):
    """Start Krita's background save of the open document whose file is `path` to that file: Krita copies the image on
    its main thread (the short part) and writes the copy on a worker thread, while the document stays usable. The copy
    replaces the file only once written, so a failed save leaves the previous file. Returns the job id, or None without
    a protocol-6 helper or the document. A save refused at once (one is already running) is a job that failed."""
    found = service(app, 6)
    if found is None:
        return None
    job = _call(found, 'saveInBackground', int, Q_ARG(str, path or ''))
    return None if job is None or job < 0 else job


def save_status(job, app=None):
    """A background save's state: {job, state: running | done | failed, ms, startMs (Krita's main thread's share),
    error, file, clean (Krita marked the document unmodified)}. Only `done` means the file holds the save; an unknown
    job is failed. None without a protocol-6 helper."""
    import json
    found = service(app, 6)
    return None if found is None else json.loads(_call(found, 'saveStatus', str, Q_ARG(int, int(job))) or '{}')


SAVE_WAIT_SECONDS = 600                   # Krita's own save of a very large painting can take minutes


def wait_for_save(job, timeout=SAVE_WAIT_SECONDS, app=None, pause=0.01):
    """Let Krita run its events (its save ends on the main thread) until the job is no longer running or `timeout`
    seconds pass. Returns the last status (still running at the timeout), or None without a protocol-6 helper."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        status = save_status(job, app)
        if status is None or status.get('state') != 'running' or time.monotonic() >= deadline:
            return status
        QCoreApplication.processEvents()
        time.sleep(pause)


class _Ticks:
    """A timer on Krita's main thread, every `interval` ms, recording the gaps between its ticks: a gap longer than the
    interval is time the main thread could not run it (Krita's window could not respond either)."""
    def __init__(self, interval):
        from .qt_compat import QTimer
        self.interval, self.gaps, self.timer = interval, [], QTimer()
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        import time
        now = time.monotonic()
        self.gaps.append((now - self.last) * 1000)
        self.last = now

    def start(self):
        import time
        self.last = time.monotonic()
        self.timer.start()

    def stop(self):
        self._tick()                                      # the gap up to now: a save that held the thread to the end
        self.timer.stop()
        return {'max_gap_ms': int(max(self.gaps)), 'ticks': len(self.gaps),
                'late_ticks': sum(1 for gap in self.gaps if gap > self.interval + 50)}


def _pump(seconds):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.002)


def save_compare(doc, plugin, rounds=1, tick_ms=10, app=None):
    """The plugin's synchronous checkpoint save (plugin.cmd_save_native: libkis saveAs) and the helper's background
    save of the open painting to its own file, `rounds` times each, with a `tick_ms` timer on the main thread showing
    how long each held it. Per round: sync {ms, max_gap_ms, ticks, late_ticks}; background {job, state, error,
    start_ms (the call), ms (until done, seen from here), helper_ms, helper_start_ms, max_gap_ms, ticks, late_ticks}.
    Rewrites the painting's file with its current state, as a checkpoint does."""
    import time
    path = doc.fileName() or ''
    if not path:
        raise ValueError('Save the painting once first: the probe saves it to its own file.')
    helper = service(app, 6) is not None
    rows = []
    for _ in range(rounds):
        row = {}
        doc.waitForDone()
        ticks = _Ticks(tick_ms); ticks.start()
        started = time.monotonic()
        saved = plugin.cmd_save_native({'path': path})
        row['sync'] = dict(ticks.stop(), ms=int((time.monotonic() - started) * 1000), error=saved.get('error'))
        _pump(0.2)
        if helper:
            doc.waitForDone()
            ticks = _Ticks(tick_ms); ticks.start()
            started = time.monotonic()
            job = save_in_background(path, app)
            start_ms = int((time.monotonic() - started) * 1000)
            status = wait_for_save(job, app=app, pause=0.002) if job is not None else {'state': 'failed', 'error': 'No such document.'}
            row['background'] = dict(ticks.stop(), job=job, state=status.get('state'), error=status.get('error') or None,
                                     start_ms=start_ms, ms=int((time.monotonic() - started) * 1000),
                                     helper_ms=status.get('ms'), helper_start_ms=status.get('startMs'))
            _pump(0.2)
        rows.append(row)
    return {'helper': helper, 'file': path, 'canvas': [doc.width(), doc.height()], 'tick_ms': tick_ms, 'rounds': rows}


PAINT_GROUP = 64                          # strokes per call: Stop is checked between groups, as between strokes today
# paint_pass paints every pass through the helper when this is on, and otherwise only passes with pen pressure, which
# the Python API cannot paint. Measured 19 October on merged New Moscow (stroke_compare, 256 strokes, three presets):
# identical pixels, 1.02-1.07x the speed, since Krita's brush engine is nearly all the time.
NATIVE_STROKES = False


# paint_pass's pen inputs beyond pressure, one entry per point like `pressure`, in the units Krita's tablet input gives
# its brush engine (krita-native/agent-accel/stroke_points.h): tilt [x, y] in degrees (-60..60), rotation in degrees
# (-180..180), speed 0..1 (Krita's: view pixels per ms over 30), time_ms since the stroke began. Protocol 5 reads them.
PEN_INPUTS = ('tilt', 'rotation', 'speed', 'time_ms')


def _inline_pen(stroke, pen=True):
    """paint_pass's per-point `pressure` and pen lists (start, then each segment end) as the helper reads them: after a
    point's x and y come pressure, x tilt, y tilt, rotation, speed and time, a mouse's values (1, 0, 0, 0, 0, 0) where
    the stroke gives none. A stroke with pressure alone keeps protocol 4's one value; `pen` False drops the rest, for a
    helper that reads pressure only."""
    given = [name for name in PEN_INPUTS if name in stroke] if pen else []
    if 'pressure' not in stroke and not given:
        return {k: v for k, v in stroke.items() if k not in PEN_INPUTS}
    rest = {k: v for k, v in stroke.items() if k != 'pressure' and k not in PEN_INPUTS}
    count = len(stroke['segments']) + 1
    pressure = stroke.get('pressure') or [1] * count
    if given:
        tilt = stroke.get('tilt') or [[0, 0]] * count
        columns = [pressure, [t[0] for t in tilt], [t[1] for t in tilt]] + [stroke.get(name) or [0] * count for name in ('rotation', 'speed', 'time_ms')]
    else:
        columns = [pressure]
    values = [[column[index] for column in columns] for index in range(count)]
    rest['start'] = list(stroke['start'][:2]) + values[0]
    rest['segments'] = [list(segment[:6]) + point for segment, point in zip(stroke['segments'], values[1:])]
    return rest


def paint_strokes(path, layer_id, strokes, defaults, group=PAINT_GROUP, app=None, stop=None):
    """Queue `strokes` (paint_pass strokes) on the layer through the helper, `group` at a time, with the defaults
    cmd_curve_stroke uses (the view's size and opacity, flow 1) filled in. The caller waits for them (waitForDone).
    Returns {strokes, jobs, groups, ms[, stopped_after_strokes][, ignored]}, or None without the helper: then paint as
    before. `ignored` names the pen inputs (PEN_INPUTS) the strokes carry that a helper older than protocol 5 cannot
    paint; it paints their pressure and leaves those out."""
    import json
    found = service(app)
    if found is None:
        return None
    pen = _call(found, 'version', int) >= 5
    ignored = [] if pen else [name for name in PEN_INPUTS if any(name in stroke for stroke in strokes)]
    base = {'size': defaults.get('size'), 'opacity': defaults.get('opacity'), 'flow': 1}
    done = {'strokes': 0, 'jobs': 0, 'groups': 0, 'ms': 0}
    for first in range(0, len(strokes), group):
        if stop is not None and stop():
            done['stopped_after_strokes'] = done['strokes']
            break
        chunk = [dict({k: v for k, v in base.items() if v is not None}, **_inline_pen(stroke, pen)) for stroke in strokes[first:first + group]]
        answer = json.loads(_call(found, 'paintStrokes', str, Q_ARG(str, path or ''), Q_ARG(str, layer_id),
                                  Q_ARG(str, json.dumps({'strokes': chunk}))) or '{}')
        if answer.get('error') or answer.get('status') != 'ok':
            raise RuntimeError('The native helper could not paint: %s' % (answer.get('error') or 'no answer'))
        done['strokes'] += answer['strokes']; done['jobs'] += answer['jobs']; done['groups'] += 1; done['ms'] += answer['ms']
    if ignored:
        done['ignored'] = ignored
    return done


def probe(doc, rect, app=None):
    """The proof the helper exists for: on one document, the full recomposite the plugin does before every
    observation today, then the helper's recomposite of just `rect`. Times in milliseconds."""
    import time
    started = time.monotonic()
    doc.refreshProjection()
    doc.waitForDone()
    full = int((time.monotonic() - started) * 1000)
    region = refresh_rect(doc.fileName() or '', rect, app)
    return {'helper': service(app) is not None, 'full_ms': full, 'region_ms': region, 'rect': [int(v) for v in rect],
            'canvas': [doc.width(), doc.height()]}


def _probe_strokes(doc, count, size):
    """`count` seeded random strokes, in paint_pass form, inside the middle of the canvas."""
    import math
    import random
    rng = random.Random(7)
    w, h = doc.width(), doc.height()
    strokes = []
    for _ in range(count):
        x, y = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
        angle, length = rng.uniform(0, math.tau), rng.uniform(60, 240)
        strokes.append({'start': [x, y], 'segments': [[x + length * 0.3, y - 20, x + length * 0.7 * math.cos(angle), y + 20,
                                                       x + length * math.cos(angle), y + length * math.sin(angle)]],
                        'size': size, 'opacity': 0.6, 'flow': 1,
                        'color': '#%02x%02x%02x' % (rng.randrange(256), rng.randrange(256), rng.randrange(256))})
    return strokes


PROBE_PRESET = 'b) Basic-5 Size'          # a plain paint brush: a fresh Krita may start on the eraser


def stroke_compare(doc, view, plugin, count=256, size=40, preset=None):
    """The same seeded strokes through the Python API (as paint_pass without the helper) and through the helper, each on
    its own temporary layer: time of each, and how alike the two layers are. Both layers are removed."""
    import time
    from .qt_compat import QPainterPath
    strokes, layers, ms = _probe_strokes(doc, count, size), [], {}
    plugin.cmd_set_brush({'preset': preset or PROBE_PRESET})   # as paint_pass selects its preset first
    from krita import Krita
    erase = Krita.instance().action('erase_action')
    state = {'selection': doc.selection() is not None, 'eraser_mode': bool(erase and erase.isChecked())}
    selection = doc.selection()
    doc.setSelection(None)                                # as paint_pass does: a saved selection would clip every stroke
    try:
        for name in ('python', 'native'):
            layer = doc.createNode('Creative Agent · compare ' + name, 'paintlayer')
            doc.rootNode().addChildNode(layer, None); doc.setActiveNode(layer); layers.append(layer)
            doc.waitForDone()
            started = time.monotonic()
            if name == 'python':
                for stroke in strokes:
                    plugin._apply_brush_state(view, size=stroke['size'], opacity=stroke['opacity'], flow=stroke['flow'], color=stroke['color'])
                    path = QPainterPath(); path.moveTo(*stroke['start']); path.cubicTo(*stroke['segments'][0])
                    layer.paintPath(path, 'ForegroundColor', 'None')
            else:
                if paint_strokes(doc.fileName() or '', layer.uniqueId().toString(), strokes, {}) is None:
                    return {'helper': False}
            doc.waitForDone()
            ms[name] = int((time.monotonic() - started) * 1000)
        w, h = doc.width(), doc.height()
        a, b = bytes(layers[0].pixelData(0, 0, w, h)), bytes(layers[1].pixelData(0, 0, w, h))
        alpha_a, alpha_b = a[3::4], b[3::4]
        covered = sum(1 for v in alpha_a if v) or 1
        differing = sum(1 for x, y in zip(alpha_a, alpha_b) if abs(x - y) > 24)
        return {'helper': True, 'state': state, 'preset': preset or PROBE_PRESET, 'strokes': count, 'size': size, 'ms': ms, 'speedup': round(ms['python'] / max(ms['native'], 1), 2),
                'painted_pixels': covered, 'alpha_differs_share': round(differing / covered, 4)}
    finally:
        for layer in layers:
            layer.remove()
        doc.setSelection(selection)


def stroke_probe(doc, view, plugin, count=256, size=40):
    """Where a chunk of strokes spends its time today, with the calls a pass makes per stroke (precision_tools
    cmd_curve_stroke with settle=False: brush state on the view, then Node.paintPath), on a new layer removed after.
    Phases in milliseconds: brush (per-stroke brush state), queue (paintPath calls), paint_wait (Krita painting the
    queued strokes), full_refresh (the recomposite the pass ends with)."""
    import math
    import random
    import time
    from .qt_compat import QPainterPath
    rng = random.Random(7)
    if hasattr(plugin, 'cmd_set_brush'):
        plugin.cmd_set_brush({'preset': PROBE_PRESET})    # as paint_pass selects its preset first
    layer = doc.createNode('Creative Agent · stroke probe', 'paintlayer')
    doc.rootNode().addChildNode(layer, None)
    doc.setActiveNode(layer)
    ms = {'brush': 0.0, 'queue': 0.0, 'paint_wait': 0.0, 'full_refresh': 0.0}
    selection = doc.selection() if hasattr(doc, 'selection') else None
    if hasattr(doc, 'setSelection'):
        doc.setSelection(None)                            # as paint_pass does: a saved selection would clip every stroke
    try:
        w, h = doc.width(), doc.height()
        for _ in range(count):
            x, y = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
            angle, length = rng.uniform(0, math.tau), rng.uniform(60, 240)
            path = QPainterPath(); path.moveTo(x, y)
            path.cubicTo(x + length * 0.3, y - 20, x + length * 0.7 * math.cos(angle), y + 20, x + length * math.cos(angle), y + length * math.sin(angle))
            started = time.monotonic()
            plugin._apply_brush_state(view, size=size, opacity=0.6, flow=1, color='#%02x%02x%02x' % (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
            queued = time.monotonic()
            layer.paintPath(path, 'ForegroundColor', 'None')
            ms['brush'] += queued - started; ms['queue'] += time.monotonic() - queued
        started = time.monotonic(); doc.waitForDone(); ms['paint_wait'] = time.monotonic() - started
        started = time.monotonic(); doc.refreshProjection(); doc.waitForDone(); ms['full_refresh'] = time.monotonic() - started
    finally:
        layer.remove()
        if hasattr(doc, 'setSelection'):
            doc.setSelection(selection)
    return {'strokes': count, 'size': size, 'canvas': [doc.width(), doc.height()], 'ms': {k: int(v * 1000) for k, v in ms.items()}}


def select_compare(doc, plugin, steps=None, count=8, tolerance=24, app=None):
    """The same seed or colour steps through the Python path and through the helper (region_craft._region_colour with
    native off, then on), each end to end into a Selection: the time of each, and how many pixels of the step's bounds
    differ. Without `steps`, `count` seeded random seeds over the whole canvas at `tolerance`. Changes nothing."""
    import random
    import time
    import numpy
    if service(app) is None:
        return {'helper': False}
    w, h = doc.width(), doc.height()
    if not steps:
        rng = random.Random(7)
        steps = [{'seed': [rng.randrange(w), rng.randrange(h)], 'tolerance': tolerance} for _ in range(count)]
    rows, total = [], {'python': 0, 'native': 0}
    for step in steps:
        source = 'seed' if 'seed' in step else 'color'
        rect = [int(v) for v in step.get('bounds') or (0, 0, w, h)]
        masks, ms = {}, {}
        for name in ('python', 'native'):
            started = time.monotonic()
            selection = plugin._region_colour(doc, step, source, native=name == 'native')
            ms[name] = int((time.monotonic() - started) * 1000)
            masks[name] = numpy.frombuffer(bytes(selection.pixelData(*rect)), numpy.uint8)
            total[name] += ms[name]
        rows.append({'step': step, 'ms': ms, 'selected_pixels': int(numpy.count_nonzero(masks['python'])),
                     'differing_pixels': int(numpy.count_nonzero(masks['python'] != masks['native']))})
    return {'helper': True, 'canvas': [w, h], 'steps': rows, 'ms': total,
            'speedup': round(total['python'] / max(total['native'], 1), 2),
            'differing_pixels': sum(row['differing_pixels'] for row in rows)}


def thickness(data, width, height, x, threshold=24):
    """How many rows of column x are covered (alpha above threshold) in 4-byte pixels `data`."""
    return sum(1 for row in range(height) if data[(row * width + x) * 4 + 3] > threshold)


TAPER = [0.05, 1, 0.05]                   # the probe's pressure: lifts in, full in the middle, lifts out
# pen_compare's input along its stroke (start, middle, end), and an installed preset whose dynamics read it (Krita 4
# default bundle, checked in its .kpp files): c) Pencil-5 Tilted widens with tilt (Size by tilt elevation, and its dab
# turns with tilt direction); d) Ink-1 Precision thins as speed rises (Size by speed, 1 to 0.53); j) WaterC Basic
# Round-Grunge changes size with time (Size by time, every 720 ms). No bundled preset reads rotation (a pen's barrel
# rotation), so it uses the plain probe brush unless a preset is given.
PEN_RAMPS = {'pressure': TAPER, 'tilt': [[0, 0], [30, 0], [60, 0]], 'rotation': [-90, 0, 90], 'speed': [0, 0.5, 1],
             'time_ms': [0, 360, 720]}
PEN_PRESETS = {'pressure': None, 'tilt': 'c) Pencil-5 Tilted', 'rotation': None, 'speed': 'd) Ink-1 Precision',
               'time_ms': 'j) WaterC Basic Round-Grunge'}
PROBE_AT = [0.05, 0.25, 0.5, 0.75, 0.95]


def pen_compare(doc, plugin, field, preset=None, size=60, image=None):
    """One straight stroke across the canvas through the helper without the pen input `field` (a mouse's: full
    pressure, upright, no rotation, speed or time) and one with it changing along the stroke (PEN_RAMPS), each on its
    own temporary layer: its thickness at five points along it (PROBE_AT). A preset that reads the input paints the
    second differently.
    `image`: a PNG path for both strokes, plain above varied. Both layers are removed."""
    from .qt_compat import QImage
    if field not in PEN_RAMPS:
        raise ValueError('input is one of: ' + ', '.join(PEN_RAMPS))
    preset = preset or PEN_PRESETS[field] or PROBE_PRESET
    plugin.cmd_set_brush({'preset': preset})
    selection = doc.selection()
    doc.setSelection(None)                                # as paint_pass does: a saved selection would clip every stroke
    w, h = doc.width(), doc.height()
    y, x0, x1 = h / 2, w * 0.2, w * 0.8
    xm = (x0 + x1) / 2
    seg = lambda a, b: [a + (b - a) / 3, y, a + 2 * (b - a) / 3, y, b, y]
    stroke = {'start': [x0, y], 'segments': [seg(x0, xm), seg(xm, x1)], 'size': size, 'opacity': 1, 'flow': 1, 'color': '#000000'}
    band = (int(x0), int(y - size), int(x1 - x0), int(2 * size))
    layers, found, bands, ignored = [], {}, [], []
    try:
        for name, varied in (('plain', None), (field, PEN_RAMPS[field])):
            layer = doc.createNode('Creative Agent · pen ' + name, 'paintlayer')
            doc.rootNode().addChildNode(layer, None); layers.append(layer)
            doc.waitForDone()
            painted = paint_strokes(doc.fileName() or '', layer.uniqueId().toString(),
                                    [dict(stroke, **{field: varied}) if varied else stroke], {})
            if painted is None:
                return {'helper': False}
            ignored += painted.get('ignored', [])
            doc.waitForDone()
            data = bytes(layer.pixelData(*band))
            bands.append(data)
            found['plain' if varied is None else 'varied'] = [thickness(data, band[2], band[3], int(band[2] * f)) for f in PROBE_AT]
        if image:
            picture = QImage(band[2], band[3] * 2, QImage.Format.Format_ARGB32)
            picture.fill(0xffffffff)
            for index, data in enumerate(bands):
                for row in range(band[3]):
                    for col in range(band[2]):
                        if data[(row * band[2] + col) * 4 + 3] > 24:
                            picture.setPixel(col, index * band[3] + row, 0xff000000)
            picture.save(image)
        result = {'helper': True, 'preset': preset, 'size': size, 'input': field, 'values': PEN_RAMPS[field], 'at': PROBE_AT,
                  'thickness': found}
        if ignored:
            result['ignored'] = ignored
        return result
    finally:
        for layer in layers:
            layer.remove()
        doc.setSelection(selection)


def pressure_compare(doc, plugin, preset=None, size=60, image=None):
    """pen_compare for pressure, in its first answer's form: thickness at full pressure and tapered (TAPER)."""
    found = pen_compare(doc, plugin, 'pressure', preset, size, image)
    if not found['helper']:
        return found
    return {'helper': True, 'preset': found['preset'], 'size': size, 'pressure': TAPER, 'at': PROBE_AT,
            'thickness': {'full': found['thickness']['plain'], 'taper': found['thickness']['varied']}}
