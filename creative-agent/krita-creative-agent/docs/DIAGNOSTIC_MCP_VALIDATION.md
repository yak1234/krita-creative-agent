# Diagnostic MCP validation — 2026-09-13

Added three tools to the existing MCP transports: inspect live state, read recent events, and collect a local report. The companion hosts a private Unix socket to inspect its existing runtime. Diagnostic requests never dispatch native painting or model calls. Native operations and passes are now included in exported evidence.

Validated:

- Full Node suite: 91 passed, including live Unix-socket state inspection, pending native work, request/result correlation, unknown-outcome handling without replay, bounded timeline eviction, concurrent report requests, journal inclusion, redaction, socket permissions and cleanup.
- Python MCP client integration: passed against a running Node diagnostic fixture, including all three registered tool functions and non-live evidence after the fixture shuts down.
- FastMCP in-process discovery: all three new tools plus existing `creative_call` registered.
- Qt smoke test: passed context receipts, streaming, plan and layout checks after adding panel build telemetry.
- Python compilation: client, MCP servers and panel passed.
- macOS arm64 release built with staged SDK import validation. Build ID: `991f61add409f1aca991798b3881664c872be479686261faf84473154d9b560b`.
- Installed through the verified release installer. Previous plugin backup: `~/Library/Application Support/krita/.creative-agent-backups/20260914T035440.666993Z`. No restart or painting was performed.

The socket integration used a controlled runtime fixture, not the artist's running painting. The running Krita process still has the preceding build loaded. Restart is required for live-Krita acceptance; this work does not establish that the new diagnostics have been exercised inside that process. MCP clients also need to reconnect to discover added tools.

The report is a snapshot taken while painting can continue. UI/bridge metadata records the last handshake time. The recent event ring holds 500 entries; current and previous disk journals are retained. Native checkpoint receipts can reference existing saves and do not by themselves prove new saves. The interface does not provide native crash recovery, widget inspection or automatic restart.
