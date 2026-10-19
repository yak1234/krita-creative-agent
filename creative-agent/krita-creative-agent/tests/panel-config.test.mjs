// Development tools find the installed panel's config: stock Krita's, or another Krita's (the Qt6 fork, with its own
// pykrita folder and bridge port) when KRITA_CREATIVE_CONFIG names it. Files go to a temporary folder that is removed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { INSTALLED_CONFIG, panelConfig, projectDir } from '../scripts/project-dir.mjs';
import { installedDataDirectory } from '../src/storage-paths.mjs';

test('the stock panel config is the default', () => {
  assert.equal(panelConfig({}), INSTALLED_CONFIG);
  assert.equal(INSTALLED_CONFIG, join(homedir(), 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json'));
});

test('KRITA_CREATIVE_CONFIG names another Krita’s panel config, for the project and the records folder', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'panel-config-'));
  try {
    const config = join(folder, 'creative-agent-config.json');
    await writeFile(config, JSON.stringify({ project_root: join(folder, 'Art'), data_dir: join(folder, 'KritaAgent/data') }));
    const env = { KRITA_CREATIVE_CONFIG: config };
    assert.equal(panelConfig(env), config);
    assert.equal(projectDir({ env }), join(folder, 'Art'));
    assert.equal(await installedDataDirectory(undefined, env), join(folder, 'KritaAgent/data'));
  } finally { await rm(folder, { recursive: true, force: true }); }
});
