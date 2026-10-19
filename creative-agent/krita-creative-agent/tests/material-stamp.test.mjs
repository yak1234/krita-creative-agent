// Material stamp: the shipped Pi extension that registers make_material and stamp_material and plans the dabs.
// A fake `pi` (registerTool) and a fake host (the studio's port); writes no files.
import test from 'node:test';
import assert from 'node:assert/strict';
import materialStamp, { planDabs, MAX_DABS } from '../extensions/material-stamp.ts';

const sheet = { type: 'image', data: 'c2hlZXQ=', mimeType: 'image/png' };

function setup() {
  const tools = {};
  const calls = [];
  const host = {
    native: async (operation, params, id) => {
      calls.push({ operation, params, id });
      const details = operation === 'make_material'
        ? { status: 'ok', material: params.name, kind: params.kind ?? 'light', tips: 6, size: 200, sheet_path: '/s/.materials/x/sheet.png' }
        : { status: 'ok', layer_id: 'L1', dabs_placed: params.dabs.length, image_path: '/s/view.png' };
      return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
    },
    reference: async id => { if (id !== 'ref-1') throw new Error('Use an attached reference ID.'); return 'cmVm'; },
    image: async path => ({ ...sheet, path }),
    canvas: () => ({ width: 6000, height: 4500 }),
  };
  materialStamp(host)({ registerTool: tool => { tools[tool.name] = tool; }, on: () => {} });
  return { tools, calls };
}

test('planned dabs stay inside their box and ranges, and the same seed plans the same dabs', () => {
  const plan = { within: [100, 50, 2000, 800], count: 300, size: [100, 400], opacity: [0.2, 0.5], rotate: 20, stretch: 1.3, tips: 6, tip_size: 200, seed: 7 };
  const dabs = planDabs(plan);
  assert.equal(dabs.length, 300);
  for (const d of dabs) {
    assert.ok(d.x >= 100 && d.x < 2100 && d.y >= 50 && d.y < 850, JSON.stringify(d));
    assert.ok(d.scale >= 0.5 - 1e-9 && d.scale <= 2 + 1e-9, 'size 100-400 px over 200 px tips');
    assert.ok(d.opacity >= 0.2 && d.opacity <= 0.5 && Math.abs(d.rotation) <= 20 && d.stretch === 1.3);
    assert.ok(Number.isInteger(d.tip) && d.tip >= 0 && d.tip < 6);
  }
  assert.deepEqual(planDabs(plan), dabs);
  assert.notDeepEqual(planDabs({ ...plan, seed: 8 }), dabs);
  assert.equal(MAX_DABS, 2000);
});

test('make_material forwards to Krita, reads a reference for an image source, and shows the tips sheet', async () => {
  const { tools, calls } = setup();
  assert.deepEqual(Object.keys(tools).sort(), ['make_material', 'stamp_material']);
  const result = await tools.make_material.execute('m1', { name: 'Clouds', source: { reference_id: 'ref-1' }, kind: 'light' });
  assert.deepEqual(calls[0], { operation: 'make_material', params: { name: 'Clouds', source: { image_base64: 'cmVm' }, kind: 'light' }, id: 'm1' });
  assert.equal(result.content.at(-1).type, 'image', 'the painter sees what it made');
  await assert.rejects(tools.make_material.execute('m2', { name: 'X', source: { reference_id: 'nope' } }), /attached reference/);
});

test('stamp_material plans dabs over the canvas by default and sends them with the area', async () => {
  const { tools, calls } = setup();
  await tools.make_material.execute('m1', { name: 'Clouds', source: { area: [{ shape: 'rectangle', bounds: [0, 0, 6000, 1400] }] } });
  const area = [{ saved: 'Sky' }];
  const result = await tools.stamp_material.execute('s1', { name: 'Cloud volume', material: 'Clouds', area, count: 500, size: [150, 450],
    tint: { color: '#cdd7eb', amount: 0.4, toward: 'top' } });
  const sent = calls.at(-1);
  assert.equal(sent.operation, 'stamp');
  assert.deepEqual({ ...sent.params, dabs: undefined }, { name: 'Cloud volume', material: 'Clouds', area, dabs: undefined,
    tint: { color: '#cdd7eb', amount: 0.4, toward: 'top' } });
  assert.equal(sent.params.dabs.length, 500);
  assert.ok(sent.params.dabs.every(d => d.x < 6000 && d.y < 4500 && d.scale >= 0.75 && d.scale <= 2.25));
  assert.equal(result.details.layer_id, 'L1');
});

test('a stamp is refused for a material not made in this chat, or over 2000 dabs', async () => {
  const { tools, calls } = setup();
  await assert.rejects(tools.stamp_material.execute('s1', { name: 'X', material: 'Nope', selection: 'Sky' }), /make_material first/);
  await tools.make_material.execute('m1', { name: 'Clouds', source: { selection: 'Sky' } });
  await assert.rejects(tools.stamp_material.execute('s2', { name: 'X', material: 'Clouds', selection: 'Sky', count: 2001 }), /2000/);
  await assert.rejects(tools.stamp_material.execute('s3', { name: 'X', material: 'Clouds' }), /area/);
  assert.equal(calls.filter(c => c.operation === 'stamp').length, 0);
});

test('stamp_material tells the painter that heavy stamps are thinned, so it builds volume in light layers', () => {
  const { tools } = setup();
  assert.match(tools.stamp_material.description, /at most 0\.6 ink per selected pixel \(coverage in the result\); a heavier stamp is thinned evenly \(opacity_scaled\)/);
});
