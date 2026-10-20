#!/bin/bash
# Every suite the creative agent owns, in one command: what a CI service runs, and what a merge needs green.
#
#   agent/ci.sh              plugin Python suite, companion JS suite and typecheck, then the C++ programs in
#                            agent/ci-tests.txt through agent/run-tests.sh (needs a build: agent/build-macos.sh --tests)
#   agent/ci.sh --no-cpp     only the first group (no build needed)
#   agent/ci.sh --only-cpp   only the C++ programs
#
# Exits 0 only when every group passed. Each group prints one verdict line; details are printed for failures only.
# Python runs through uv (the system python has no PyQt); JS needs `npm ci` once in creative-agent/krita-creative-agent.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
agent="$root/creative-agent/krita-creative-agent"
cpp=1; plain=1
case "${1:-}" in --no-cpp) cpp=0 ;; --only-cpp) plain=0 ;; "") ;; *) sed -n 2,9p "$0"; exit 2 ;; esac
failed=0
log="$(mktemp "${TMPDIR:-/tmp}/ci.XXXXXX")"; trap 'rm -f "$log"' EXIT

group() {                                                 # group NAME COMMAND...
    local name="$1"; shift
    if "$@" > "$log" 2>&1; then echo "PASS   $name"; else echo "FAIL   $name"; tail -40 "$log"; failed=1; fi
}

if [ "$plain" = 1 ]; then
    cd "$agent" || exit 1
    # Python: pass on "OK" in the last lines (unittest exits non-zero on failure, so the exit code is enough).
    group "plugin Python suite" uv run -q --with pyqt5 --with pillow --with numpy --with httpx --with opencv-python-headless \
        python -m unittest discover -s tests -p 'test_*.py'
    group "companion JS suite" npm run -s test:unit
    group "companion typecheck" npm run -s typecheck
fi

if [ "$cpp" = 1 ]; then
    # The C++ programs are the binaries last built: refuse to call them current when the sources have moved on. The build's
    # own ninja only (another version deletes the build log and forces a full rebuild).
    ninja="$root/_krita-tools/ninja/ninja"
    if [ -x "$ninja" ] && ! "$ninja" -C "$root/_build" -n 2>&1 | grep -q "no work to do"; then
        echo "FAIL   C++ programs: the build is not current (sources changed since it was built): agent/build-macos.sh --tests"
        exit 1
    fi
    programs=$(grep -v '^[[:space:]]*#' "$root/agent/ci-tests.txt" | grep -v '^[[:space:]]*$')
    # shellcheck disable=SC2086
    if "$root/agent/run-tests.sh" --timeout 600 $programs > "$log" 2>&1 && ! grep -qE '^(FAIL!|HUNG|CRASH|ENDED|MISSING)' "$log"; then
        echo "PASS   C++ programs ($(grep -c '^Totals' "$log") run, $(grep -c '^SKIP' "$log") skipped)"
    else
        echo "FAIL   C++ programs"; grep -E '^(FAIL!|HUNG|CRASH|ENDED|MISSING|QFATAL)' "$log" | head -20; failed=1
    fi
fi
exit $failed
