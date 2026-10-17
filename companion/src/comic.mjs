// @ts-check
// Comic pages: a setting that works with every mode, not a mode. The artist picks a layout in the
// panel; the host builds the page (comic_page) when painting starts; the painter scopes work to
// panels and letters with `letter`; plans carry a story with one beat per panel.
import { Type } from 'typebox';

const object = fields => Type.Object(fields, { additionalProperties: false });
const line = Type.String({ minLength: 1, maxLength: 2000 });
export const panelId = Type.String({ pattern: '^P[0-9]{1,2}$' });

// The story a comic plan carries: a logline and one beat per panel.
export const storySchema = object({
  logline: line,
  panels: Type.Array(object({ panel: panelId, beat: line, shot: line,
    characters: Type.Array(line, { maxItems: 12 }),
    caption: Type.Optional(Type.String({ maxLength: 400 })),
    dialogue: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 400 }), { maxItems: 6 })) }), { minItems: 1, maxItems: 24 }),
});

/** Problems with a comic plan against the page's panels, as one message; null when it fits. */
export function comicPlanProblems(brief, panels) {
  const ids = (panels ?? []).map(panel => panel.id);
  if (!brief.story) return 'With Comic on, the plan needs a story: a logline and one beat per panel ('+ids.join(', ')+'). Ask the artist for missing plot details, with a You decide option.';
  const problems = [];
  const told = brief.story.panels.map(entry => entry.panel);
  const missing = ids.filter(id => !told.includes(id));
  const unknown = told.filter(id => !ids.includes(id));
  const repeated = told.filter((id, index) => told.indexOf(id) !== index);
  if (missing.length) problems.push(missing.join(', ')+(missing.length > 1 ? ' have' : ' has')+' no beat');
  if (unknown.length) problems.push('the page has no '+[...new Set(unknown)].join(', ')+' (it has '+ids.join(', ')+')');
  if (repeated.length) problems.push([...new Set(repeated)].join(', ')+' told more than once');
  const stepped = new Set(brief.steps.flatMap(step => step.panels ?? []));
  const unpainted = ids.filter(id => !stepped.has(id));
  if (unpainted.length) problems.push('no step paints '+unpainted.join(', ')+' (name panels on each step)');
  const strayStep = brief.steps.flatMap(step => step.panels ?? []).filter(id => !ids.includes(id));
  if (strayStep.length) problems.push('steps name unknown panels '+[...new Set(strayStep)].join(', '));
  return problems.length ? 'The comic plan does not fit the page: '+problems.join('; ')+'.' : null;
}

/** The comic model the painter, plan and review see. */
export function comicContext(comic) {
  if (!comic) return null;
  return { built: !!comic.built, reading: comic.layout?.reading ?? 'ltr',
    panels: (comic.panels ?? []).map(({ id, bounds, order }) => ({ id, bounds, order })) };
}

const CRAFT = 'Comic craft: vary the shots (wide to set the scene, medium for action, close-up for emotion); keep the reading order (left to right, top to bottom; right to left for manga) and lead the eye to the next panel; keep the 180-degree rule between panels of one scene; keep each character the same in every panel (their character record); captions at a panel’s top-left, balloons above the speaker and in reading order; leave room for lettering when composing a panel.';

export const COMIC_GUIDANCE = {
  ask: 'COMIC PAGE ON. When teaching, cover comic craft too, panel by panel, with the Krita way to do each: '+CRAFT,
  plan: 'COMIC PAGE ON. The plan is a story for the panels listed in comic.panels. Include story: a logline and, for every panel, its beat (what happens), shot (wide, medium, close-up, extreme close-up, over-the-shoulder…), characters, and the caption or dialogue to letter. Steps paint panels in reading order and name them in panels (several panels may share a step); the last step letters the page. Keep the artist’s plot; ask about missing plot details with a You decide option rather than inventing a different story. '+CRAFT,
  agent: 'COMIC PAGE ON. The page is laid out: comic.panels lists each panel’s id and bounds [x,y,w,h] in page pixels. Give panel on paint_pass, paint_recipe, create_layer, fill_region and apply_filter so the work goes inside that panel and is clipped to it; stay inside its bounds. Paint panel by panel. Letter last with letter (one call per caption or balloon), from the story’s captions and dialogue. Never paint on the borders or lettering layers. '+CRAFT,
};

export const COMIC_REVIEW = 'This is a comic page. Check each panel against its story beat, shot and characters; that characters look the same in every panel; that the reading order and lettering are clear and the lettering is legible and does not cover faces; and that the page reads as one story.';
