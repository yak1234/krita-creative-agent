## Why

Luna's decisions steer every painting run (pacing, pass checks, review progress, layer need, routing), yet the code
that asks for them is the least checked in the companion. `src/decisions/client.mjs` and `src/decisions/service.mjs`
have no `// @ts-check` at all, and everything Luna returns is the loose shape `{answers} | {fallback}`, which no type
describes. A caller can read `answers` without first handling `fallback`, and nothing notices.

This is step 1 of the TypeScript priorities research (`docs/superpowers/specs/2026-10-18-typescript-and-extensions-priorities-design.md`,
candidate 1 "a typed decisions core", and section 6 step 1). It applies phase 6 of `typed-companion-and-pi-update`
("rename to `.ts`") to the Luna leaves, which also makes them strict (phase 5) file by file, as the research recommends.
It is a prerequisite for the later `luna-pacing` Pi extension, not that extension.

## What Changes

- Rename to strict TypeScript, with no behaviour change: `src/decisions/protocols`, `endpoints`, `client`, `service`,
  `src/luna-decisions`, `src/visual-checks`, `src/pacing` (`.mjs` → `.ts`). Public names, arguments and results stay
  the same.
- Add `src/decisions/types.ts`: the decision request and result types, the question and answer forms, endpoints,
  and the `DecisionMaker` interface the checks call.
- Update every import in `src/`, `tests/` and `scripts/` to the `.ts` paths.

Not in this change: the `luna-pacing` extension, `studio.mjs` (stays unchecked `.mjs`), `routing.mjs` and
`layer-need.mjs` (stay `// @ts-check` `.mjs`; they only consume the types), and fixes for anything the types expose
(listed in `design.md`, each its own decision).

## Capabilities

### Modified Capabilities
- `typed-companion`: the Luna decision core is strict TypeScript, and a decision result must be checked for a fallback
  before its answers are read.

## Impact

- **Companion:** the seven files above plus `types.ts`; import lines in `studio.mjs`, `routing.mjs`, `layer-need.mjs`,
  tests and two scripts.
- **Release:** none. esbuild already bundles `.ts`; `visual-check-questions.json` is still copied beside `main.mjs`.
- **Plugin:** none.
- **Risk:** low. Type annotations are erased; the tests for decisions, pacing, visual checks, routing and the studio run
  unchanged.
