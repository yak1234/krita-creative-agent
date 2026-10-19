# Krita MCP server

Lets Claude, or any [Model Context Protocol](https://modelcontextprotocol.io/) client, paint in a running Krita through the bridge plugin in `../plugin`.

```
MCP client ──stdio──▶ server.py (FastMCP) ──HTTP 127.0.0.1:5678──▶ Krita bridge plugin ──▶ Krita main thread
```

## Run

1. Install the plugin: copy `plugin/kritamcp` and `plugin/kritamcp.desktop` into Krita's `pykrita` folder, or use the release installer. Then enable **Krita MCP Bridge** in the Python Plugin Manager and restart Krita.
2. Add the server to your MCP client, for example in Claude Code:
   ```sh
   claude mcp add krita -- uv run --with fastmcp --with httpx python /path/to/krita-creative-agent/mcp-server/server.py
   ```

## Tools

- **Canvas:** `krita_new_canvas`, `krita_open_file`, `krita_save`, `krita_get_canvas`, `krita_clear`, `krita_undo`, `krita_redo`.
- **Painting:** `krita_set_color`, `krita_set_brush`, `krita_list_brushes`, `krita_stroke`, `krita_draw_shape`, `krita_fill`, `krita_flood_fill`, `krita_paint_pixels`, `krita_paint_grid`, `krita_get_color_at`.
- **Batching:** `krita_batch` runs up to about 150 commands in one request.
- **Diagnostics** (read-only, for the Creative Agent): `creative_inspect_state`, `creative_recent_events`, `creative_collect_report`.
- `krita_health`.

## Test

```sh
uv run --with pytest --with httpx --with fastmcp pytest -q tests
```
