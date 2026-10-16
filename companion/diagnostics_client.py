"""MCP access to the existing companion's local diagnostic socket."""
import json
import os
from pathlib import Path
import httpx


def state_directory(value=""):
    if value:
        return Path(value).expanduser().resolve()
    config = os.environ.get("KRITA_CREATIVE_CONFIG")
    candidates = [Path(config)] if config else [
        Path.home() / "Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json",
        Path(__file__).parent / ".local-config.json",
    ]
    for path in candidates:
        if path.is_file():
            return Path(json.loads(path.read_text())["output"]).expanduser().resolve()
    raise ValueError("Supply state_directory: the project's .creative-agent folder.")


def diagnostic_request(route, state_directory_path="", method="GET", params=None):
    directory = None
    try:
        directory = state_directory(state_directory_path)
        endpoint = json.loads((directory / "diagnostics-endpoint.json").read_text())
        transport = httpx.HTTPTransport(uds=endpoint["socket"])
        with httpx.Client(transport=transport, timeout=30, trust_env=False) as client:
            response = client.request(method, "http://localhost" + route, params=params)
            response.raise_for_status()
            return response.json()
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        result = {"error_code": "diagnostics_unavailable", "live": False,
                  "error": "Cannot reach the live companion diagnostics. Open the updated Creative Agent panel, or supply its project's .creative-agent directory."}
        if directory:
            report = directory / "diagnostics/latest.json"
            if report.is_file():
                result["previous_report"] = str(report)
                result["previous_report_is_live"] = False
            log = directory / "diagnostic-events.jsonl"
            if log.is_file():
                result["persisted_timeline"] = str(log)
        return result


def register_diagnostic_tools(mcp):
    @mcp.tool()
    def creative_inspect_state(state_directory: str = "") -> dict:
        """Inspect the running companion: builds, document, stage, pending work and errors.

        Optional state_directory selects the project's .creative-agent folder.
        Reads live memory without starting a model request or changing artwork.
        Panel and bridge metadata are the last reported snapshots, with freshness labels.
        """
        return diagnostic_request("/state", state_directory)

    @mcp.tool()
    def creative_recent_events(state_directory: str = "", after: int = 0, limit: int = 100) -> dict:
        """Read timestamped model/tool/native/save/review events from the live companion.

        Pass the last received sequence as after; reset after to zero when instance changes.
        limit is 1–500. Native request IDs pair dispatch/results; tool IDs link model tools.
        A save receipt may refer to an existing checkpoint; it is not proof of a new save.
        """
        if after < 0 or not 1 <= limit <= 500:
            return {"error_code": "invalid_arguments", "error": "after must be nonnegative; limit must be 1–500"}
        return diagnostic_request("/events", state_directory, params={"after": after, "limit": limit})

    @mcp.tool()
    def creative_collect_report(state_directory: str = "") -> dict:
        """Collect a local troubleshooting report and return its file path.

        Includes live state, event timeline, saved conversation, native operation records
        and Python errors. Redacts credentials and omits image bytes and artwork.
        No upload, painting, model request, restart, or replay. May capture ongoing work.
        If the companion is unavailable, returns available previous evidence paths as stale.
        """
        return diagnostic_request("/report", state_directory, method="POST")
