// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// The library of effects (openspec custom-effects): the bundled recipes (krita-creative-agent/effects/) and the artist's own
// (a folder the caller names, in the data dir, never the painting's folder). An own effect overrides a bundled one of the
// same name. A recipe that does not check is skipped with its file and field named; the others still load.
import { copyFile, mkdir, readdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { stringify } from 'yaml';
import { NAME_PATTERN, parseRecipe, type Recipe } from './recipe.ts';

export type LibraryEffect = Recipe & { source: 'bundled' | 'own'; file: string };
export type Library = { effects: Map<string, LibraryEffect>; skipped: string[] };

/** A kept effect's texture (the last-resort AI texture, effects/build.ts) lies beside its recipe as <name>.texture.png; the
 * recipe's texture block names it relatively, and paint_effect copies it into the chat's folder before painting. */
export const TEXTURE_FILE = /^[a-z0-9-]{1,60}\.texture\.png$/;
export const textureFile = (name: string) => `${name}.texture.png`;

/** Files in the bundled folder that are settings, not recipes. */
const NOT_RECIPES = new Set(['policy.yaml']);

async function yamlFiles(dir: string): Promise<string[]> {
  try {
    return (await readdir(dir)).filter(f => f.endsWith('.yaml') && !f.startsWith('.')).sort();
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT' || (e as NodeJS.ErrnoException).code === 'ENOTDIR') return [];
    throw e;
  }
}

export async function loadEffects(dirs: { bundled: string; own: string }): Promise<Library> {
  const effects = new Map<string, LibraryEffect>();
  const skipped: string[] = [];
  for (const source of ['bundled', 'own'] as const) {
    const dir = dirs[source];
    for (const name of await yamlFiles(dir)) {
      if (source === 'bundled' && NOT_RECIPES.has(name)) continue;
      const file = join(dir, name);
      let text: string;
      try {
        text = await readFile(file, 'utf8');
      } catch (e) {
        skipped.push(`${name}: could not be read (${(e as Error).message})`);
        continue;
      }
      const parsed = parseRecipe(text, name);
      if ('error' in parsed) skipped.push(parsed.error);
      else effects.set(parsed.recipe.name, { ...parsed.recipe, source, file });
    }
  }
  return { effects, skipped };
}

function ownFile(own: string, name: string): string {
  if (!NAME_PATTERN.test(name)) throw new Error(`An effect name is lowercase letters, digits and hyphens (got ${JSON.stringify(name)}).`);
  return join(own, `${name}.yaml`);
}

/** Writes <own>/<name>.yaml atomically (a temp file, then rename). Returns the path. A recipe that would not load is refused.
 * `texture`: an image the recipe's texture blocks name by that path (in a chat's folder); it is copied beside the recipe as
 * <name>.texture.png and those blocks then name it relatively, so the effect paints in any later chat. */
export async function saveEffect(own: string, recipe: Recipe, texture?: string): Promise<string> {
  const file = ownFile(own, recipe.name);
  const kept: Recipe = texture
    ? { ...recipe, blocks: recipe.blocks.map(b => (b.block === 'texture' && b.image_path === texture ? { ...b, image_path: textureFile(recipe.name) } : b)) }
    : recipe;
  const text = stringify(kept);
  const checked = parseRecipe(text, `${recipe.name}.yaml`);
  if ('error' in checked) throw new Error(checked.error);
  await mkdir(own, { recursive: true });
  const temp = join(own, `.${recipe.name}.yaml.${process.pid}.tmp`);
  const image = join(own, textureFile(recipe.name)), imageTemp = join(own, `.${textureFile(recipe.name)}.${process.pid}.tmp`);
  try {
    if (texture) { await copyFile(texture, imageTemp); await rename(imageTemp, image); }
    await writeFile(temp, text, 'utf8');
    await rename(temp, file);
  } catch (e) {
    await rm(temp, { force: true }); await rm(imageTemp, { force: true });
    throw e;
  }
  return file;
}

/** Deletes the artist's effect of that name, found by the recipe's own `name:` in whatever file holds it (a file named
 * after another effect is left alone), and its texture; false if nothing was removed. */
export async function removeEffect(own: string, name: string): Promise<boolean> {
  ownFile(own, name);                                                  // the name check
  let removed = false;
  for (const file of await yamlFiles(own)) {
    let text: string;
    try { text = await readFile(join(own, file), 'utf8'); } catch { continue; }
    const parsed = parseRecipe(text, file);
    if ('error' in parsed || parsed.recipe.name !== name) continue;
    try { await rm(join(own, file)); removed = true; } catch (e) { if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e; }
  }
  if (removed) await rm(join(own, textureFile(name)), { force: true });
  return removed;
}

/** Deletes every effect in the artist's folder: each *.yaml and each <name>.texture.png (nothing else, never the bundled
 * folder). Returns how many recipes. */
export async function resetEffects(own: string): Promise<number> {
  const files = await yamlFiles(own);
  for (const name of files) await rm(join(own, name), { force: true });
  let textures: string[] = [];
  try { textures = (await readdir(own)).filter(f => TEXTURE_FILE.test(f)); } catch { /* no folder: nothing to delete */ }
  for (const name of textures) await rm(join(own, name), { force: true });
  return files.length;
}
