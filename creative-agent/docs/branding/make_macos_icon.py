# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The macOS app icon: the T emblem (toska-emblem.png) on a Toska Night rounded tile (Apple icon grid: 824 px tile on a
1024 canvas, ~22% corners, soft drop shadow), written as toska-icon-macos.png. Then, in this folder:
    mkdir Toska.iconset; for s in 16 32 128 256 512: sips -z s s and 2s 2s into icon_SxS.png and icon_SxS@2x.png
    iconutil -c icns Toska.iconset -o Toska.icns
Usage: uv run --with pillow python -I make_macos_icon.py toska-emblem.png toska-icon-macos.png"""
import sys
from PIL import Image, ImageDraw, ImageFilter
emblem = Image.open(sys.argv[1]).convert('RGBA')
out = sys.argv[2]
N = 1024; inset = 100; side = N - 2 * inset; radius = int(side * 0.2237)   # Apple's macOS icon grid: 824 px tile, ~185 px corners
# tile: Toska Night navy, a quiet top-to-bottom shift from #1a2330 to #0b1119 (the logo's sky)
tile = Image.new('RGBA', (side, side))
top, bottom = (26, 35, 48), (11, 17, 25)
for y in range(side):
    t = y / (side - 1)
    c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    ImageDraw.Draw(tile).line([(0, y), (side, y)], fill=c)
mask = Image.new('L', (side, side), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, side - 1, side - 1], radius=radius, fill=255)
tile.putalpha(mask)
# a thin light rim, as macOS tiles have
rim = Image.new('RGBA', (side, side), (0, 0, 0, 0))
ImageDraw.Draw(rim).rounded_rectangle([1, 1, side - 2, side - 2], radius=radius - 1, outline=(245, 219, 174, 40), width=3)
tile.alpha_composite(rim)
# the emblem, centred, ~86% of the tile
e = emblem.resize((int(side * 1.08), int(side * 1.08)), Image.LANCZOS)
layer = Image.new('RGBA', (side, side), (0, 0, 0, 0)); layer.alpha_composite(e, ((side - e.width) // 2, (side - e.height) // 2) if e.width <= side else (0, 0)) if e.width <= side else layer.paste(e.crop(((e.width - side) // 2, (e.height - side) // 2, (e.width - side) // 2 + side, (e.height - side) // 2 + side)), (0, 0))
layer.putalpha(Image.composite(layer.split()[3], Image.new('L', (side, side), 0), mask))
tile.alpha_composite(layer)
# canvas with the standard soft drop shadow under the tile
canvas = Image.new('RGBA', (N, N), (0, 0, 0, 0))
shadow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
sm = Image.new('L', (N, N), 0)
ImageDraw.Draw(sm).rounded_rectangle([inset, inset + 12, inset + side - 1, inset + side + 11], radius=radius, fill=110)
shadow.putalpha(sm.filter(ImageFilter.GaussianBlur(14)))
canvas.alpha_composite(shadow)
canvas.alpha_composite(tile, (inset, inset))
canvas.save(out)
print('ok', out)
