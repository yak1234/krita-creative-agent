# Toska's plugin and MCP server

The Python plugin that runs inside Toska (the agent panel, the painting tools and a local bridge), and an MCP server
([Model Context Protocol](https://modelcontextprotocol.io/)) that lets a coding agent such as Claude Code drive Toska for
development and testing. Painting in Toska doesn't need the MCP server.

## How It Works

Two components:

1. **Krita Plugin** (`krita-plugin/`) — A Python plugin that runs inside Krita, exposing an HTTP server on `localhost:5679` in Toska (`5678` in stock Krita). It receives paint commands and executes them on Krita's main thread via a command queue.

2. **MCP Server** (`server.py`) — A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes painting tools to any MCP client. It translates MCP tool calls into HTTP requests to the Krita plugin.

```
MCP Client (Claude, etc.)  ←→  MCP Server (server.py)  ←→  Krita Plugin (HTTP on :5679)  ←→  Krita
```

## Setup

### 1. Install the Krita Plugin

Copy the plugin files to your Krita plugins directory:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\krita\pykrita\` |
| Linux | `~/.local/share/krita/pykrita/` |
| macOS | `~/Library/Application Support/krita/pykrita/` |

Copy both:
- `krita-plugin/kritamcp/` (the folder with `__init__.py`)
- `krita-plugin/kritamcp.desktop`

Then in Krita: **Settings → Configure Krita → Python Plugin Manager → Enable "Krita MCP Bridge"** and restart Krita.

### 2. Install the MCP Server

```bash
pip install fastmcp httpx
```

Or with a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Configure Your MCP Client

Add to your MCP client config (e.g., Claude Desktop's `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "krita": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

If using a virtual environment:
```json
{
  "mcpServers": {
    "krita": {
      "command": "/path/to/.venv/Scripts/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `krita_health` | Check if Krita is running with the plugin active |
| `krita_new_canvas` | Create a new canvas (width, height, background color) |
| `krita_set_color` | Set foreground paint color (hex) |
| `krita_set_brush` | Set brush preset, size, and opacity |
| `krita_stroke` | Paint a stroke through a list of [x, y] points |
| `krita_fill` | Fill a circular area at a point |
| `krita_draw_shape` | Draw rectangle, ellipse, or line |
| `krita_get_canvas` | Export canvas to PNG (for AI to see progress) |
| `krita_save` | Save canvas to a specific file path |
| `krita_undo` / `krita_redo` | Undo/redo actions |
| `krita_clear` | Clear canvas to a solid color |
| `krita_get_color_at` | Eyedropper — sample color at a pixel |
| `krita_list_brushes` | List available brush presets |
| `krita_open_file` | Open an existing .kra, .png, .jpg, etc. |
| `krita_flood_fill` | Contiguous flood fill from a seed pixel |
| `krita_paint_pixels` / `krita_paint_grid` | Paint many solid cells in one call |
| `krita_batch` | Run many commands in order with few round trips (see below) |

## Timeouts and Unknown Outcomes

The plugin executes one command at a time on Krita's main thread, so a slow
command (export, save, a long stroke) delays everything queued behind it.

- `server.py` sends each command's queue timeout in the request body and waits
  20 s longer on HTTP, so the plugin always answers first. Defaults: 120 s;
  300 s for `open_file`, `new_canvas`, `get_canvas`, `save`, `save_native` and
  `flood_fill`.
- When a command times out before Krita starts it, the plugin drops it from the
  queue, so it never paints late. A command already running cannot be
  interrupted; its late result is discarded.
- If a command that changes the artwork times out or its reply is lost, the tool
  reports an **unknown outcome**. Inspect the canvas before repeating it,
  otherwise the marks may be painted twice.

## Batching

`krita_batch` sends consecutive paint, layer and brush commands to the plugin's
native `batch` action in chunks of up to 64 commands, and sends other commands
(`undo`, `get_color_at`, `flood_fill`, `save_native`, ...) individually, keeping
input order. It returns one line per command (`ok`, `FAILED` or
`UNKNOWN-OUTCOME`) plus a summary. `partial` results count as failures, and
diagnostic readback (image paths, layer lists, brush settings) is not truncated.

## Configuration

| Setting | Default | How to Change |
|---------|---------|---------------|
| Plugin HTTP port | `5679` in Toska, `5678` in stock Krita | Chosen by the app (`bridge_config.py` server_port) |
| MCP server URL | `http://localhost:5679` in Toska | Set `KRITA_URL` env var |
| Shared token | none | Set the same `KRITA_MCP_TOKEN` for Krita and the MCP server |
| Canvas output dir | `~/krita-mcp-output` | Edit `CANVAS_OUTPUT_DIR` in plugin `__init__.py` |

## Painting Approach

Strokes use Krita's native brush engine (`Node.paint*`) with the active preset,
pressure, flow and rotation. Some fills (`clear`, `paint_pixels`, flood fill,
filled shapes) write pixels directly for speed and exact colour.

## License

GPL-3.0-or-later (see [LICENSE](LICENSE)). Krita's extension API is GPL, so a distributed Krita plugin is too.
This project was MIT until 19 October 2026; that notice is kept in [LICENSE.MIT-original](LICENSE.MIT-original) for any code
that came from elsewhere.
