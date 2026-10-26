// creative_test_command (the MCP's test tools, scripts/test-driver.ts): what the panel's buttons send, for a test chat
// only, so a rehearsal (open the project folder, plan, Start painting, Find it, Paint only here, Met or Redo) runs end to
// end without the panel. Only the commands below, each checked against what the test chat shows now: its plan, its
// question, its found outlines; a mask only from inside the test chat's own folder. Everything else is refused before it
// reaches the test companion (main.mjs, which validates again). Development only.
import { randomUUID } from 'node:crypto';
import { extname, isAbsolute, resolve, sep } from 'node:path';
import { PLAN_STEP_ACTIONS, type StepView } from './plan-steps.ts';

export const TEST_COMMANDS = ['start_plan', 'plan_step', 'find_it', 'paint_only_here', 'answer', 'closeup_answer', 'folder_guess', 'folder_study', 'sharpen_answer', 'canvas_reference_answer', 'effect_build_answer', 'set_mode', 'set_limits', 'stop'] as const;
export type TestCommand = typeof TEST_COMMANDS[number];
const MODES = ['ask', 'plan', 'agent', 'autopilot'];

/** A refused command: the caller's mistake (HTTP 400), never sent. */
export class CommandRefusal extends Error {}

export type Rect = [number, number, number, number];
/** The companion's found_area event: an outline (or the error of a find). */
export type FoundEvent = { request_id?: string; part?: string | null; mask_path?: string; bounds?: number[]; canvas?: number[]; error?: string };
export type Question = { id: string; question?: string; options?: string[]; recommended?: string; select_area?: { part?: string; proposal?: { mask_path?: string; bounds?: number[]; canvas?: number[] } } };
/** The Sharpen goal card the panel shows (goal-sharpen.ts): the offer, or the side by side after sharpening. */
export type SharpenCard = { kind: 'offer' | 'review'; id: string; options: string[]; text: string; image_path?: string; progress?: string };
/** The canvas reference card (canvas-reference.ts): the canvas and the reference side by side, its buttons as actions. */
export type ReferenceCard = { id: string; options: string[]; actions: string[]; text: string; image_path?: string };
export type CommandView = { testFolder: string; mode?: string | null; planSteps: StepView[]; question: Question | null;
  closeupQuestion: Question | null; foundAreas: FoundEvent[]; folderElements: string[]; folderImages?: string[]; sharpen?: SharpenCard | null;
  canvasReference?: ReferenceCard | null; effectBuild?: ReferenceCard | null };
/** The panel's buttons on the Sharpen goal card: Sharpen / Use as is on the offer, Use sharpened / Keep original after. */
const SHARPEN_ACTIONS = { offer: ['sharpen', 'original'], review: ['use', 'keep'] } as const;
export type AreaCommand = { action: 'clear' } | { action: 'set'; mask_path: string; bounds: Rect; canvas: [number, number]; name: string | null };
/** What to do: the area first (sent, adopted, then protected on the test copy), then the command. */
export type Planned = { area?: AreaCommand; command?: Record<string, unknown> };

const refuse = (message: string): never => { throw new CommandRefusal(message); };
const id = () => randomUUID().replace(/-/g, '');

function fields(params: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (params === undefined || params === null) return {};
  if (typeof params !== 'object' || Array.isArray(params)) return refuse('params is an object.');
  for (const key of Object.keys(params)) if (!allowed.includes(key)) refuse(`unknown parameter ${key.slice(0, 40)}${allowed.length ? ' (allowed: ' + allowed.join(', ') + ')' : ''}.`);
  return params as Record<string, unknown>;
}
function text(value: unknown, name: string, limit: number, optional = false): string | undefined {
  if (value === undefined && optional) return undefined;
  if (typeof value !== 'string' || !value.trim()) return refuse(`${name} is required text.`);
  return value.trim().slice(0, limit);
}
function integers(value: unknown, count: number, name: string): number[] {
  if (!Array.isArray(value) || value.length !== count || !value.every(n => Number.isInteger(n) && n >= 0)) refuse(`${name} is ${count} whole numbers.`);
  return value as number[];
}
/** A mask the companion may read: a PNG inside the test chat's own folder. */
function mask(path: unknown, view: CommandView): string {
  const root = resolve(view.testFolder);
  if (typeof path !== 'string' || !isAbsolute(path) || extname(path).toLowerCase() !== '.png' || !resolve(path).startsWith(root + sep))
    return refuse('mask_path must be a PNG inside the test chat’s folder (a found outline, or a mask written there).');
  return resolve(path);
}
function areaOf(source: { mask_path?: unknown; bounds?: unknown; canvas?: unknown }, name: unknown, view: CommandView): AreaCommand {
  const bounds = integers(source.bounds, 4, 'bounds'), canvas = integers(source.canvas, 2, 'canvas');
  return { action: 'set', mask_path: mask(source.mask_path, view), bounds: bounds as Rect, canvas: canvas as [number, number],
    name: typeof name === 'string' && name.trim() ? name.trim().slice(0, 60) : null };
}
function foundArea(view: CommandView, requestId?: unknown): FoundEvent {
  const outlines = view.foundAreas.filter(f => !f.error && f.mask_path);
  const chosen = requestId === undefined ? outlines.at(-1) : outlines.find(f => f.request_id === requestId);
  if (!chosen) return refuse(requestId === undefined ? 'No outline found yet: send find_it first (Find it for me).' : `There is no found area ${String(requestId).slice(0, 40)}.`);
  return chosen;
}
function pendingQuestion(asked: Question | null, given: unknown, kind: string): Question {
  if (!asked) return refuse(`The test chat shows no ${kind} now.`);
  if (given !== undefined && given !== asked.id) refuse(`The ${kind} shown now is ${asked.id}.`);
  return asked;
}
const message = (view: CommandView, extra: Record<string, unknown>) =>
  ({ type: 'prompt', chat_mode: view.mode ?? 'agent', references: [], message_id: id(), ...extra });

/** The command `type` with `params`, checked against `view`, as the panel would send it; refused otherwise. */
export function panelCommand(type: unknown, params: unknown, view: CommandView): Planned {
  if (typeof type !== 'string' || !(TEST_COMMANDS as readonly string[]).includes(type))
    return refuse(`${String(type).slice(0, 40) || 'That'} is not a test command. Allowed: ${TEST_COMMANDS.join(', ')}.`);
  switch (type as TestCommand) {
    case 'stop': fields(params, []); return { command: { type: 'stop' } };
    case 'set_mode': {
      const { mode } = fields(params, ['mode']);
      if (typeof mode !== 'string' || !MODES.includes(mode)) refuse(`mode is one of ${MODES.join(', ')}.`);
      return { command: { type: 'set_mode', mode } };
    }
    case 'set_limits': {                             // the panel's allowance for this chat: AI images 0-20, or null for no limit
      const { ai_images } = fields(params, ['ai_images']);
      if (!(ai_images === null || (Number.isInteger(ai_images) && (ai_images as number) >= 0 && (ai_images as number) <= 20))) refuse('ai_images is 0-20, or null for no limit.');
      return { command: { type: 'set_limits', limits: { minutes: 0, passes: 0, ai_images } } };
    }
    case 'start_plan':                               // the Plan tab's and the Now card's Start painting
      fields(params, []);
      if (!view.planSteps.length) refuse('The test chat has no plan yet: ask for one first (a message in Agent mode with the folder open).');
      return { command: message({ ...view, mode: 'agent' }, { text: 'Start painting from this plan.', start_plan: true }) };
    case 'plan_step': {
      const { action, step_key, text: words } = fields(params, ['action', 'step_key', 'text']);
      if (typeof action !== 'string' || !(PLAN_STEP_ACTIONS as readonly string[]).includes(action)) refuse(`action is one of ${PLAN_STEP_ACTIONS.join(', ')}.`);
      if (!view.planSteps.some(step => step.key === step_key))
        refuse(`${String(step_key).slice(0, 60)} is not a step of the plan. Steps: ${view.planSteps.map(s => s.key).join(', ') || 'none'}.`);
      if (words !== undefined && action !== 'redo') refuse('text is only for Redo.');
      const note = text(words, 'text', 1000, true);
      return { command: { type: 'plan_step', id: id(), action, step_key, ...(note ? { text: note } : {}) } };
    }
    case 'find_it': {                                // Find it for me, by name (the found_area comes back in the state)
      const { part } = fields(params, ['part']);
      return { command: { type: 'find_it', request_id: id(), part: text(part, 'part', 60) } };
    }
    case 'paint_only_here': {
      const input = fields(params, ['action', 'found', 'mask_path', 'bounds', 'canvas', 'name']);
      if (input.action === 'clear') { fields(params, ['action']); return { area: { action: 'clear' } }; }
      if (input.action !== 'set') refuse('action is set or clear.');
      if (input.mask_path !== undefined) {
        if (input.found !== undefined) refuse('Give found or mask_path, not both.');
        return { area: areaOf(input, input.name, view) };
      }
      const outline = foundArea(view, input.found);
      return { area: areaOf(outline, input.name ?? outline.part, view) };
    }
    case 'answer': {                                 // a question card's button, or a typed answer
      const input = fields(params, ['text', 'question_id', 'area', 'found']);
      const asked = pendingQuestion(view.question, input.question_id, 'question');
      const words = text(input.text, 'text', 2000) as string;
      let area: AreaCommand | undefined;
      if (input.area === 'proposal') {               // Use this: the companion's outline on the card
        const proposal = asked.select_area?.proposal;
        if (!proposal) refuse('The question has no proposed outline: answer with area "found" after find_it, or without an area.');
        area = areaOf(proposal as object, asked.select_area?.part, view);
      } else if (input.area === 'found') {           // Use my selection: a found outline stands in for the artist's selection
        const outline = foundArea(view, input.found);
        area = areaOf(outline, asked.select_area?.part ?? outline.part, view);
      } else if (input.area !== undefined) refuse('area is "proposal" or "found".');
      return { ...(area ? { area } : {}), command: message(view, { text: words }) };
    }
    case 'closeup_answer': {
      const input = fields(params, ['answer', 'question_id']);
      const asked = pendingQuestion(view.closeupQuestion, input.question_id, 'close-up question');
      const options = asked.options ?? [];
      if (typeof input.answer !== 'string' || (options.length && !options.includes(input.answer))) refuse(`answer is one of ${options.join(', ') || 'the options'}.`);
      return { command: { type: 'closeup_answer', question_id: asked.id, answer: input.answer } };
    }
    case 'sharpen_answer': {                        // the Sharpen goal card's buttons, or Stop while it sharpens
      const { action } = fields(params, ['action']);
      const card = view.sharpen;
      if (!card) return refuse('The test chat shows no Sharpen goal card now.');
      const allowed: readonly string[] = [...SHARPEN_ACTIONS[card.kind], 'cancel'];
      if (typeof action !== 'string' || !allowed.includes(action)) refuse(`action is ${SHARPEN_ACTIONS[card.kind].join(' or ')} (or cancel while it sharpens).`);
      return { command: { type: 'goal_sharpen', id: card.id, action } };
    }
    case 'canvas_reference_answer': {               // the canvas reference card's buttons: Use as the target, Try again, Discard
      const { action } = fields(params, ['action']);
      const card = view.canvasReference;
      if (!card) return refuse('The test chat shows no canvas reference card now.');
      if (typeof action !== 'string' || !card.actions.includes(action)) refuse(`action is ${card.actions.join(' or ')}.`);
      return { command: { type: 'canvas_reference', id: card.id, action } };
    }
    case 'effect_build_answer': {                   // the custom effect card's buttons (effects/build.ts): Keep, Try again, Discard; Remove effect after Keep
      const { action } = fields(params, ['action']);
      const card = view.effectBuild;
      if (!card) return refuse('The test chat shows no custom effect card now.');
      if (typeof action !== 'string' || !card.actions.includes(action)) refuse(`action is ${card.actions.join(' or ')}.`);
      return { command: { type: 'effect_build', id: card.id, action } };
    }
    case 'folder_guess': {                           // the folder card: the artist names an element
      const input = fields(params, ['name', 'guess']);
      if (typeof input.name !== 'string' || !view.folderElements.includes(input.name)) refuse(`name is an element of the project folder: ${view.folderElements.join(', ') || 'none'}.`);
      return { command: { type: 'folder_guess', name: input.name, guess: text(input.guess, 'guess', 80) } };
    }
    case 'folder_study': {                           // the Folder tab's study menu (Study, Exclude, Include), choice card and Stop
      const input = fields(params, ['action', 'name', 'choice', 'picked']);
      const images = view.folderImages ?? view.folderElements;      // the goal too (it can be studied; the companion refuses excluding it)
      const element = (name: unknown) => typeof name === 'string' && images.includes(name) ? name
        : refuse(`name is an image (element) of the project folder: ${images.join(', ') || 'none'}.`);
      if (input.action === 'stop') return { command: { type: 'folder_study', action: 'stop' } };
      if (input.action === 'choose') {
        if (!['plan', 'all', 'pick', 'none'].includes(input.choice as string)) refuse('choice is plan, all, pick or none.');
        if (input.choice !== 'pick') return { command: { type: 'folder_study', action: 'choose', choice: input.choice } };
        if (!Array.isArray(input.picked) || input.picked.length > 400) refuse('picked is a list of the folder\'s element names.');
        return { command: { type: 'folder_study', action: 'choose', choice: 'pick', picked: (input.picked as unknown[]).map(element) } };
      }
      if (['study', 'exclude', 'include'].includes(input.action as string)) return { command: { type: 'folder_study', action: input.action, name: element(input.name) } };
      return refuse('action is choose, study, exclude, include or stop.');
    }
  }
}
