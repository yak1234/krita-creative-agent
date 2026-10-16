// The artwork project folder (holds .env and .creative-agent/), independent of where this checkout lives:
// KRITA_PROJECT_DIR, else the project the installed plugin was set up for.
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

export const INSTALLED_CONFIG = join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json');

export function projectDir({ env = process.env, configFile = INSTALLED_CONFIG } = {}) {
  if (env.KRITA_PROJECT_DIR) return resolve(env.KRITA_PROJECT_DIR);
  try {
    const root = JSON.parse(readFileSync(configFile, 'utf8')).project_root;
    if (root) return resolve(root);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  throw new Error('Set KRITA_PROJECT_DIR to your artwork folder, or install the plugin first.');
}
