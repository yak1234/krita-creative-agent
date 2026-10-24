// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The one sharpening model: Real-ESRGAN x4plus (xinntao/Real-ESRGAN, BSD-3-Clause, Copyright (c) 2021 Xintao Wang), as
// Qualcomm AI Hub exports it to ONNX (the Hugging Face card qualcomm/Real-ESRGAN-x4plus: licence bsd-3-clause, its
// LICENSE file points to the original's). Qualcomm publishes the ONNX export as a zip on its public asset bucket, at a
// versioned path the card links (release v0.65.0); the archive and each file in it are pinned by size and SHA-256 (taken
// from the files, 2026-10-24), so a changed upload is refused, never used. It downloads on first use into the companion's
// data folder, as the shape model does (shapes/model.ts), so Toska's download stays the same size.
// The graph takes one RGB tile [1,3,128,128] in 0..1 ("image") and gives it 4x larger [1,3,512,512] ("upscaled_image").
import type { ModelSpec } from '../shapes/model.ts';

export const UPSCALE_MODEL: ModelSpec = {
  name: 'real-esrgan-x4plus',
  repo: 'qualcomm/Real-ESRGAN-x4plus',
  revision: 'qai-hub-models-v0.65.0',
  licence: 'BSD-3-Clause',
  label: 'the sharpening model',
  archive: {
    url: 'https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/real_esrgan_x4plus/releases/v0.65.0/real_esrgan_x4plus-onnx-float.zip',
    size: 62174027, sha256: '05aa31323c6a7e831493171cac970e398697709cae7e7ae8e0760e6da4d64ca4', folder: 'real_esrgan_x4plus-onnx-float/',
  },
  files: [
    { name: 'real_esrgan_x4plus.onnx', size: 3158313, sha256: '0c40d89889e621d4f1a9a0a6d728e4ccd612a67a90927ca8b394eb0917329ed9' },
    { name: 'real_esrgan_x4plus.data', size: 66737664, sha256: '28fada125730d3c87d504d48dd8332837f65811ec431a570ea4919ba3eee3287' },
  ],
};
export const UPSCALE_GRAPH = 'real_esrgan_x4plus.onnx';
/** The graph's fixed tile: 128 pixels a side in, SCALE times that out. */
export const TILE = 128;
export const SCALE = 4;
