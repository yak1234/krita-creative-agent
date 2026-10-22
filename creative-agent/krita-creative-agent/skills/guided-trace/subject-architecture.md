# Guiding architecture

**What to guide**
- The eye level and the vanishing points first. Every horizontal edge of a building recedes to one of them: roof lines,
  cornices, window rows, kerbs, railings.
- The silhouette from the reference (`from_reference`, `detail: 'medium'`). Use the tiers, setbacks and the spire
  rather than one box.
- The verticals stay vertical unless the reference looks steeply up or down.
- A centre line for anything symmetrical (a tower, a gate, a dome), and the height of one storey to count by.
- Arches as curves: three or more points on each arch, springing from the same line.
- A row of buildings (a skyline) as separate heights, measured from the reference, never one rectangle.
- Lit windows and lamps as light shapes (`weight: 'light'`) when they are the brightest things.

**Common errors**
- One box for a cluster of skyscrapers: each one has its own height, width and top.
- A plain rectangle for a tower that has tiers, wings or a spire.
- Zig-zags for arches.
- Window rows that do not run to the vanishing point.
- A building placed by eye: measure its top, bottom and centre as fractions of the reference.
