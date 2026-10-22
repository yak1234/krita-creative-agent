// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The one shape model, SAM 2.1 base-plus (Apache-2.0), downloaded on first use into the companion's data folder rather
// than bundled, so Toska's download stays the same size. Pinned: the repository, the revision, and each file's size and
// SHA-256 (taken from the files of that revision, 2026-10-21). There is no other model and no fallback.
// The download goes over HTTPS from <base>/<repo>/resolve/<revision>/onnx/<file>, resumes a broken file from its .part
// (HTTP Range), and refuses (removes) a file whose checksum differs. A folder is ready when verified.json records this
// revision and every file has its pinned size; the hash is checked once, at download.
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, open, readFile, rename, rm, stat, statfs, writeFile, type FileHandle } from 'node:fs/promises';
import { join } from 'node:path';

export type ModelFile = { name: string; size: number; sha256: string };
export type ModelSpec = { name: string; repo: string; revision: string; licence: string; files: readonly ModelFile[] };

export const SHAPES_MODEL: ModelSpec = {
  name: 'sam2.1-hiera-base-plus',
  repo: 'onnx-community/sam2.1-hiera-base-plus-ONNX',
  revision: 'bab18593f44e652f04cf18b60b3690f60e8996b0',
  licence: 'Apache-2.0',
  files: [
    { name: 'vision_encoder.onnx', size: 702836, sha256: '6fd992cf796e6ad5a29f3b92a127f2ce33f7f320d63c8b3f02bf3775f5f692f4' },
    { name: 'vision_encoder.onnx_data', size: 305746496, sha256: 'f8a5f1b14d02eb7ed3b3576ad6774b8ebcfef6cc20674d5f316d6144c60a08a5' },
    { name: 'prompt_encoder_mask_decoder.onnx', size: 213114, sha256: 'f39eeec20243ed1c8f2cd013812e77813d937ddbc800fa4bc703761adc7e63cd' },
    { name: 'prompt_encoder_mask_decoder.onnx_data', size: 20958208, sha256: '445cd3f72a218815db10e336f4f1c46a6eb2713a0160a85af5365134607f32a7' },
  ],
};
export const MODEL_HOST = 'https://huggingface.co';
const MARKER = 'verified.json';

export const modelBytes = (spec: ModelSpec = SHAPES_MODEL): number => spec.files.reduce((sum, file) => sum + file.size, 0);
/** The model's folder in the companion's data folder: one per model and revision. */
export const modelDirectory = (dataDir: string, spec: ModelSpec = SHAPES_MODEL): string => join(dataDir, 'models', spec.name, spec.revision);

/** True when the folder holds this revision, verified at download, with every file at its pinned size. */
export async function modelReady(directory: string, spec: ModelSpec = SHAPES_MODEL): Promise<boolean> {
  try {
    const marker = JSON.parse(await readFile(join(directory, MARKER), 'utf8'));
    if (marker.revision !== spec.revision) return false;
    for (const file of spec.files) {
      if (marker.files?.[file.name] !== file.sha256) return false;
      if ((await stat(join(directory, file.name))).size !== file.size) return false;
    }
    return true;
  } catch { return false; }
}

async function fileHash(path: string): Promise<string> {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path)) hash.update(chunk as Buffer);
  return hash.digest('hex');
}

export type DownloadErrorCode = 'checksum' | 'http' | 'network' | 'space';
export class ModelDownloadError extends Error {
  readonly code: DownloadErrorCode;
  constructor(code: DownloadErrorCode, message: string) { super(message); this.name = 'ModelDownloadError'; this.code = code; }
}

const MB = (bytes: number, round: (n: number) => number) => round(bytes / 1e6);
const diskFull = () => new ModelDownloadError('space', 'The disk is full: the shape model download stopped and its partial file was removed. '
  + 'Free some space and try again.');

/** Downloads what is missing of the model into `directory`, resuming, checking each file's SHA-256. The free space is
 * checked first; a disk that fills up anyway removes the file being written (Ruling: its space goes back to the artist,
 * and the files already complete stay). An abort keeps the .part for next time. */
export async function downloadModel({ directory, spec = SHAPES_MODEL, baseUrl = MODEL_HOST, fetch = globalThis.fetch, onProgress, signal,
  freeBytes = async (dir: string) => { const disk = await statfs(dir); return disk.bavail * disk.bsize; },
  write = (handle: FileHandle, chunk: Uint8Array) => handle.write(chunk) }:
  { directory: string; spec?: ModelSpec; baseUrl?: string; fetch?: typeof globalThis.fetch; onProgress?: (done: number, total: number) => void;
    signal?: AbortSignal; freeBytes?: (directory: string) => Promise<number>; write?: (handle: FileHandle, chunk: Uint8Array) => Promise<unknown> }): Promise<void> {
  if (await modelReady(directory, spec)) return;
  signal?.throwIfAborted();
  await mkdir(directory, { recursive: true });
  const total = modelBytes(spec);
  let present = 0;
  for (const file of spec.files) {
    const size = (await stat(join(directory, file.name)).catch(() => null))?.size ?? (await stat(join(directory, file.name + '.part')).catch(() => null))?.size ?? 0;
    present += Math.min(size, file.size);
  }
  const needed = total - present, free = await freeBytes(directory);
  if (free < needed)
    throw new ModelDownloadError('space', `Downloading the shape model needs about ${MB(needed, Math.ceil)} MB free on this disk; ${MB(free, Math.floor)} MB are free. `
      + 'Free some space and try again.');
  let before = 0;
  for (const file of spec.files) {
    const target = join(directory, file.name), part = target + '.part';
    const existing = await stat(target).catch(() => null);
    if (existing?.size === file.size && await fileHash(target) === file.sha256) { before += file.size; onProgress?.(before, total); continue; }
    let have = (await stat(part).catch(() => null))?.size ?? 0;
    if (have > file.size) { await rm(part, { force: true }); have = 0; }
    if (have < file.size) {
      const url = `${baseUrl}/${spec.repo}/resolve/${spec.revision}/onnx/${encodeURIComponent(file.name)}`;
      const get = async (from: number): Promise<Response> => {
        try { return await fetch(url, { headers: from ? { Range: `bytes=${from}-` } : {}, signal: signal ?? null, redirect: 'follow' }); }
        catch (error) { throw new ModelDownloadError('network', `Downloading ${file.name} failed: ${(error as Error).message}. It resumes next time.`); }
      };
      let response = await get(have);
      // A 206 must continue where the file stopped; one that starts elsewhere is not appended: the file starts again.
      const start = Number(/^bytes (\d+)-/.exec(response.headers.get('content-range') ?? '')?.[1] ?? NaN);
      if (response.status === 206 && start !== have) { await response.body?.cancel(); have = 0; response = await get(0); }
      if (response.status !== 200 && response.status !== 206) throw new ModelDownloadError('http', `Downloading ${file.name} failed: HTTP ${response.status}.`);
      if (response.status === 200) have = 0;           // the server sent the whole file: start it again
      if (!response.body) throw new ModelDownloadError('network', `Downloading ${file.name} failed: no data.`);
      const handle = await open(part, have ? 'a' : 'w');
      let done = have, refused: ModelDownloadError | null = null;
      try {
        for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
          if (done + chunk.length > file.size) { refused = new ModelDownloadError('checksum', `${file.name} is larger than its pinned size: refused and removed.`); break; }
          await write(handle, chunk); done += chunk.length;
          onProgress?.(before + done, total);
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOSPC') refused = diskFull();
        else throw new ModelDownloadError('network', `Downloading ${file.name} stopped: ${(error as Error).message}. It resumes next time.`);
      } finally { await handle.close(); }
      if (refused) { await rm(part, { force: true }); throw refused; }
    }
    if ((await stat(part)).size !== file.size) throw new ModelDownloadError('network', `Downloading ${file.name} stopped early. It resumes next time.`);
    if (await fileHash(part) !== file.sha256) {
      await rm(part, { force: true });
      throw new ModelDownloadError('checksum', `${file.name} does not match its pinned checksum: refused and removed.`);
    }
    await rename(part, target);
    before += file.size; onProgress?.(before, total);
  }
  const marker = { model: spec.name, repo: spec.repo, revision: spec.revision, files: Object.fromEntries(spec.files.map(f => [f.name, f.sha256])),
    verified_at: new Date().toISOString() };
  await writeFile(join(directory, MARKER + '.tmp'), JSON.stringify(marker, null, 2));
  await rename(join(directory, MARKER + '.tmp'), join(directory, MARKER));
}
