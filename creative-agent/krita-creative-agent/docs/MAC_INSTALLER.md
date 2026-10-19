# Graphical Mac installer

The installer is a compiled AppKit application. An artist opens **Creative Agent Setup.app**, chooses a painting folder, and selects **Install Creative Agent**. It uses the Node runtime inside the application; the artist does not need Python, npm, Homebrew, Xcode or a terminal.

Installation copies the verified plugin and companion to the current user's Application Support folders. It preserves previous plugin files in a dated backup, keeps runtime releases in separate immutable directories, and restores the previous plugin if replacing either component fails. It does not open, save or paint a document, read API keys, restart Krita, or enable a plugin by rewriting Krita preferences. The final screen explains how to enable **Krita MCP Bridge** and open the **Creative Agent** docker after the artist saves their work and reloads Krita.

## Components

- `scripts/mac-installer.swift`: native folder chooser, installation status, guarded close/quit during replacement, and a headless embedded-payload verification entry point.
- `scripts/install-release.mjs`: dependency-free Node installer. Validates every manifest hash, the complete physical file inventory, component build IDs, platform/architecture, and the canonical release digest. Rejects symbolic links and unsafe manifest paths. Preserves the previous state location for runtime migration. It never accepts an API key.
- `scripts/build-mac-installer.py`: build-machine helper. Takes an already verified release, compiles the native launcher, embeds the release and installer module, seals the application with an ad-hoc signature, and runs the compiled launcher's verification path.
- `tests/installer.test.mjs`: temporary-destination tests for install/update, rollback after replacing one component, inventory/path/link rejection, tampered payload/runtime rejection, and build-ID encoding for Unicode filenames.

The existing `build-release.py` and `install.py` were not changed for this installer. Their release manifest is the source of truth. The new engine implements that same manifest and installation layout, including private configuration permissions and legacy state discovery.

## Build a current installer

Build the release first, then use a new output name:

```sh
python3 scripts/build-mac-installer.py \
  --bundle output/RELEASE_FOLDER \
  --output 'output/Creative Agent Setup.app'
```

The build machine needs Apple's Swift compiler and SDK. The packaged installer does not. The builder refuses to overwrite an existing `.app` and checks that the release matches the build machine's platform/architecture. The candidate minimum deployment target is macOS 13.5; this setting is not evidence of a completed compatibility test on that OS.

A compiled app can verify its own payload without showing UI or installing anything:

```sh
'output/Creative Agent Setup.app/Contents/MacOS/CreativeAgentInstaller' --verify-bundle
```

## Verified in this workspace

On macOS 15.6 / Apple Silicon:

- All six installer engine tests passed.
- Swift compilation and application assembly succeeded.
- The compiled launcher's `--verify-bundle` validated the embedded runtime, installer module and complete release.
- The packaged Node and installer module completed an installation into temporary folders with `PATH=/usr/bin:/bin`. The temporary painting bytes remained unchanged and no project state directory was created by installation.
- The candidate app's ad-hoc application signature passed local verification.

The current installer candidate is `output/Creative Agent Setup 0.2 candidate 3.app`. It embeds `live-candidate-003`, build `80897285444336afd992b11558b230c2ea9752175eded7646ad382be8a3116f5`. Its compiled verification entry point, complete embedded release inventory, and strict local ad-hoc signature verification passed. Source and artifact hashes are recorded in `output/live-candidate-003-installer-validation.json`.

All 61 Node tests passed against a disposable physical copy of `live-candidate-001`, using its bundled Node and an isolated home and executable search path. Candidate 003 has exactly the same companion source, locked dependencies, Node runtime, and non-UI native plugin bytes; only `creative_docker.py` and the derived build metadata changed. The exact comparison is recorded in `output/live-candidate-003-build-validation.json`; test hashes and output are in `output/live-candidate-001-test-validation.json` and `output/live-candidate-001-tests.log`. These installer checks did not install or load candidate 003 into Krita.

## Release gates still open

This is not a notarized public release. Developer ID signing, notarization, Gatekeeper behavior for a downloaded artifact, a clean supported Mac installation, Intel compatibility if claimed, and a person completing the graphical flow are not verified. Headless validation must not be described as graphical or clean-machine testing. These flags are recorded in the packaged `installer-validation.json`.
