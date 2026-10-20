# Pigment-style colour mixing for the agent (future change, not scheduled)

Status: parked by the artist on 20 October 2026. Do not start before Demo v1 (see krita-fork/tasks.md, section 7) is done.

## Idea
Pigment.O (a Krita colour picker, mixer and sampler plugin, https://krita-artists.org/t/pigment-o-plugin/4531) models how physical
pigments blend instead of plain RGB maths, which avoids muddy mixes. The agent today only samples exact canvas colours
(`sample_canvas_colors`) and picks colours as hex values itself; mixing happens only inside Krita's brush engine.

## Possible scope
- A `mix_colors` function (pure Python, tested, pigment-style mixing such as a Kubelka-Munk style calculation) and an agent tool for it.
- A palette built from samples of a reference painting.
- Mixing in the loop: sample two places, mix, paint with the result.

## First step when it is picked up
A read-only survey: Pigment.O's licence (we must not copy code unless it is compatible), its algorithm, its sampling approach,
and whether Krita master already has something (the colour smudge engine, the mixer slider docker).
