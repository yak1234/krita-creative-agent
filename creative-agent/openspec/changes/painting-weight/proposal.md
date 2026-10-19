## Why

On 2026-10-18, live tests on `new_moscow_finished.kra` (6000×4500) stalled or crashed Krita again and again:
- one `observe` took 909 s;
- two `fill_region` results were lost while a checkpoint saved;
- Krita ran at 9 GB RSS.

The cause was the shape of the layer tree, not leftovers (the tidy had already removed 348 MB of hidden layers):
- 248 of its 258 nodes are the agent's kept, unmerged work, 537 MB of the 637 MB file;
- it has 147 group layers, each with a cached projection;
- 10 live filter masks, a wavelet noise reducer among them, are recomputed on every refresh.

Neither the painter nor the artist could see any of this. The painter saw slow, failing calls; the artist saw a crash.

## What Changes

- **The plugin measures the painting's weight** with every observation. The measure is read-only and reads no pixels:
  - node, group, paint-layer and filter-mask counts;
  - the expensive filters by name;
  - the agent's hidden leftovers;
  - an estimated memory size;
  - a level: `ok`, `heavy` or `too_heavy`, with the reasons.
- **A Pi extension, `extensions/painting-weight.ts`,** adds one line to the painter's tool result when the level rises, or
  when an operation was slow (`timings_ms`). The line names the cause and the cheapest fix. It never blocks.
- **The artist hears it once per chat**, in the panel's status line: what makes the painting heavy, and the fixes:
  - **Tidy** (leftovers);
  - **Merge kept moves** (`merge_kept`);
  - **Bake filter masks**.

  The fixes stay the artist's choice. The monitor itself never changes the painting.

## Capabilities

### New Capabilities
- `painting-weight`: measuring a painting's weight, telling the painter and the artist what makes it heavy, and
  naming the fix.

## Impact

- Plugin: `painting_weight.py` (a pure measure over the node tree), with observations carrying `weight`.
- Companion: the `painting-weight.ts` extension, registered inline, and a studio status notice.
- Panel buttons for merge and bake: a later change, since the panel needs a Krita restart.
