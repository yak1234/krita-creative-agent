// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// One real folder study (openspec folder-study 5.1), as the companion runs it: the folder is copied to a temporary folder
// first and only the copy is read; its goal and element images are studied by FolderStudy (4 at a time, a timeout per
// image, images at most 2000 px), through Pi's model runtime (completeSimple) as scripts/resolution-probe.ts calls models.
// Prints the time, the cost and every note as JSON; the notes file stays in the temporary folder, which is removed.
//   node scripts/folder-study-run.ts --folder <project folder> [--model openrouter/qwen/qwen3-vl-235b-a22b-instruct] [--out run.json]
// Keys come from Pi's own auth (as the app); they are never printed. A failed image reports a classified reason only.
import { parseArgs } from 'node:util';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { scanFolder } from '../src/project-folder.ts';
import { FolderStudy, piReader, STUDY_MODEL, type StudyImage } from '../src/folder-study.ts';
import { boundedPicture } from '../src/folder-study-chat.ts';

const { values } = parseArgs({ options: { folder: { type: 'string' }, model: { type: 'string' }, out: { type: 'string' }, timeout: { type: 'string' } } });
if (!values.folder) { process.stderr.write('Give --folder <project folder>.\n'); process.exit(2); }
const route = values.model ?? STUDY_MODEL, slash = route.indexOf('/');
if (slash < 1) { process.stderr.write('Give the model as provider/model.\n'); process.exit(2); }

const scratch = await mkdtemp(join(tmpdir(), 'folder-study-run-'));
try {
  const copy = join(scratch, 'folder'), chat = join(scratch, 'chat');
  await cp(values.folder, copy, { recursive: true }); await mkdir(chat);
  const index = await scanFolder(copy);
  const images: StudyImage[] = [...(index.goal ? [{ name: index.goal.name, path: index.goal.path, role: 'goal' as const, guess: 'Goal image' }] : []),
    ...index.elements.map(e => ({ name: e.name, path: e.path, role: 'element' as const, guess: e.guess, ...(e.prompt ? { prompt: e.prompt } : {}) }))];
  const goal = images.find(i => i.role === 'goal') ?? null;

  const { ModelRuntime, getAgentDir } = await import('@earendil-works/pi-coding-agent');
  // @ts-ignore: an .mjs module (allowJs is off in the strict project)
  const { inheritPiCatalog } = await import('../src/model-catalog.mjs');
  const pi = getAgentDir();
  const models = await ModelRuntime.create({ allowModelNetwork: false, authPath: join(pi, 'auth.json'), modelsPath: join(pi, 'models.json'),
    modelsStorePath: await inheritPiCatalog(pi, scratch), signal: AbortSignal.timeout(15000) });
  const model = models.getModel(route.slice(0, slash), route.slice(slash + 1));
  if (!model) throw new Error(`Pi has no model ${route}.`);
  if (!model.input.includes('image')) throw new Error(`${route} does not read images.`);
  if (!models.hasConfiguredAuth(model.provider)) throw new Error(`${model.provider} is not connected in Pi.`);

  const events: Record<string, unknown>[] = [];
  const study = new FolderStudy({ directory: () => chat, readImage: path => readFile(path), picture: (_path, data, side) => boundedPicture(data, side),
    reader: async () => piReader(models, model), changed: () => {}, record: event => {
      events.push(event);
      if (event.type === 'folder_study_image') process.stderr.write(`${event.name}: ${event.ok ? 'studied' : 'not studied (' + event.reason + ')'} in ${event.ms} ms, $${Number(event.cost ?? 0).toFixed(5)}\n`);
    } }, values.timeout ? { timeoutMs: Number(values.timeout) } : {});
  const started = Date.now();
  const result = await study.run(images, { goal });
  const ms = Date.now() - started, per = events.filter(e => e.type === 'folder_study_image');
  const report = { model: route, folder: index.root.split('/').at(-1), images: images.length, ...result, wall_ms: ms,
    cost: Math.round(per.reduce((s, e) => s + Number(e.cost ?? 0), 0) * 1e6) / 1e6,
    per_image_ms: per.filter(e => e.ok).map(e => e.ms), notes: Object.fromEntries(images.map(i => [i.name, study.noteOf(i.name)])) };
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  if (values.out) await writeFile(values.out, JSON.stringify(report, null, 2) + '\n');
} finally { await rm(scratch, { recursive: true, force: true }); }
