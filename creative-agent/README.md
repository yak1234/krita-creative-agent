# Krita Creative Agent (development tree)

| Folder | What it is |
|---|---|
| `krita-mcp/` | Krita Python plugin (`krita-plugin/kritamcp`: panel, native painting tools, HTTP bridge) and the FastMCP server (`server.py`) |
| `krita-creative-agent/` | Node companion: Pi agent runtime, modes, decision models, Langfuse tracing, release and install scripts |
| `openspec/` | Specs and change history |

The two packages find each other as siblings, so keep them side by side. Nothing depends on where this checkout lives.

Your artwork folder (with `.env` and `.creative-agent/`) is separate from this checkout. Scripts use `KRITA_PROJECT_DIR`, or else the folder the installed plugin was set up for.

## Tests

```sh
cd krita-creative-agent
node --test tests/*.test.mjs
uv run --with pyqt5 --with pillow --with numpy --with httpx python -m unittest discover -s tests -p 'test_*.py'
QT_QPA_PLATFORM=offscreen uv run --with pyqt5 python tests/ui_smoke.py
cd ../krita-mcp && uv run --with pytest --with fastmcp --with httpx python -m pytest -q tests
```

## Release and public repo

- `python3 krita-creative-agent/scripts/build-release.py` builds the bundle; `scripts/install-release.mjs` installs it into Krita.
- Publishing to the public repository is `agent/publish.sh` (see the root README).
