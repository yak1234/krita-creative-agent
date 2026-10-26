// @ts-check
// Every execution setting, declared once: the companion validates and defaults from here, and the panel
// builds its controls from the `generic` ones (sent as a settings_schema event). Adding a setting is one
// entry here, with no panel change. panel: generic (a combo box built from options), custom (the panel
// has its own control: reasoning levels depend on the model) or hidden (fixed, not shown). A generic setting may carry
// a `button` beside its control: {label, command (sent as is), confirm (asked first; No sends nothing)}.
// The default planner (the artist, 2026-10-24: "I want planner Qwen VL" for its image reading; deepseek-flash paints). Used
// when connected; otherwise plan turns quietly run on the painter.
export const DEFAULT_PLANNER = 'openrouter/qwen/qwen3-vl-235b-a22b-instruct';
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
  // Auto-approve (auto-approve.ts; the artist 2026-10-25: "it's standard in agentic systems"): each card that waits for
  // the artist takes its default answer after this delay, unless the artist acts first. The panel counts down.
  { key: 'auto_approve', type: 'choice', default: 'off', panel: 'generic', label: 'Auto-approve', accessible: 'Auto-approve',
    error: 'Auto-approve: choose Off, Immediately, 10, 30 or 60 seconds.', options: [['off', 'Off'], [0, 'Immediately'], [10, '10 s'], [30, '30 s'], [60, '60 s']],
    tooltip: 'When a card waits for you, its default is taken after this delay, with a countdown: Met for a finished plan step, Keep for a move, Sharpen and Use sharpened for the goal image, and the recommended option of a question that has one. Undo, Redo, Stop, typing or any button stops the countdown. Start painting and anything that deletes or discards work are never pressed for you.' },
  // Guided trace (guide-tool.ts): the painter may sketch construction lines on a guide layer when the artist asks for them.
  // A combo, as merge_kept: the panel's checkbox starts unchecked until the settings arrive, which suits only a default-off setting.
  { key: 'guides', type: 'boolean', default: true, panel: 'generic', label: 'Guides', accessible: 'Draw guides from references',
    error: 'guides must be true or false.', options: [[true, 'Draw guides from references'], [false, 'No guides']],
    tooltip: 'Lets the painter draw guides (construction lines on a guide layer) when you ask for them: guides, perspective or a construction, drawn by hand (nothing is traced). They show until the element is finished, then hide.' },
  // Reference first (reference-first.ts): with a goal reference, an Agent move gets the reference-transfer skill and a nudge
  // before a flat fill, until a reference colour pass exists. A combo, as guides (default on).
  { key: 'reference_first', type: 'boolean', default: true, panel: 'generic', label: 'Reference colours', accessible: 'Start from the reference\'s colours',
    error: 'reference_first must be true or false.', options: [[true, 'Start from the reference\'s colours'], [false, 'Choose colours freely']],
    tooltip: 'Applies when a goal reference is attached: Agent mode lays the reference\'s colours first, then refines with its own strokes (guides only when you ask). Turn it off for stylised work, or for a base you paint yourself.' },
  { key: 'assets', type: 'choice', default: 'codex', panel: 'generic', label: 'Image assets', accessible: 'Image assets',
    error: 'Choose image assets from codex or openrouter.', options: [['codex', 'ChatGPT (Codex sign-in)'], ['openrouter', 'OpenRouter image models']],
    tooltip: 'Where the painter makes image assets (a tree, a sky) that it then repaints with brush strokes. ChatGPT uses your Codex sign-in and is included in your ChatGPT plan; OpenRouter costs about 1-2 cents an image.' },
  // The starting AI image allowance of a new chat; each chat keeps its own (goal.limits.ai_images), changed in the panel.
  { key: 'ai_images', type: 'choice', default: 0, panel: 'generic', label: 'AI images per chat', accessible: 'AI images per chat',
    error: 'Choose how many AI images a new chat may use: 0, 1, 3, 5 or unlimited.',
    options: [[0, 'None: paint by hand'], [1, '1 image'], [3, '3 images'], [5, '5 images'], ['unlimited', 'No limit']],
    tooltip: 'How many AI-generated images (a sky, a tree) the painter may make in a new chat before repainting them with brushes. Change it for the open chat in the panel.' },
  // Preview additions (canvas-reference.ts; the artist, 2026-10-25): before a plan's "Add: <thing>" step paints, a canvas
  // reference shows the canvas with that thing added, and the step paints toward it inside the changed area when it is used.
  { key: 'preview_additions', type: 'boolean', default: false, panel: 'generic', label: 'Preview additions', accessible: 'Preview additions with a canvas reference',
    error: 'preview_additions must be true or false.', options: [[false, 'Off'], [true, 'Preview with a canvas reference']],
    tooltip: 'Before a plan step that adds something (Add: snow, Add: ghosts) paints, an image model shows the canvas with it added: a canvas reference beside the chat. Use it as the target and the step paints toward it only where it differs; each picture is one AI image of the chat\'s allowance.' },
  // Custom effects (openspec custom-effects): the painter uses the effect library (fog, snow and the artist's own) through
  // paint_effect. Off by default: no paint_effect, and paint_snow unchanged.
  // Its button: Reset custom effects… (studio.mjs resetEffects) deletes the artist's own effects after the panel asks.
  { key: 'custom_effects', type: 'boolean', default: false, panel: 'generic', control: 'checkbox', label: 'Custom effects (experimental)', accessible: 'Custom effects',
    error: 'custom_effects must be true or false.', options: [[false, 'Off'], [true, 'Paint effects from the effect library']],
    tooltip: 'Off by default. When painting an effect fails twice, Toska builds a new effect from tested building blocks and asks you to keep it. Keep it, try again or discard it; Reset removes all your own effects.',
    button: { label: 'Reset custom effects…', command: { type: 'reset_effects' }, confirm: 'Remove all your own effects? Fog and snow stay. This cannot be undone.' } },
  // Off by default: a screen that never sleeps must be the artist's choice. The panel shows when it holds.
  { key: 'keep_screen_awake', type: 'boolean', default: false, panel: 'generic', control: 'checkbox', label: 'Screen', accessible: 'Keep the screen awake while painting',
    error: 'keep_screen_awake must be true or false.', options: [[false, 'Let the screen sleep'], [true, 'Keep the screen awake while painting']],
    tooltip: 'Krita can only paint while its window is active, so Autopilot pauses when the screen sleeps. With this on, the screen stays awake only while a run is painting, and the panel shows it.' },
  // Sharpen goal (goal-sharpen.ts): a goal image enlarged more than 2x onto the canvas is sharpened 4x on this computer
  // (Real-ESRGAN). Always by default (the artist, 2026-10-25: "the underpainting waits for sharpening to finish and it's by
  // default always"): it starts as soon as the goal is known and every move that reads the goal waits for it. Ask is the cards.
  { key: 'sharpen_goal', type: 'choice', default: 'always', panel: 'generic', label: 'Sharpen the goal', accessible: 'Sharpen the goal',
    error: 'Sharpen the goal: choose Always, Ask or Never.', options: [['always', 'Always'], ['ask', 'Ask'], ['never', 'Never']],
    tooltip: 'When the goal image is more than 2x smaller than the canvas, detail blurs. Toska sharpens it 4x on this computer with Real-ESRGAN (nothing is uploaded; a one-time 62 MB model download). Always sharpens it as soon as the goal is known and the underpainting waits for it; Ask shows a card, then the result side by side before it is used; Never paints from the goal as it is.' },
  // Sharper eyes (view-size.ts; luna-goal-reviewer goal 3, the artist 2026-10-24): the canvas view's long side. Auto is
  // what the painter's model reads, measured by the resolution probe (at most 2000 px: Pi shrinks anything larger), else the size used before.
  { key: 'view_size', type: 'choice', default: 'auto', panel: 'generic', label: 'Canvas view size', accessible: 'Canvas view size',
    error: 'Choose a canvas view size: Auto, 1024, 1568 or 2000 pixels.',
    options: [['auto', 'Auto: what the model reads'], [1024, '1024 px'], [1568, '1568 px'], [2000, '2000 px']],
    tooltip: 'How large the painter sees the canvas (the long side). Auto uses the size the painter\'s model was measured to read in full, up to 2000 px, and 1568 px for a model not measured yet. Larger views show finer detail but cost more per look.' },
  // Planner model (plan-from-request goal 4, the artist 2026-10-24: try stronger planners for planning only): a
  // provider/model route, or the painter's own. Its options are the routes the companion lists (panelSchema({models})):
  // the connected models measured by the resolution probe (model-resolutions.json), the painter's and the saved one.
  { key: 'planner_model', type: 'model', default: 'default', panel: 'generic', label: 'Planner model', accessible: 'Planner model',
    error: 'Planner model: choose Same as the painter or a connected provider/model.', options: [['default', `Default: Qwen3 VL 235B A22B Instruct (${DEFAULT_PLANNER})`], ['painter', 'Same as the painter']],
    tooltip: 'The model that makes and revises the plan (a project folder\'s plan, Plan mode). Painting always uses the painter model chosen above. A model that is not connected plans as the painter.' },
  // Folder study (folder-study.ts, approved 2026-10-24): a vision model writes a short note per project folder image, so the
  // planner and painter read the notes as text and open an image only when they need it. Off: file names only, as before.
  { key: 'study_folder', type: 'boolean', default: true, panel: 'generic', label: 'Study folder images', accessible: 'Study folder images',
    error: 'Study folder images must be On or Off.', options: [[true, 'On: a short note per image'], [false, 'Off: file names only']],
    tooltip: 'When a project folder opens, a vision model writes a short note per image (what it shows, where it sits in the goal, its colours and shapes), so the planner and painter know every image without receiving them all. A folder of more than 20 images asks first. Under $0.001 an image with qwen3-vl (13 images: about 36 s).' },
  { key: 'routing', type: 'choice', default: 'guide', panel: 'generic', label: 'Decision checks', accessible: 'Decision checks',
    error: 'Unknown decisions mode.', options: [['off', 'Off'], ['evaluate', 'Evaluate only'], ['guide', 'Guide agent']],
    note: 'Fast typed decisions: request routing, artifacts a pass introduced, progress between reviews and run pacing. When on, the canvas, pass images and your direction go to the decision endpoint below. Evaluate only records results; Guide agent also acts on them. The painter still decides and edits the image. Until the decision endpoint has a key, checks stay off.' },
  // Strokes only is no longer offered; scripts can still pass false for comparisons.
  { key: 'native_craft', type: 'boolean', default: true, panel: 'hidden', error: 'native_craft must be true or false.' },
]);

export const SETTING_DEFAULTS = Object.freeze(Object.fromEntries(SETTINGS.map(s => [s.key, s.default])));

/** The value, or throws the setting's own message when it is not allowed. */
export function validSetting(setting, value) {
  const ok = setting.type === 'boolean' ? typeof value === 'boolean'
    : setting.type === 'model' ? value === setting.default || (setting.options ?? []).some(([option]) => option === value) || (typeof value === 'string' && value.length <= 200 && /^[A-Za-z0-9][\w.-]*\/\S+$/.test(value))
    : setting.options.some(([v]) => v === value);
  if (!ok) throw new Error(setting.error);
  return value;
}

/** What the panel needs to build the generic controls, in display order. `models`: the routes a model setting offers
 * after its own options ([{route: 'provider/id', label}]), listed by the companion. */
export function panelSchema({ models = [] } = {}) {
  return SETTINGS.filter(s => s.panel === 'generic').map(({ key, type, label, accessible, options, tooltip, note, control, button }) =>
    ({ key, label, accessible, tooltip: tooltip ?? '', note: note ?? '', control: control ?? 'combo',
      options: [...options.map(([value, text]) => ({ value, label: text })), ...(type === 'model' ? models.map(m => ({ value: m.route, label: m.label })) : [])],
      ...(button ? { button } : {}) }));
}
