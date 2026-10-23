// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A stand-in for the plugin's trace_edges (kritamcp/edge_trace.py, tested in tests/test_edge_trace.py) for companion
// tests: with shape labels, the outline of the labelled area as two row-scan polylines (its left and right ends on each
// row, joined across the top and bottom), in reference pixels; without labels, one line across the source (the real
// tracer's brightness split is the plugin's to test). Each request is recorded.
import { decodePlane } from '../../src/shapes/png.ts';

/** size(id): the reference's listed [width, height], the pixels the plugin answers in. */
export function fakeTraceEdges(size, requests = []) {
  return async request => {
    requests.push(request);
    const [width, height] = size(request.reference_id), base = { ms: 1, width, height, original_width: width, original_height: height };
    const [sx, sy, sw, sh] = request.source;
    if (!request.labels) return { ...base, silhouette: 'brightness', lines: [{ kind: 'outline', points: [[sx, sy + sh / 2], [sx + sw, sy + sh / 2]] }] };
    const { bounds: [bx, by], space: [W, H] } = request.labels, plane = decodePlane(Buffer.from(request.labels.png_base64, 'base64'));
    const kx = width / W, ky = height / H, left = [], right = [];
    for (let j = 0; j < plane.height; j++) {
      let first = -1, last = -1;
      for (let i = 0; i < plane.width; i++) if (plane.data[j * plane.width + i]) { if (first < 0) first = i; last = i; }
      if (first < 0) continue;
      left.push([(bx + first) * kx, (by + j + 0.5) * ky]); right.push([(bx + last + 1) * kx, (by + j + 0.5) * ky]);
    }
    if (!left.length) return { ...base, silhouette: 'shapes', lines: [] };
    return { ...base, silhouette: 'shapes', lines: [{ kind: 'outline', points: [...left.slice().reverse(), ...right] }, { kind: 'outline', points: [left.at(-1), right.at(-1)] }] };
  };
}
