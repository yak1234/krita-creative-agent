// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// SAM 2.1 on ONNX Runtime's Node package, for the shape worker only (the companion never loads the native binding).
// The ONNX export (onnx-community/sam2.1-hiera-base-plus-ONNX) is two graphs:
// - vision_encoder.onnx: pixel_values [1,3,1024,1024] -> image_embeddings.0/.1/.2;
// - prompt_encoder_mask_decoder.onnx: input_points [1,1,N,2], input_labels [1,1,N] (int64), input_boxes [1,B,4] and the
//   three embeddings -> iou_scores [1,1,3], pred_masks [1,1,3,256,256] (logits), object_score_logits.
// A box prompt has no points (N = 0); a points prompt has no box (B = 0), which the export accepts.
// The encoder runs on the chosen provider; the decoder (a few ms) on the CPU, as in the proven Python reference.
import { join } from 'node:path';
import ort from 'onnxruntime-node';
import type { LoadedModel, Provider, ShapeRuntime, Tensor } from './core.ts';

export const ENCODER_FILE = 'vision_encoder.onnx';
export const DECODER_FILE = 'prompt_encoder_mask_decoder.onnx';

export async function onnxRuntime(): Promise<ShapeRuntime> {
  return {
    async load(modelDir: string, provider: Provider): Promise<LoadedModel> {
      const encoder = await ort.InferenceSession.create(join(modelDir, ENCODER_FILE), { executionProviders: [provider] });
      const decoder = await ort.InferenceSession.create(join(modelDir, DECODER_FILE), { executionProviders: ['cpu'] });
      return {
        async encode(pixelValues) {
          const out = await encoder.run({ pixel_values: new ort.Tensor('float32', pixelValues, [1, 3, 1024, 1024]) });
          return encoder.outputNames.map(name => {
            const tensor = out[name];
            if (!tensor) throw new Error('The shape model gave no ' + name + '.');
            return { name, data: tensor.data as Float32Array, dims: tensor.dims };
          });
        },
        async decode(feed, embeddings: Tensor[]) {
          const inputs: Record<string, InstanceType<typeof ort.Tensor>> = {
            input_points: new ort.Tensor('float32', feed.points, [1, 1, feed.count, 2]),
            input_labels: new ort.Tensor('int64', feed.labels, [1, 1, feed.count]),
            input_boxes: new ort.Tensor('float32', feed.box ?? new Float32Array(0), [1, feed.box ? 1 : 0, 4]),
          };
          for (const embedding of embeddings) inputs[embedding.name] = new ort.Tensor('float32', embedding.data, [...embedding.dims]);
          const out = await decoder.run(inputs), iou = out.iou_scores, masks = out.pred_masks;
          if (!iou || !masks) throw new Error('The shape model gave no masks.');
          return { iou: iou.data as Float32Array, masks: masks.data as Float32Array, maskSize: Number(masks.dims.at(-1)) };
        },
      };
    },
  };
}
