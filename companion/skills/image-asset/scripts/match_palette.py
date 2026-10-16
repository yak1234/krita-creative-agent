"""Shift an asset's colours toward the painting's so it belongs in the scene: histogram matching
against a crop of the canvas around where it will go. Alpha is kept.
ARGS: input (asset file in /work), palette_from (canvas crop file in /work), output, strength (0-1, default 0.6)."""
import asset_ops as ops

im = ops.match_palette(ops.load_rgba('/work/' + ARGS['input']), ops.load_rgba('/work/' + ARGS['palette_from']), strength=ARGS.get('strength', 0.6))
info = ops.save(im, '/work/' + ARGS['output'])
RESULT = {'outputs': [{**info, 'notes': 'palette matched at strength %s' % ARGS.get('strength', 0.6)}]}
