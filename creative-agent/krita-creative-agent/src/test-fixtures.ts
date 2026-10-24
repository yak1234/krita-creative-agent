// The test driver's copies (scripts/test-driver.ts, the MCP's creative_test_* tools). A test chat never sees the
// artist's project folder or reference images: they are copied into the test chat's own folder first, and the copies are
// deleted when it ends. Test assets are fixtures the driver keeps in its own folder (test-assets/<name>), prepared once
// from a source folder that is only ever read, and copied again for each test chat (folder 'test-assets:<name>').
// Development only.
import { copyFile, lstat, mkdir, readFile, readdir, realpath, rm, stat } from 'node:fs/promises';
import { basename, extname, isAbsolute, join, relative, resolve, sep } from 'node:path';

/** How much one copy may hold: a project folder of references, not a disk. */
export type CopyLimits = { files: number; bytes: number };
const LIMITS: CopyLimits = { files: 400, bytes: 600 * 1024 * 1024 };
const IMAGE = new Set(['.png', '.jpg', '.jpeg', '.gif']);
/** A fixture's fresh plan: the source's PLAN.md, its backups and NOTES.md stay behind. */
const FIXTURE_SKIP = /^(PLAN([.-].*)?\.md|NOTES([.-].*)?\.md)$/i;
export const ASSETS_PREFIX = 'test-assets:';
const NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,99}$/;

/** The folder creative_test_assets 'prepare' copies when it names none, relative to a panel config's project root. */
export const ASSETS_SOURCE = join('new_moscow', 'moscow-painting-assets');

/** The default test-assets source: `override` (TEST_ASSETS_SOURCE) when set, else ASSETS_SOURCE under the first of the
 * panel configs' project roots that has it (the fork's own config first, then stock Krita's: in Toska the project root is
 * Toska's paintings folder, the artist's folder is stock Krita's), else under the first root, so a refusal names it. */
export async function assetsSource({ override, configs }: { override?: string; configs: readonly string[] }): Promise<string | undefined> {
  if (override) return override;
  const roots: string[] = [];
  for (const config of configs) {
    try { const root = JSON.parse(await readFile(config, 'utf8')).project_root; if (typeof root === 'string' && isAbsolute(root)) roots.push(root); }
    catch { /* no such Krita on this computer */ }
  }
  for (const root of roots) if (await stat(join(root, ASSETS_SOURCE)).then(info => info.isDirectory(), () => false)) return join(root, ASSETS_SOURCE);
  return roots[0] ? join(roots[0], ASSETS_SOURCE) : undefined;
}

const inside = (child: string, parent: string) => child === parent || child.startsWith(parent + sep);

/** The real path of `path` as far as it exists, then the rest as written (a destination not made yet). */
async function realish(path: string): Promise<string> {
  let head = resolve(path), tail = '';
  for (;;) {
    try { return join(await realpath(head), tail); }
    catch {
      const parent = resolve(head, '..');
      if (parent === head) return resolve(path);
      tail = join(basename(head), tail); head = parent;
    }
  }
}

async function sourceFolder(path: string): Promise<string> {
  if (typeof path !== 'string' || !isAbsolute(path)) throw new Error('The project folder must be an absolute path.');
  const real = await realpath(path).catch(() => null);
  if (!real || !(await lstat(real)).isDirectory()) throw new Error(`${basename(path)} is not a folder.`);
  return real;
}

/** Copy the folder `source` into `parent`/<its name>: its regular files and those of its subfolders one level down (as
 * the project folder scan reads it), never a link or a hidden file. `skip` leaves out matching file names. The copy can
 * never land inside the source. Returns the copy's path. */
export async function copyProjectFolder(source: string, parent: string, limits: Partial<CopyLimits> = {},
  skip?: RegExp): Promise<string> {
  const { files, bytes } = { ...LIMITS, ...limits };
  const root = await sourceFolder(source);
  const target = join(parent, basename(root));
  if (inside(await realish(target), root)) throw new Error('The copy would be inside the folder it copies: choose another test folder.');
  const plan: { from: string; to: string }[] = [];
  let total = 0;
  const visit = async (folder: string, depth: number) => {
    for (const entry of (await readdir(folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name.startsWith('.') || entry.isSymbolicLink()) continue;
      const path = join(folder, entry.name);
      if (entry.isDirectory()) { if (depth === 0) await visit(path, 1); continue; }
      if (!entry.isFile() || skip?.test(entry.name)) continue;
      total += (await lstat(path)).size;
      plan.push({ from: path, to: join(target, relative(root, path)) });
      if (plan.length > files) throw new Error(`The folder has more than ${files} files: copy a smaller folder for a test.`);
      if (total > bytes) throw new Error(`The folder holds more than ${Math.round(bytes / 1048576)} MB: copy a smaller folder for a test.`);
    }
  };
  await visit(root, 0);
  try {
    for (const { from, to } of plan) { await mkdir(resolve(to, '..'), { recursive: true }); await copyFile(from, to); }
    if (!plan.length) await mkdir(target, { recursive: true });
  } catch (error) { await rm(target, { recursive: true, force: true }); throw error; }
  return target;
}

/** Copy up to four reference images (absolute paths of PNG, JPEG or GIF files) into `folder`, numbered in order. */
export async function copyReferences(paths: readonly string[], folder: string): Promise<string[]> {
  if (!Array.isArray(paths)) throw new Error('references is a list of image paths.');
  if (paths.length > 4) throw new Error('Attach up to four reference images.');
  for (const path of paths) {
    if (typeof path !== 'string' || !isAbsolute(path)) throw new Error('Each reference must be an absolute path.');
    if (!IMAGE.has(extname(path).toLowerCase())) throw new Error(`${basename(path)}: attach a PNG, JPEG or GIF reference image.`);
    const info = await lstat(path).catch(() => null);
    if (!info?.isFile()) throw new Error(`${basename(path)} is not a regular file (links are not followed).`);
  }
  const copies: string[] = [];
  try {
    for (const [index, path] of paths.entries()) {
      await mkdir(folder, { recursive: true });
      const copy = join(folder, `${index + 1}-${basename(path)}`);
      await copyFile(path, copy); copies.push(copy);
    }
  } catch (error) { await rm(folder, { recursive: true, force: true }); throw error; }
  return copies;
}

/** The driver's test assets: fixtures in `root` (its own folder, never the artist's), each prepared once from a source. */
export class TestAssets {
  readonly root: string;
  constructor(root: string) { this.root = root; }

  private path(name: string): string {
    if (typeof name !== 'string' || !NAME.test(name) || name.includes('..')) throw new Error('A test asset is named by a plain folder name.');
    return join(this.root, name);
  }

  /** Copy `source` into test-assets/<its name> unless it is there already; the source is only read. */
  async prepare(source: string): Promise<{ status: 'ok'; name: string; folder: string; prepared: boolean; files: number }> {
    const real = await sourceFolder(source);
    if (inside(await realish(this.root), real)) throw new Error('The test assets would be inside the folder they copy.');
    const name = basename(real), target = this.path(name);
    let prepared = false;
    if (!(await lstat(target).catch(() => null))) { await copyProjectFolder(real, this.root, {}, FIXTURE_SKIP); prepared = true; }
    return { status: 'ok', name, folder: ASSETS_PREFIX + name, prepared, files: await count(target) };
  }

  async list(): Promise<{ name: string; folder: string; files: number }[]> {
    const entries = await readdir(this.root, { withFileTypes: true }).catch(() => []);
    const found = [];
    for (const entry of entries.filter(e => e.isDirectory() && !e.name.startsWith('.')).sort((a, b) => a.name.localeCompare(b.name)))
      found.push({ name: entry.name, folder: ASSETS_PREFIX + entry.name, files: await count(join(this.root, entry.name)) });
    return found;
  }

  async remove(name: string): Promise<{ status: 'ok'; removed: string }> {
    const target = this.path(name);
    if (!(await lstat(target).catch(() => null))) throw new Error(`There is no test asset ${name}.`);
    await rm(target, { recursive: true, force: true });
    return { status: 'ok', removed: name };
  }

  /** 'test-assets:<name>' as its fixture's path (which must be prepared); any other folder as given. */
  async resolve(folder: string): Promise<string> {
    if (!folder.startsWith(ASSETS_PREFIX)) return folder;
    const name = folder.slice(ASSETS_PREFIX.length), target = this.path(name);
    if (!(await lstat(target).catch(() => null))?.isDirectory()) throw new Error(`The test asset ${name} is not prepared: run creative_test_assets('prepare') first.`);
    return target;
  }
}

async function count(folder: string): Promise<number> {
  return (await readdir(folder, { recursive: true, withFileTypes: true }).catch(() => [])).filter(e => e.isFile()).length;
}
