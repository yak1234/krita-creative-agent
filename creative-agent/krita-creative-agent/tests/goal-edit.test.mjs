// Use as the new goal (goal-edit.ts): the canvas reference's change pasted into the goal picture through the goal's
// placement, softened at its edge, and the goal swapped (and back) as Sharpen swaps it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { blendIntoGoal, adoptEditedGoal, originalGoal, goalView } from '../src/goal-edit.ts';

const RED = [255, 0, 0, 255], BLUE = [0, 0, 255, 255];
const flat = (width, height, colour) => { const data = new Uint8Array(width * height * 4); for (let i = 0; i < width * height; i++) data.set(colour, i * 4); return { width, height, data }; };
const pixel = (img, x, y) => [...img.data.subarray((y * img.width + x) * 4, (y * img.width + x) * 4 + 4)];
const area = (bounds, value = 255) => ({ bounds, plane: { width: bounds[2], height: bounds[3], data: new Uint8Array(bounds[2] * bounds[3]).fill(value) } });

test('only the goal pixels that land inside the area take the reference; the rest of the goal is untouched', () => {
  // A goal 8 x 8 over a canvas 4 x 4: each canvas pixel is 2 x 2 goal pixels.
  const goal = flat(8, 8, RED), out = blendIntoGoal(goal, flat(4, 4, BLUE), area([2, 2, 1, 1]), [4, 4], { source: [0, 0, 8, 8], target: [0, 0, 4, 4] }, 0);
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++)
    assert.deepEqual(pixel(out, x, y), x >= 4 && x < 6 && y >= 4 && y < 6 ? BLUE : RED, `${x},${y}`);
  assert.deepEqual(pixel(goal, 4, 4), RED, 'the goal itself is not changed');
  assert.deepEqual([out.width, out.height], [8, 8], 'the same size: its placement stays valid');
});

test('through the placement: a goal placed on part of the canvas, an area off the goal changes nothing', () => {
  // A goal 4 x 8 placed on the canvas's right half [2, 0, 2, 4]: a goal pixel is half a canvas pixel.
  const placement = { source: [0, 0, 4, 8], target: [2, 0, 2, 4] };
  const off = blendIntoGoal(flat(4, 8, RED), flat(4, 4, BLUE), area([0, 0, 1, 4]), [4, 4], placement, 0);
  assert.ok([...Array(32).keys()].every(i => pixel(off, i % 4, Math.floor(i / 4)).join() === RED.join()), 'the left of the canvas is not on the goal');
  const on = blendIntoGoal(flat(4, 8, RED), flat(4, 4, BLUE), area([3, 0, 1, 4]), [4, 4], placement, 0);
  for (let x = 0; x < 4; x++) assert.deepEqual(pixel(on, x, 3), x >= 2 ? BLUE : RED, `column ${x}`);
});

test('the whole reference (the artist, 2026-10-25: "it went back to the original goal painting again then added fog"): every goal pixel on the canvas becomes the canvas with the change; the part cropped off the canvas keeps the goal', () => {
  // A goal 4 x 8 whose top half is placed on the whole 4 x 4 canvas: its bottom half is cropped off.
  const out = blendIntoGoal(flat(4, 8, RED), flat(4, 4, BLUE), null, [4, 4], { source: [0, 0, 4, 4], target: [0, 0, 4, 4] });
  for (let y = 0; y < 8; y++) for (let x = 0; x < 4; x++) assert.deepEqual(pixel(out, x, y), y < 4 ? BLUE : RED, `${x},${y}`);
});

test('the edge is softened so the pasted change does not show a seam', () => {
  const out = blendIntoGoal(flat(8, 8, RED), flat(8, 8, BLUE), area([3, 3, 2, 2]), [8, 8], { source: [0, 0, 8, 8], target: [0, 0, 8, 8] }, 1);
  const [r, , b] = pixel(out, 3, 3);
  assert.ok(r > 0 && r < 255 && b > 0 && b < 255, 'a mix at the edge: ' + pixel(out, 3, 3));
  assert.deepEqual(pixel(out, 0, 0), RED, 'far from the area: the goal');
});

test('the goal is swapped as Sharpen swaps it: same id and placement, the picture remembered, and back to the original', () => {
  const goal = { id: 'g1', path: '/chat/goal.png', width: 8, height: 8, mimeType: 'image/png', mass_map: { x: 1 } };
  adoptEditedGoal(goal, '/chat/goal-edits/r1.png', 'r1', '2026-10-25T18:00:00.000Z');
  assert.equal(goal.id, 'g1'); assert.equal(goal.path, '/chat/goal-edits/r1.png'); assert.equal(goal.mimeType, 'image/png');
  assert.equal(goal.mass_map, undefined, 'made again from the new picture');
  assert.deepEqual(goal.edits, [{ from: { path: '/chat/goal.png', width: 8, height: 8, mimeType: 'image/png' }, canvas_reference: 'r1', at: '2026-10-25T18:00:00.000Z' }]);
  adoptEditedGoal(goal, '/chat/goal-edits/r2.png', 'r2', '2026-10-25T18:05:00.000Z');
  assert.equal(goal.edits.length, 2);
  assert.equal(originalGoal(goal), true);
  assert.equal(goal.path, '/chat/goal.png', 'the picture the chat started from, not the edit before the last');
  assert.equal(goal.edits, undefined);
  assert.equal(originalGoal(goal), false, 'never edited: nothing to go back to');
  adoptEditedGoal(goal, '/chat/goal-edits/r3.png', 'r3', '2026-10-25T18:10:00.000Z');
  Object.assign(goal, { path: '/chat/goal-sharpen/x4.png', width: 32, height: 32 });   // sharpened since
  originalGoal(goal);
  assert.deepEqual([goal.path, goal.width, goal.height], ['/chat/goal.png', 8, 8], 'its size too');
});

test('a sharpened goal: the edit gets its own small view for the painter and Find it; the sharpening record stays for transfers', () => {
  const sharpened = { from: { path: '/chat/goal.png', width: 8, height: 8, sha256: 'a'.repeat(64) }, model: 'm', revision: 'r', scale: 4, full: '/chat/x4.png', at: 't' };
  const goal = { id: 'g1', path: '/chat/goal-sharpen/x.reference.png', width: 32, height: 32, mimeType: 'image/png', sharpened };
  assert.equal(goalView(goal), '/chat/goal.png', 'before an edit: the picture it was, as now');
  adoptEditedGoal(goal, '/chat/goal-edits/r1.png', 'r1', 't1', '/chat/goal-edits/r1.view.png');
  assert.equal(goalView(goal), '/chat/goal-edits/r1.view.png', 'the painter sees the edit');
  assert.equal(goal.sharpened, sharpened, 'transfers made before sharpening still map through it');
  assert.equal(goalView({ path: '/p.png' }), '/p.png');
  // Sharpened after the edit, then /original-goal: back to exactly what it was, sharpening record and view included.
  goal.sharpened = { ...sharpened, from: { ...sharpened.from, path: '/chat/goal-edits/r1.png' } };
  originalGoal(goal);
  assert.equal(goal.sharpened, sharpened); assert.equal(goal.view_path, undefined); assert.equal(goal.path, '/chat/goal-sharpen/x.reference.png');
  const plain = { id: 'g2', path: '/chat/p.png', width: 8, height: 8 };
  adoptEditedGoal(plain, '/chat/goal-edits/r2.png', 'r2', 't2');
  plain.sharpened = sharpened;                                  // Always sharpened the edited picture
  originalGoal(plain);
  assert.equal(plain.sharpened, undefined, 'never sharpened before the edit: not sharpened after going back');
});
