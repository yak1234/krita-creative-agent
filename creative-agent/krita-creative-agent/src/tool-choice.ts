// Tool choice: which Krita method each of a painter's calls used, scored against what a good run of a request uses,
// so builds can be compared (scripts/evaluate-tool-choice.mjs). A stroke mass is judged by the same rule the loop
// guards hint on (extensions/loop-guards.ts). Pure functions; no I/O.
import { actionsOf, area, plain, MASS_SHARE, type Action } from '../extensions/loop-guards.ts';

export type Call = { tool: string; args: Record<string, any> };
export type Canvas = { width: number; height: number };
/** A request in the test set: `good` lists alternatives per need (any one method of each inner list). */
export type Scenario = { id: string; painting: string; prompt: string; good: string[][]; bad: string[] };
export type Score = { used: string[]; score: number; missing: string[]; avoided: string[] };
export type Run = { run: number; used: string[]; score: number; painted: boolean };
export type Summary = { id: string; counts: Record<string, number>; good: Record<string, string>; bad: Record<string, string>;
  mean_score: number; changed_nothing: number[] };
export type Report = { runs_per_scenario: number; scenarios: Pick<Summary, 'id' | 'good' | 'bad' | 'mean_score'>[] };
export type Change = { method: string; before: string; after: string; verdict: 'changed' | 'noise' };

const AVOIDED_PENALTY = 0.5;

function methodOf({ tool, args }: Action, canvas: Canvas): string[] {
  switch (tool) {
    case 'select': return [(args.steps ?? []).some((s: any) => Array.isArray(s?.seed)) ? 'seed' : 'select'];
    case 'split_by_color': return ['split'];
    case 'fill_region': case 'bucket_fill': case 'enclose_and_fill': case 'krita_gradient': return ['fill'];
    case 'smart_patch': return ['patch'];
    case 'create_layer': return [args.type === 'fill' ? 'fill_layer' : 'layer'];
    case 'apply_filter': return [args.mode === 'copy' ? 'filter' : 'filter_mask'];
    case 'clone_layer': return ['clone'];
    case 'krita_action': return ['action'];
    case 'observe_canvas': return ['look'];
    case 'paint_pass': case 'paint_recipe': case 'paint_contours': case 'painting_toolbox': {
      const mass = plain({ tool, args }) && area({ tool, args }) / (canvas.width * canvas.height) >= MASS_SHARE;
      return mass ? ['strokes', 'strokes_mass'] : ['strokes'];
    }
    default: return [tool];
  }
}

/** The methods one call used, in order; a batch is its actions. */
export function methodsOf(call: Call, canvas: Canvas): string[] {
  return actionsOf(call.tool, call.args).flatMap(action => methodOf(action, canvas));
}

export function scoreToolChoice(calls: Call[], scenario: Scenario, canvas: Canvas): Score {
  const used = [...new Set(calls.flatMap(call => methodsOf(call, canvas)))];
  const met = scenario.good.filter(options => options.some(method => used.includes(method)));
  const missing = scenario.good.filter(options => !met.includes(options)).map(options => options.join('|'));
  const avoided = scenario.bad.filter(method => used.includes(method));
  const score = Math.max(0, met.length / Math.max(1, scenario.good.length) - AVOIDED_PENALTY * avoided.length);
  return { used, score: Math.round(score * 100) / 100, missing, avoided };
}

/** The tool calls in a chat's stored session entries (Pi's message entries), in order. */
export function toolCallsFromEntries(entries: any[]): Call[] {
  return entries.flatMap(entry => entry?.message?.role === 'assistant' && Array.isArray(entry.message.content)
    ? entry.message.content.filter((part: any) => part?.type === 'toolCall').map((part: any) => ({ tool: part.name, args: part.arguments ?? {} }))
    : []);
}

/** Counts across a scenario's runs: one run is a sample, so results are "k/n", never one run's story. */
export function summarizeRuns(scenario: Scenario, runs: Run[]): Summary {
  const n = runs.length, ratio = (k: number) => `${k}/${n}`;
  const counts: Record<string, number> = {};
  for (const run of runs) for (const method of new Set(run.used)) counts[method] = (counts[method] ?? 0) + 1;
  const good = Object.fromEntries(scenario.good.map(options => [options.join('|'), ratio(runs.filter(r => options.some(m => r.used.includes(m))).length)]));
  const bad = Object.fromEntries(scenario.bad.map(method => [method, ratio(runs.filter(r => r.used.includes(method)).length)]));
  const mean = n ? runs.reduce((sum, r) => sum + r.score, 0) / n : 0;
  return { id: scenario.id, counts, good, bad, mean_score: Math.round(mean * 100) / 100,
    changed_nothing: runs.filter(r => !r.painted).map(r => r.run) };
}

/** Per scenario, the methods whose run counts differ between two reports; a difference of one run is noise. */
export function compareReports(before: Report, after: Report): { id: string; changes: Change[] }[] {
  const count = (ratio: string) => Number(ratio.split('/')[0]);
  return after.scenarios.map(scenario => {
    const earlier = before.scenarios.find(s => s.id === scenario.id);
    const changes: Change[] = [];
    for (const [method, now] of Object.entries({ ...scenario.good, ...scenario.bad })) {
      const was = earlier ? ({ ...earlier.good, ...earlier.bad } as Record<string, string>)[method] : undefined;
      if (was === undefined || was === now) continue;
      changes.push({ method, before: was, after: now, verdict: Math.abs(count(now) - count(was)) <= 1 ? 'noise' : 'changed' });
    }
    return { id: scenario.id, changes };
  });
}
