"""Make an asset's plain background transparent (flood fill from the border, so background-coloured
parts inside the subject stay) and crop to the subject.
ARGS: input (asset file in /work), output, tolerance (0-255, default 40; raise it for a noisy background),
crop (default true), feather (px, default 1.5)."""
import asset_ops as ops

im, removed = ops.cutout(ops.load_rgba('/work/' + ARGS['input']), tolerance=ARGS.get('tolerance', 40), feather=ARGS.get('feather', 1.5))
if ARGS.get('crop', True):
    im = ops.crop_to_content(im)
info = ops.save(im, '/work/' + ARGS['output'])
RESULT = {'outputs': [{**info, 'notes': 'cut out (%d%% background removed)' % round(removed * 100)}]}
