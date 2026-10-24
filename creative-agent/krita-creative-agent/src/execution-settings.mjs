// @ts-check
import { SETTINGS, SETTING_DEFAULTS, validSetting } from './settings-schema.mjs';
// The decision endpoint and model default to GPT-6 Luna Decisions on OpenRouter.
export const DEFAULT_DECISIONS = Object.freeze({endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'});
// Defaults and validation come from the declarations in settings-schema.mjs; decisions keeps its own.
export const DEFAULT_EXECUTION_SETTINGS = Object.freeze({ ...SETTING_DEFAULTS, decisions: DEFAULT_DECISIONS });
export function executionSettings(value={}) {
  /** @type {Record<string, any>} */
  const settings={...DEFAULT_EXECUTION_SETTINGS,...value};
  // 2048 px was a choice until Pi's image resize (2000 px a side at most) was found to shrink it: a saved 2048 is 2000.
  if (settings.view_size===2048) settings.view_size=2000;
  // Only declared keys survive, so a setting an older build saved is dropped.
  const result=Object.fromEntries(SETTINGS.map(setting=>[setting.key,validSetting(setting,settings[setting.key])]));
  const decisions={...DEFAULT_DECISIONS,...(settings.decisions ?? {})};
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(decisions.endpoint) || typeof decisions.model!=='string' || !decisions.model || decisions.model.length>200)
    throw new Error('Choose a decision endpoint and model.');
  return {...result,decisions:{endpoint:decisions.endpoint,model:decisions.model}};
}
// Auto spends reasoning where calls are few and judgement decides the outcome: the plan and the visual review
// (a handful of calls a chat) think at medium. Painting turns (dozens to hundreds) think at low: on the same
// build, Rothko and Mondrian painted in half the time at low as at medium, with every review check met.
export const AUTO_REASONING = Object.freeze({ ask:'low', plan:'medium', agent:'low', review:'medium', preparation:'low' });
export const AUTO_REASONING_NOTE = 'Auto thinks at medium for the plan and the visual review, and at low while painting.';
/** The level for a session in this phase (ask, plan, agent, review or preparation): the artist's choice, or Auto's. */
export function thinkingLevel(settings,model,phase='agent') {
  if (!model.reasoning) return 'off';
  return settings?.reasoning==='auto' || !settings?.reasoning ? AUTO_REASONING[phase] ?? 'low' : settings.reasoning;
}
