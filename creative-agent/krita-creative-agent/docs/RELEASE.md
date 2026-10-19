# Creative Agent 0.2 — release preparation

This is a **candidate Mac release**, not a claim that the product has passed its live artwork, clean Mac, accessibility or artist usability gates. The release builder verifies a self-contained dependency snapshot and the installer is exercised only against temporary test destinations during automated tests.

## Build and install model

The release contains the native Krita plugin, the JavaScript companion, pinned installed JavaScript packages, a standalone macOS Node runtime and its license. Node talks directly to the local Krita HTTP bridge. There is no separate Python/virtual-environment dependency for the companion. Krita supplies the Python runtime used by the native plugin.

Source configuration and release payloads contain no developer-specific executable paths. The installer resolves its own destination paths on the recipient's Mac and writes them into that installation's private configuration. Artwork identity is stored relative to the selected project root, independently of those runtime paths.

`build-release.py` requires a physical dependency tree installed from the registry lockfile, checks installed versions against that lockfile, copies the complete tree including hoisted dependencies, rejects a Node binary linked to non-system libraries, and imports the actual bundled Pi SDK with an isolated home. A SHA-256 inventory identifies the complete payload; that identity is written into identical `build-info.json` files in the plugin and companion. Development source without a stamped build is explicitly `development-unverified`.

`package-lock.json` was generated against the public npm registry in a clean temporary directory, followed by a successful `npm ci --ignore-scripts` and Pi SDK import using Node 22.23.2 with an empty home. It pins 137 dependency entries, including Pi 0.84.3 and TypeBox 1.3.7, and contains no local links or developer paths. Six nested Pi entries inherit upstream shrinkwrap metadata without individual integrity fields; the complete release inventory additionally hashes every installed file. The original development dependency links were not modified. Evidence is recorded in `output/registry-lock-validation.json`. Use the lockfile for dependency installation and retain the approved release artifact; the lockfile does not replace runtime, Mac or artistic validation.

## Build a candidate

Use a clean dependency install matching `package.json`. The existing local setup script no longer creates links into a developer's global Pi installation.

```sh
npm ci --ignore-scripts
python3 scripts/build-release.py --output /path/to/new/release-folder --node /path/to/standalone-node/bin/node
```

The builder can use a separate clean dependency installation with `--dependencies /path/to/clean/node_modules`; it refuses development symlinks and missing locked packages. This allows release validation without changing an existing development checkout. The Node distribution's `LICENSE` is located beside its `bin` directory, or can be supplied using `--node-license`. Do not pass a Homebrew binary with external library dependencies. The builder refuses to overwrite an existing output folder.

For artists, build the graphical installer described in [MAC_INSTALLER.md](MAC_INSTALLER.md). It embeds Node and has no user Python requirement. The following command remains available for development and temporary-profile testing, from the resulting bundle:

```sh
python3 install.py --bundle . --project /path/to/artwork-folder
```

The installation stages files without restarting Krita or changing open paintings. It preserves the previous plugin in a timestamped backup and keeps runtime releases in separate immutable directories. A failure during the plugin swap rolls back the previous plugin. A repeated install verifies an existing runtime before reusing it. The active panel must then load and report the same build identity as the companion and native bridge; installation alone is not that verification.

For a disposable installation test, provide **both** overrides:

```sh
python3 scripts/install.py --bundle /path/to/release-folder --project /path/to/test-project --destination /path/to/test-profile/pykrita --runtime-destination /path/to/test-runtime/releases
```

Never run a staging test against the real Krita profile. `python3 -m unittest discover -s tests -p test_packaging.py` creates its own throwaway profile, runtime and artwork fixtures.

## Project records and migration

New records use `.creative-agent/project.json` and `.creative-agent/studies/<conversation-id>/`. Each study's `record.json` is the authoritative atomic record containing both painting metadata and its goal; `study.json` and `goal.json` are readable compatibility mirrors. References, snapshots and session locations are stored relative to the project and resolved when used. Artwork remains in ordinary `.kra` files in the chosen folder.

Legacy migration copies conversation records, reference images and sessions into the new state directory. It leaves original records and all `.kra` files untouched. It excludes symlinks and live locks, records the import result, and skips already imported studies. It never automatically moves artwork. Structured native operation ledgers are remapped from their old study-directory base to the new one: copied previews follow the migration, while historical `.kra` paths still refer to the actual unmoved artwork. A failed partial import is preserved for inspection rather than overwritten. Original directories remain the rollback source until a separately reviewed cleanup is requested.

Historical session text is copied as historical text; arbitrary prose is not rewritten to guess which strings are paths. The active manifest and structured attachment paths become portable. External references are copied by the runtime before inclusion. A painting deliberately linked outside the project uses a relative path that may require relinking if moved independently.

History searches names, artwork filenames, objectives and requirements. A missing painting is marked **Needs relink**. Relinking validates an existing `.kra`, updates the record, clears native ownership and pauses active goals; it does not save, open, recreate or edit the painting. Save As is reconciled by the runtime/native document lifecycle before the next save.

## Validation still required before distribution

- Verify the exact loaded build in a supported Krita version. Krita 5.2/5.3 are candidate targets; the current machine reports **5.3.3 (git 858d352)**. None of these versions is release-verified by the build script.
- Run the real panel at narrow and wide sizes, light/dark themes and larger text, including keyboard navigation, attachments, long streamed replies, errors and interruptions.
- Verify clean installation on a fresh supported Mac with no development tools or global Pi packages. The compiled AppKit installer uses bundled Node and passes isolated installation checks; its actual graphical flow and a clean external Mac remain unverified.
- Validate native package dependencies and any bundled executable code on the intended architecture, signing, notarization, Gatekeeper behavior and update distribution.
- Verify model routes using both image input and tool calls, without storing credentials in diagnostics.
- Complete the plan's artistic evaluations on separate test copies and its review with one non-artist and two practicing artists. A long goal run and successful brush calls do not prove artistic quality.

Do not describe those external gates as passed based on the packaging tests or SDK import.
