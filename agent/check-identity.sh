#!/bin/zsh
# Gate for the fork's own application identity (KisAppIdentity, cmake/modules/KritaAppIdentity.cmake): fails when
# upstream code reaches stock Krita's per-user files directly instead of through the identity. Run it after every
# rebase (AGENT-FORK.md, "Rebase cadence").
#
# It looks, outside tests, for
#   - QStandardPaths::writableLocation(GenericConfigLocation | GenericDataLocation)
#   - QSettings objects
#   - config file names: string literals ending in "rc" (kritarc, kritadisplayrc, ...)
# and accepts a line when it, or one of the four lines around it, goes through KisAppIdentity (or, where KisAppIdentity
# cannot be called, the organization name it sets). Everything else must be listed in agent/check-identity.allow,
# with the reason it is safe.
#
#   agent/check-identity.sh          check; exit 1 and list the new hits if any
set -euo pipefail
ROOT=${0:A:h:h}
cd "$ROOT"
exec /usr/bin/python3 -I - "$ROOT" <<'PYTHON'
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
allow_file = root / "agent" / "check-identity.allow"

patterns = [
    ("generic location", re.compile(r"Generic(Config|Data)Location")),
    ("QSettings", re.compile(r"\bQSettings\s*(\w+\s*)?\(|new\s+QSettings\b|QSettingsPtr\(")),
    ("config file name", re.compile(r"\"/?[A-Za-z][A-Za-z0-9_.-]{2,}rc\"")),
]
routed = re.compile(r"KisAppIdentity::|identityConfigLocation\(|organizationName\(\)")
context_lines = 4

allowed = []  # (path, substring)
for number, line in enumerate(allow_file.read_text().splitlines(), 1):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    path, sep, rest = line.partition(": ")
    if not sep:
        sys.exit(f"{allow_file}:{number}: expected '<path>: <text on the line> -- <why it is safe>'")
    text = rest.split(" -- ")[0].strip()
    allowed.append((path, text))

files = subprocess.run(
    ["git", "ls-files", "*.cpp", "*.cc", "*.c", "*.h", "*.mm", "*.py"],
    cwd=root, check=True, capture_output=True, text=True).stdout.split()

used = set()
hits = []
for name in files:
    if "/tests/" in name or name.startswith(("benchmarks/", "agent/")):
        continue
    try:
        lines = (root / name).read_text(errors="replace").splitlines()
    except OSError:
        continue
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "#", "/*")) and "QSettings" not in stripped.split("//")[0]:
            continue
        kinds = [kind for kind, pattern in patterns if pattern.search(line)]
        if not kinds:
            continue
        window = lines[max(0, index - context_lines):index + context_lines + 1]
        if any(routed.search(previous) for previous in window):
            continue
        match = next((entry for entry in allowed if entry[0] == name and entry[1] in line), None)
        if match:
            used.add(match)
            continue
        hits.append(f"{name}:{index + 1}: [{', '.join(kinds)}] {stripped}")

stale = [entry for entry in allowed if entry not in used]
for path, text in stale:
    print(f"note: allow-list entry no longer matches anything: {path}: {text}", file=sys.stderr)

if hits:
    print("Per-user files reached without KisAppIdentity (route them through it, or list them in "
          "agent/check-identity.allow with the reason they are safe):", file=sys.stderr)
    for hit in hits:
        print("  " + hit, file=sys.stderr)
    sys.exit(1)
print(f"check-identity: {len(files)} files, no unrouted per-user paths ({len(used)} allow-listed lines)")
PYTHON
