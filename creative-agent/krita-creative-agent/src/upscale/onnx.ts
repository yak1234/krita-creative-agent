// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// Real-ESRGAN x4plus on ONNX Runtime's Node package, for the sharpening worker only (the companion never loads the native
// binding). The export (model.ts) is one graph with its weights beside it: image [1,3,128,128] -> upscaled_image
// [1,3,512,512], both RGB in 0..1.
import { join } from 'node:path';
import ort from 'onnxruntime-node';
import type { Provider, UpscaleRuntime } from './core.ts';
import { SCALE, TILE, UPSCALE_GRAPH } from './model.ts';

export async function onnxUpscaler(): Promise<UpscaleRuntime> {
  return {
    async load(modelDir: string, provider: Provider) {
      const session = await ort.InferenceSession.create(join(modelDir, UPSCALE_GRAPH), { executionProviders: [provider] });
      const input = session.inputNames[0] ?? 'image', output = session.outputNames[0] ?? 'upscaled_image';
      return {
        async run(tile: Float32Array) {
          const out = (await session.run({ [input]: new ort.Tensor('float32', tile, [1, 3, TILE, TILE]) }))[output];
          if (!out || out.dims.at(-1) !== TILE * SCALE) throw new Error('The sharpening model gave no tile.');
          return out.data as Float32Array;
        },
      };
    },
  };
}
