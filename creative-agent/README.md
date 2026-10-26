# Toska's agent

This folder holds everything in Toska that is not Krita itself, from the plugin inside the app to the companion that runs the
agents.

| Folder | What it is |
|---|---|
| `krita-mcp/` | The Python plugin inside Toska (`krita-plugin/kritamcp`, with the agent panel and its painting tools) and an MCP server for development (`server.py`) |
| `krita-creative-agent/` | The companion: the agents on Agent Pi, decision models, tracing, effects, and their tests |
| `krita-native/` | A native helper for stock Krita 5.3.3, kept for the plugin-only branch (Toska has these abilities built in) |
| `docs/` | Branding and the example painting |
| `openspec/` | Designs and task lists for each change (finished ones in `openspec/changes/archive/`) |

The plugin and the companion find each other as siblings, so keep them side by side.

## Tests

`agent/ci.sh` at the root of the repository runs everything. To run one part:

```sh
cd krita-creative-agent
npm run test:unit                      # the companion's tests
npx tsc --noEmit -p .                  # its typecheck
uv run --with pyqt5 --with pillow --with numpy --with httpx --with opencv-python-headless \
    python -m unittest discover -s tests -p 'test_*.py'   # the plugin's tests
```
