// @ts-check
// Pi extensions shipped with the companion (krita-creative-agent/extensions/*.ts). Pi's extension discovery stays
// off (noExtensions), so the user's own Pi extensions never run in the painting loop. Ours register inline
// (extensionFactories): esbuild compiles them into the release bundle and Node runs the .ts in a checkout, so
// nothing is compiled or resolved at runtime (Pi's path loader cannot resolve its own modules inside the bundle).
import loopGuards from '../extensions/loop-guards.ts';

export const LOOP_GUARDS = { name: 'loop-guards', factory: loopGuards };
// The channel on Pi's event bus that carries the settings the loop guards follow.
export const GUARDS_CHANNEL = 'krita:guards';
