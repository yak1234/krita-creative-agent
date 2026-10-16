// Agent Skills bundled with the companion (krita-creative-agent/skills/<name>/SKILL.md). Pi lists
// them in the painter's system prompt when a tool named `read` exists, and the artist can type
// /skill:name in the panel. Only these skills load: the user's coding-agent skills are noise here.
// The painter's `read` opens skill files and nothing else; it has no general file access.
import { Type } from 'typebox';
import { readFileSync, readdirSync, existsSync, realpathSync, statSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// A checkout runs src/skills.mjs; the release bundle runs src/main.mjs. Both sit one folder below skills/.
export const SKILLS_DIR = fileURLToPath(new URL('../skills/', import.meta.url));
const READ_LIMIT = 100_000;

function frontmatter(text) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
  if (!match) return { fields: {}, body: text };
  const fields = Object.fromEntries(match[1].split(/\r?\n/).map(line => /^([a-z-]+):\s*(.*)$/.exec(line)).filter(Boolean)
    .map(([, key, value]) => [key, value.replace(/^["']|["']$/g, '')]));
  return { fields, body: text.slice(match[0].length) };
}

export function listSkills(directory = SKILLS_DIR) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).filter(entry => entry.isDirectory())
    .map(entry => join(directory, entry.name, 'SKILL.md')).filter(existsSync)
    .map(file => { const { fields } = frontmatter(readFileSync(file, 'utf8')); return { name: fields.name, description: fields.description, filePath: file, baseDir: join(file, '..') }; })
    .filter(skill => skill.name && skill.description);
}

// The artist's "/skill:name rest" (Pi's form) or "/name rest" (the panel's slash menu) becomes the
// skill's instructions followed by the rest, as Pi does. The studio expands before it adds its own
// context, which would otherwise hide the command from Pi. "/word" that names no skill is left as typed.
export function expandSkillCommand(text, directory = SKILLS_DIR) {
  const match = /^\/(skill:)?([a-z0-9-]+)(?:\s+([\s\S]*))?$/.exec(text?.trim() ?? '');
  if (!match) return text;
  const skill = listSkills(directory).find(s => s.name === match[2]);
  if (!skill && !match[1]) return text;
  if (!skill) throw new Error('Unknown skill "' + match[2] + '". Available: ' + listSkills(directory).map(s => s.name).join(', ') + '.');
  const body = frontmatter(readFileSync(skill.filePath, 'utf8')).body.trim();
  const block = `<skill name="${skill.name}" location="${skill.filePath}">\nReferences are relative to ${skill.baseDir}.\n\n${body}\n</skill>`;
  return match[3]?.trim() ? block + '\n\n' + match[3].trim() : block;
}

// The real path must stay inside the skills folder: no "..", no absolute paths elsewhere, no symlinks out.
export function skillFile(path, directory = SKILLS_DIR) {
  const root = realpathSync(directory);
  const target = resolve(root, String(path ?? ''));
  let real;
  try { real = realpathSync(target); } catch { throw new Error('No such skill file: ' + path); }
  if (real !== root && !real.startsWith(root + sep)) throw new Error('read opens skill files only (under ' + root + ').');
  if (!statSync(real).isFile()) throw new Error('Not a file: ' + path);
  return real;
}

export function skillReadTool(directory = SKILLS_DIR) {
  return {
    name: 'read', label: 'Reading a skill', executionMode: 'sequential',
    description: 'Read a skill file: a SKILL.md listed in available_skills, or a file it references (relative paths resolve against the skill folder). Opens skill files only.',
    parameters: Type.Object({ path: Type.String({ minLength: 1, maxLength: 1000 }) }, { additionalProperties: false }),
    execute: async (_id, { path }) => {
      const file = skillFile(path, directory);
      const text = readFileSync(file, 'utf8');
      return { content: [{ type: 'text', text: text.length > READ_LIMIT ? text.slice(0, READ_LIMIT) + '\n[truncated]' : text }], details: { path: file } };
    },
  };
}
