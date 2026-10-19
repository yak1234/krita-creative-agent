#!/usr/bin/env node
// Rollback for storage-layout phase A: move a project's chats from the agent records back into the
// project's .creative-agent/studies/ folder, in the format earlier builds read. Run with Krita idle.
//   node scripts/unmigrate.mjs <project folder>
import { ProjectStore } from '../src/project-store.mjs';
import { installedDataDirectory } from '../src/storage-paths.mjs';

const [project] = process.argv.slice(2);
if (!project) { console.error('Usage: unmigrate.mjs <project folder>'); process.exit(2); }
const store = new ProjectStore({ projectRoot: project, dataDirectory: await installedDataDirectory() });
const report = await store.unmigrateProjectFolder();
store.close();
console.log(`Moved ${report.restored.length} chats back into the project.` + (report.errors.length ? ` ${report.errors.length} failed: ${JSON.stringify(report.errors)}` : ''));
process.exit(report.errors.length ? 1 : 0);
