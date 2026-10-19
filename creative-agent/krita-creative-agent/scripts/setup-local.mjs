import { existsSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectDir } from './project-dir.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageInfo = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
for (const [name, version] of Object.entries(packageInfo.dependencies)) {
  const directory = join(root, 'node_modules', name);
  if (!existsSync(join(directory, 'package.json'))) throw new Error(`Run npm install first. Missing dependency: ${name}`);
  const installed = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8'));
  if (installed.version !== version) throw new Error(`Install the pinned ${name} ${version}; found ${installed.version}.`);
  const path = relative(root, realpathSync(directory));
  if (path.startsWith('..') || isAbsolute(path))
    throw new Error(`${name} points outside this project. Replace development symlinks with npm install before setup.`);
}
const configFile = join(root, '.local-config.json');
let existing = {};
if (existsSync(configFile)) existing = JSON.parse(readFileSync(configFile, 'utf8'));
const projectRoot = resolve(process.env.KRITA_PROJECT_DIR || existing.project_root || existing.paintings_dir || projectDir());
const config = {
  ...existing,
  node: process.execPath,
  companion: join(root, 'src/main.mjs'),
  project_root: projectRoot,
  paintings_dir: projectRoot,
  output: join(projectRoot, '.creative-agent'),
  legacy_output: existing.legacy_output || existing.output || join(root, 'output'),
  bridge_url: existing.bridge_url || 'http://127.0.0.1:5678',
};
delete config.python;
writeFileSync(configFile, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 });
console.log('Local companion configured. Artwork stays in: ' + projectRoot);
console.log('Build and stage a release to install it into Krita. No plugin files were changed.');
