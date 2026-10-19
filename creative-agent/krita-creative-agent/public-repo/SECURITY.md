# Security

Please report vulnerabilities privately through GitHub's **Report a vulnerability** (Security tab), not as public issues. Include steps to reproduce, and say whether API keys or local files could be exposed.

Scope that matters most:
- the Krita bridge listens on `127.0.0.1:5678` only; anything that exposes it beyond localhost or bypasses its operation validation;
- leaking API keys into traces, logs, diagnostics or artwork;
- writing outside the paintings folder, or overwriting an original artwork file.
