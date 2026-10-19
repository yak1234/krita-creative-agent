## 1. Plugin measure
- [x] 1.1 `painting_weight.weight(nodes, width, height)` with unit tests:
  - New Moscow's shape (147 groups, a wavelet filter mask, 6000×4500) → `too_heavy`, wavelet named;
  - a small painting → `ok`;
  - 40 hidden agent layers → `heavy` with fix `tidy`.
- [x] 1.2 Observations carry `weight` (`_creative_observe`), with a test that no pixel method is called.

## 2. Companion
- [x] 2.1 `extensions/painting-weight.ts` with tests:
  - a line when the level rises;
  - no repeat;
  - a slow-operation line;
  - nothing on `ok`.
- [x] 2.2 Studio: one status notice per chat (test). The extension is registered inline.

## 3. Verify
- [ ] 3.1 Suites and the typecheck; build, install, reload; the offline measure on new_moscow_finished.kra matches the
  zip breakdown (counts).
