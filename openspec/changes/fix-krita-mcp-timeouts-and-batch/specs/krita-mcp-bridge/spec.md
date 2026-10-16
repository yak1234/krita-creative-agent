## Purpose

Defines how the external Krita MCP server and the Krita plugin bridge exchange commands so that an agent never paints the same work twice, never loses a failure report, and can tell a definite failure from an unknown outcome.

## ADDED Requirements

### Requirement: Timed-out commands are never executed late
When the bridge stops waiting for a queued command, it SHALL remove that command from the queue if it has not started, and SHALL NOT retain a result that no caller will collect. The timeout response SHALL include `error_code: "timeout"` and an error message containing "Timeout waiting for command".

#### Scenario: Queued command times out before it starts
- **WHEN** a command's queue timeout expires while the command is still waiting behind other work
- **THEN** the bridge responds with `error_code: "timeout"` and the command is never executed afterward

#### Scenario: Command finishes after its caller gave up
- **WHEN** a command was already executing when its timeout expired and it finishes later
- **THEN** its result is discarded rather than kept indefinitely

### Requirement: Client waits longer than the bridge
For every command, the MCP server SHALL tell the bridge which queue timeout to use and SHALL wait for the HTTP response for longer than that timeout. Commands the bridge treats as long-running (`open_file`, `new_canvas`, `get_canvas`, `save`, `save_native`) and `flood_fill` SHALL receive a long timeout of at least the bridge's long-running default.

#### Scenario: Slow command completes inside the bridge timeout
- **WHEN** a stroke takes 45 seconds to execute
- **THEN** the MCP tool reports its real result instead of a client-side timeout

#### Scenario: Bridge times out first
- **WHEN** a command exceeds its queue timeout
- **THEN** the MCP server receives and reports the bridge's timeout response, not its own HTTP timeout

### Requirement: Unknown outcomes are reported distinctly
When a mutating command times out, or its HTTP response is lost after the request was sent, the MCP server SHALL report the outcome as unknown and instruct the agent to inspect the canvas before retrying. Read-only commands SHALL report an ordinary error. Connection refusals SHALL still report that Krita or the plugin is not running.

#### Scenario: Stroke response lost
- **WHEN** a `stroke` request was sent and no response arrives
- **THEN** the tool reports an unknown outcome and recommends inspecting the canvas before repeating it

#### Scenario: Krita not running
- **WHEN** the bridge port refuses connections
- **THEN** the tool reports that Krita with the MCP plugin is not reachable, and does not report an unknown outcome

### Requirement: Batch uses native batching where supported
`krita_batch` SHALL execute consecutive commands that the bridge's native batch supports in as few bridge requests as possible, bounded by a fixed maximum number of commands per request. Commands the native batch does not support SHALL be sent individually. Execution order SHALL match the input order, and a failing command SHALL NOT prevent later commands from running.

#### Scenario: Pure painting batch
- **WHEN** `krita_batch` receives 150 `set_color`/`stroke` commands and the chunk limit is 64
- **THEN** it makes 3 bridge requests and reports 150 result lines in input order

#### Scenario: Mixed batch
- **WHEN** a batch contains `stroke`, `get_color_at`, `stroke`
- **THEN** the strokes and the color sample execute in that order and each has its own result line

### Requirement: Batch reports every failure
`krita_batch` SHALL output one line per input command. A command SHALL be reported as failed when its result has an error or a non-ok status such as `partial`, including failures inside a nested batch. Diagnostic readback (image paths, layer lists, brush settings, canvas info, comparisons) SHALL NOT be truncated, and a summary line SHALL state the number of failed commands.

#### Scenario: Partial nested result
- **WHEN** a command returns `{"status": "partial", "failures": [...]}`
- **THEN** its line is marked as failed and includes the failure details

#### Scenario: Unknown action
- **WHEN** a batch item names an action the bridge does not know
- **THEN** that line reports the error and the remaining commands still run

### Requirement: Optional token authentication works end to end
When `KRITA_MCP_TOKEN` is set in the MCP server's environment, the MCP server SHALL send it as a bearer token on every bridge request, including health checks. `krita_health` SHALL distinguish unreachable, unauthorized and malformed responses.

#### Scenario: Token configured on both sides
- **WHEN** the plugin and MCP server share the same `KRITA_MCP_TOKEN`
- **THEN** all tools succeed as they do without a token

#### Scenario: Token missing or wrong
- **WHEN** the plugin requires a token and the MCP server sends none or a different one
- **THEN** `krita_health` reports that the bridge rejected authorization rather than that Krita is not running
