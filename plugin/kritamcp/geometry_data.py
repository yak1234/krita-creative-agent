"""Validated geometry for precise painting operations."""
from math import isfinite

def finite(v):
    if isinstance(v, bool) or not isinstance(v, (float,int)) or not isfinite(v):
        raise ValueError('Coordinates must be finite numbers')
    return v

def bounds(value, width, height):
    if not isinstance(value, (list,tuple)) or len(value)!=4:
        raise ValueError('bounds must be [x,y,width,height]')
    x,y,w,h=[finite(v) for v in value]
    if any(int(v)!=v for v in (x,y,w,h)) or x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height:
        raise ValueError('bounds must be positive integer-sized and inside the image')
    return tuple(map(int,(x,y,w,h)))

def polygon(points, width, height):
    """Checked polygon points inside the canvas and their pixel bounds (x, y, w, h)."""
    if not isinstance(points, list) or not 3 <= len(points) <= 1000:
        raise ValueError('a polygon needs 3-1000 points [x,y]')
    checked = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError('polygon points must be [x,y]')
        x, y = finite(point[0]), finite(point[1])
        if not 0 <= x <= width or not 0 <= y <= height:
            raise ValueError('polygon points must lie inside the canvas')
        checked.append((x, y))
    xs, ys = [p[0] for p in checked], [p[1] for p in checked]
    left, top = int(min(xs)), int(min(ys))
    right, bottom = min(width, int(max(xs)) + 1), min(height, int(max(ys)) + 1)
    if right - left < 1 or bottom - top < 1 or max(xs) == min(xs) or max(ys) == min(ys):
        raise ValueError('the polygon has no area')
    return checked, (left, top, right - left, bottom - top)

def curve(start, segments):
    if not isinstance(start,(list,tuple)) or len(start)!=2:
        raise ValueError('start must be [x,y]')
    if not isinstance(segments,list) or not 1<=len(segments)<=1000:
        raise ValueError('segments must contain 1..1000 cubic segments')
    result=[]
    for part in segments:
        if not isinstance(part,(list,tuple)) or len(part)!=6:
            raise ValueError('Each cubic is [control1x,control1y,control2x,control2y,endx,endy]')
        result.append(tuple(finite(v) for v in part))
    return tuple(finite(v) for v in start),result
