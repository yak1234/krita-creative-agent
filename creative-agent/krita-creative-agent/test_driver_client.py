"""MCP tools that drive test chats in a separate test companion, for testing and refining Agent mode.

A test chat runs in its own companion process with its own data folder (scripts/test-driver.ts, started on demand),
so it never appears in the artist's chat list. Development only: registered by server.py, not the artist server.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx

SCRIPT = Path(__file__).parent / 'scripts' / 'test-driver.ts'
PANEL_CONFIG = Path.home() / 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json'


def panel_config():
    """The installed panel's config: stock Krita's, or another Krita's (the fork's) when KRITA_CREATIVE_CONFIG names it."""
    return Path(os.environ.get('KRITA_CREATIVE_CONFIG') or PANEL_CONFIG)


def _endpoint_path():
    override = os.environ.get('TEST_DRIVER_ENDPOINT')
    if override:
        return Path(override)
    config = json.loads(panel_config().read_text())
    port = urlparse(config.get('bridge_url') or '').port
    # A Krita on another port (the fork) has its own driver, so a stock driver already running is never reused for it.
    name = 'test-driver.json' if port in (None, 5678) else 'test-driver-%d.json' % port
    return Path(config['project_root']) / 'benchmark-runs' / name


def _driver_environment(endpoint):
    return {**os.environ, 'KRITA_CREATIVE_CONFIG': str(panel_config()), 'TEST_DRIVER_ENDPOINT': str(endpoint)}


def _request(method, route, body=None, params=None, timeout=75):
    endpoint = json.loads(_endpoint_path().read_text())
    transport = httpx.HTTPTransport(uds=endpoint['socket'])
    with httpx.Client(transport=transport, timeout=timeout, trust_env=False) as client:
        response = client.request(method, 'http://localhost' + route, json=body, params=params)
        return response.json()


def _alive():
    try:
        _request('GET', '/state', timeout=5)       # answers (409 when no chat) while the driver runs
        return True
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        return False


def _ensure_driver():
    """Start the test driver when it is not running; it stays up between calls, one test chat at a time."""
    if _alive():
        return None
    path = _endpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path.with_suffix('.log'), 'a')
    subprocess.Popen(['node', str(SCRIPT)], cwd=SCRIPT.parent.parent, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, env=_driver_environment(path))
    for _ in range(100):
        time.sleep(0.2)
        if _alive():
            return None
    return {'error': 'The test driver did not start; see ' + str(path.with_suffix('.log'))}


def _call(method, route, body=None, params=None, timeout=75):
    failed = _ensure_driver()
    if failed:
        return failed
    try:
        return _request(method, route, body, params, timeout=timeout)
    except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
        return {'error': 'The test driver did not answer: ' + str(error)}


def register_test_tools(mcp):
    @mcp.tool()
    def creative_test_start(prompt: str, painting: str = "", width: int = 0, height: int = 0,
                            provider: str = "", model: str = "", loop_guards: bool = True, luna: str = "",
                            folder: str = "", references: list[str] | None = None) -> dict:
        """Start a test chat in Agent mode in a separate test companion (never in the artist's chat list).

        painting: a .kra path relative to the project folder; a COPY is opened in Krita (the result says so) and is
        closed unsaved and deleted by creative_test_end. Without it the test chat makes a new painting
        (width x height). Krita must be idle with no artist chat painting. Returns at once; poll creative_test_state.
        luna: 'off', 'evaluate' or 'guide' for this test chat only (default: the artist's Luna setting).
        folder: a project folder (absolute path), or 'test-assets:<name>' for a fixture from creative_test_assets. It
        is COPIED into the test chat's own folder and opened there as the panel's Open project folder does, so the
        test chat (and its PLAN.md) only ever sees the copy; the copy is deleted by creative_test_end.
        references: up to four absolute image paths, copied the same way and attached as the panel attaches them.
        """
        body = {'prompt': prompt, 'loopGuards': loop_guards}
        if painting: body['painting'] = painting
        if folder: body['folder'] = folder
        if references: body['references'] = list(references)
        if width: body['width'] = width
        if height: body['height'] = height
        if provider: body['provider'] = provider
        if model: body['model'] = model
        if luna: body['luna'] = luna
        return _call('POST', '/start', body, timeout=900)             # copying and opening a large painting takes minutes

    @mcp.tool()
    def creative_test_prompt(text: str) -> dict:
        """Send the test chat a message, as the artist would type it in the panel (a correction or a next request)."""
        return _call('POST', '/prompt', {'text': text})

    @mcp.tool()
    def creative_test_move(action: str) -> dict:
        """Keep or undo the test chat's latest move (action: keep | undo), as the panel's buttons do; both start the next move."""
        return _call('POST', '/move', {'action': action})

    @mcp.tool()
    def creative_test_state(wait_seconds: int = 0) -> dict:
        """The test chat's state: moves, busy, the latest canvas image path (read it to see the painting), the painter's
        tool calls with their Krita methods, a pending question (with its options; select_area for a Paint only here
        card) and close-up question, the plan and its plan_steps (keys for creative_test_command), the Now card,
        the Paint only here area, the latest found_areas (Find it), the project folder copy and errors.
        wait_seconds (0-55) waits for the current move to finish first; poll again for longer moves."""
        return _call('GET', '/state', params={'wait': wait_seconds})

    @mcp.tool()
    def creative_test_protect(name: str) -> dict:
        """Keep the test painter's proposed protected area `name` (e.g. "Moon"), as the artist's panel click would.
        Only on the test chat's painting copy; the plugin refuses on any other document."""
        return _call('POST', '/protect', {'name': name})

    @mcp.tool()
    def creative_test_command(type: str, params: dict | None = None) -> dict:
        """Send the test chat a panel command, as the panel's buttons do (test chat only; anything else is refused):
        start_plan {} (Start painting); plan_step {action: skip|restore|good_enough|met|redo, step_key, text?};
        find_it {part} (Find it for me; the outline appears in found_areas, with request_id); paint_only_here
        {action: clear} or {action: set, found?: request_id (default the latest), name?} or {action: set, mask_path,
        bounds, canvas, name?} with a mask inside the test chat's folder; answer {text, question_id?, area?: proposal
        | found} (a question card: 'Use this' with area proposal, 'Paint everywhere', or typed); closeup_answer
        {answer}; folder_guess {name, guess}; set_mode {mode}; stop {}. An area is protected in Krita only on the test
        chat's own document (the result says so)."""
        return _call('POST', '/command', {'type': type, 'params': params or {}})

    @mcp.tool()
    def creative_test_assets(action: str, source: str = "", name: str = "") -> dict:
        """The test driver's own test assets (benchmark-runs/test-assets, never the artist's folders).
        action 'prepare' copies `source` (default: new_moscow/moscow-painting-assets) once, read only: its images and
        generation-prompts.json, no PLAN.md, its backups or NOTES.md (a fresh plan); then creative_test_start(folder=
        'test-assets:<name>') works on a fresh copy of it per test chat. 'list' shows them; 'remove' deletes `name`."""
        body = {'action': action}
        if source: body['source'] = source
        if name: body['name'] = name
        return _call('POST', '/assets', body, timeout=300)

    @mcp.tool()
    def creative_test_end() -> dict:
        """End the test chat: stop its companion, close the painting copy unsaved and delete it, and delete the project
        folder and reference copies (the result says what it closed)."""
        return _call('POST', '/end', timeout=360)
