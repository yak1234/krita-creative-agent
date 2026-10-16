"""Turn a model's raw image into a paintable asset: RGBA PNG under 5 MB, optionally cut out of a plain
background and cropped to the subject, plus a small preview. make_asset runs this after every image.
ARGS: input, output, preview (file names in /work); cutout (bool), tolerance, crop (bool), max_side;
fit [width, height] and anchor (bottom, center, fill) to size it for one canvas target."""
import asset_ops as ops

im = ops.load_rgba('/work/' + ARGS['input'])
removed = None
if ARGS.get('cutout') and ops.has_transparency(im) and not ARGS.get('tolerance'):
    # The model returned a transparent background already (Codex does): keep it, drop faint specks.
    im, removed = ops.clean_alpha(im)
elif ARGS.get('cutout'):
    im, removed = ops.cutout(im, tolerance=ARGS.get('tolerance', 40))
    if ARGS.get('crop', True):
        im = ops.crop_to_content(im)
if ARGS.get('fit'):
    im = ops.fit_to(im, *ARGS['fit'], anchor=ARGS.get('anchor', 'bottom'))
info = ops.save(im, '/work/' + ARGS['output'], max_side=ARGS.get('max_side', 2560))
ops.preview(ops.load_rgba('/work/' + ARGS['output']), '/work/' + ARGS['preview'])
RESULT = {**info, 'background_removed_share': removed}
