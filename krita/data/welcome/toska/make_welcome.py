# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Builds Toska's welcome page background (toska-welcome.jpg here) from the artist's source painting: the same pixels
# (1774 x 887), as a progressive JPEG with full-resolution colour (4:4:4, so the red moon and the ember edges stay
# crisp) small enough to compile into the app (under 600 KB). No ICC profile: Qt reads an untagged JPEG as sRGB,
# which the source is (its PNG carries an sRGB chunk).
# Usage: python make_welcome.py <toska-welcome-source.png> <toska-welcome.jpg>
import io
import sys

from PIL import Image

source_path, out_path = sys.argv[1:3]
LIMIT = 600 * 1024
image = Image.open(source_path).convert('RGB')
for quality in (88, 85, 82, 78):
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=quality, optimize=True, progressive=True, subsampling=0)
    if len(buffer.getvalue()) <= LIMIT:
        break
else:
    sys.exit('the painting does not fit in %d bytes even at quality %d' % (LIMIT, quality))
with open(out_path, 'wb') as out:
    out.write(buffer.getvalue())
print('%s: %d x %d, quality %d, %d bytes' % (out_path, image.width, image.height, quality, len(buffer.getvalue())))
