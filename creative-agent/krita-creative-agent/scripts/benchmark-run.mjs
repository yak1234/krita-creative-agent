// Speed report for one Krita chat, from its Langfuse session: painter calls,
// minutes per category, tokens, and review checks met over time.
//   node scripts/benchmark-run.mjs <chat-id> [--keys env|dotenv] [--json report.json]
// --keys env uses the shell's LANGFUSE_* (e.g. to read an older project); the default
// is the project's .env, like the companion.
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { projectDir } from './project-dir.mjs';
import { connectLangfuse } from '../src/langfuse-tracing.mjs';

const [chatId, ...rest] = process.argv.slice(2);
if (!chatId) { console.error('Usage: node scripts/benchmark-run.mjs <chat-id> [--keys env|dotenv] [--json report.json]'); process.exit(2); }
const flag = name => { const i = rest.indexOf(name); return i >= 0 ? rest[i + 1] : undefined; };
const useEnv = flag('--keys') === 'env';
const dotEnvPath = join(projectDir(), '.env');
const tracing = await connectLangfuse(useEnv ? { env: process.env, keychain: async () => null } : { dotEnvPath });

const rows = [];
let cursor;
do {
  const page = await tracing.client.api.observations.getMany({ sessionId: chatId, fields: 'core,basic,usage,metrics,io', limit: 1000, ...(cursor ? { cursor } : {}) });
  rows.push(...page.data); cursor = page.meta?.cursor;
} while (cursor);
await tracing.shutdown();
if (!rows.length) { console.error('No observations for chat ' + chatId + ' in ' + tracing.describe() + '.'); process.exit(1); }

export function benchmark(observations) {
  const seconds = o => o.endTime ? (Date.parse(o.endTime) - Date.parse(o.startTime)) / 1000 : 0;
  const category = o => o.name === 'choose-next-action' ? 'painter model calls'
    : ['review-canvas'].includes(o.name) ? 'reviews'
    : o.name.startsWith('luna-') ? 'Luna decisions'
    : o.name === 'prepare-batch' ? 'parallel preparation'
    : o.type === 'TOOL' && !['submit_review', 'submit_batch_proposal'].includes(o.name) ? 'painting tools'
    : null;
  const totals = {};
  for (const o of observations) { const c = category(o); if (c) { totals[c] ??= { calls: 0, minutes: 0 }; totals[c].calls++; totals[c].minutes += seconds(o) / 60; } }
  const painter = observations.filter(o => o.name === 'choose-next-action');
  const input = painter.map(o => o.usageDetails?.input ?? 0);
  const runs = observations.filter(o => o.name === 'paint-goal');
  const reviews = observations.filter(o => o.name === 'submit_review').sort((a, b) => a.startTime.localeCompare(b.startTime)).map(o => {
    const value = typeof o.input === 'string' ? JSON.parse(o.input) : o.input;
    const checks = value?.checks ?? [];
    return { at: o.startTime, met: checks.filter(c => c.met).length, total: checks.length };
  });
  return {
    painting_minutes: runs.reduce((sum, o) => sum + seconds(o) / 60, 0),
    painter_calls: painter.length,
    painter_mean_seconds: painter.length ? painter.reduce((s, o) => s + seconds(o), 0) / painter.length : 0,
    painter_input_tokens: { mean: input.length ? Math.round(input.reduce((a, b) => a + b, 0) / input.length) : 0, max: Math.max(0, ...input) },
    categories: totals,
    reviews: reviews.length,
    best_checks_met: reviews.reduce((best, r) => r.met / (r.total || 1) > best.met / (best.total || 1) ? r : best, { met: 0, total: 0 }),
    last_checks_met: reviews.at(-1) ?? null,
  };
}

const report = { chat_id: chatId, project: tracing.describe(), ...benchmark(rows) };
const fmt = n => n.toFixed(1);
console.log(`Chat ${chatId} (${report.project})`);
console.log(`Painting: ${fmt(report.painting_minutes)} min · painter calls ${report.painter_calls} (${fmt(report.painter_mean_seconds)} s each, input ${report.painter_input_tokens.mean} mean / ${report.painter_input_tokens.max} max tokens)`);
for (const [name, t] of Object.entries(report.categories).sort((a, b) => b[1].minutes - a[1].minutes)) console.log(`  ${name.padEnd(22)} ${String(t.calls).padStart(4)} calls  ${fmt(t.minutes).padStart(6)} min`);
console.log(`Reviews: ${report.reviews} · best ${report.best_checks_met.met}/${report.best_checks_met.total} · last ${report.last_checks_met ? report.last_checks_met.met + '/' + report.last_checks_met.total : 'none'}`);
if (flag('--json')) await writeFile(flag('--json'), JSON.stringify(report, null, 2) + '\n');
