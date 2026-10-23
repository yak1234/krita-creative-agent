import test from 'node:test';
import assert from 'node:assert/strict';
import { mayBeDone, askWhenDoneNote, DONE_CONFIDENCE } from '../src/ask-when-done.ts';

// Two traced New Moscow chats: after the underpainting the next-layer decision fell from 0.97 to 0.12-0.22, spread over
// texture, accents and done (done 0.23-0.27), and the painter invented strokes on one head for 18 minutes.
test('the next-layer decision may say the area is done: done in its top two, or confidence under 0.3', () => {
  assert.equal(DONE_CONFIDENCE, 0.3);
  assert.equal(mayBeDone({ need: 'done', confidence: 0.9 }), 'done', 'done chosen');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.35, probabilities: { texture: 0.35, done: 0.27, accents: 0.2, light: 0.18 } }), 'done', 'done second');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.22, probabilities: { texture: 0.22, accents: 0.21, light: 0.2, done: 0.19 } }), 'unsure', 'spread thin');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.2 }), 'unsure', 'no probabilities: confidence alone');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.8, probabilities: { texture: 0.8, accents: 0.15, done: 0.05 } }), null, 'a clear next layer');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.8, probabilities: { texture: 0.8, done: 0.1, accents: 0.1 } }), null, 'a tie for second counts against done');
  assert.equal(mayBeDone({ need: 'flat', confidence: 0.97, probabilities: { flat: 0.97, done: 0.008, shadow: 0.007, light: 0.005, texture: 0.005, glow: 0.002, depth: 0.002, accents: 0.001 } }), null,
    'a confident decision with a trace of done second is not "done in the top two" (done must reach 0.15)');
  assert.equal(mayBeDone({ need: 'texture', confidence: 0.5, probabilities: { texture: 0.5, done: 0.15, accents: 0.1 } }), 'done', 'done at 0.15, second');
  assert.equal(mayBeDone({ need: 'flat', confidence: null }), null, 'no confidence reported');
  assert.equal(mayBeDone({ fallback: 'timeout' }), null, 'no decision, no nudge');
  assert.equal(mayBeDone(null), null);
});

test('the note ends the move and asks the artist, offering the elements still lacking detail', () => {
  const note = askWhenDoneNote('done', 'the woman’s head', ['Woman', 'Kremlin towers', 'Snow']);
  assert.match(note, /the woman’s head/);
  assert.match(note, /finish_move/);
  assert.match(note, /ask the artist what to work on next/i);
  assert.match(note, /Woman, Kremlin towers, Snow/);
  assert.match(note, /do not invent/i);
  assert.match(askWhenDoneNote('unsure', 'sky', []), /elements you see still lacking detail/, 'without a list the painter names them');
  assert.match(askWhenDoneNote('unsure', 'sky', []), /unsure/);
});
