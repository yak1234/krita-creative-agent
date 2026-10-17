// @ts-check
// Chat modes. Ask and Plan never paint. Agent (collaborative: one move per turn, then
// Keep / Undo / Refine) and Autopilot (self-driving until the review passes) both paint.
export const MODES = ['ask', 'plan', 'agent', 'autopilot'];
export const PAINTING_MODES = ['agent', 'autopilot'];
export const isPaintingMode = mode => PAINTING_MODES.includes(mode);
