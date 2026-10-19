## Purpose

The agent starts on every platform Krita runs on, from a runtime the plugin ships and verifies, and its Python sandbox is locked, or refuses to run, on each.

## ADDED Requirements

### Requirement: The managed runtime covers macOS, Windows and Linux
The plugin SHALL resolve a pinned Node runtime for macOS (arm64, x64), Windows (x64, arm64) and Linux (x64, arm64). It SHALL download the official archive, verify its SHA-256 against the pinned value, and unpack it under the OS's per-user data folder. An unsupported OS or architecture SHALL get a clear message.

#### Scenario: Windows x64
- **WHEN** the panel starts the companion on Windows x64
- **THEN** the pinned `node-v…-win-x64.zip` is verified, unpacked under `%LOCALAPPDATA%`, and the companion starts with its `node.exe`

### Requirement: The Python sandbox fails closed
The sandbox runner SHALL check, before running any job, that the home folder cannot be read. If it can be read, the runner SHALL run nothing and report that the sandbox is not locked.

#### Scenario: A runtime that ignores permission flags
- **WHEN** the runner is started by a runtime that accepts `--permission` but does not enforce it
- **THEN** no Python runs, and the error says the sandbox is not locked

### Requirement: A platform is supported only after a clean-machine install
A release for a platform SHALL be marked supported only after it is installed on a clean account or machine of that OS, with a clean Krita resources folder, and a chat paints. The manifest SHALL record this per platform.

#### Scenario: Linux before its check
- **WHEN** the Linux release has not passed a clean-machine install
- **THEN** its manifest says `clean_verified: false`, and the README does not list Linux as supported
