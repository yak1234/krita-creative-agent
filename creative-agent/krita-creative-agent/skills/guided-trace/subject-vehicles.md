# Guiding vehicles

**What to guide**
- The ground line under the wheels and the eye level. A car seen from above the eye level shows its roof; seen from
  below, it does not.
- The body's silhouette from the reference (`from_reference` with `shape: {box}` around the car alone, `detail:
  'simple'`), then the wheel arches and the windows (`'medium'`). Two cars are two shapes.
- Wheels as ellipses whose short axis points along the axle. Both wheels of one side sit on one line to the vanishing
  point.
- The body's long edges (sills, the waist line, the roof line) recede to the vanishing point.
- Headlamps, tail lamps and bright reflections as light shapes (`lights: true` or `weight: 'light'`).

**Common errors**
- A foreground car drawn too small: measure its top and bottom in the reference. A car that fills the bottom half
  there fills it on the canvas.
- Round wheels on a car seen at an angle.
- Front and back wheels at heights that do not fit the perspective.
- Headlamps painted dark because they were never marked as light.
