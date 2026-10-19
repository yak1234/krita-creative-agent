"""Seams baked into a painting: straight joins of pasted panels or upscaling tiles.

A seam is a faint, even step in brightness along a long, perfectly straight horizontal or vertical line through
otherwise smooth paint. Painting across one keeps it, and a wash over an area can make it stand out more: on New
Moscow they were the "flat block" Luna kept undoing. These are candidates only; the companion asks Luna about each
from its close-up and tells the painter the confirmed ones, so it repairs them before painting near them.
Calibrated on New Moscow (2026-10-19): the panel edges and river tiles found, roofs, towers and bridge not.
"""
import os
import cv2
import numpy as np

SIDE = 1500                 # scanned on a copy this wide
MAX_STEP = 14               # grey levels: a faint join; a stronger step is an object's edge
MIN_SHARE = 0.05            # long: this share of the scanned side
TEXTURE = 14                # smooth surroundings only (local Laplacian mean)
CROP_SIDE = 768             # close-ups for Luna, at most this large


def _scan(g, max_step, min_len, texture):
    """(row, start, end, step) for rows where `g` steps evenly, faintly, along a long straight run in smooth paint."""
    s = cv2.blur(g, (9, 1))                                  # along the line: painterly texture averages out
    d = s[1:] - s[:-1]
    busy = cv2.blur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (15, 15))
    out = []
    for y in range(6, d.shape[0] - 6):
        base = np.median(np.abs(np.concatenate([d[y - 6:y - 1], d[y + 2:y + 7]])), axis=0)
        ok = (np.abs(d[y]) - base > 1.5) & (np.abs(d[y]) < max_step) & (busy[y] < texture) & (busy[y + 1] < texture)
        x, n = 0, len(ok)
        while x < n:
            if not ok[x]:
                x += 1; continue
            a = b = x
            while x < n and (ok[x] or x - b <= 6):          # small gaps (a snowflake) do not break a join
                if ok[x]: b = x
                x += 1
            if b - a + 1 >= min_len:
                seg = d[y, a:b + 1]
                if abs(np.sign(seg).sum()) / len(seg) > 0.8:  # a pasted edge steps the same way along its length
                    out.append((y, a, b, float(np.abs(seg).mean())))
    out.sort(); merged = []
    for r in out:                                            # neighbouring rows describe one join: keep the strongest
        if merged and r[0] - merged[-1][0] <= 2 and not (r[2] < merged[-1][1] or r[1] > merged[-1][2]):
            if (r[2] - r[1]) * r[3] > (merged[-1][2] - merged[-1][1]) * merged[-1][3]:
                merged[-1] = r
        else:
            merged.append(r)
    return merged


def candidates(bgra):
    """Candidate seams of a BGRA painting (H, W, 4), in canvas pixels: [{axis: h|v, at, from, to, step}]."""
    H, W = bgra.shape[:2]
    k = min(1.0, SIDE / W)
    small = cv2.resize(bgra[..., :3], (max(1, round(W * k)), max(1, round(H * k))), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_BGR2GRAY).astype(np.float32)
    found = []
    for axis, grey in (('h', g), ('v', np.ascontiguousarray(g.T))):
        for at, a, b, step in _scan(grey, MAX_STEP, MIN_SHARE * grey.shape[1], TEXTURE):
            found.append({'axis': axis, 'at': int(at / k), 'from': int(a / k), 'to': int(b / k), 'step': round(step, 1)})
    return found


def close_ups(bgra, found, folder):
    """A JPEG close-up of each candidate with its line across the middle, for Luna. Adds `crop` and `crop_size`."""
    H, W = bgra.shape[:2]
    os.makedirs(folder, exist_ok=True)
    out = []
    for index, c in enumerate(found):
        mid, span = (c['from'] + c['to']) // 2, c['to'] - c['from']
        along, across = max(span, 900) * 0.75, 300
        cx, cy, hw, hh = (mid, c['at'], along, across) if c['axis'] == 'h' else (c['at'], mid, across, along)
        x0, x1 = int(max(0, cx - hw)), int(min(W, cx + hw)); y0, y1 = int(max(0, cy - hh)), int(min(H, cy + hh))
        crop = bgra[y0:y1, x0:x1, :3]
        k = min(1.0, CROP_SIDE / max(crop.shape[:2]))
        crop = cv2.resize(np.ascontiguousarray(crop), (max(1, round(crop.shape[1] * k)), max(1, round(crop.shape[0] * k))), interpolation=cv2.INTER_AREA)
        path = os.path.join(folder, 'seam-%d.jpg' % index)
        cv2.imwrite(path, crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        out.append(dict(c, crop=path, crop_size=[crop.shape[1], crop.shape[0]]))
    return out
