// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// A stand-in for ONNX Runtime and Real-ESRGAN (tests only; src/upscale/core.ts's UpscaleRuntime): each input pixel becomes
// a 4x4 block, so a test can say exactly what the sharpened picture holds. FAKE_UPSCALE_FAIL names a provider whose load
// throws; FAKE_UPSCALE_DELAY is milliseconds per tile (to stop a job half-way); FAKE_UPSCALE_OFF names a provider whose
// tiles come out wrong (an accelerator that disagrees with the CPU).
export function nearest(input, tile = 128, scale = 4) {
  const side = tile * scale, out = new Float32Array(3 * side * side);
  for (let c = 0; c < 3; c++) for (let y = 0; y < side; y++) for (let x = 0; x < side; x++)
    out[c * side * side + y * side + x] = input[c * tile * tile + Math.floor(y / scale) * tile + Math.floor(x / scale)];
  return out;
}

export function fakeUpscaler({ counts = { load: [], run: {} }, fail = process.env.FAKE_UPSCALE_FAIL, off = process.env.FAKE_UPSCALE_OFF,
  delay = Number(process.env.FAKE_UPSCALE_DELAY ?? 0), broken = null } = {}) {
  return {
    counts,
    async load(modelDir, provider) {
      counts.load.push(provider);
      if (fail && provider === fail) throw new Error(provider + ' is not available here');
      return {
        async run(tile) {
          counts.run[provider] = (counts.run[provider] ?? 0) + 1;
          if (tile.length !== 3 * 128 * 128) throw new Error('bad tile');
          if (broken && provider === broken.provider && counts.run[provider] >= broken.after) throw new Error('the accelerator stopped');
          if (delay) await new Promise(resolve => setTimeout(resolve, delay));
          const out = nearest(tile);
          if (off && provider === off) out.fill(0.5);
          return out;
        },
      };
    },
  };
}

export default fakeUpscaler();
