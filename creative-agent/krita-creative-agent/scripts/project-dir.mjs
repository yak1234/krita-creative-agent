// The artwork project folder (holds .env and .creative-agent/), independent of where this checkout lives:
// KRITA_PROJECT_DIR, else the project the installed plugin was set up for. The installed plugin is stock Krita's unless
// KRITA_CREATIVE_CONFIG names another Krita's panel config (the Qt6 fork's, in its own pykrita folder, on its own port).
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

export const INSTALLED_CONFIG = join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json');

/** The installed panel's creative-agent-config.json that development tools follow. */
export function panelConfig(env = process.env) { return env.KRITA_CREATIVE_CONFIG || INSTALLED_CONFIG; }

export function projectDir({ env = process.env, configFile = panelConfig(env) } = {}) {
  if (env.KRITA_PROJECT_DIR) return resolve(env.KRITA_PROJECT_DIR);
  try {
    const root = JSON.parse(readFileSync(configFile, 'utf8')).project_root;
    if (root) return resolve(root);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  throw new Error('Set KRITA_PROJECT_DIR to your artwork folder, or install the plugin first.');
}
