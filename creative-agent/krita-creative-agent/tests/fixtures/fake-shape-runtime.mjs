// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A stand-in for ONNX Runtime and SAM 2.1 (tests only; src/shapes/core.ts's ShapeRuntime): the "mask" is the prompt's box
// (or a disc around each included point) on a 16x16 grid in the 1024 space, and the scores are fixed, so a test can say
// exactly which pixels a shape holds. FAKE_SHAPES_FAIL names a provider whose load throws.
export const MASK = 16;

export function fakeRuntime({ counts = { load: 0, encode: 0, decode: 0 }, fail = process.env.FAKE_SHAPES_FAIL } = {}) {
  return {
    counts,
    async load(modelDir, provider) {
      counts.load++;
      if (fail && provider === fail) throw new Error(provider + ' is not available here');
      return {
        async encode(pixels) {
          counts.encode++;
          if (pixels.length !== 3 * 1024 * 1024) throw new Error('bad encoder input');
          let sum = 0; for (let i = 0; i < pixels.length; i += 4099) sum += pixels[i];
          return [{ name: 'image_embeddings.0', data: Float32Array.of(sum), dims: [1] }];
        },
        async decode(feed, embeddings) {
          counts.decode++;
          if (embeddings.length !== 1) throw new Error('bad embeddings');
          const masks = new Float32Array(3 * MASK * MASK).fill(-5), cell = 1024 / MASK;
          for (let y = 0; y < MASK; y++) for (let x = 0; x < MASK; x++) {
            const cx = (x + 0.5) * cell, cy = (y + 0.5) * cell;
            let inside = false;
            if (feed.box) inside = cx >= feed.box[0] && cx <= feed.box[2] && cy >= feed.box[1] && cy <= feed.box[3];
            for (let i = 0; i < feed.count; i++) {
              const near = Math.hypot(cx - feed.points[i * 2], cy - feed.points[i * 2 + 1]) < 100;
              if (near) inside = feed.labels[i] === 1n;
            }
            if (inside) masks[MASK * MASK + y * MASK + x] = 5;           // the second mask is the best one
          }
          return { iou: Float32Array.of(0.5, 0.93, 0.7), masks, maskSize: MASK };
        },
      };
    },
  };
}

export default fakeRuntime();
