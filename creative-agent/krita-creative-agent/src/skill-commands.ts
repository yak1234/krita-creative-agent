// The artist's short slash commands, beside Pi's /skill:name: one table, read by the studio (expandSkillCommand in
// skills.mjs) and sent to the panel for its "/" menu (the skills event), so the panel
// never names a skill itself.
// Ruling: /refine is repaint-area. Its first rule is "refine or replace": refining keeps the forms already painted and
// adds light, edges and detail on clipped layers, never a fill over them. fix-region repairs damage (a seam, a wrong
// building); reference-transfer is already /colour. /trace (guides traced from the reference) was removed by
// crisp-accents: traced lines never helped a painting, and accents (paint_accents) make it crisp.

export type SkillCommand = {
  name: string;
  aliases: readonly string[];
  /** The skill it expands to; none for a command the studio answers without the painter. */
  skill?: string;
  description: string;
  /** The Agent move the command starts: guides draws guides only (studio.mjs). */
  move_kind?: 'guides';
  /** Listed only while this is available: guides needs our Krita and the Guides setting. */
  needs?: 'guides';
  /** The studio answers the command itself, never the painter: canvas_reference makes a reference picture of an edit
   * (canvas-reference.ts); its skill is what the painter reads when it paints toward it. original_goal puts back the goal
   * picture a canvas reference changed (goal-edit.ts). */
  action?: 'canvas_reference' | 'original_goal';
};

export const SKILL_COMMANDS: readonly SkillCommand[] = Object.freeze([
  { name: 'colour', aliases: ['color', 'from-reference'], skill: 'reference-transfer',
    description: 'Lay the reference\'s colours on the canvas first, then refine them.' },
  { name: 'refine', aliases: [], skill: 'repaint-area',
    description: 'Refine painted work: keep its forms, add light, edges and detail.' },
  // The artist, 2026-10-25: "not make the edits but make a reference generation of what the edit would look like".
  // Renamed from /canvas-reference (the artist, 2026-10-25: "it's not an edit of the goal"); the old name still works.
  { name: 'canvas-edit-ref', aliases: ['preview', 'canvas-reference'], skill: 'canvas-reference', action: 'canvas_reference',
    description: 'Preview an edit of the canvas as it is now: an image model shows it changed; nothing is painted until you use it.' },
  { name: 'original-goal', aliases: [], action: 'original_goal',
    description: 'Go back to the original goal picture after a canvas edit reference was used as the new goal.' },
]);

/** The short command that starts the artist's message, and the text after it; null for anything else. Any case, and
 * punctuation after the command word ("/Colour:", "/refine.") is allowed. */
export function skillCommand(text: string | undefined): (SkillCommand & { rest: string }) | null {
  const match = /^\/([a-z-]+)[.,:;!?]*(?:\s+([\s\S]*))?$/i.exec(text?.trim() ?? '');
  if (!match) return null;
  const word = (match[1] ?? '').toLowerCase();
  const command = SKILL_COMMANDS.find(c => c.name === word || c.aliases.includes(word));
  return command ? { ...command, rest: match[2]?.trim() ?? '' } : null;
}

export type MenuEntry = { command: string; aliases: string[]; description: string };

/** The panel's "/" menu: the short commands available now, then /skill:<name> for every bundled skill. */
export function slashMenu(skills: readonly { name: string; description: string }[], { guides = true }: { guides?: boolean } = {}): MenuEntry[] {
  return [
    ...SKILL_COMMANDS.filter(c => c.needs !== 'guides' || guides).map(c => ({ command: '/' + c.name, aliases: c.aliases.map(a => '/' + a), description: c.description })),
    ...skills.map(s => ({ command: '/skill:' + s.name, aliases: [], description: s.description })),
  ];
}
