// @ts-check
// Entry point of the bundled release only (scripts/build-release.py). Pi loads its OAuth sign-in
// flows (ChatGPT Codex, Claude, ...) through a variable import a bundler cannot follow, so a bundle
// failed with "Cannot find module .../src/openai-codex.js". Registering them statically embeds them,
// as Pi's own standalone binary does. A checkout runs src/main.mjs, where the variable import works.
// @ts-ignore: a Bun-only build entry; this subpath ships no type declarations.
import { registerBunOAuthFlows } from '@earendil-works/pi-ai/bun-oauth';

registerBunOAuthFlows();
await import('./main.mjs');
