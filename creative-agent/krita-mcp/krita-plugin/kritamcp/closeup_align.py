# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a close-up sits in the goal image (after-the-underpainting goal 1, close-up references for detail).

A close-up is a sharper picture of part of the goal: a crop of a larger original, a photo of the figure, a detail scan.
`align` finds it with SIFT features, Lowe's ratio test and a RANSAC homography, then checks the answer three ways
before calling it aligned: enough matches agree (MIN_INLIERS, MIN_INLIER_RATIO), they cover the close-up and not one
corner of it (MIN_SPREAD), and the close-up warped into the goal looks like the goal there (MIN_SIMILARITY, a
correlation of the blurred grey values). A repainting of the same subject (an element generated again, not cut from the
goal) passes none of these reliably and is refused with the reason; there is no silent fallback. Shapes (SAM) are not
used: matching a different painting's figure to the goal's needs judgement, which is the artist's confirmation.

`align_closeup` is the bridge operation: both images checked against their hashes, their headers read (PNG or JPEG,
declared size) before anything is decoded, decoded reduced to at most DECODE_PIXELS, matched at WORK_SIDE. Answers are
in each file's own pixels. Nothing here touches a Krita document.
"""
import base64
import hashlib
import time

import cv2
import numpy as np

WORK_SIDE = 1600            # both images are matched at most this a side
DECODE_PIXELS = 4_000_000   # and decoded at most this many pixels (as trace_edges)
MAX_SIDE = 30000            # a header declaring more than this a side is refused before decoding
MAX_DECLARED = 100_000_000  # or more than this many pixels in all
ALLOCATION_MB = 256         # Qt's own allocation limit for one decode, where Qt has it
MAX_STRETCH = 0.1           # the placement may scale across and down by this much differently
GOAL_CACHE = 2              # goals whose features are kept, by content
MAX_FILE = 64 * 1024 * 1024     # creative_reference.REFERENCE_FILE_BYTES: a goal sharpened 4x
MIN_FEATURES = 40           # fewer in the close-up: too little detail to match
RATIO = 0.75                # Lowe's ratio test
MIN_INLIERS = 25
MIN_INLIER_RATIO = 0.3      # of the matches that passed the ratio test
MIN_SPREAD = 0.1            # the agreeing features' hull, a share of the close-up
MIN_SIMILARITY = 0.6        # correlation of the warped close-up with the goal under it
MIN_INSIDE = 0.6            # this share of the placed close-up lies on the goal
PREVIEW_SIDE = 640


def _work(gray):
    k = min(1.0, WORK_SIDE / max(gray.shape))
    if k < 1:
        gray = cv2.resize(gray, (max(1, round(gray.shape[1] * k)), max(1, round(gray.shape[0] * k))), interpolation=cv2.INTER_AREA)
    return gray, k


_GOALS = {}                 # goal sha256 -> (working copy, its scale, keypoints, descriptors), the newest last


def _goal_features(goal, key, sift):
    if key is not None and key in _GOALS:
        _GOALS[key] = _GOALS.pop(key)
        return _GOALS[key]
    G, kg = _work(goal)
    found = (G, kg) + tuple(sift.detectAndCompute(G, None))
    if key is not None:
        _GOALS[key] = found
        while len(_GOALS) > GOAL_CACHE:
            _GOALS.pop(next(iter(_GOALS)))
    return found


def _refused(reason, started, **found):
    return dict(found, aligned=False, reason=reason, ms=int((time.monotonic() - started) * 1000))


def align(goal, close, goal_key=None):
    """Place `close` (H, W uint8 grey) in `goal` (grey). Returns aligned, and when aligned: matrix (3x3, row-major,
    close-up pixels to goal pixels), quad (the close-up's corners in the goal), box [x, y, w, h] (its bounds on the
    goal), scale (close-up pixels per goal pixel at its centre: how much sharper it is), rotation (degrees); always
    matches, inliers, inlier_ratio, spread, similarity, score (0-1) and ms; reason when refused. goal_key (the goal's
    sha256) keeps the goal's features for the next close-up of the same goal."""
    started = time.monotonic()
    sift = cv2.SIFT_create(nfeatures=12000)
    G, kg, pg, dg = _goal_features(goal, goal_key, sift)
    C, kc = _work(close)
    pc, dc = sift.detectAndCompute(C, None)
    if dc is None or len(pc) < MIN_FEATURES:
        return _refused('The close-up has too little detail to match (%d features).' % (0 if dc is None else len(pc)), started, matches=0, inliers=0)
    if dg is None or len(pg) < MIN_FEATURES:
        return _refused('The goal image has too little detail to match.', started, matches=0, inliers=0)
    pairs = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64)).knnMatch(dc, dg, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
    if len(good) < MIN_INLIERS:
        return _refused('Too few features match the goal (%d; %d needed).' % (len(good), MIN_INLIERS), started, matches=len(good), inliers=0)
    src = np.float32([pc[m.queryIdx].pt for m in good])
    dst = np.float32([pg[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0, maxIters=5000, confidence=0.999)
    inliers = int(mask.sum()) if mask is not None else 0
    found = dict(matches=len(good), inliers=inliers, inlier_ratio=round(inliers / len(good), 3))
    if H is None or inliers < MIN_INLIERS or inliers < MIN_INLIER_RATIO * len(good):
        return _refused('The matching features do not agree on one place in the goal (%d of %d agree).' % (inliers, len(good)), started, **found)
    keep = mask.ravel().astype(bool)
    spread = cv2.contourArea(cv2.convexHull(src[keep])) / float(C.shape[0] * C.shape[1])
    found['spread'] = round(spread, 3)
    if spread < MIN_SPREAD:
        return _refused('Only a small part of the close-up matches the goal (%d%% of it).' % round(spread * 100), started, **found)
    # The placement in each file's own pixels: close-up original -> close-up work -> goal work -> goal original.
    full = np.diag([1 / kg, 1 / kg, 1.0]) @ H @ np.diag([kc, kc, 1.0])
    full = full / full[2, 2]
    h, w = close.shape[:2]
    quad = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), full)[0].astype(np.float64)
    area = _signed_area(quad)
    if area <= 0 or not cv2.isContourConvex(quad.astype(np.float32)):
        return _refused('The matches place the close-up mirrored or folded, not as a part of the goal.', started, **found)
    gh, gw = goal.shape[:2]
    clipped = _clip_area(quad, gw, gh)
    if clipped < MIN_INSIDE * area:
        return _refused('The matches place the close-up mostly outside the goal.', started, **found)
    jac = _jacobian(full, w / 2, h / 2)
    across, down = np.hypot(jac[0, 0], jac[1, 0]), np.hypot(jac[0, 1], jac[1, 1])
    if not (across > 0 and down > 0) or abs(across / down - 1) > MAX_STRETCH:
        return _refused('The matches stretch the close-up to fit the goal (%.2f across, %.2f down): not a close-up of it.' % (across, down), started, **found)
    # Does it look like the goal there? The close-up reduced (area-averaged) to about the goal's pixels, warped onto the
    # goal's working copy, compared under its own area.
    k = min(1.0, float(np.sqrt(abs(np.linalg.det(H[:2, :2])))))
    small = cv2.resize(C, (max(1, round(C.shape[1] * k)), max(1, round(C.shape[0] * k))), interpolation=cv2.INTER_AREA) if k < 1 else C
    Hs = H @ np.diag([C.shape[1] / small.shape[1], C.shape[0] / small.shape[0], 1.0])
    warped = cv2.warpPerspective(small.astype(np.float32), Hs, (G.shape[1], G.shape[0]), flags=cv2.INTER_LINEAR)
    under = cv2.warpPerspective(np.full(small.shape, 255, np.uint8), Hs, (G.shape[1], G.shape[0]), flags=cv2.INTER_NEAREST)
    under = cv2.erode(under, np.ones((5, 5), np.uint8)) > 0
    similarity = 0.0
    if under.sum() > 100:
        a = cv2.GaussianBlur(warped, (0, 0), 1.5)[under]
        b = cv2.GaussianBlur(G.astype(np.float32), (0, 0), 1.5)[under]
        if a.std() > 1e-3 and b.std() > 1e-3:
            similarity = float(np.corrcoef(a, b)[0, 1])
    found['similarity'] = round(similarity, 3)
    if similarity < MIN_SIMILARITY:
        return _refused('The close-up does not look like that part of the goal (similarity %.2f).' % similarity, started, **found)
    det = abs(np.linalg.det(jac))
    scale = 1 / np.sqrt(det) if det > 0 else 0.0
    rotation = float(np.degrees(np.arctan2(jac[1, 0], jac[0, 0])))
    x0, y0 = max(0, int(round(quad[:, 0].min()))), max(0, int(round(quad[:, 1].min())))
    x1, y1 = min(gw, int(round(quad[:, 0].max()))), min(gh, int(round(quad[:, 1].max())))
    score = max(0.0, similarity) * min(1.0, found['inlier_ratio'] / 0.5) * min(1.0, inliers / (2 * MIN_INLIERS))
    return dict(found, aligned=True, matrix=[round(float(v), 9) for v in full.ravel()],
                quad=[[round(float(x), 2), round(float(y), 2)] for x, y in quad], box=[x0, y0, x1 - x0, y1 - y0],
                scale=round(float(scale), 3), rotation=round(rotation, 2), score=round(score, 3),
                ms=int((time.monotonic() - started) * 1000))


def _jacobian(m, x, y):
    """d(goal)/d(close-up) of the homography at (x, y)."""
    u, v, s = m @ [x, y, 1]
    return np.array([[(m[0, 0] * s - u * m[2, 0]) / s ** 2, (m[0, 1] * s - u * m[2, 1]) / s ** 2],
                     [(m[1, 0] * s - v * m[2, 0]) / s ** 2, (m[1, 1] * s - v * m[2, 1]) / s ** 2]])


def _signed_area(quad):
    x, y = quad[:, 0], quad[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _clip_area(quad, width, height):
    """Area of the convex quad inside [0, width] x [0, height]."""
    inside, _ = cv2.intersectConvexConvex(quad.astype(np.float32), np.float32([[0, 0], [width, 0], [width, height], [0, height]]))
    return float(inside)


def _header(data):
    """'png' or 'jpeg' and the size a file declares, read from its first bytes; None when it is neither."""
    if len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
        return 'png', int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if len(data) >= 4 and data[:2] == b'\xff\xd8':
        at = 2
        while at + 9 < len(data) and data[at] == 0xff:
            while at + 1 < len(data) and data[at + 1] == 0xff:      # fill bytes before a marker
                at += 1
            if at + 9 >= len(data):
                break
            marker = data[at + 1]
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                return 'jpeg', int.from_bytes(data[at + 7:at + 9], 'big'), int.from_bytes(data[at + 5:at + 7], 'big')
            if marker in (0xd8, 0xd9, 0xda):
                break
            length = int.from_bytes(data[at + 2:at + 4], 'big')
            if length < 2:
                break
            at += 2 + length
    return None


def _decode(item, name):
    """One image of the request: {image_base64, sha256}, checked and decoded reduced, as grey and BGR numpy arrays."""
    from .creative_validation import fields
    if not isinstance(item, dict):
        raise ValueError('%s is {image_base64, sha256}.' % name)
    fields(item, ('image_base64', 'sha256'), ('image_base64', 'sha256'))
    encoded = item['image_base64']
    if not isinstance(encoded, str) or len(encoded) > (MAX_FILE * 4) // 3 + 4:
        raise ValueError('The %s image must be at most %d MB.' % (name, MAX_FILE // (1024 * 1024)))
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError('The %s image is not base64.' % name)
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('The %s image content changed.' % name)
    header = _header(data)
    if header is None:
        raise ValueError('The %s image must be a PNG or JPEG.' % name)
    kind, width, height = header
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE) or width * height > MAX_DECLARED:
        raise ValueError('The %s image declares %d x %d pixels; at most %d a side and %d million in all.' % (name, width, height, MAX_SIDE, MAX_DECLARED // 1_000_000))
    from .qt_compat import QByteArray, QBuffer, QIODevice, QSize, QImage, QImageReader, QColorSpace
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    if hasattr(reader, 'setAllocationLimit'):
        reader.setAllocationLimit(ALLOCATION_MB)
    size = reader.size()
    if not size.isValid() or (size.width(), size.height()) != (width, height):
        raise ValueError('Could not decode the %s image.' % name)
    k = min(1.0, (DECODE_PIXELS / (width * height)) ** 0.5)
    if k < 1:
        reader.setScaledSize(QSize(max(1, round(width * k)), max(1, round(height * k))))
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode the %s image.' % name)
    if image.colorSpace().isValid():
        image.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    dw, dh = image.width(), image.height()
    rows = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(dh, image.bytesPerLine())
    rgba = np.ascontiguousarray(rows[:, :dw * 4].reshape(dh, dw, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR), (width, height), dw / width


def _preview(bgr, quad):
    """The goal, at most PREVIEW_SIDE a side, with the close-up's place drawn on it: a JPEG for the artist's yes."""
    k = min(1.0, PREVIEW_SIDE / max(bgr.shape[:2]))
    small = cv2.resize(bgr, (max(1, round(bgr.shape[1] * k)), max(1, round(bgr.shape[0] * k))), interpolation=cv2.INTER_AREA)
    points = np.int32(np.round(np.array(quad) * k))
    cv2.polylines(small, [points], True, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.polylines(small, [points], True, (0, 230, 255), 2, cv2.LINE_AA)
    ok, data = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(data.tobytes()).decode('ascii')


def align_closeup(params):
    """The bridge operation: {goal, closeup: {image_base64, sha256}, preview?}. Returns status ok and align()'s answer in
    each file's own pixels, with goal_size and closeup_size; preview_jpeg_base64 (the goal with the place drawn) when
    asked and aligned."""
    from .creative_validation import fields
    fields(params, ('goal', 'closeup', 'preview'), ('goal', 'closeup'))
    if not isinstance(params.get('preview', False), bool):
        raise ValueError('preview must be true or false')
    started = time.monotonic()
    goal_gray, goal_bgr, goal_size, kg = _decode(params['goal'], 'goal')
    close_gray, _, close_size, kc = _decode(params['closeup'], 'closeup')
    out = align(goal_gray, close_gray, goal_key=params['goal']['sha256'])
    if out['aligned']:
        # From the decodes back to the files' own pixels (a decode is reduced only past DECODE_PIXELS).
        m = np.diag([1 / kg, 1 / kg, 1.0]) @ np.array(out['matrix']).reshape(3, 3) @ np.diag([kc, kc, 1.0])
        m = m / m[2, 2]
        w, h = close_size
        quad = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), m)[0].astype(np.float64)
        gw, gh = goal_size
        x0, y0 = max(0, int(round(quad[:, 0].min()))), max(0, int(round(quad[:, 1].min())))
        x1, y1 = min(gw, int(round(quad[:, 0].max()))), min(gh, int(round(quad[:, 1].max())))
        out.update(matrix=[round(float(v), 9) for v in m.ravel()], quad=[[round(float(x), 2), round(float(y), 2)] for x, y in quad],
                   box=[x0, y0, x1 - x0, y1 - y0], scale=round(out['scale'] * kg / kc, 3))
        if params.get('preview'):
            out['preview_jpeg_base64'] = _preview(goal_bgr, np.array(out['quad']) * kg)
    out.update(status='ok', method='sift-homography', goal_size=list(goal_size), closeup_size=list(close_size),
               ms=int((time.monotonic() - started) * 1000))
    return out
