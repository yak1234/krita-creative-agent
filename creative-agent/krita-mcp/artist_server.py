"""Artist-level MCP tools for a running local Krita MCP Bridge."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'krita-creative-agent'))
from diagnostics_client import register_diagnostic_tools

KRITA_URL = "http://127.0.0.1:5678"
CONFIG_PATH = Path(__file__).with_name("painting_config.json")
mcp = FastMCP("krita-artist")
register_diagnostic_tools(mcp)

DEFAULT_CONFIG: dict[str, Any] = {
    "name": "untitled",
    "width": 1536,
    "height": 864,
    "brush": "Bristles-2 Flat Rough",
    "regions": {
        "left": {
            "bounds": [30, 80, 700, 700],
            "palette": ["#b17b3b", "#cf934c", "#ad7332", "#936732"],
        },
        "right": {
            "bounds": [820, 80, 680, 700],
            "palette": ["#071826", "#122431", "#0d1a24", "#18232a"],
        },
    },
    "sample_points": [],
}


def command(action: str, params: dict[str, Any] | None = None, timeout: float = 120.0) -> dict[str, Any]:
    try:
        response = httpx.post(KRITA_URL, json={"action": action, "params": params or {}, "timeout": timeout}, timeout=timeout + 10)
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG


def export_canvas(name: str) -> str | None:
    result = command("get_canvas", {"filename": f"{name}.png"}, timeout=300.0)
    return result.get("path")


@mcp.tool()
def krita_artist_health() -> dict[str, Any]:
    """Confirm that Krita is running and its Krita MCP Bridge is enabled."""
    try:
        response = httpx.get(f"{KRITA_URL}/health", timeout=5.0)
        return response.json()
    except Exception as exc:
        return {"error": "Cannot reach Krita MCP Bridge", "detail": str(exc)}


@mcp.tool()
def artist_load_config(painting: dict[str, Any]) -> dict[str, Any]:
    """Save a reusable painting configuration: dimensions, named regions, palettes, and sample points."""
    merged = {**DEFAULT_CONFIG, **painting}
    CONFIG_PATH.write_text(json.dumps(merged, indent=2) + "\n")
    return merged


@mcp.tool()
def artist_observe(name: str = "observe") -> dict[str, Any]:
    """Export a fresh canvas view and return layers plus configured color samples. Call before and after painting."""
    current = config()
    samples = []
    for item in current.get("sample_points", []):
        if len(item) != 3:
            continue
        label, x, y = item
        result = command("get_color_at", {"x": x, "y": y})
        samples.append({"label": label, "x": x, "y": y, "color": result.get("color")})
    layers = command("list_layers").get("layers", [])
    canvas = export_canvas(f"{name}_canvas")
    return {"painting": current.get("name"), "canvas_path": canvas, "layers": layers, "samples": samples}


@mcp.tool()
def artist_build_mass(region: str, passes: int = 2, brush_size: int = 165, opacity: float = 0.6, seed: int | None = None) -> dict[str, Any]:
    """Build a painterly color mass in a named configured region, then export a fresh view."""
    current = config()
    spec = current.get("regions", {}).get(region)
    if not spec:
        return {"error": f"Unknown region: {region}", "available_regions": list(current.get("regions", {}))}
    x, y, width, height = spec["bounds"]
    palette = spec.get("palette", [])
    if not palette:
        return {"error": f"Region {region} has no palette"}
    rng = random.Random(seed)
    brush_result = command("set_brush", {"preset": current.get("brush"), "size": brush_size, "opacity": opacity})
    if brush_result.get("error"):
        return brush_result
    painted = 0
    for _ in range(max(1, passes) * 5):
        cy = rng.randint(y, y + height)
        start_x = rng.randint(x, x + max(1, width // 5))
        end_x = rng.randint(x + (width * 3 // 5), x + width)
        points = [[start_x, cy], [(start_x + end_x) // 2, cy + rng.randint(-40, 40)], [end_x, cy + rng.randint(-30, 30)]]
        command("set_color", {"color": rng.choice(palette)})
        result = command("stroke", {"points": points, "pressure": rng.uniform(0.65, 0.95)})
        if not result.get("error"):
            painted += 1
    return {"region": region, "strokes": painted, "canvas_path": export_canvas(f"after_{region}_mass")}


@mcp.tool()
def artist_save_view(name: str = "current") -> dict[str, Any]:
    """Export the current canvas to a PNG for review without changing the painting."""
    return {"canvas_path": export_canvas(name)}


@mcp.tool()
def krita_batch(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run precise bridge commands. Bridge 2 supports stroke points [x,y,pressure]
    or pressure scalar/list; set_brush size/opacity/flow/rotation; select_layer
    by name/id; brush_settings; configure_brush properties; restore_brush;
    set_brush_texture path/scale/strength. Pressure paths render as native
    line segments (brush state may restart at joins). New layers become active.
    Inspect brush_settings before changing existing property keys. Preset
    customization is in memory; restore_brush restores the original settings.
    Prefer brush_controls controls={pigment:0..1,blend:0..1,scatter:0..1,
    pigment_dynamics:bool,blend_dynamics:bool}. PressureColorRate is an enable
    switch, NOT pressure modulation. brush_probe tests the current preset on a
    disposable two-color swatch and returns changed_pixels and canvas_path.
    Bridge 2.2: selection(shape=rectangle/ellipse/polygon, bounds or points,
    mode=replace/add/subtract/intersect/clear, feather). curve_stroke(start,
    segments=[[c1x,c1y,c2x,c2y,endx,endy]], size,opacity,color) renders one
    native path; no variable pressure. compare_region(bounds,reference_path,
    reference_bounds,scale) exports labeled closeups. duplicate_document(name)
    makes an unsaved working copy. layer_settings(opacity=0..1,visible=bool)
    adjusts the active layer. Selections constrain native strokes; raw pixel
    commands do not honor them.
    Bridge 2.3: duplicate_layer(name) copies the active layer and selects it;
    move_layer(dx,dy) translates the entire unlocked paint layer in integer
    canvas pixels, regardless of selection. modify_selection(operation=
    grow/shrink/feather/smooth,radius=1..128) adjusts the active selection;
    smooth takes no radius. layer_settings also accepts alpha_locked and
    locked booleans. Alpha lock constrains native painting, not raw pixels.
    """
    return [{"action": item.get("action"), "result": command(str(item.get("action", "")), item.get("params") or {})} for item in commands]


if __name__ == "__main__":
    mcp.run()
