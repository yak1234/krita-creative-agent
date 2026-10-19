"""The bridge's port, so stock Krita and a Krita with its own settings folder (the Qt6 fork) can run at once.

The installer writes `bridge_url` into the plugin's creative-agent-config.json, which lives in the running app's own
pykrita folder; the companion, server.py and the test driver follow the same file. Without a usable config, stock
Krita (an empty organization name) keeps 5678, and an app with its own settings folder takes 5679. Canvas exports
follow the same rule (output_dir).
"""
import json
import os
from urllib.parse import urlparse

STOCK_PORT = 5678
OWN_SETTINGS_PORT = 5679


def bridge_port(config_path, organization=''):
    """The port named by `config_path`'s bridge_url, else the default for an app with this organization name."""
    try:
        with open(config_path) as stream:
            port = urlparse(json.load(stream)['bridge_url']).port
        if port:
            return port
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return OWN_SETTINGS_PORT if organization else STOCK_PORT


def output_dir(environ, organization=''):
    """Where canvas exports go (KRITA_MCP_OUTPUT, else ~/krita-mcp-output): in a subfolder named for an app with its own
    settings folder, so the fork never overwrites stock Krita's canvas.png while both run."""
    base = os.path.expanduser(environ.get('KRITA_MCP_OUTPUT', '~/krita-mcp-output'))
    return os.path.join(base, organization) if organization else base
