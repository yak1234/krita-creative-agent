// Every execution setting, declared once: the companion validates and defaults from here, and the panel
// builds its controls from the `generic` ones (sent as a settings_schema event). Adding a setting is one
// entry here, with no panel change. panel: generic (a combo box built from options), custom (the panel
// has its own control: reasoning levels depend on the model) or hidden (fixed, not shown).
export const SETTINGS = Object.freeze([
  { key: 'reasoning', type: 'choice', default: 'auto', panel: 'custom', error: 'Unknown reasoning level.',
    options: [['auto', 'Auto'], ['off', 'Off'], ['minimal', 'Minimal'], ['low', 'Low'], ['medium', 'Medium'], ['high', 'High'], ['xhigh', 'Extra high'], ['max', 'Maximum']] },
  { key: 'concurrency', type: 'choice', default: 1, panel: 'generic', label: 'Preparation', accessible: 'Agent concurrency',
    error: 'Choose one painter or two parallel preparation workers.',
    options: [[1, 'Single painter'], [2, 'Parallel preparation · 2 workers']],
    note: 'Parallel workers suggest batches from the same canvas. One painter applies them. This uses extra model requests; speed depends on the step.' },
  { key: 'move_size', type: 'choice', default: 'subject', panel: 'generic', label: 'Agent move size', accessible: 'Agent move size',
    error: 'Choose a move size: quick, subject or large.',
    options: [['subject', 'Subject: finish one subject'], ['quick', 'Quick: one painting call'], ['large', 'Large: up to 20 calls']],
    tooltip: 'How much one Agent move paints before you keep, undo or correct it. Subject works one subject (a building, the sky) through to finished.' },
  { key: 'merge_kept', type: 'boolean', default: true, panel: 'generic', label: 'Layers after accepting', accessible: 'Layers after accepting',
    error: 'merge_kept must be true or false.', options: [[true, 'Merge kept passes'], [false, 'Keep every pass']],
    tooltip: 'When you keep an Agent move or a review passes, adjacent stroke layers merge into one. Fills, clipped and blended layers stay separate.' },
  { key: 'assets', type: 'choice', default: 'codex', panel: 'generic', label: 'Image assets', accessible: 'Image assets',
    error: 'Choose image assets from codex or openrouter.', options: [['codex', 'ChatGPT (Codex sign-in)'], ['openrouter', 'OpenRouter image models']],
    tooltip: 'Where the painter makes image assets (a tree, a sky) that it then repaints with brush strokes. ChatGPT uses your Codex sign-in and is included in your ChatGPT plan; OpenRouter costs about 1-2 cents an image.' },
  { key: 'routing', type: 'choice', default: 'off', panel: 'generic', label: 'Decision checks', accessible: 'Decision checks',
    error: 'Unknown decisions mode.', options: [['off', 'Off'], ['evaluate', 'Evaluate only'], ['guide', 'Guide agent']],
    note: 'Fast typed decisions: request routing, artifacts a pass introduced, progress between reviews and run pacing. When on, the canvas, pass images and your direction go to the decision endpoint below. Evaluate only records results; Guide agent also acts on them. The painter still decides and edits the image.' },
  // Strokes only is no longer offered; scripts can still pass false for comparisons.
  { key: 'native_craft', type: 'boolean', default: true, panel: 'hidden', error: 'native_craft must be true or false.' },
]);

export const SETTING_DEFAULTS = Object.freeze(Object.fromEntries(SETTINGS.map(s => [s.key, s.default])));

/** The value, or throws the setting's own message when it is not allowed. */
export function validSetting(setting, value) {
  const ok = setting.type === 'boolean' ? typeof value === 'boolean' : setting.options.some(([v]) => v === value);
  if (!ok) throw new Error(setting.error);
  return value;
}

/** What the panel needs to build the generic controls, in display order. */
export function panelSchema() {
  return SETTINGS.filter(s => s.panel === 'generic').map(({ key, label, accessible, options, tooltip, note }) =>
    ({ key, label, accessible, tooltip: tooltip ?? '', note: note ?? '', options: options.map(([value, text]) => ({ value, label: text })) }));
}
