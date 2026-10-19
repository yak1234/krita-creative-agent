## ADDED Requirements

### Requirement: Agent painting speed does not depend on document size
The fork SHALL let scripts refresh a region, paint strokes asynchronously with job status, read a cheap revision, and
read a scaled projection. With these, a 1024-stroke chunk SHALL take about as long on a 6000×4500 painting as on a
1024×768 one, and an observation of a 6000×4500 painting SHALL take under 2 seconds.

#### Scenario: New Moscow
- **WHEN** the same 1024-stroke chunk is painted on new_moscow_merged (6000×4500) and on a 1024×768 painting
- **THEN** the chunk times, from `timings_ms`, differ by less than a factor of 1.5, where stock Krita differs by much
  more

### Requirement: A busy Krita reports job status instead of timing out
A script's asynchronous stroke job SHALL report its state, progress and changed area while it runs, and SHALL run
without blocking Krita's window. A job's result SHALL never be lost because Krita was busy. Waiting SHALL be per job:
a script waiting for its own job SHALL NOT wait for unrelated work in the image, as `Document.waitForDone()` does.
Jobs SHALL be cancellable. Their purpose is status, nothing lost, pressure and undo: batching strokes into fewer jobs
painted identical pixels at only 1.02–1.07× the speed (19 October 2026), since Krita's brush engine does most of the
work.

#### Scenario: A long transfer
- **WHEN** the companion asks about a reference transfer that is still painting
- **THEN** it gets the job's state and progress, not a timeout or "Lost the painting operation result"

#### Scenario: The artist works during a pass
- **WHEN** an agent pass is painting and the artist pans the canvas or opens a menu
- **THEN** the window responds normally, and the pass finishes with its result intact

### Requirement: Scripts see what changed
The fork SHALL give scripts a revision counter that increases on every change to the image, the area changed since a
given revision, and a signal carrying each changed area as Krita's own canvas receives it. Changes by the artist and
by the agent SHALL both be reported, each marked with who made it.

#### Scenario: The artist paints between two moves
- **WHEN** the artist paints a stroke over the moon between two agent moves
- **THEN** the next observation reports the moon's area as changed by the artist, without hashing the full canvas

### Requirement: Cheap views of the canvas
Scripts SHALL read the composited image of a region at a chosen scale without copying the full-size canvas first, with
memory near the output size and time well under a full read plus downscale. The read averages every source pixel it
covers, so thin strokes survive; its time therefore grows with the region's area. Level-of-detail projections would
make it grow with the output size, but they exist only while a canvas shows instant preview, so they are an optional
later path.

#### Scenario: The model's view of a large painting
- **WHEN** the plugin reads a 1568 px view of a 6000×4500 painting
- **THEN** it uses about the output's memory (not the 216 MB of a full read) and well under the time of a full read and
  downscale, with thin strokes kept

### Requirement: Strokes carry pressure
The agent's strokes SHALL carry per-point pressure, and tilt and speed where the API offers them, through Krita's
freehand stroke system (master's `paintPolylineStroke`, or `FreehandStrokeStrategy` with a `KisPaintInformation` per
point, which 5.3.3 already has), each stroke one undoable freehand stroke, and Undo of a move SHALL still reject all
of its passes.

#### Scenario: Tapered strokes
- **WHEN** the painter sends a stroke with pressure falling from 1 to 0.1
- **THEN** the stroke tapers as a pen stroke would, and Undo of its move removes it

### Requirement: Agent work has its own place in the history
Each agent move SHALL be one named undo step ("Agent: <move>") however many passes and strokes it painted, so a move
never uses up Krita's undo limit. The undo history SHALL show which steps are the agent's. The artist's own strokes
SHALL stay separate steps, as today.

#### Scenario: A 1400-stroke move
- **WHEN** a move paints 6 passes and 1400 strokes and the artist then presses Undo once
- **THEN** the whole move is undone in one step, and the artist's earlier strokes are still in the history
