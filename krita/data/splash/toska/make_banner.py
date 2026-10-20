# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Builds the Toska splash banner (banner.svg here): the logo at half size with a soft light halo baked in, padded so
# the halo is not clipped, embedded as one PNG; the invisible rectangle "toska-logo" marks the logo's own frame.
# Usage: python make_banner.py <toska-logo.png> <banner.svg> [<banner preview.png>]
import base64, io, sys
import numpy as np
from PIL import Image, ImageFilter
from PIL.PngImagePlugin import PngInfo

logo_path, out_svg = sys.argv[1:3]
out_halo_png = sys.argv[3] if len(sys.argv) > 3 else None
LOGO_W = 1086                      # half of the artist's 2172 px: about 2x the logo's on-screen width on a Retina splash
PAD = 48                           # room for the halo on every side
logo = Image.open(logo_path)
srgb = logo.info.get('srgb')          # the artist's logo is tagged sRGB: keep the tag on the embedded PNG
logo = logo.convert('RGBA')
lh = round(logo.height * LOGO_W / logo.width)
logo = logo.resize((LOGO_W, lh), Image.LANCZOS)

alpha = logo.split()[3]
grown = alpha.filter(ImageFilter.MaxFilter(7))
soft = grown.filter(ImageFilter.GaussianBlur(18))
a = np.asarray(soft, dtype=np.float32) / 255.0
a = np.clip(a * 1.6, 0, 1) * 0.30          # peak opacity of the halo
halo = Image.new('RGBA', logo.size, (236, 228, 216, 0))
halo.putalpha(Image.fromarray((a * 255).astype(np.uint8)))

canvas = Image.new('RGBA', (LOGO_W + 2 * PAD, lh + 2 * PAD), (0, 0, 0, 0))
big_halo = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
big_halo.paste(halo, (PAD, PAD))
# blur once more on the padded canvas so the halo fades out before the edge
big_halo = big_halo.filter(ImageFilter.GaussianBlur(6))
canvas.alpha_composite(big_halo)
canvas.alpha_composite(logo, (PAD, PAD))
edge = np.asarray(canvas)[..., 3]
assert edge[0].max() == 0 and edge[-1].max() == 0 and edge[:, 0].max() == 0 and edge[:, -1].max() == 0, 'halo clipped'
tags = PngInfo()
if srgb is not None:
    tags.add(b'sRGB', bytes([srgb]))
buf = io.BytesIO(); canvas.save(buf, 'PNG', optimize=True, pnginfo=tags)
if out_halo_png:
    canvas.save(out_halo_png, "PNG", optimize=True, pnginfo=tags)
b64 = base64.b64encode(buf.getvalue()).decode('ascii')
W, H = canvas.size
svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<!--
  Toska splash banner, aliased as :/splash/banner.svg by krita/data/splash/splash-toska.qrc. The logo is artwork owned
  by the artist, licence to be decided (README.md here). The logo has a soft light halo baked into the PNG (QtSvg
  filters are not relied on). The invisible rectangle "toska-logo" is the logo's own frame (the artist's PNG frame);
  KisSplashScreen places that frame, and the halo padding falls outside it. Made by
  krita/data/splash/toska/make_banner.py from creative-agent/docs/branding/toska-logo.png.
-->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
 <title>Toska</title>
 <image id="toska-banner" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="none" xlink:href="data:image/png;base64,{b64}"/>
 <rect id="toska-logo" x="{PAD}" y="{PAD}" width="{LOGO_W}" height="{lh}" fill="none" stroke="none"/>
</svg>
'''
open(out_svg, 'w').write(svg)
print('banner', W, H, 'logo frame', PAD, PAD, LOGO_W, lh, 'png bytes', len(buf.getvalue()), 'svg bytes', len(svg))
