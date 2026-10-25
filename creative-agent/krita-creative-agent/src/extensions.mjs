// @ts-check
// Pi extensions shipped with the companion (krita-creative-agent/extensions/*.ts). Pi's extension discovery stays
// off (noExtensions), so the user's own Pi extensions never run in the painting loop. Ours register inline
// (extensionFactories): esbuild compiles them into the release bundle and Node runs the .ts in a checkout, so
// nothing is compiled or resolved at runtime (Pi's path loader cannot resolve its own modules inside the bundle).
import loopGuards from '../extensions/loop-guards.ts';
import lunaReview from '../extensions/luna-review.ts';
import materialStamp from '../extensions/material-stamp.ts';
import saveTiming from '../extensions/save-timing.ts';
import seamCheck from '../extensions/seam-check.ts';
import goalLikeness from '../extensions/goal-likeness.ts';
import paintingWeight from '../extensions/painting-weight.ts';
import architectureTexture from '../extensions/architecture-texture.ts';

export const LOOP_GUARDS = { name: 'loop-guards', factory: loopGuards };
// What makes the painting heavy for Krita, told to the painter from the observations' `weight` (painting_weight.py).
export const PAINTING_WEIGHT = { name: 'painting-weight', factory: paintingWeight() };
// Luna's per-batch review of Agent moves, bound to the studio's ReviewHost (studio.mjs reviewHost).
/** @param {import('../extensions/luna-review.ts').ReviewHost} host */
export const lunaReviewExtension = host => ({ name: 'luna-review', factory: lunaReview(host) });
// The goal-likeness check of each Agent batch, bound to the studio's LikenessHost (studio.mjs likenessHost). Runs before Luna review.
/** @param {import('../extensions/goal-likeness.ts').LikenessHost} host */
export const goalLikenessExtension = host => ({ name: 'goal-likeness', factory: goalLikeness(host) });
// make_material and stamp_material, bound to the studio's MaterialHost (studio.mjs materialHost).
/** @param {import('../extensions/material-stamp.ts').MaterialHost} host */
export const materialStampExtension = host => ({ name: 'material-stamp', factory: materialStamp(host), tools: ['make_material', 'stamp_material'] });
// The architecture texture of a "Refine: <parts>" step, bound to the studio's TextureHost (studio.mjs textureHost).
/** @param {import('../extensions/architecture-texture.ts').TextureHost} host */
export const architectureTextureExtension = host => ({ name: 'architecture-texture', factory: architectureTexture(host), tools: ['texture_architecture'] });
// Saves the painting during the model's turn instead of during painting calls (studio.mjs saveHost).
/** @param {import('../extensions/save-timing.ts').SaveHost} host */
export const saveTimingExtension = host => ({ name: 'save-timing', factory: saveTiming(host) });
// Luna confirms the seams baked into the painting on the chat's first look (studio.mjs seamHost).
/** @param {import('../extensions/seam-check.ts').SeamHost} host */
export const seamCheckExtension = host => ({ name: 'seam-check', factory: seamCheck(host) });
// The channel on Pi's event bus that carries the settings the loop guards follow.
export const GUARDS_CHANNEL = 'krita:guards';
