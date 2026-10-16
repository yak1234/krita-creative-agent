# Changelog

## 1.0.0

First public release.

- **Four modes: Ask · Plan · Agent · Autopilot.** Agent is new and collaborative: one substantial move per message (a batch sized to a visible step), then Keep, Undo (rejects the whole move) or a typed correction. Autopilot is the self-driving mode, renamed; older chats reopen in it.
- **Decision endpoints.** OpenRouter (every decision model, listed live), OpenAI's Decisions API, TypeSafe and custom System One endpoints, with a two-image check that gates visual decisions.
- **API keys only.** OAuth sign-ins are not offered; a chat saved with one continues on a key-connected model.

- **Speed.** Several painting actions per model call (`paint_batch`). Lean model context: no host bookkeeping, results capped, only the newest canvas images kept. Full `.kra` saves every few actions instead of after every action. Decision-model pacing that advances plan steps and calls the reviewer. A `benchmark-run.mjs` report built from Langfuse sessions.
- **Autonomous runs.** Plan steps are a painting order, not approval gates. One final review decides completion from per-check evidence. No mid-run stops except the artist's Stop and hard failures.
- **Decision models.** GPT-6 Luna Decisions (OpenRouter) for routing, per-pass defect checks, review-to-review progress and pacing, behind a Decisions API interface that accepts your own Unsloth decision model.
- **Optional Langfuse tracing.** One session per chat, generations, tools, review scores and typed decisions with images. Credentials from `.env`, the environment or the macOS Keychain.
- **Small releases (293 MB → 15 MB).** The companion is one esbuild bundle instead of ~17,500 node_modules files, with every bundled package's license in THIRD_PARTY_LICENSES.txt. Node is no longer shipped: the panel fetches the pinned, checksum-verified Node runtime once (about 50 MB) and every release shares it, like uv's managed Python. Installs hard-link unchanged files and keep only recent releases.
- **Decision-model dataset.** Typed decisions recorded with their images, an annotation queue for artist verdicts, and an export to Unsloth typed-decisions rows.
