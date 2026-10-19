# Tracing with Langfuse

Tracing is optional. Add Langfuse keys and every chat is traced; without keys, chats run untraced and the panel shows *Tracing off*.

## Setup

Add these to `.env` in your paintings folder (see `.env.example`):

```sh
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or https://us.cloud.langfuse.com, or self-hosted
```

The companion looks for keys in the project `.env`, then the environment, then the macOS Keychain. A key pair is never mixed across sources.

- `node companion/scripts/langfuse-credentials.mjs --check` prints the organization, project and key source.
- `--store-keychain` copies the `.env` keys into the Keychain.

When it connects, the panel says what it connected to, for example *Langfuse tracing connected: Acme / krita · development, keys from .env*. A wrong project is visible immediately.

## What a chat looks like

- **Session** = one Krita chat, from its first message until **New chat**, which records an `end-chat` event and flushes. Restoring a chat continues its session.
- **Trace** = one agent run, named `paint-goal`, `plan-painting`, `answer-artist`, `review-canvas` or `prepare-batch`. It is an `agent` root containing:
  - one `generation` per model call (`choose-next-action`, `judge-canvas`, `propose-batch`), with the messages the model newly saw in OpenAI chat format (images as Langfuse media), its reply with thinking and tool calls, model, tokens, cost and time to first token;
  - one `tool` per tool call, as siblings of the generations.
- **Decision calls** are their own generations (`decision-route-request`, `decision-detect-pass-failures`, `decision-pace-run`, …) in the same session, tagged with the endpoint.
- **Scores:** every review adds `review-passed` (boolean) and `review-checks-met` (0–1) to its trace.
- **Typed decisions** for the dataset are `decide-*` event traces (see [decision models](decision-models.md)).

API keys are masked before export. Environment comes from `LANGFUSE_TRACING_ENVIRONMENT` (default `development`), and release is the build id.

## Tools

- `companion/scripts/langfuse-smoke.mjs <provider/model>`: one small traced run without Krita (environment `smoke-test`).
- `companion/scripts/benchmark-run.mjs <chat-id>`: speed report for a chat (minutes per category, painter calls, tokens, review results).
