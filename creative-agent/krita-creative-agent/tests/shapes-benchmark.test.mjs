// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// OPT-IN benchmark of element shapes with the real model (skipped unless TOSKA_SHAPES_MODEL_DIR names the folder holding
// vision_encoder.onnx and prompt_encoder_mask_decoder.onnx with their .onnx_data). It runs on a copy of a real reference:
// TOSKA_SHAPES_BENCHMARK_IMAGE, by default final_goal.png two folders above the model folder (the scratch layout
// <dir>/final_goal.png, <dir>/sam2.1-hiera-base-plus/onnx/). Budgets on a Mac M-series CPU: study <= 3 s (model load
// included), each shape <= 50 ms; the tower's score >= 0.9 (the Python reference gave tower 0.96, bridge 0.88).
// Prints the timings. Writes its masks to a temporary folder that is removed.
//   TOSKA_SHAPES_MODEL_DIR=.../onnx node --test tests/shapes-benchmark.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { shapeService } from '../src/shapes/index.ts';
import { decodePng } from './fixtures/png-rgba.ts';

const MODEL_DIR = process.env.TOSKA_SHAPES_MODEL_DIR;
const IMAGE = process.env.TOSKA_SHAPES_BENCHMARK_IMAGE ?? (MODEL_DIR ? resolve(MODEL_DIR, '../../final_goal.png') : '');
const skip = !MODEL_DIR ? 'set TOSKA_SHAPES_MODEL_DIR to run the shapes benchmark'
  : !existsSync(join(MODEL_DIR, 'vision_encoder.onnx')) ? 'no vision_encoder.onnx in TOSKA_SHAPES_MODEL_DIR'
  : !existsSync(IMAGE) ? 'no benchmark image at ' + IMAGE : false;
const BOXES = { tower: [282, 24, 201, 354], bridge: [483, 523, 724, 72] };

test('SAM 2.1 base-plus on a real reference: study and shapes within budget, tower found confidently', { skip, timeout: 120000 }, async t => {
  const dir = await mkdtemp(join(tmpdir(), 'shapes-benchmark-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const image = decodePng(await readFile(IMAGE)), timings = [];
  const service = shapeService({ modelDir: async () => MODEL_DIR, cacheDir: () => dir, onTiming: entry => timings.push(entry) });
  t.after(() => service.close());
  const study = await service.study('benchmark', image.data, image.width, image.height);
  const results = {};
  for (const [name, box] of Object.entries(BOXES)) results[name] = await service.shape('benchmark', { box });
  const point = await service.shape('benchmark', { points: [[382, 200, 1]] });            // on the tower, points only (no box)
  const lines = [`shapes benchmark (${image.width}x${image.height}, provider ${study.provider}): study ${study.ms} ms (model load ${study.load_ms} ms), peak ${study.peak_mb} MB`];
  for (const [name, r] of Object.entries(results)) lines.push(`  ${name}: score ${r.score.toFixed(3)}, ${r.ms} ms, bounds [${r.bounds}], peak ${r.peak_mb} MB`);
  lines.push(`  tower by one point: score ${point.score.toFixed(3)}, ${point.ms} ms, bounds [${point.bounds}]`);
  console.log(lines.join('\n'));
  t.diagnostic(lines.join(' | '));
  assert.ok(study.ms <= 3000, `study took ${study.ms} ms (budget 3000)`);
  for (const [name, r] of Object.entries(results)) assert.ok(r.ms <= 50, `${name} took ${r.ms} ms (budget 50)`);
  assert.ok(results.tower.score >= 0.9, `tower score ${results.tower.score}`);
  const [px, py, pw, ph] = point.bounds, [tx, ty, tw, th] = results.tower.bounds;
  assert.ok(px < tx + tw && tx < px + pw && py < ty + th && ty < py + ph, 'a point on the tower finds a shape over the tower');
  assert.deepEqual(timings.map(entry => entry.kind), ['study', 'shape', 'shape', 'shape']);
});
