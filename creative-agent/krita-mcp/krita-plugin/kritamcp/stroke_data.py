"""Validated stroke input, independent of Krita/Qt for regression tests."""
import math


def number(value, label, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{label} must be in {low}..{high}")
    return value


def normalize_stroke(params):
    points = params.get("points", [])
    if not isinstance(points, list) or not 2 <= len(points) <= 10000:
        raise ValueError("points must contain 2..10000 [x,y] or [x,y,pressure] entries")
    pressure = params.get("pressure")
    if isinstance(pressure, list) and len(pressure) != len(points):
        raise ValueError("pressure list must match points length")
    explicit = pressure is not None or any(isinstance(p, (list, tuple)) and len(p) == 3 for p in points)
    out = []
    for i, p in enumerate(points):
        if not isinstance(p, (list, tuple)) or len(p) not in (2, 3):
            raise ValueError(f"point {i} must be [x,y] or [x,y,pressure]")
        base = pressure[i] if isinstance(pressure, list) else (1.0 if pressure is None else pressure)
        out.append((number(p[0], "x"), number(p[1], "y"), number(p[2] if len(p) == 3 else base, "pressure", 0, 1)))
    return out, explicit
