"""Structured MCP transport for the creative commands in the existing Krita bridge."""
import os
from urllib.parse import urlparse
import httpx
from fastmcp import FastMCP
from diagnostics_client import register_diagnostic_tools

mcp = FastMCP('krita-creative-agent')
register_diagnostic_tools(mcp)
URL = os.environ.get('KRITA_URL', 'http://127.0.0.1:5678')
parsed = urlparse(URL)
if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
    raise RuntimeError('The Krita bridge must be local to this Mac.')


@mcp.tool()
def creative_call(request: dict) -> dict:
    """Execute one structured creative request. The Krita main thread validates it."""
    token = os.environ.get('KRITA_MCP_TOKEN', '')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        response = httpx.post(URL, json={'action': 'creative', 'params': request, 'timeout': 120},
                              headers=headers, timeout=130, trust_env=False)
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('Invalid bridge response')
        if 'Timeout waiting for command' in result.get('error', ''):
            result['error_code'] = 'outcome_unknown'
        return result
    except httpx.TimeoutException:
        return {'error': 'The bridge response timed out. The operation may have completed. '
                'Observe the study before continuing; do not repeat the painting request.',
                'error_code': 'outcome_unknown'}
    except httpx.ConnectError:
        return {'error': 'Open Krita and enable the Krita MCP Bridge.', 'error_code': 'unavailable'}


if __name__ == '__main__':
    mcp.run(show_banner=False)
