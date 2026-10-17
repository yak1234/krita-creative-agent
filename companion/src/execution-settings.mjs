// @ts-check
import { SETTINGS, SETTING_DEFAULTS, validSetting } from './settings-schema.mjs';
// The decision endpoint and model default to GPT-6 Luna Decisions on OpenRouter.
export const DEFAULT_DECISIONS = Object.freeze({endpoint:'openrouter',model:'openai/gpt-6-luna-decisions'});
// Defaults and validation come from the declarations in settings-schema.mjs; decisions keeps its own.
export const DEFAULT_EXECUTION_SETTINGS = Object.freeze({ ...SETTING_DEFAULTS, decisions: DEFAULT_DECISIONS });
export function executionSettings(value={}) {
  const settings={...DEFAULT_EXECUTION_SETTINGS,...value};
  // Only declared keys survive, so a setting an older build saved is dropped.
  const result=Object.fromEntries(SETTINGS.map(setting=>[setting.key,validSetting(setting,settings[setting.key])]));
  const decisions={...DEFAULT_DECISIONS,...(settings.decisions ?? {})};
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(decisions.endpoint) || typeof decisions.model!=='string' || !decisions.model || decisions.model.length>200)
    throw new Error('Choose a decision endpoint and model.');
  return {...result,decisions:{endpoint:decisions.endpoint,model:decisions.model}};
}
export function thinkingLevel(settings,model) {
  return model.reasoning ? (settings?.reasoning==='auto' || !settings?.reasoning ? 'low':settings.reasoning):'off';
}
