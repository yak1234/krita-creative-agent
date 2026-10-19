"""
Krita MCP Server
Bridge between Claude (or any MCP client) and Krita painting application.

Uses FastMCP to expose Krita painting tools over the Model Context Protocol,
communicating with a Krita plugin via HTTP.
"""

from fastmcp import FastMCP
import httpx
import json
import os
from typing import Any, Dict, List, Optional

# Configuration


def krita_url(environ=os.environ) -> str:
    """The Krita bridge to paint in: KRITA_URL, else the bridge_url of the panel config KRITA_CREATIVE_CONFIG names
    (a Krita with its own settings folder, such as the fork, listens on its own port), else stock Krita's."""
    if environ.get("KRITA_URL"):
        return environ["KRITA_URL"]
    try:
        with open(environ["KRITA_CREATIVE_CONFIG"]) as stream:
            return str(json.load(stream)["bridge_url"])
    except (KeyError, OSError, ValueError, TypeError):
        return "http://localhost:5678"


KRITA_URL = krita_url()
# Must match the plugin's KRITA_MCP_TOKEN when the plugin requires one.
KRITA_TOKEN = os.environ.get("KRITA_MCP_TOKEN", "").strip()

mcp = FastMCP("krita-mcp")

# Share the companion diagnostic client with the existing painting MCP.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'krita-creative-agent'))
from diagnostics_client import register_diagnostic_tools
register_diagnostic_tools(mcp)
# Test chats in a separate test companion, for refining Agent mode (development only; not in artist_server.py).
from test_driver_client import register_test_tools
register_test_tools(mcp)

# Queue timeouts sent to the plugin. The HTTP wait adds HTTP_MARGIN so the
# plugin always answers first (same pattern as krita-creative-agent/bridge.mjs).
DEFAULT_TIMEOUT = 120.0
LONG_TIMEOUT = 300.0
HTTP_MARGIN = 20.0
LONG_RUNNING = {"open_file", "new_canvas", "get_canvas", "save", "save_native", "flood_fill"}

# Actions that cannot change the artwork; a lost reply for these is a plain error.
READ_ONLY = {"health", "get_color_at", "list_brushes", "canvas_info", "list_layers",
             "brush_settings", "get_canvas", "compare_region", "test_pixel"}

# Mirror of the handler table in the plugin's cmd_batch (checked by a test).
NATIVE_BATCH_ACTIONS = {
    "set_color", "set_brush", "stroke", "fill", "draw_shape", "new_layer", "clear",
    "paint_pixels", "select_layer", "brush_settings", "selection", "layer_settings",
    "duplicate_layer", "move_layer", "modify_selection", "curve_stroke",
    "compare_region", "duplicate_document", "brush_controls", "brush_probe",
    "configure_brush", "restore_brush", "set_brush_texture",
}
BATCH_CHUNK = 64

# Results whose full text the agent needs (image paths, readback).
DIAGNOSTIC_ACTIONS = {"compare_region", "brush_probe", "brush_settings",
                      "brush_controls", "canvas_info", "list_layers"}

UNREACHABLE = "Cannot connect to Krita. Is Krita running with the MCP plugin enabled?"


def _headers() -> dict:
    return {"Authorization": f"Bearer {KRITA_TOKEN}"} if KRITA_TOKEN else {}


def timeout_for(action: str) -> float:
    return LONG_TIMEOUT if action in LONG_RUNNING else DEFAULT_TIMEOUT


def _unknown(action: str, reason: str) -> dict:
    """A mutation may or may not have happened; say so instead of inviting a retry."""
    if action in READ_ONLY:
        return {"error": reason}
    return {"error": f"{reason}. Outcome unknown: inspect the canvas before repeating "
                     f"this {action}.", "error_code": "outcome_unknown"}


def _decode(response: httpx.Response) -> dict:
    if response.status_code == 401:
        return {"error": "Krita bridge rejected authorization: set the same "
                         "KRITA_MCP_TOKEN for Krita and this MCP server.",
                "error_code": "unauthorized"}
    try:
        data = response.json()
    except ValueError:
        return {"error": f"Bridge returned a non-JSON response (HTTP {response.status_code})",
                "error_code": "bad_response"}
    if not isinstance(data, dict):
        return {"error": "Bridge returned an unexpected JSON value", "error_code": "bad_response"}
    return data


def send_command(action: str, params: dict = None, timeout: float = None) -> dict:
    """Send command to Krita plugin and return result."""
    if params is None:
        params = {}
    if timeout is None:
        timeout = timeout_for(action)
    try:
        response = httpx.post(
            KRITA_URL,
            json={"action": action, "params": params, "timeout": timeout},
            headers=_headers(),
            timeout=httpx.Timeout(timeout + HTTP_MARGIN, connect=5.0),
        )
    except httpx.ConnectError:
        return {"error": UNREACHABLE, "error_code": "unreachable"}
    except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as e:
        return _unknown(action, f"No response from Krita ({type(e).__name__})")
    except Exception as e:
        return {"error": str(e)}
    result = _decode(response)
    if result.get("error_code") == "timeout":
        return _unknown(action, result["error"])
    return result


@mcp.tool()
def krita_health() -> str:
    """Check if Krita is running and the MCP plugin is active."""
    try:
        response = httpx.get(f"{KRITA_URL}/health", headers=_headers(), timeout=5.0)
    except httpx.ConnectError:
        return UNREACHABLE
    except httpx.TimeoutException:
        return ("Krita accepted the connection but did not answer within 5s; "
                "it may be busy with a long command such as a save.")
    except httpx.HTTPError as e:
        return f"Error reaching Krita: {e}"
    data = _decode(response)
    if "error" in data:
        return f"Error: {data['error']}"
    return (f"Krita is running. Plugin: {data.get('plugin', 'unknown')} "
            f"{data.get('version', '')}".rstrip())


def _failure_text(result: dict) -> str:
    parts = [str(result.get("error") or f"status {result.get('status')}")]
    if result.get("failures"):
        parts.append(f"failures={result['failures']}")
    return " ".join(parts)


def _batch_line(i: int, action: str, result: dict) -> tuple:
    """Format one krita_batch line; returns (line, kind) with kind ok/failed/unknown."""
    if result.get("error_code") == "outcome_unknown":
        return f"{i}: {action} UNKNOWN-OUTCOME {result['error']}", "unknown"
    if result.get("error") or result.get("status") not in (None, "ok"):
        return f"{i}: {action} FAILED {_failure_text(result)}", "failed"
    text = str({k: v for k, v in result.items() if k != "brushes"})
    if action not in DIAGNOSTIC_ACTIONS:
        text = text[:100]
    return f"{i}: {action} ok {text}", "ok"


def _run_batch(commands: list) -> list:
    """Execute commands in order; returns one result dict per input command."""
    results = [None] * len(commands)
    i = 0
    while i < len(commands):
        cmd = commands[i] if isinstance(commands[i], dict) else {}
        action = str(cmd.get("action", ""))
        if action not in NATIVE_BATCH_ACTIONS:
            results[i] = send_command(action, cmd.get("params") or {})
            i += 1
            continue
        # Contiguous run of natively batchable commands, at most BATCH_CHUNK long.
        j = i
        while (j < len(commands) and j - i < BATCH_CHUNK and isinstance(commands[j], dict)
               and str(commands[j].get("action", "")) in NATIVE_BATCH_ACTIONS):
            j += 1
        chunk = [{"action": c["action"], "params": c.get("params") or {}} for c in commands[i:j]]
        reply = send_command("batch", {"commands": chunk}, timeout=DEFAULT_TIMEOUT)
        items = reply.get("results")
        if isinstance(items, list) and len(items) == len(chunk):
            for item in items:
                res = item.get("result")
                res = res if isinstance(res, dict) else {"value": res}
                if not item.get("ok") and not (res.get("error") or res.get("status") not in (None, "ok")):
                    res = {**res, "error": "failed"}
                results[i + item.get("index", 0)] = res
        else:
            # Whole chunk failed, timed out or the plugin predates per-item results.
            if reply.get("error_code") == "outcome_unknown" or "error" not in reply:
                reason = reply.get("error") or "Batch reply had no per-command results"
                fill = _unknown("batch", reason)
            else:
                fill = reply
            for k in range(i, j):
                results[k] = fill
        i = j
    return results


@mcp.tool()
def krita_batch(commands: List[Dict[str, Any]]) -> str:
    """
    Execute several plugin commands sequentially in ONE call. Painting needs
    hundreds of color+draw pairs; this collapses them into few round trips:
    consecutive paint/layer/brush commands run inside Krita as native batches
    of up to 64, other commands are sent individually, always in input order.
    A failing command does not stop later ones.

    Args:
        commands: List of {"action": name, "params": {...}} items, executed in
            order. Actions: set_color, set_brush, stroke, fill, draw_shape,
            undo, redo, clear, get_color_at, list_brushes, canvas_info,
            list_layers, new_layer, select_layer, curve_stroke, flood_fill, compare_region,
            brush_probe, brush_settings, brush_controls, configure_brush,
            restore_brush, set_brush_texture, selection, modify_selection,
            duplicate_document, duplicate_layer, move_layer, layer_settings,
            save_native (layered .kra; params: path).
            curve_stroke takes start:[x,y], segments:[[c1x,c1y,c2x,c2y,x,y],...]
            plus size/opacity/flow/color; do NOT supply pressure.
            compare_region takes bounds:[x,y,w,h], reference_path,
            reference_bounds:[x,y,w,h], scale; crop aspect ratios must match.
            brush_probe takes size (1..180), exports a diagnostic and restores
            the previous document. Probe/comparison exports use the plugin output
            directory; read their returned canvas_path to inspect the images.

    Returns:
        One line per command, in order: "i: action ok|FAILED|UNKNOWN-OUTCOME ...",
        then a summary. UNKNOWN-OUTCOME means the command may have painted:
        inspect the canvas before repeating it.
    """
    if not isinstance(commands, list):
        return "Error: commands must be a list of {action, params} objects"
    lines, failed, unknown = [], 0, 0
    for i, (cmd, result) in enumerate(zip(commands, _run_batch(commands))):
        action = str(cmd.get("action", "")) if isinstance(cmd, dict) else "?"
        line, kind = _batch_line(i, action, result)
        lines.append(line)
        failed += kind == "failed"
        unknown += kind == "unknown"
    lines.append(f"{len(commands)} commands, {failed} failed, {unknown} unknown")
    return "\n".join(lines)


@mcp.tool()
def krita_new_canvas(
    width: int = 800,
    height: int = 600,
    name: str = "New Canvas",
    background: str = "#1a1a2e"
) -> str:
    """
    Create a new canvas in Krita.

    Args:
        width: Canvas width in pixels (default 800)
        height: Canvas height in pixels (default 600)
        name: Document name
        background: Background color as hex (default dark blue)
    """
    result = send_command("new_canvas", {
        "width": width,
        "height": height,
        "name": name,
        "background": background
    })

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Created canvas: {width}x{height}, background: {background}"


@mcp.tool()
def krita_set_color(color: str) -> str:
    """
    Set the foreground (paint) color.

    Args:
        color: Hex color code (e.g., "#ff6b6b", "#b8a9c9")
    """
    result = send_command("set_color", {"color": color})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Color set to {color}"


@mcp.tool()
def krita_set_brush(
    preset: Optional[str] = None,
    size: Optional[int] = None,
    opacity: Optional[float] = None
) -> str:
    """
    Set brush preset and properties.

    Args:
        preset: Brush preset name (partial match, e.g., "Basic", "Soft", "Airbrush")
        size: Brush size in pixels
        opacity: Brush opacity (0.0 to 1.0)
    """
    params = {}
    if preset:
        params["preset"] = preset
    if size:
        params["size"] = size
    if opacity is not None:
        params["opacity"] = opacity

    result = send_command("set_brush", params)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Brush set: preset={preset}, size={size}, opacity={opacity}"


@mcp.tool()
def krita_stroke(points: list[list[int]], pressure: float = 1.0) -> str:
    """
    Paint a stroke through a series of points.

    Args:
        points: List of [x, y] coordinate pairs, e.g., [[100, 100], [150, 120], [200, 150]]
        pressure: Brush pressure (0.0 to 1.0, affects stroke thickness/opacity)
    """
    if len(points) < 2:
        return "Error: Need at least 2 points for a stroke"

    result = send_command("stroke", {
        "points": points,
        "pressure": pressure
    })

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Stroke painted with {len(points)} points"


@mcp.tool()
def krita_fill(x: int, y: int, radius: int = 50) -> str:
    """
    Fill an area with current color (paints a filled circle at the point).

    Args:
        x: X coordinate
        y: Y coordinate
        radius: Fill radius in pixels
    """
    result = send_command("fill", {"x": x, "y": y, "radius": radius})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Filled at ({x}, {y}) with radius {radius}"


@mcp.tool()
def krita_flood_fill(
    x: int,
    y: int,
    color: str = "#ffffff",
    tolerance: float = 12,
    connectivity: int = 4,
    sample_merged: bool = True,
    max_pixels: Optional[int] = None,
) -> str:
    """Contiguously flood-fill a region from a seed pixel.

    The default samples the flattened visible image, which is useful for
    filling regions on a new layer above ink. The result is written to the
    active layer. Tolerance is RGB Euclidean distance in 8-bit space.

    Args:
        x: Seed X coordinate.
        y: Seed Y coordinate.
        color: Replacement hex color.
        tolerance: RGB tolerance from 0 to 441; 0 means exact match.
        connectivity: 4 or 8 pixel connectivity.
        sample_merged: Sample the flattened projection when true.
        max_pixels: Safety cap; omitted means the full canvas.
    """
    params = {
        "x": x, "y": y, "color": color,
        "tolerance": tolerance, "connectivity": connectivity,
        "sample_merged": sample_merged,
    }
    if max_pixels is not None:
        params["max_pixels"] = max_pixels
    result = send_command("flood_fill", params)
    if "error" in result:
        return f"Error: {result['error']}"
    return (f"Flood-filled {result.get('filled', 0)} pixels at ({x}, {y}) "
            f"with {color} ({result.get('status')})")


@mcp.tool()
def krita_paint_pixels(cells: list) -> str:
    """Paint many solid cells at once (fast faithful color field).

    Args:
        cells: List of [x, y, w, h, color] e.g. [[0,0,8,8,"#ff0000"], ...].
            Applied in ONE HTTP call with a single projection refresh.
    """
    if not isinstance(cells, list) or not cells:
        return "Error: cells must be a non-empty list of [x,y,w,h,color]"
    result = send_command("paint_pixels", {"cells": cells})
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Painted {result.get('painted', 0)} cells ({result.get('status')})"


@mcp.tool()
def krita_paint_grid(cells: list) -> str:
    """Alias for paint_pixels (some UIs use grid semantics). Same as krita_paint_pixels."""
    return krita_paint_pixels(cells)


@mcp.tool()
def krita_draw_shape(
    shape: str,
    x: int,
    y: int,
    width: int = 100,
    height: int = 100,
    fill: bool = True,
    stroke: bool = False,
    x2: Optional[int] = None,
    y2: Optional[int] = None
) -> str:
    """
    Draw a shape on the canvas.

    Args:
        shape: Type of shape - "rectangle", "ellipse", or "line"
        x: X coordinate (top-left for shapes, start point for lines)
        y: Y coordinate (top-left for shapes, start point for lines)
        width: Width of shape (ignored for lines if x2/y2 provided)
        height: Height of shape (ignored for lines if x2/y2 provided)
        fill: Whether to fill the shape
        stroke: Whether to draw outline
        x2: End X for lines (optional)
        y2: End Y for lines (optional)
    """
    params = {
        "shape": shape,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fill": fill,
        "stroke": stroke
    }
    if x2 is not None:
        params["x2"] = x2
    if y2 is not None:
        params["y2"] = y2

    result = send_command("draw_shape", params)

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Drew {shape} at ({x}, {y})"


@mcp.tool()
def krita_get_canvas(filename: str = "canvas.png") -> str:
    """
    Export current canvas to a PNG file and return the path.
    Use this to see your painting progress.

    Args:
        filename: Output filename (saved to configured output directory)
    """
    # Long timeout (see LONG_RUNNING) — export can take a while on large canvases
    result = send_command("get_canvas", {"filename": filename})

    if "error" in result:
        return f"Error: {result['error']}"

    path = result.get("path", "")
    return f"Canvas saved to: {path}"


@mcp.tool()
def krita_undo() -> str:
    """Undo the last action."""
    result = send_command("undo", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Undone"


@mcp.tool()
def krita_redo() -> str:
    """Redo the last undone action."""
    result = send_command("redo", {})

    if "error" in result:
        return f"Error: {result['error']}"
    return "Redone"


@mcp.tool()
def krita_clear(color: str = "#1a1a2e") -> str:
    """
    Clear the canvas to a solid color.

    Args:
        color: Color to fill canvas with (default dark blue)
    """
    result = send_command("clear", {"color": color})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Canvas cleared to {color}"


@mcp.tool()
def krita_save(path: str) -> str:
    """
    Save the current canvas to a specific file path.

    Args:
        path: Full file path to save to (e.g., "C:/art/my_painting.png")
    """
    # Long timeout (see LONG_RUNNING) — saving large files can take a while
    result = send_command("save", {"path": path})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Saved to {path}"


@mcp.tool()
def krita_get_color_at(x: int, y: int) -> str:
    """
    Sample the color at a specific pixel (eyedropper).

    Args:
        x: X coordinate
        y: Y coordinate
    """
    result = send_command("get_color_at", {"x": x, "y": y})

    if "error" in result:
        return f"Error: {result['error']}"
    return f"Color at ({x}, {y}): {result.get('color', 'unknown')} (R:{result.get('r')}, G:{result.get('g')}, B:{result.get('b')})"


@mcp.tool()
def krita_list_brushes(filter: str = "", limit: int = 20) -> str:
    """
    List available brush presets.

    Args:
        filter: Filter brushes by name (partial match)
        limit: Maximum number to return
    """
    result = send_command("list_brushes", {"filter": filter, "limit": limit})

    if "error" in result:
        return f"Error: {result['error']}"

    brushes = result.get("brushes", [])
    if not brushes:
        return "No brushes found matching filter"

    return f"Available brushes ({len(brushes)}):\n" + "\n".join(f"  - {b}" for b in brushes)


@mcp.tool()
def krita_open_file(path: str) -> str:
    """
    Open an existing file in Krita (.kra, .png, .jpg, etc).

    Args:
        path: Full file path to open (e.g., "C:/art/my_painting.kra")
    """
    result = send_command("open_file", {"path": path})

    if "error" in result:
        return f"Error: {result['error']}"

    return f"Opened: {result.get('name', 'unknown')} ({result.get('width')}x{result.get('height')})"


if __name__ == "__main__":
    mcp.run()


@mcp.tool()
def krita_tidy_painting(dry_run: bool = True) -> dict:
    """
    Remove the agent's hidden leftovers from the painting open in Krita: hidden layers inside its
    "Creative Agent ·" groups (copy-edit originals, rejected passes) and its groups left empty. Nothing
    outside those groups is touched (the artist's hidden layers, the protected areas).

    dry_run (default true) only lists what would go. With dry_run false the saved file is backed up as
    <name>.before-tidy.kra first; the painting is not saved, so the artist looks and saves.
    Refused while a painting session is open.
    """
    return send_command("creative", {"operation": "tidy_painting", "params": {"dry_run": dry_run}}, timeout=300)
