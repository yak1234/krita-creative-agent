// @ts-check
// Where the agent keeps records and caches. Artwork stays in the project folder; records go to the
// platform's application-data directory and caches to its cache directory (storage-layout design 1).
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';

/** Standard data and cache directories for Creative Agent on this platform. */
export function storagePaths({ platform = process.platform, env = process.env, home = homedir() } = {}) {
  if (platform === 'darwin')
    return { data: join(home, 'Library/Application Support/Creative Agent/data'), cache: join(home, 'Library/Caches/Creative Agent') };
  if (platform === 'win32') {
    const roaming = env.APPDATA || join(home, 'AppData/Roaming'), local = env.LOCALAPPDATA || join(home, 'AppData/Local');
    return { data: join(roaming, 'Creative Agent/data'), cache: join(local, 'Creative Agent/Cache') };
  }
  return { data: join(env.XDG_DATA_HOME || join(home, '.local/share'), 'creative-agent'),
    cache: join(env.XDG_CACHE_HOME || join(home, '.cache'), 'creative-agent') };
}

/** The records folder the installed plugin's companion uses, for command-line tools. */
export async function installedDataDirectory(home = homedir()) {
  try { return JSON.parse(await readFile(join(home, 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json'), 'utf8')).data_dir; }
  catch { return undefined; }
}
