## Context

The decision code is seven small modules (about 590 lines). `protocols`, `endpoints`, `luna-decisions`, `pacing` and
`visual-checks` are `// @ts-check` JSDoc files under the non-strict project; `client` and `service` are unchecked.
New TypeScript is strict, erasable-only and checked by `tsconfig.extensions.json` (AGENTS.md). Node runs `.ts` in a
checkout; esbuild bundles it in the release.

## Decisions

**D1. Leaves first, one module (or a small group) per commit.** `protocols` + `endpoints` + `types` → `client` +
`luna-decisions` → `service` → `visual-checks` → `pacing`. A strict `.ts` should not import an unchecked `.mjs`, so the
order follows the imports. The one remaining `.mjs` import (`service` → `parseDotEnv` from `langfuse-tracing.mjs`) is
typed at the import site.

**D2. The typed interfaces** (`src/decisions/types.ts`):
- `DecisionPart` = text `string` | an image (`data`, optional `mimeType`; Pi's `ImageContent` fits) | `null`/`undefined`
  (dropped before sending).
- `Question` = `NoulQuestion | ChoiceQuestion | ScoreQuestion` (the System One form callers write); `Questions` by name.
- `Answer` = `NoulAnswer | ChoiceAnswer | ScoreAnswer | RefusalAnswer`; `Answers` by name, each possibly missing.
- `DecisionRequest` = `{parts?, questions, signal?, purpose?}`.
- `DecisionResult` = `DecisionAnswered | DecisionFallback`, discriminated by `fallback` (each side declares the other's
  fields as `undefined`), so `if (result.fallback)` narrows and code cannot read `answers` before handling a fallback.
  `FallbackReason` lists the reasons the client produces.
- `DecisionMaker` = `{decide(request): Promise<DecisionResult>}`: what the checks need. Tests pass fakes of this shape.
- `Endpoint`, `ModelInfo`, `Protocol`, `DecisionTracing` (the one `observeGeneration` method the client uses).
- `pacing.ts` and `visual-checks.ts` export their own result types (`PaceDecision`, `PaceAction`, `Finding`, ...).

**D3. Pi's types where they apply.** Images are Pi's `ImageContent` from `@earendil-works/pi-ai` (type import only);
the client and service take no other Pi type.

**D4. No behaviour change.** Wire answers are not validated more than before: the System One protocol still passes the
body's `answers` through, so `Answers` describes what callers check for, not a guarantee. Where a type exposes a real
bug it is listed below, not fixed.

## Risks

- A cast hiding a mismatch. Casts are limited to the wire (JSON bodies) and the questions JSON file.
- Public curation (`scripts/curate-public-repo.py`) rewrites text files by suffix and `.ts` is not in its list, so the
  rewrite of `visual-checks`' comment about the private evaluation script no longer applies. Noted for a follow-up.

- Each `.ts` an `.mjs` imports is also checked by the loose `tsconfig.json`, without `strictNullChecks`, where the
  `DecisionResult` union does not narrow. Code reads `answers?.` where a helper takes a whole result, so both pass.

## Found by the types (not fixed here)

Listed in `tasks.md` section 3.
