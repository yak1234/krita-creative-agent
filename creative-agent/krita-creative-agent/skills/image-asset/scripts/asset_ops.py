"""Image operations shared by the image-asset scripts. Runs in the Pyodide sandbox: numpy and Pillow,
the job's folder at /work (read and write) and this folder at /skill (read only)."""
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# paint_from_reference refuses references over 5 MB.
MAX_BYTES = 4_500_000


def load_rgba(path):
    return Image.open(path).convert('RGBA')


def border_colour(im):
    """Median colour of the outer 2% of the image: the background of an isolated subject."""
    a = np.asarray(im.convert('RGB'))
    h, w = a.shape[:2]
    b = max(2, int(min(h, w) * 0.02))
    ring = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(ring, axis=0))


def cutout(im, tolerance=40, feather=1.5, despeckle=5):
    """Make the background transparent: flood fill from every border pixel that matches the border
    colour, so a background colour inside the subject (white snow on a tree) stays opaque. A textured
    background (models often paint "paper") raises the tolerance, and despeckle removes the specks
    and thin threads a fill leaves behind (a live tree kept 46,000 light specks that painted as haze)."""
    rgb = im.convert('RGB')
    w, h = rgb.size
    marker = (255, 0, 255)
    filled = rgb.copy()
    key = np.array(border_colour(rgb))
    a = np.asarray(rgb).astype(int)
    b = max(2, int(min(h, w) * 0.02))
    ring = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    tolerance = int(min(90, max(tolerance, 3 * float(np.abs(ring - key).max(axis=1).std()) + 20)))
    step = max(1, min(w, h) // 64)
    seeds = [(x, 0) for x in range(0, w, step)] + [(x, h - 1) for x in range(0, w, step)] + \
            [(0, y) for y in range(0, h, step)] + [(w - 1, y) for y in range(0, h, step)]
    for x, y in seeds:
        if np.abs(a[y, x] - key).max() <= tolerance and filled.getpixel((x, y)) != marker:
            ImageDraw.floodfill(filled, (x, y), marker, thresh=tolerance)
    background = np.all(np.asarray(filled) == marker, axis=2)
    # Noisy background pixels stop a flood fill. A pixel near the background colour that is mostly
    # surrounded by background is background too; snow inside a tree is surrounded by tree and stays.
    near_key = np.abs(a - key).max(axis=2) <= tolerance * 1.8
    around = np.asarray(Image.fromarray((background * 255).astype('uint8')).filter(ImageFilter.BoxBlur(max(4, min(w, h) // 80)))) / 255
    background |= near_key & (around > 0.5)
    alpha = Image.fromarray(np.where(background, 0, 255).astype('uint8'))
    if despeckle:
        size = despeckle if despeckle % 2 else despeckle + 1
        alpha = alpha.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))
        background = np.asarray(alpha) < 128
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    out = im.copy()
    final = np.minimum(np.asarray(alpha), np.asarray(im.getchannel('A')))
    out.putalpha(Image.fromarray(final))
    return decontaminate(out), float(background.mean())


def decontaminate(im, radius=3):
    """Give semi-transparent edge pixels the colour of the subject next to them instead of the removed
    background, so a soft edge does not paint a pale outline: an alpha-weighted blur of the opaque colours."""
    a = np.asarray(im).astype(float)
    alpha = a[..., 3:4] / 255
    solid = (alpha >= 0.98).astype(float)
    blur = lambda x: np.asarray(Image.fromarray(np.clip(x, 0, 255).astype('uint8')).filter(ImageFilter.GaussianBlur(radius))).astype(float)
    weight = blur(solid[..., 0] * 255)[..., None] / 255
    colour = np.stack([blur(a[..., c] * solid[..., 0]) for c in range(3)], axis=2)
    spread = np.where(weight > 0.01, colour / np.maximum(weight, 0.01), a[..., :3])
    edge = (alpha > 0) & (alpha < 0.98)
    a[..., :3] = np.where(edge, spread, a[..., :3])
    return Image.fromarray(np.clip(a, 0, 255).astype('uint8'), 'RGBA')


def has_transparency(im, share=0.05):
    """True when at least share of the image is already transparent (a model returned a cut-out)."""
    return float((np.asarray(im.getchannel('A')) < 8).mean()) >= share


def clean_alpha(im, floor=12, despeckle=3):
    """Tidy a model's own transparency: near-invisible pixels become fully transparent, isolated
    specks go, and soft edges take the subject's colour."""
    alpha = np.asarray(im.getchannel('A')).copy()
    alpha[alpha < floor] = 0
    mask = Image.fromarray(np.where(alpha > 0, 255, 0).astype('uint8')).filter(ImageFilter.MinFilter(despeckle)).filter(ImageFilter.MaxFilter(despeckle))
    alpha = np.where(np.asarray(mask) > 0, alpha, 0).astype('uint8')
    out = im.copy()
    out.putalpha(Image.fromarray(alpha))
    return decontaminate(out), float((alpha == 0).mean())


def crop_to_content(im, margin=0.03):
    box = im.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError('The image is fully transparent.')
    m = int(max(im.size) * margin)
    return im.crop((max(0, box[0] - m), max(0, box[1] - m), min(im.width, box[2] + m), min(im.height, box[3] + m)))


def match_palette(im, palette_from, strength=0.6):
    """Move the image's colours toward another image's (a crop of the painting): per-channel
    histogram matching over opaque pixels, blended by strength. Alpha is kept."""
    src = np.asarray(im).astype(float)
    ref = np.asarray(palette_from.convert('RGB')).reshape(-1, 3).astype(float)
    opaque = src[..., 3] > 8
    out = src.copy()
    for c in range(3):
        values = src[..., c][opaque]
        if values.size == 0:
            continue
        s_sorted = np.sort(values)
        r_sorted = np.sort(ref[:, c])
        quantiles = np.searchsorted(s_sorted, values, side='right') / s_sorted.size
        mapped = np.interp(quantiles, np.linspace(0, 1, r_sorted.size), r_sorted)
        out[..., c][opaque] = values * (1 - strength) + mapped * strength
    return Image.fromarray(np.clip(out, 0, 255).astype('uint8'), 'RGBA')


def fade_edges(im, edges='bottom', width=0.12):
    """Fade alpha to zero over the given edges (any of top, bottom, left, right) so a patch such as a
    sky band melts into the painting instead of ending in a hard line."""
    a = np.asarray(im.getchannel('A')).astype(float)
    h, w = a.shape
    ramp = lambda n: np.clip(np.arange(n) / max(1, int(n * width)), 0, 1)
    if 'bottom' in edges:
        a *= ramp(h)[::-1][:, None]
    if 'top' in edges:
        a *= ramp(h)[:, None]
    if 'left' in edges:
        a *= ramp(w)[None, :]
    if 'right' in edges:
        a *= ramp(w)[::-1][None, :]
    out = im.copy()
    out.putalpha(Image.fromarray(a.astype('uint8')))
    return out


def fit_to(im, width, height, anchor='bottom'):
    """Scale the asset to sit inside width x height and pad it with transparency to exactly that size,
    so paint_from_reference gets source [0,0,width,height] for a canvas target of the same size.
    anchor bottom stands a subject on the target's bottom edge; center centres it; fill crops to cover."""
    width, height = int(width), int(height)
    if anchor == 'fill':
        scale = max(width / im.width, height / im.height)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        left, top = (im.width - width) // 2, (im.height - height) // 2
        return im.crop((left, top, left + width, top + height))
    scale = min(width / im.width, height / im.height)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    out = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    out.paste(im, ((width - im.width) // 2, height - im.height if anchor == 'bottom' else (height - im.height) // 2))
    return out


def fit(im, max_side=2560, max_bytes=MAX_BYTES):
    """Shrink to max_side, then further until the PNG is under max_bytes. Returns (image, png bytes)."""
    if max(im.size) > max_side:
        im = im.resize((round(im.width * max_side / max(im.size)), round(im.height * max_side / max(im.size))), Image.LANCZOS)
    while True:
        buf = io.BytesIO()
        im.save(buf, 'PNG', optimize=True)
        if buf.tell() <= max_bytes or max(im.size) < 256:
            return im, buf.getvalue()
        im = im.resize((round(im.width * 0.85), round(im.height * 0.85)), Image.LANCZOS)


def preview(im, path, side=768):
    """A small JPEG for the model to look at: transparency shown over a mid-grey checkerboard."""
    small = im.copy()
    small.thumbnail((side, side))
    board = Image.new('RGB', small.size, (128, 128, 128))
    cell = 16
    draw = ImageDraw.Draw(board)
    for y in range(0, small.height, cell):
        for x in range((y // cell % 2) * cell, small.width, cell * 2):
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(160, 160, 160))
    board.paste(small, (0, 0), small)
    board.save(path, 'JPEG', quality=85)


def save(im, path, **fit_options):
    im, data = fit(im, **fit_options)
    with open(path, 'wb') as f:
        f.write(data)
    alpha = np.asarray(im.getchannel('A'))
    return {'path': path, 'width': im.width, 'height': im.height, 'bytes': len(data),
            'transparent_share': round(float((alpha < 8).mean()), 3)}
