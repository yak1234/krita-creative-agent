# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who the bridge answers (the public-download review, 2026-10-25). The bridge listens on 127.0.0.1, so no other computer
reaches it, but a web page open in the artist's browser can: its commands include saving to any path. Browsers mark
their requests (Origin, Sec-Fetch-Site); the artist's own programs (the companion, the MCP server, the test driver,
scripts) send neither and address the bridge as 127.0.0.1, localhost or [::1]. No Krita imports: tested on its own."""

LOCAL_NAMES = ('127.0.0.1', 'localhost', '[::1]')


def refusal(headers, port):
    """Why a request is refused, or None to answer it. `headers` is any mapping with .get (http.server's message)."""
    if headers.get('Origin') is not None:
        return 'refused: a request from a browser page (the bridge answers only programs on this computer)'
    site = headers.get('Sec-Fetch-Site')
    if site is not None and site.lower() != 'none':
        return 'refused: a request from a browser page (the bridge answers only programs on this computer)'
    host = headers.get('Host')
    # A Host naming anything but this bridge's local address (DNS rebinding: a site's name pointed at 127.0.0.1).
    if host is not None and host.strip().lower() not in {f'{name}:{port}' for name in LOCAL_NAMES}:
        return f'refused: addressed to {host!r}, not this computer\'s bridge address (127.0.0.1:{port})'
    return None
