"""
Krita MCP Bridge — HTTP server for external paint commands in Krita.
Allows Claude (or any MCP client) to paint by sending commands to this plugin.

Architecture and command-queue design adapted from nanayax3/krita-mcp (MIT).
Rendering upgraded to Krita's native brush engine (Node.paint*), which is
colorspace-correct and honors the active brush preset; upstream's BGRA8 pixel
renderer is retained as an opt-in fallback for per-call hardness control.
"""

from krita import *
from . import vendor
vendor.add_vendor_path()                        # numpy and other native packages the plugin ships (vendor.py)
from .qt_compat import QTimer, QThread, pyqtSignal, QPointF, QPoint, QRectF, QByteArray, QBuffer, QIODevice, QCoreApplication
from .qt_compat import QColor, QPainterPath, QImage
from .qt_compat import QMessageBox
import json
import threading
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import os
import math
import base64
import hashlib
import xml.etree.ElementTree as ET
from .stroke_data import normalize_stroke, number
from .brush_controls import control_changes
from .precision_tools import PrecisionTools
from .creative_tools import CreativeTools
from .command_queue import CommandQueue
from .bridge_config import bridge_port, output_dir

BRIDGE_VERSION = "2.3.0"

# Configuration - customize these as needed
SERVER_PORT = 5678                 # stock Krita's; the running app's port comes from server_port() (bridge_config.py)
CANVAS_OUTPUT_DIR = output_dir(os.environ, QCoreApplication.organizationName())

# Optional shared secret. When set, POSTs must send `Authorization: Bearer <token>`.
# Default empty = open localhost-only endpoint (matches upstream behavior).
AUTH_TOKEN = os.environ.get("KRITA_MCP_TOKEN", "").strip()

MAX_BODY_BYTES = 24 * 1024 * 1024    # a 12 MB reference sent to model_image is ~16 MB as base64


# Global command queue
command_queue = CommandQueue()
command_counter = 0

# Commands whose work can legitimately exceed the default 120s timeout.
LONG_RUNNING = {"get_canvas", "save", "save_native", "open_file", "new_canvas"}
DEFAULT_TIMEOUT = 120
LONG_TIMEOUT = 300

ALL_COMMANDS = [
    "creative",
    "health", "new_canvas", "open_file", "set_color", "set_brush", "stroke",
    "fill", "flood_fill", "draw_shape", "get_canvas", "undo", "redo", "clear", "save",
    "save_native", "get_color_at", "list_brushes", "list_layers",
    "new_layer", "canvas_info", "test_pixel", "reload",
    "duplicate_layer", "move_layer", "modify_selection", "layer_settings", "selection", "curve_stroke", "compare_region", "duplicate_document", "batch", "brush_controls", "brush_probe", "paint_pixels", "select_layer", "brush_settings", "configure_brush", "restore_brush", "set_brush_texture",
]


class PaintRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for paint commands."""

    def log_message(self, format, *args):
        # Suppress HTTP logging
        pass

    def send_json_response(self, data, status=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not AUTH_TOKEN:
            return True
        return self.headers.get('Authorization', '') == f'Bearer {AUTH_TOKEN}'

    def do_GET(self):
        """Handle GET requests - health and introspection."""
        parsed = urlparse(self.path)

        if not self._authorized():
            self.send_json_response({"error": "unauthorized"}, 401)
            return

        if parsed.path == '/health':
            self.send_json_response({"status": "ok", "plugin": "kritamcp", "version": BRIDGE_VERSION,
                                     "auth_required": bool(AUTH_TOKEN)})
        elif parsed.path in ('/info', '/'):
            self.send_json_response({
                "status": "ok",
                "canvas_dir": CANVAS_OUTPUT_DIR,
                "commands": ALL_COMMANDS,
            })
        else:
            self.send_json_response({"error": "Unknown endpoint"}, 404)

    def do_POST(self):
        """Handle POST requests - paint commands."""
        global command_counter

        if not self._authorized():
            self.send_json_response({"error": "unauthorized"}, 401)
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_json_response({"error": f"body must be 1..{MAX_BODY_BYTES} bytes"}, 400)
            return

        body = self.rfile.read(content_length).decode('utf-8')

        try:
            command = json.loads(body)
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON"}, 400)
            return

        if not isinstance(command, dict):
            self.send_json_response({"error": "body must be a JSON object"}, 400)
            return

        action = command.get("action")
        if action not in ALL_COMMANDS:
            self.send_json_response(
                {"error": f"unknown action {action!r}", "commands": ALL_COMMANDS}, 400)
            return

        # Per-command queue timeout; the client may also request one.
        timeout = command.get("timeout")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = LONG_TIMEOUT if action in LONG_RUNNING else DEFAULT_TIMEOUT

        # Assign command ID and queue it
        command_counter += 1
        command_id = command_counter
        command_queue.push(command_id, command)

        # Wait for result from main thread
        result = command_queue.get_result(command_id, timeout=timeout)

        if "error" in result:
            self.send_json_response(result, 500)
        else:
            self.send_json_response(result)


def server_port():
    """The port this Krita's bridge listens on: the bridge_url in this plugin folder's creative-agent-config.json, else
    5678 in stock Krita and 5679 in a Krita with its own settings folder (the fork), so both can run at once."""
    return bridge_port(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'creative-agent-config.json'),
                       QCoreApplication.organizationName())


class ServerThread(QThread):
    """Thread to run HTTP server without blocking Krita UI."""

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.server = None

    def run(self):
        self.server = HTTPServer(('127.0.0.1', self.port), PaintRequestHandler)
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()


class KritaMCPExtension(CreativeTools, PrecisionTools, Extension):
    """Main Krita extension class."""

    def __init__(self, parent):
        super().__init__(parent)
        self.server_thread = None
        self.timer = None
        self.current_brush_size = 20
        self.current_opacity = 1.0
        self._impl = None  # for future split handlers / reload

    def setup(self):
        """Called when extension is loaded."""
        pass

    def createActions(self, window):
        """Called when a new window is created."""
        # Ensure output directory exists
        os.makedirs(CANVAS_OUTPUT_DIR, exist_ok=True)

        # Start HTTP server
        if self.server_thread is None:
            port = server_port()
            self.server_thread = ServerThread(port)
            self.server_thread.start()
            print(f"[KritaMCP] HTTP server started on 127.0.0.1:{port}"
                  + (" (token auth)" if AUTH_TOKEN else ""))

        # Start timer to process command queue
        if self.timer is None:
            self.timer = QTimer()
            self.timer.timeout.connect(self.process_commands)
            self.timer.start(50)  # Check every 50ms

    def process_commands(self):
        """Process queued commands in main thread (drain up to 16 per tick)."""
        # A stroke pass lets Krita handle clicks between strokes (so Stop and the window respond);
        # a timer tick inside it must not start another command in the middle of that one.
        if getattr(self, '_executing', False):
            return
        for _ in range(16):
            item = command_queue.pop()
            if item is None:
                return
            command_id, command = item
            self._executing = True
            try:
                result = self.execute_command(command)
            finally:
                self._executing = False
            command_queue.set_result(command_id, result)

    def execute_command(self, command):
        """Execute a paint command and return result."""
        try:
            action = command.get("action")
            params = command.get("params", {})

            handlers = {
                "creative": self.cmd_creative,
                "health": self.cmd_health,
                "new_canvas": self.cmd_new_canvas,
                "open_file": self.cmd_open_file,
                "set_color": self.cmd_set_color,
                "set_brush": self.cmd_set_brush,
                "stroke": self.cmd_stroke,
                "fill": self.cmd_fill,
                "flood_fill": self.cmd_flood_fill,
                "draw_shape": self.cmd_draw_shape,
                "get_canvas": self.cmd_get_canvas,
                "undo": self.cmd_undo,
                "redo": self.cmd_redo,
                "clear": self.cmd_clear,
                "save": self.cmd_save,
                "save_native": self.cmd_save_native,
                "get_color_at": self.cmd_get_color_at,
                "list_brushes": self.cmd_list_brushes,
                "list_layers": self.cmd_list_layers,
                "new_layer": self.cmd_new_layer,
                "canvas_info": self.cmd_canvas_info,
                "test_pixel": self.cmd_test_pixel,
                "reload": self.cmd_reload,
                "batch": self.cmd_batch,
                "paint_pixels": self.cmd_paint_pixels,
                "select_layer": self.cmd_select_layer,
                "brush_settings": self.cmd_brush_settings,
                "selection": self.cmd_selection,
                "layer_settings": self.cmd_layer_settings,
                "duplicate_layer": self.cmd_duplicate_layer,
                "move_layer": self.cmd_move_layer,
                "modify_selection": self.cmd_modify_selection,
                "curve_stroke": self.cmd_curve_stroke,
                "compare_region": self.cmd_compare_region,
                "duplicate_document": self.cmd_duplicate_document,
                "brush_controls": self.cmd_brush_controls,
                "brush_probe": self.cmd_brush_probe,
                "configure_brush": self.cmd_configure_brush,
                "restore_brush": self.cmd_restore_brush,
                "set_brush_texture": self.cmd_set_brush_texture,
            }
            handler = handlers.get(action)
            if handler is None:
                return {"error": f"Unknown action: {action}"}
            return handler(params)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}", "error_code": "internal"}

    # ── Context resolution ─────────────────────────────────────────────

    def get_active_document(self):
        """Get active document or return None."""
        app = Krita.instance()
        return app.activeDocument()

    def get_active_view(self):
        """Get active view or return None."""
        app = Krita.instance()
        window = app.activeWindow()
        if window:
            return window.activeView()
        return None

    def get_active_layer(self):
        """Get active paint layer."""
        doc = self.get_active_document()
        if doc:
            return doc.activeNode()
        return None

    def _require_document(self):
        doc = self.get_active_document()
        if not doc:
            return None, {"error": "No open document. Call new_canvas or open_file first."}
        return doc, None

    def _require_layer(self):
        doc = self.get_active_document()
        if not doc:
            return None, None, {"error": "No open document. Call new_canvas or open_file first."}
        layer = self.get_active_layer()
        if not layer:
            return doc, None, {"error": "No active layer"}
        return doc, layer, None

    def _apply_brush_state(self, view, size=None, opacity=None, flow=None, color=None):
        """Push brush geometry/opacity/flow/color onto the View for paint* calls."""
        if view is None:
            return
        if size is not None:
            try:
                view.setBrushSize(float(size))
            except Exception:
                pass
        if opacity is not None:
            try:
                view.setPaintingOpacity(float(opacity))
            except Exception:
                pass
        if flow is not None:
            try:
                view.setPaintingFlow(float(flow))
            except Exception:
                pass
        if color is not None:
            try:
                view.setForeGroundColor(ManagedColor.fromQColor(QColor(color), view.canvas()))
            except Exception:
                pass

    @staticmethod
    def _hex_rgb(hex_color):
        """Parse #rgb / #rrggbb into (r, g, b) ints, or None if invalid."""
        s = (hex_color or "").strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return None
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError:
            return None

    @staticmethod
    def _pixel_ok(doc):
        try:
            return doc.colorSpace() == "RGBA" and doc.colorDepth() == "U8"
        except Exception:
            return True

    def _pixel_fill_rect(self, doc, node, x, y, w, h, hex_color):
        """Solid rectangle fill via QImage + setPixelData.

        This is the reliable path. Raw bytes (even correct length) can return
        False depending on layer state / bounds. We capture the bool return
        and surface diagnostics.
        """
        rgb = self._hex_rgb(hex_color)
        if rgb is None:
            return {"error": f"Bad color: {hex_color}"}
        if not self._pixel_ok(doc):
            return {"error": "pixel fill needs an RGBA/U8 document"}
        xx, yy = int(x), int(y)
        ww, hh = int(w), int(h)
        if ww <= 0 or hh <= 0:
            return {"error": "fill size must be positive"}
        r, g, b = rgb
        # Krita setPixelData for RGBA/U8 expects BGRA byte order (empirically verified)
        row = bytes((b, g, r, 255)) * ww
        data = row * hh
        ok = node.setPixelData(data, xx, yy, ww, hh)
        if not ok:
            bnds = getattr(node, 'bounds', lambda: None)()
            return {
                "error": "setPixelData returned False",
                "x": xx, "y": yy, "w": ww, "h": hh,
                "data_len": len(data),
                "expected": ww * hh * 4,
                "layer_name": getattr(node, 'name', lambda: '<?>')(),
                "color_model": getattr(doc, 'colorModel', lambda: '?')(),
                "color_depth": getattr(doc, 'colorDepth', lambda: '?')(),
                "bounds": str(bnds) if bnds else None,
            }
        doc.refreshProjection()
        return {"status": "ok", "bytes": len(data)}

    def _pixel_fill_ellipse(self, doc, node, cx, cy, rx, ry, hex_color):
        """Solid ellipse via per-row chords (RGBA order) + return value checks."""
        rgb = self._hex_rgb(hex_color)
        if rgb is None:
            return {"error": f"Bad color: {hex_color}"}
        if not self._pixel_ok(doc):
            return {"error": "pixel fill needs an RGBA/U8 document"}
        if rx <= 0 or ry <= 0:
            return {"error": "fill size must be positive"}
        r, g, b = rgb
        px = bytes((b, g, r, 255))  # Krita RGBA/U8 pixelData uses BGRA
        ok = True
        for yy in range(int(math.floor(cy - ry)), int(math.ceil(cy + ry)) + 1):
            dy = (yy + 0.5 - cy) / ry
            if abs(dy) >= 1.0:
                continue
            half = rx * math.sqrt(1.0 - dy * dy)
            x0, x1 = int(math.floor(cx - half)), int(math.ceil(cx + half))
            if x1 > x0:
                if not node.setPixelData(px * (x1 - x0), x0, yy, x1 - x0, 1):
                    ok = False
        doc.refreshProjection()
        return {"status": "ok" if ok else "partial", "note": "some rows may have failed"} if ok else {"error": "setPixelData returned False for some rows"}

    def _pick_color_profile(self):
        """Choose a valid sRGB profile instead of an empty string (upstream used "")."""
        app = Krita.instance()
        try:
            profiles = app.profiles("RGBA", "U8") or []
        except Exception:
            profiles = []
        for preferred in ("sRGB-elle-V2-srgbtrc.icc",):
            if preferred in profiles:
                return preferred
        for p in profiles:
            if "srgb" in str(p).lower():
                return p
        return profiles[0] if profiles else ""

    def _export_document(self, doc, filepath):
        """Flatten and write the document, suppressing the export dialog."""
        try:
            doc.refreshProjection()
            doc.waitForDone()
        except Exception:
            pass
        os.makedirs(os.path.dirname(os.path.abspath(filepath)) or ".", exist_ok=True)
        doc.setBatchmode(True)
        try:
            ok = doc.exportImage(filepath, InfoObject())
        finally:
            doc.setBatchmode(False)
        if not ok or not os.path.exists(filepath):
            return {"error": f"Export failed: {filepath}"}
        return None

    # ── Commands ───────────────────────────────────────────────────────

    def cmd_health(self, params):
        """Report plugin + document + brush state."""
        app = Krita.instance()
        doc = app.activeDocument()
        out = {
            "status": "ok",
            "krita_version": str(app.version() or "unknown"),
            "bridge_version": BRIDGE_VERSION,
            "bridge_port": self.server_thread.port if self.server_thread else None,
            "settings_folder": QCoreApplication.organizationName(),
            "has_canvas": doc is not None,
            "canvas_dir": CANVAS_OUTPUT_DIR,
        }
        if doc is not None:
            view = self.get_active_view()
            layer = doc.activeNode()
            out.update({
                "document": doc.name(),
                "width": doc.width(),
                "height": doc.height(),
                "color_model": doc.colorModel(),
                "color_depth": doc.colorDepth(),
                "active_layer": layer.name() if layer else None,
            })
            if view is not None:
                try:
                    out["brush_size"] = view.brushSize()
                except Exception:
                    pass
                try:
                    preset = view.currentBrushPreset()
                    out["brush_preset"] = preset.name() if preset else None
                except Exception:
                    pass
        return out

    def cmd_new_canvas(self, params):
        """Create a new canvas."""
        width = int(params.get("width", 800))
        height = int(params.get("height", 600))
        name = params.get("name", "New Canvas")
        bg_color = params.get("background", "#1a1a2e")
        if width <= 0 or height <= 0:
            return {"error": "width and height must be positive"}

        app = Krita.instance()

        # Create document with a real color profile (upstream passed "")
        doc = app.createDocument(width, height, name, "RGBA", "U8",
                                 self._pick_color_profile(), 120.0)

        window = app.activeWindow()
        if window:
            window.addView(doc)

        # Create a paint layer
        root = doc.rootNode()
        layer = doc.createNode("paint", "paintlayer")
        root.addChildNode(layer, None)
        doc.setActiveNode(layer)  # ensure subsequent pixel ops target it

        # Fill background via pixel data (fillStyle hex is ignored by libkis)
        self._pixel_fill_rect(doc, layer, 0, 0, width, height, bg_color)
        doc.refreshProjection()

        return {"status": "ok", "width": width, "height": height, "name": name}

    def cmd_open_file(self, params):
        """Open an existing file in Krita."""
        filepath = params.get("path")
        if not filepath:
            return {"error": "No path specified"}

        filepath = os.path.expanduser(filepath)
        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}

        app = Krita.instance()
        doc = app.openDocument(filepath)
        if not doc:
            return {"error": f"Failed to open: {filepath}"}

        window = app.activeWindow()
        if window:
            window.addView(doc)

        return {"status": "ok", "path": filepath, "name": doc.name(),
                "width": doc.width(), "height": doc.height()}

    def cmd_set_color(self, params):
        """Set foreground color."""
        color_hex = params.get("color", "#ffffff")

        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        color = QColor(color_hex)
        if not color.isValid():
            return {"error": f"Invalid color: {color_hex!r}"}
        mc = ManagedColor.fromQColor(color, view.canvas())
        view.setForeGroundColor(mc)

        return {"status": "ok", "color": color_hex}

    def cmd_set_brush(self, params):
        """Set brush preset and size."""
        for key, low, high in (("size", 0.01, 10000), ("opacity", 0, 1), ("flow", 0, 1), ("rotation", -36000, 36000)):
            if params.get(key) is not None:
                number(params[key], key, low, high)
        preset_name = params.get("preset", None)
        size = params.get("size", None)
        opacity = params.get("opacity", None)

        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        if preset_name:
            presets = Krita.instance().resources("preset")
            found = presets.get(preset_name)
            if found is None:
                matches = [preset for name, preset in presets.items() if preset_name.lower() in name.lower()]
                if len(matches) > 1:
                    return {"error": "Ambiguous preset; use exact name", "matches": [p.name() for p in matches]}
                found = matches[0] if matches else None
            if found:
                view.setCurrentBrushPreset(found)
            else:
                return {"error": f"Brush preset not found: {preset_name}"}

        if size is not None:
            self.current_brush_size = size
            view.setBrushSize(size)

        if opacity is not None:
            self.current_opacity = opacity
            try:
                view.setPaintingOpacity(float(opacity))
            except Exception:
                pass

        if params.get("flow") is not None:
            view.setPaintingFlow(float(params["flow"]))
        if params.get("rotation") is not None:
            view.setBrushRotation(float(params["rotation"]))
        self.current_brush_size = view.brushSize()
        self.current_opacity = view.paintingOpacity()
        return {"status": "ok", "preset": view.currentBrushPreset().name(), "size": view.brushSize(),
                "opacity": view.paintingOpacity(), "flow": view.paintingFlow(), "rotation": view.brushRotation()}

    # ── Native brush-engine rendering (new; replaces fragile BGRA8 math) ──

    def cmd_stroke(self, params):
        """Paint a stroke along points.

        engine="native" (default) routes through Krita's brush engine so the
        active preset's texture/dynamics apply and any colorspace works.
        engine="pixel" uses upstream's BGRA8 soft-circle renderer with per-call
        hardness control (RGBA8 documents only).
        """
        points, has_pressure = normalize_stroke(params)
        size = number(params.get("size", self.current_brush_size), "size", 0.01, 10000)
        opacity = number(params.get("opacity", self.current_opacity), "opacity", 0, 1)
        for key, low, high in (("flow", 0, 1), ("rotation", -36000, 36000)):
            if params.get(key) is not None:
                number(params[key], key, low, high)
        engine = params.get("engine", "native")
        if engine not in ("native", "pixel"):
            return {"error": "engine must be native or pixel"}
        doc, layer, err = self._require_layer()
        if err:
            return err
        if layer.locked() or not layer.visible():
            return {"error": "Active layer is locked or hidden"}
        ability = layer.paintAbility()
        if ability != "PAINT":
            return {"error": "Layer cannot be painted", "paint_ability": ability}
        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}
        if params.get("color") is not None and not QColor(params["color"]).isValid():
            return {"error": "Invalid stroke color"}
        if engine == "pixel" and has_pressure:
            return {"error": "Pressure input requires engine=native"}
        self._apply_brush_state(view, size=size, opacity=opacity,
                                flow=params.get("flow"), color=params.get("color"))
        if params.get("rotation") is not None:
            view.setBrushRotation(float(params["rotation"]))
        if engine == "pixel":
            return self._stroke_pixel(params, doc, layer, view)
        if has_pressure:
            previous = view.disablePressure()
            view.setDisablePressure(False)
            try:
                for start, end in zip(points, points[1:]):
                    if start[:2] == end[:2]:
                        continue
                    # This installed Krita binding takes QPoint (integer coordinates).
                    layer.paintLine(QPoint(round(start[0]), round(start[1])),
                                    QPoint(round(end[0]), round(end[1])),
                                    start[2], end[2], "ForegroundColor")
            finally:
                view.setDisablePressure(previous)
        else:
            path = QPainterPath()
            path.moveTo(QPointF(points[0][0], points[0][1]))
            for x, y, pressure in points[1:]:
                path.lineTo(QPointF(x, y))
            layer.paintPath(path, "ForegroundColor", "None")
        doc.refreshProjection()
        return {"status": "ok", "points_count": len(points), "engine": "native",
                "pressure_mode": "segments" if has_pressure else "preset_path",
                "layer": layer.name()}

    def _stroke_pixel(self, params, doc, layer, view):
        """Upstream's BGRA8 soft-circle renderer (kept for hardness control)."""
        points = params.get("points", [])
        brush_size = params.get("size", self.current_brush_size)
        hardness = params.get("hardness", 0.5)  # 0.0 = very soft, 1.0 = hard edge
        opacity = params.get("opacity", self.current_opacity)

        if doc.colorModel() != "RGBA" or doc.colorDepth() != "U8":
            return {"error": "engine='pixel' requires an RGBA/U8 document; use engine='native' for other color models/depths"}

        fg = view.foregroundColor()
        qcolor = fg.colorForCanvas(view.canvas())
        r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

        width = doc.width()
        height = doc.height()
        radius = max(1, int(brush_size) // 2)

        min_x = max(0, int(min(p[0] for p in points)) - radius - 2)
        min_y = max(0, int(min(p[1] for p in points)) - radius - 2)
        max_x = min(width, int(max(p[0] for p in points)) + radius + 2)
        max_y = min(height, int(max(p[1] for p in points)) + radius + 2)

        w = max_x - min_x
        h = max_y - min_y
        if w <= 0 or h <= 0:
            return {"error": "Stroke out of bounds"}

        existing = layer.pixelData(min_x, min_y, w, h)
        pixels = bytearray(existing)

        def draw_soft_circle(cx, cy, point_opacity=1.0):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    dist_sq = dx * dx + dy * dy
                    if dist_sq <= radius * radius:
                        px = int(cx) + dx - min_x
                        py = int(cy) + dy - min_y
                        if 0 <= px < w and 0 <= py < h:
                            dist = math.sqrt(dist_sq) / radius if radius > 0 else 0
                            if hardness >= 1.0:
                                alpha_factor = 1.0
                            elif dist < hardness:
                                alpha_factor = 1.0
                            else:
                                falloff = (dist - hardness) / (1.0 - hardness)
                                alpha_factor = 1.0 - falloff
                            final_alpha = int(255 * alpha_factor * opacity * point_opacity)
                            if final_alpha > 0:
                                idx = (py * w + px) * 4
                                eb, eg, er, ea = pixels[idx], pixels[idx+1], pixels[idx+2], pixels[idx+3]
                                blend = final_alpha / 255.0
                                pixels[idx] = int(eb * (1 - blend) + b * blend)
                                pixels[idx+1] = int(eg * (1 - blend) + g * blend)
                                pixels[idx+2] = int(er * (1 - blend) + r * blend)
                                pixels[idx+3] = max(ea, final_alpha)

        def draw_line(x1, y1, x2, y2):
            dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            steps = max(1, int(dist / max(1, radius / 3)))
            for i in range(steps + 1):
                t = i / steps if steps > 0 else 0
                draw_soft_circle(x1 + t * (x2 - x1), y1 + t * (y2 - y1))

        for i in range(len(points)):
            draw_soft_circle(points[i][0], points[i][1])
            if i > 0:
                draw_line(points[i-1][0], points[i-1][1], points[i][0], points[i][1])

        layer.setPixelData(bytes(pixels), min_x, min_y, w, h)
        doc.refreshProjection()
        return {"status": "ok", "points_count": len(points), "hardness": hardness, "engine": "pixel"}

    def cmd_fill(self, params):
        """Fill a circular area with the current color (native brush engine)."""
        x = float(params.get("x", 0))
        y = float(params.get("y", 0))
        radius = float(params.get("radius", 50))
        if radius <= 0:
            return {"error": "radius must be positive"}

        doc, layer, err = self._require_layer()
        if err:
            return err
        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        self._apply_brush_state(view, opacity=params.get("opacity"), color=params.get("color"))
        fill_color = params.get("color") or "#ffffff"
        rect = QRectF(x - radius, y - radius, radius * 2, radius * 2)
        layer.paintEllipse(rect, None, fill_color)
        doc.refreshProjection()
        return {"status": "ok", "x": x, "y": y, "radius": radius}

    def cmd_flood_fill(self, params):
        """Contiguously flood-fill pixels matching the seed color.

        The source is the flattened projection by default, so this works for
        coloring on a new layer above ink. Set sample_merged=False to sample
        only the active layer. RGB tolerance is Euclidean distance in 8-bit
        space; connectivity may be 4 or 8. The fill writes opaque BGRA pixels
        to the active layer and respects a max_pixels safety limit.
        """
        doc, layer, err = self._require_layer()
        if err:
            return err

        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        width, height = doc.width(), doc.height()
        if not (0 <= x < width and 0 <= y < height):
            return {"error": f"({x}, {y}) outside canvas {width}x{height}"}

        tolerance = float(params.get("tolerance", 12))
        if tolerance < 0 or tolerance > 441:
            return {"error": "tolerance must be between 0 and 441"}
        max_pixels = int(params.get("max_pixels", width * height))
        if max_pixels <= 0:
            return {"error": "max_pixels must be positive"}
        connectivity = int(params.get("connectivity", 4))
        if connectivity not in (4, 8):
            return {"error": "connectivity must be 4 or 8"}

        # Krita's U8 pixel buffers are BGRA. The projection gives us the
        # visible image, while the active node is the destination.
        if params.get("sample_merged", True):
            source = bytes(doc.rootNode().projectionPixelData(0, 0, width, height))
        else:
            source = bytes(layer.pixelData(0, 0, width, height))
        destination = bytearray(layer.pixelData(0, 0, width, height))
        expected = width * height * 4
        if len(source) < expected or len(destination) < expected:
            return {"error": "flood_fill requires an RGBA/U8 document"}

        seed = (y * width + x) * 4
        target_b, target_g, target_r = source[seed], source[seed + 1], source[seed + 2]
        replacement = params.get("color") or "#ffffff"
        qcolor = QColor(replacement)
        if not qcolor.isValid():
            return {"error": f"invalid fill color: {replacement}"}
        fill_r, fill_g, fill_b, fill_a = qcolor.red(), qcolor.green(), qcolor.blue(), qcolor.alpha()
        threshold = tolerance * tolerance

        visited = bytearray(width * height)
        queue = deque([(x, y)])
        visited[y * width + x] = 1
        filled = 0
        min_x = max_x = x
        min_y = max_y = y
        if connectivity == 8:
            neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1))
        else:
            neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1))

        while queue and filled < max_pixels:
            px, py = queue.popleft()
            pixel = (py * width + px) * 4
            sb, sg, sr = source[pixel], source[pixel + 1], source[pixel + 2]
            db = sb - target_b; dg = sg - target_g; dr = sr - target_r
            if db * db + dg * dg + dr * dr > threshold:
                continue
            destination[pixel:pixel + 4] = bytes((fill_b, fill_g, fill_r, fill_a))
            filled += 1
            min_x = min(min_x, px); max_x = max(max_x, px)
            min_y = min(min_y, py); max_y = max(max_y, py)
            for dx, dy in neighbors:
                nx, ny = px + dx, py + dy
                if 0 <= nx < width and 0 <= ny < height:
                    index = ny * width + nx
                    if not visited[index]:
                        visited[index] = 1
                        queue.append((nx, ny))

        if filled:
            layer.setPixelData(bytes(destination), 0, 0, width, height)
            doc.refreshProjection()
        return {
            "status": "truncated" if queue else "ok",
            "x": x, "y": y, "filled": filled,
            "target_color": "#{:02x}{:02x}{:02x}".format(target_r, target_g, target_b),
            "fill_color": "#{:02x}{:02x}{:02x}{:02x}".format(fill_r, fill_g, fill_b, fill_a),
            "bounds": [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1],
            "tolerance": tolerance, "connectivity": connectivity,
        }

    def cmd_draw_shape(self, params):
        """Draw a shape (rectangle, ellipse, line, polygon).

        Fills go through setPixelData because libkis fillStyle hex strings
        are silently ignored; outlines use the brush engine, where
        strokeStyle=None strokes with the current brush/color.
        """
        shape = params.get("shape", "rectangle")

        doc, layer, err = self._require_layer()
        if err:
            return err
        view = self.get_active_view()
        if not view:
            return {"error": "No active view"}

        self._apply_brush_state(view, size=params.get("size"),
                                opacity=params.get("opacity"), color=params.get("color"))
        color = params.get("color") or "#ffffff"
        fill = params.get("fill", True)
        stroke = params.get("stroke", False)

        if shape in ("rectangle", "ellipse"):
            x = float(params.get("x", 0)); y = float(params.get("y", 0))
            w = float(params.get("width", 100)); h = float(params.get("height", 100))
            rect = QRectF(x, y, w, h)
            if fill:
                if shape == "rectangle":
                    res = self._pixel_fill_rect(doc, layer, x, y, w, h, color)
                else:
                    res = self._pixel_fill_ellipse(doc, layer, x + w / 2.0, y + h / 2.0,
                                                   w / 2.0, h / 2.0, color)
                if "error" in res:
                    return res
            if stroke or not fill:
                if shape == "rectangle":
                    layer.paintRectangle(rect, None, None)
                else:
                    layer.paintEllipse(rect, None, None)
        elif shape == "line":
            x = float(params.get("x", 0)); y = float(params.get("y", 0))
            x2 = float(params.get("x2", x + 100)); y2 = float(params.get("y2", y + 100))
            pressure = float(params.get("pressure", 1.0))
            layer.paintLine(QPoint(int(x), int(y)), QPoint(int(x2), int(y2)),
                            pressure, pressure, color)
        elif shape == "polygon":
            pts = params.get("points")
            if not pts:
                return {"error": "polygon requires points: [[x,y], ...]"}
            qpoints = [QPointF(float(p[0]), float(p[1])) for p in pts]
            layer.paintPolygon(qpoints, None, None)
        else:
            return {"error": f"Unknown shape '{shape}'. Use rectangle, ellipse, line, polygon."}

        doc.refreshProjection()
        return {"status": "ok", "shape": shape}

    def cmd_clear(self, params):
        """Clear the active layer to a solid color."""
        doc, layer, err = self._require_layer()
        if err:
            return err

        bg_color = params.get("color", "#1a1a2e")
        res = self._pixel_fill_rect(doc, layer, 0, 0, doc.width(), doc.height(), bg_color)
        if "error" in res:
            return res
        doc.refreshProjection()
        return {"status": "ok", "color": bg_color}

    def cmd_get_canvas(self, params):
        """Export current canvas to file and return path."""
        doc, err = self._require_document()
        if err:
            return err

        filename = params.get("filename", "canvas.png")
        if not filename.endswith('.png'):
            filename += '.png'
        filepath = os.path.join(CANVAS_OUTPUT_DIR, filename)

        export_err = self._export_document(doc, filepath)
        if export_err:
            return export_err

        result = {"status": "ok", "path": filepath,
                  "bytes": os.path.getsize(filepath),
                  "width": doc.width(), "height": doc.height()}

        # Optional scaled thumbnail for cheap preview
        max_dim = params.get("max_dimension")
        if max_dim:
            try:
                scale = int(max_dim) / max(doc.width(), doc.height())
                thumb = doc.rootNode().thumbnail(
                    max(1, int(doc.width() * scale)), max(1, int(doc.height() * scale)))
                thumb_path = os.path.splitext(filepath)[0] + "_thumb.png"
                if thumb is not None and thumb.save(thumb_path, "PNG"):
                    result["thumbnail"] = thumb_path
            except Exception:
                pass
        return result

    def cmd_save(self, params):
        """Save (flattened export) to a specific path."""
        doc, err = self._require_document()
        if err:
            return err

        filepath = params.get("path")
        if not filepath:
            filepath = os.path.join(CANVAS_OUTPUT_DIR,
                                    f"saved_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        filepath = os.path.expanduser(filepath)

        export_err = self._export_document(doc, filepath)
        if export_err:
            return export_err
        return {"status": "ok", "path": filepath, "bytes": os.path.getsize(filepath)}

    def cmd_save_native(self, params):
        """Save as .kra, preserving layers."""
        doc, err = self._require_document()
        if err:
            return err

        filepath = params.get("path")
        if not filepath:
            filepath = os.path.join(CANVAS_OUTPUT_DIR,
                                    f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}.kra")
        filepath = os.path.expanduser(filepath)
        if not filepath.lower().endswith(".kra"):
            filepath += ".kra"

        doc.setBatchmode(True)
        try:
            ok = doc.saveAs(filepath)
        finally:
            doc.setBatchmode(False)
        if not ok:
            return {"error": f"saveAs failed: {filepath}"}
        return {"status": "ok", "path": filepath, "bytes": os.path.getsize(filepath)}

    def cmd_undo(self, params):
        """Undo last action."""
        action = Krita.instance().action('edit_undo')
        if action:
            if not action.isEnabled():
                return {"status": "ok", "note": "nothing to undo"}
            action.trigger()
            return {"status": "ok"}
        return {"error": "Could not trigger undo"}

    def cmd_redo(self, params):
        """Redo last undone action."""
        action = Krita.instance().action('edit_redo')
        if action:
            if not action.isEnabled():
                return {"status": "ok", "note": "nothing to redo"}
            action.trigger()
            return {"status": "ok"}
        return {"error": "Could not trigger redo"}

    def cmd_get_color_at(self, params):
        """Get color at specific pixel (eyedropper) from the flattened projection."""
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))

        doc, err = self._require_document()
        if err:
            return err

        if not (0 <= x < doc.width() and 0 <= y < doc.height()):
            return {"error": f"({x},{y}) outside canvas {doc.width()}x{doc.height()}"}

        # Projection = all layers flattened (better than single-layer pixelData)
        pixel_data = bytes(doc.rootNode().projectionPixelData(x, y, 1, 1))
        if len(pixel_data) >= 4:
            b, g, r, a = pixel_data[0], pixel_data[1], pixel_data[2], pixel_data[3]
            return {"status": "ok", "color": "#{:02x}{:02x}{:02x}".format(r, g, b),
                    "r": r, "g": g, "b": b, "a": a, "x": x, "y": y}
        return {"error": "Could not read pixel"}

    def cmd_list_brushes(self, params):
        """List available brush presets."""
        filter_str = params.get("filter", "")
        limit = int(params.get("limit", 50))

        presets = Krita.instance().resources("preset")
        brush_list = []
        for name in sorted(presets.keys()):
            if filter_str.lower() in name.lower():
                brush_list.append(name)
                if len(brush_list) >= limit:
                    break
        return {"status": "ok", "brushes": brush_list, "count": len(brush_list),
                "total": len(presets)}

    def cmd_list_layers(self, params):
        """List every layer with visibility/opacity/blending mode."""
        doc, err = self._require_document()
        if err:
            return err
        active = doc.activeNode()
        layers = []
        for child in (doc.rootNode().childNodes() if doc.rootNode() else []) or []:
            layers.append({
                "id": child.uniqueId().toString(),
                "name": child.name(),
                "type": child.type(),
                "visible": child.visible(),
                "opacity": child.opacity(),
                "blending_mode": child.blendingMode(),
                "active": active is not None and child.uniqueId() == active.uniqueId(),
            })
        return {"status": "ok", "layers": layers, "count": len(layers)}

    def cmd_new_layer(self, params):
        """Add a new empty paint layer on top."""
        doc, err = self._require_document()
        if err:
            return err
        name = params.get("name") or f"MCP Layer {datetime.now().strftime('%H%M%S')}"
        node = doc.createNode(name, "paintlayer")
        if not node:
            return {"error": "Could not create paint layer"}

        if params.get("opacity") is not None:
            node.setOpacity(max(0, min(255, int(float(params["opacity"]) * 255))))
        if params.get("blending_mode"):
            node.setBlendingMode(params["blending_mode"])

        root = doc.rootNode()
        children = root.childNodes() or []
        top = children[-1] if children else None
        if not root.addChildNode(node, top):
            return {"error": "Failed to insert layer"}
        doc.setActiveNode(node)
        doc.refreshProjection()
        return {"status": "ok", "name": node.name(), "id": node.uniqueId().toString(), "type": node.type(), "active": True}

    def cmd_select_layer(self, params):
        doc, err = self._require_document()
        if err:
            return err
        def descendants(node):
            for child in node.childNodes():
                yield child
                yield from descendants(child)
        matches = [n for n in descendants(doc.rootNode())
                   if (n.uniqueId().toString() == params["id"] if params.get("id") else n.name() == params.get("name"))]
        if len(matches) != 1:
            return {"error": "Expected one matching layer; use id if names repeat", "matches": len(matches)}
        doc.setActiveNode(matches[0])
        return {"status": "ok", "name": matches[0].name(), "id": matches[0].uniqueId().toString()}

    def cmd_brush_controls(self, params):
        """Set pigment/blending without confusing option enablement with dynamics."""
        settings = self.cmd_brush_settings({})
        if "error" in settings:
            return settings
        changes = control_changes(params.get("controls"), settings["properties"])
        result = self.cmd_configure_brush({"properties": changes})
        if "error" not in result:
            result["controls"] = params["controls"]
            result["readback"] = {k: v for k, v in self.cmd_brush_settings({})["properties"].items() if k in changes}
        return result

    def cmd_brush_probe(self, params):
        """Render a diagnostic stroke in a disposable document, preserving artwork."""
        old_view = self.get_active_view()
        if not old_view:
            return {"error": "No active view"}
        size = number(params.get("size", 80), "size", 1, 180)
        window = Krita.instance().activeWindow()
        resource = old_view.currentBrushPreset()
        state = (self.current_brush_size, self.current_opacity)
        view_state = (old_view.brushSize(), old_view.paintingOpacity(), old_view.paintingFlow(), old_view.brushRotation(), old_view.foregroundColor())
        doc = None
        try:
            doc = Krita.instance().createDocument(640, 256, "MCP brush probe", "RGBA", "U8", self._pick_color_profile(), 120.0)
            view = window.addView(doc)
            window.showView(view)
            layer = doc.createNode("Diagnostic swatch", "paintlayer")
            doc.rootNode().addChildNode(layer, None)
            doc.setActiveNode(layer)
            self._pixel_fill_rect(doc, layer, 0, 0, 320, 256, "#556879")
            self._pixel_fill_rect(doc, layer, 320, 0, 320, 256, "#b59978")
            view.setCurrentBrushPreset(resource)
            view.setBrushRotation(old_view.brushRotation())
            doc.refreshProjection()
            doc.waitForDone()
            before = bytes(layer.pixelData(0, 0, 640, 256))
            result = self.cmd_stroke({"points": [[70,128,.9],[570,128,.9]], "size": size, "opacity": 1, "flow": 1, "color": "#ed9e53"})
            if "error" in result:
                return result
            doc.waitForDone()
            after = bytes(layer.pixelData(0, 0, 640, 256))
            changed = sum(before[i:i+4] != after[i:i+4] for i in range(0,len(before),4))
            path = os.path.join(CANVAS_OUTPUT_DIR, "brush_probe_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png")
            error = self._export_document(doc, path)
            if error:
                return error
            return {"status": "ok", "preset": resource.name(), "mark_detected": changed > 0,
                    "changed_pixels": changed, "canvas_path": path,
                    "scope": "one stroke over a two-color ground; detects both painting and blending"}
        finally:
            if doc is not None:
                doc.setModified(False)
                doc.close()
            window.showView(old_view)
            old_view.setBrushSize(view_state[0])
            old_view.setPaintingOpacity(view_state[1])
            old_view.setPaintingFlow(view_state[2])
            old_view.setBrushRotation(view_state[3])
            old_view.setForeGroundColor(view_state[4])
            self.current_brush_size, self.current_opacity = state

    def cmd_brush_settings(self, params):
        view = self.get_active_view()
        if not view or not view.currentBrushPreset():
            return {"error": "No active brush"}
        xml = Preset(view.currentBrushPreset()).toXML()
        root = ET.fromstring(xml)
        props = {e.get("name"): e.text or "" for e in root.iter("param")}
        out = {"status": "ok", "preset": view.currentBrushPreset().name(),
               "properties": {k: (v if len(v) <= 2048 or params.get("include_data") else {"embedded_characters": len(v)}) for k, v in props.items()},
               "rotation": view.brushRotation(), "flow": view.paintingFlow()}
        if params.get("include_xml"):
            out["xml"] = xml
        return out

    def cmd_configure_brush(self, params):
        """Change existing preset properties in memory; keep original XML for restore."""
        view = self.get_active_view()
        if not view or not view.currentBrushPreset():
            return {"error": "No active brush"}
        changes = params.get("properties")
        if not isinstance(changes, dict) or not changes:
            return {"error": "properties must be a nonempty object; inspect brush_settings first"}
        resource = view.currentBrushPreset()
        preset = Preset(resource)
        original = preset.toXML()
        root = ET.fromstring(original)
        props = {e.get("name"): e for e in root.iter("param")}
        unknown = sorted(set(changes) - set(props))
        if unknown:
            return {"error": "Unknown preset properties; inspect brush_settings. If disabling texture removed its settings, call restore_brush first.", "unknown": unknown}
        for key, value in changes.items():
            if not isinstance(value, (str, int, float, bool)):
                return {"error": "Property values must be scalar", "property": key}
            props[key].text = str(value).lower() if isinstance(value, bool) else str(value)
        if not hasattr(self, "_preset_originals"):
            self._preset_originals = {}
        self._preset_originals.setdefault(resource.name(), original)
        preset.fromXML(ET.tostring(root, encoding="unicode"))
        view.setCurrentBrushPreset(resource)
        return {"status": "ok", "preset": resource.name(), "changed": list(changes), "persistence": "in_memory", "restore": "restore_brush"}

    def cmd_set_brush_texture(self, params):
        """Embed a local texture image into a preset that already supports texture."""
        path = os.path.abspath(os.path.expanduser(params.get("path", "")))
        if not os.path.isfile(path):
            return {"error": "Texture file does not exist"}
        patterns = Krita.instance().resources("pattern")
        matches = [r for r in patterns.values() if os.path.basename(r.filename()) == os.path.basename(path)]
        if len(matches) != 1:
            return {"error": "Import this file as Patterns in Settings > Manage Resources first", "path": path, "matches": len(matches)}
        image = QImage(path)
        if image.isNull() or max(image.width(), image.height()) > 4096:
            return {"error": "Texture must be a readable image no larger than 4096 pixels per side"}
        if matches[0].image().convertToFormat(QImage.Format.Format_ARGB32) != image.convertToFormat(QImage.Format.Format_ARGB32):
            return {"error": "Imported pattern differs from this file; import it with a unique filename", "path": path}
        scale = number(params.get("scale", 1), "scale", .01, 10)
        strength = number(params.get("strength", 1), "strength", 0, 1)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return {"error": "Could not encode texture"}
        buffer.close()
        raw = bytes(data)
        # Krita stores a base64 PNG in a QByteArray; XML serializes that as base64 again.
        def xml_bytes(value):
            return base64.b64encode(base64.b64encode(value)).decode("ascii")
        changes = {"Texture/Pattern/Pattern": xml_bytes(raw),
                   "Texture/Pattern/PatternMD5": xml_bytes(hashlib.md5(raw).digest()),
                   "Texture/Pattern/PatternFileName": path,
                   "Texture/Pattern/Name": os.path.basename(path),
                   "Texture/Pattern/Enabled": True,
                   "Texture/Pattern/Scale": scale,
                   "Texture/Strength/Value": strength}
        result = self.cmd_configure_brush({"properties": changes})
        if "error" not in result:
            result.update({"texture": path, "width": image.width(), "height": image.height()})
        return result

    def cmd_restore_brush(self, params):
        view = self.get_active_view()
        if not view or not view.currentBrushPreset():
            return {"error": "No active brush"}
        resource = view.currentBrushPreset()
        original = getattr(self, "_preset_originals", {}).get(resource.name())
        if original is None:
            return {"error": "No saved settings for this brush in this session"}
        Preset(resource).fromXML(original)
        view.setCurrentBrushPreset(resource)
        del self._preset_originals[resource.name()]
        return {"status": "ok", "preset": resource.name()}

    def cmd_canvas_info(self, params):
        """Report the active document's dimensions and color setup."""
        doc, err = self._require_document()
        if err:
            return err
        view = self.get_active_view()
        out = {
            "status": "ok",
            "name": doc.name(),
            "width": doc.width(),
            "height": doc.height(),
            "resolution": doc.resolution(),
            "color_model": doc.colorModel(),
            "color_depth": doc.colorDepth(),
            "color_profile": doc.colorProfile(),
            "modified": doc.modified(),
        }
        if view is not None:
            try:
                out["brush_size"] = view.brushSize()
            except Exception:
                pass
        return out

    def cmd_test_pixel(self, params):
        """Diagnostic: write a small solid rect via the pixel path and read it back.
        Use this to validate setPixelData without painting the whole canvas.
        """
        doc, layer, err = self._require_layer()
        if err:
            return err
        x = int(params.get("x", 100))
        y = int(params.get("y", 100))
        size = int(params.get("size", 64))
        color = params.get("color", "#ff00ff")
        # Write
        res = self._pixel_fill_rect(doc, layer, x, y, size, size, color)
        if "error" in res:
            return res
        # Read back a point in the middle
        cx, cy = x + size // 2, y + size // 2
        read = self.cmd_get_color_at({"x": cx, "y": cy})
        doc.refreshProjection()
        return {
            "status": "ok",
            "wrote": color,
            "at": (x, y, size, size),
            "read": read.get("color"),
            "match": read.get("color", "").lower() == color.lower() or read.get("color", "").lower() == "#" + color.lower().lstrip("#"),
            "readback": read,
        }

    def cmd_batch(self, params):
        """Run a list of sub-commands in ONE HTTP request on the main thread.
        Each sub-command: {"action": name, "params": {...}}. This is far faster
        than N HTTP round-trips. Each paint command still refreshes its projection.
        """
        commands = params.get("commands") or []
        if not isinstance(commands, list):
            return {"error": "commands must be a list"}
        handlers = {
            "set_color": self.cmd_set_color,
            "set_brush": self.cmd_set_brush,
            "stroke": self.cmd_stroke,
            "fill": self.cmd_fill,
            "draw_shape": self.cmd_draw_shape,
            "new_layer": self.cmd_new_layer,
            "clear": self.cmd_clear,
            "paint_pixels": self.cmd_paint_pixels,
                "select_layer": self.cmd_select_layer,
                "brush_settings": self.cmd_brush_settings,
                "selection": self.cmd_selection,
                "layer_settings": self.cmd_layer_settings,
                "duplicate_layer": self.cmd_duplicate_layer,
                "move_layer": self.cmd_move_layer,
                "modify_selection": self.cmd_modify_selection,
                "curve_stroke": self.cmd_curve_stroke,
                "compare_region": self.cmd_compare_region,
                "duplicate_document": self.cmd_duplicate_document,
                "brush_controls": self.cmd_brush_controls,
                "brush_probe": self.cmd_brush_probe,
                "configure_brush": self.cmd_configure_brush,
                "restore_brush": self.cmd_restore_brush,
                "set_brush_texture": self.cmd_set_brush_texture,
        }
        errors = 0
        failures = []
        results = []

        def record(i, action, res=None, error=None):
            nonlocal errors
            if error is None and isinstance(res, dict):
                if res.get("error"):
                    error = res["error"]
                elif res.get("status") not in (None, "ok"):
                    error = f"status {res.get('status')}"
            if error is not None:
                errors += 1
                failures.append({"index": i, "action": action, "error": error})
            brief = ({k: v for k, v in res.items() if k != "brushes"}
                     if isinstance(res, dict) else res)
            results.append({"index": i, "action": action, "ok": error is None,
                            "result": brief if res is not None else {"error": error}})

        for i, c in enumerate(commands):
            if not isinstance(c, dict):
                record(i, None, error="Command must be an object")
                continue
            action = c.get("action")
            p = c.get("params") or {}
            h = handlers.get(action)
            if h is None:
                record(i, action, error="Unsupported batch action")
                continue
            try:
                record(i, action, h(p))
            except Exception as e:
                record(i, action, error=str(e))
        # Final projection refresh after the per-command refreshes.
        doc = self.get_active_document()
        if doc:
            try:
                doc.refreshProjection()
            except Exception:
                pass
        return {"status": "ok" if errors == 0 else "partial", "count": len(commands), "errors": errors, "failures": failures[:20],
                "results": results}

    def cmd_paint_pixels(self, params):
        """Paint many solid cells at once via setPixelData (fast, faithful color field).
        params: {"cells": [[x, y, w, h, "#hex"], ...]} OR {"rect": [x,y,w,h,"#hex"]}.
        Applies all cells in one pass, then a single refreshProjection.
        """
        doc, node, err = self._require_layer()
        if err:
            return err
        if not self._pixel_ok(doc):
            return {"error": "paint_pixels needs an RGBA/U8 document"}
        cells = params.get("cells")
        if cells is None and params.get("rect"):
            cells = [params["rect"]]
        if not isinstance(cells, list) or not cells:
            return {"error": "cells required: [[x,y,w,h,color], ...] or rect"}
        ok = True
        painted = 0
        for c in cells:
            if not isinstance(c, (list, tuple)) or len(c) < 5:
                continue
            x, y, w, h, hex_color = c[0], c[1], c[2], c[3], c[4]
            rgb = self._hex_rgb(hex_color)
            if rgb is None:
                ok = False
                continue
            r, g, b = rgb
            xx, yy = int(x), int(y)
            ww, hh = int(w), int(h)
            if ww <= 0 or hh <= 0:
                continue
            row = bytes((b, g, r, 255)) * ww  # BGRA for RGBA/U8
            data = row * hh
            try:
                res = node.setPixelData(data, xx, yy, ww, hh)
            except Exception:
                res = False
            if not res:
                ok = False
            else:
                painted += 1
        doc.refreshProjection()
        return {"status": "ok" if ok else "partial", "painted": painted, "total": len(cells)}

    def cmd_reload(self, params):
        """Load an installed build without restarting Krita (see dev_reload.py)."""
        import importlib
        from . import dev_reload
        importlib.reload(dev_reload)
        return dev_reload.reload(self, companion=params.get('companion', True) is not False)


from .crash_diagnostics import install as install_crash_diagnostics
install_crash_diagnostics()

# Register the extension
Krita.instance().addExtension(KritaMCPExtension(Krita.instance()))

from .creative_docker import register_creative_docker
register_creative_docker()
