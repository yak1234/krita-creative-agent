"""Fade an asset's alpha to zero over some edges so a patch (a sky band, a background strip) melts into
the painting instead of ending in a hard line.
ARGS: input (asset file in /work), output, edges (e.g. "bottom" or "left right bottom"), width (share of the size, default 0.12)."""
import asset_ops as ops

im = ops.fade_edges(ops.load_rgba('/work/' + ARGS['input']), edges=ARGS.get('edges', 'bottom'), width=ARGS.get('width', 0.12))
info = ops.save(im, '/work/' + ARGS['output'])
RESULT = {'outputs': [{**info, 'notes': 'edges faded: %s' % ARGS.get('edges', 'bottom')}]}
