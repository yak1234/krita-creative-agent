# Contributing

Thanks for helping. A few conventions keep this project reviewable.

## Workflow

1. **Behaviour changes start with an issue** describing what the artist sees and why. Refactors and documentation fixes don't need one.
2. **Keep tests green.** Run every suite from the README's *Develop* section. New behaviour needs a test that would fail without it.
3. **Never test on real artwork.** Live checks use a disposable document. The plugin refuses to overwrite the original file, and tests must not weaken that.
4. **Secrets stay out.** No API keys, personal paths or study data in commits. CI runs gitleaks.

## Style

- Match the surrounding code: dense, comment the *why*, not the *what*.
- Model-facing text (`companion/src/prompt.mjs`, tool descriptions) is behaviour: change it deliberately, and say why in the PR.
- Python: the standard library in the plugin (it runs inside Krita); use `uv` for development tools.

## Pull requests

Describe the user-visible change, link the issue if there is one, and include test output. For speed changes, include a `benchmark-run.mjs` report.
