## 1. Typed decisions core

- [x] 1.1 `src/decisions/types.ts`; `protocols.ts` and `endpoints.ts` strict.
- [x] 1.2 `client.ts` and `luna-decisions.ts` strict (`DecisionResult` union).
- [x] 1.3 `service.ts` strict. Its one `.mjs` import (`parseDotEnv`) is typed at the import, under `@ts-ignore`: the
  strict project has `allowJs` off, while `tsconfig.json` (which also checks every `.ts` an `.mjs` imports) resolves it.
- [x] 1.4 `visual-checks.ts` strict.
- [x] 1.5 `pacing.ts` strict.
- [x] 1.6 Imports in `src/`, `tests/`, `scripts/` point at `.ts`. After each step: `npm run -s typecheck` clean,
  `npm run -s test:unit` 319/319.

## 2. Verify

- [x] 2.1 Python unit tests (unaffected): 252 OK.
- [x] 2.2 `scripts/build-release.py` bundles the `.ts` modules and the bundled companion starts; output deleted.

## 3. Found by the types (each a separate decision; 3.1-3.3 and 3.6 fixed on 2026-10-18 with tests, 3.5 by the curation .ts change, 3.4 open)

- [x] 3.1 `DecisionClient.decide()` with tracing on builds the trace input from the raw parts: a `null`/`undefined`
  part throws there (`request()` drops it), and an image without `mimeType` is traced as `data:undefined;base64,…`
  while the request sends `image/png`.
- [x] 3.2 `stepWork(work, call, {revision})` throws when there is no work record and `revision` is `undefined`
  (`work?.revision === revision` is true). Goals start at revision 0, so only an old or malformed goal reaches it.
- [x] 3.3 Endpoint lookups index plain objects: inherited keys resolve. `resolveEndpoint('constructor')` returns
  `Object`, `addEndpoint({id: 'constructor'})` is refused as "a built-in endpoint", and a custom lookup of such an id
  fails with a `TypeError` instead of "Unknown decision endpoint". `Object.hasOwn` would fix all three.
- [ ] 3.4 System One answers pass through unvalidated (`protocols.ts`): `Answers` describes what callers check for.
  Every caller checks the type and range today; a shared validator would make the type true at the boundary.
- [x] 3.5 `scripts/curate-public-repo.py` treats only listed suffixes as text, and `.ts` is not one: its rewrites and
  its private-path and key scan skip every `.ts` file (already true for `extensions/*.ts`), and the rewrite of
  `visual-checks`' comment about the private evaluation script no longer applies.
- [x] 3.6 Stale `visual-checks.mjs` paths in comments outside this change's files:
  `scripts/calibrate-luna-artifacts.mjs` (header) and `scripts/evaluate-visual-checks.py` (docstring).
