# Layer plan: a professional layer structure the painter works in

Status: APPROVED by the artist (2026-10-24: goals 1-6 "are good", "yes please"; goals 7-8 "yes as long as 8 doesn't
result in saves that make it slow"). Builds after "Find it for me" (agent/find-it).

## Why

Toska treats the layer stack as a pile: every pass makes a new layer inside a per-move group, undone or retried passes
stay behind hidden (one New Moscow chat had 46 hidden leftovers and Krita slowed down), merging only happens when the
artist runs "merge agent work", and the painter does not know which layer holds the underpainting, an element or the
accents. A professional Krita painter keeps a locked base, one group per element or plane, clipped light/shadow layers,
and tidies as stages are approved.

## Goals

1. **Underpainting locked.** When the artist keeps the whole-picture underpainting, its layers merge into one layer named
   "Underpainting", locked (Krita's layer lock) so nothing paints on it.
2. **One group per element or plane**, named after the plan ("Sky", "Kremlin towers", "Accents"); an element's work lands
   inside its group, not in a new loose layer per pass.
3. **Light and shadow as clipped layers** inside an element's group (Screen/Add for light, Multiply for shadow, clipped
   to the element), so they stay adjustable.
4. **Met merges.** When the artist presses Met on a step, that group's passes merge into one tidy layer (the group stays,
   named).
5. **No hidden leftovers.** Undone or replaced passes are deleted when the artist keeps or undoes, never left hidden.
6. **The painter sees the stack**: a short summary of the layer structure (groups, locked base, where its current move
   paints) in its context before each move.
7. **Value check.** A hidden "Value check" desaturate filter layer at the top the artist can toggle; the goal-likeness
   check also measures lightness (grey) separately from colour so value mistakes are caught on their own.
8. **Automatic snapshots without slowness.** At each Met, Toska records a named Krita snapshot ("after underpainting",
   "after accents") — never a file save. Guard rails, because large saves and many live masks slowed Krita before:
   keep at most the 3 most recent Toska snapshots (older ones removed), skip a snapshot (and say so) when Krita's memory
   use is high, and measure the time and memory of taking one on a 6000x4500 New Moscow copy in the live Toska test
   before shipping; if a snapshot costs more than about a second or a large share of memory, ship without goal 8 and
   report the numbers.

## Non-goals

- No change to the artist's own layers; only layers and groups Toska created are merged, locked or deleted.
- No new file saves.

## Done when

On a copy of New Moscow in Toska (live, per AGENTS.md): after the underpainting and two element steps the stack reads
like the structure above, no hidden leftovers remain, Met merges, the snapshot list holds at most 3 Toska snapshots,
and snapshot time/memory are reported.
