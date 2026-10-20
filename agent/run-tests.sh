#!/bin/bash
# Run Krita unit tests from a worktree's build the one way that works on macOS, without crash dialogs.
#
#   agent/run-tests.sh TestDocumentHistory kis_kra_saver_test        whole test programs
#   agent/run-tests.sh TestDocument testAnnotations                   one program, named functions only
#   agent/run-tests.sh --timeout 600 kis_image_test                   a longer limit (seconds per program)
#
# Run it from the worktree whose _build you mean (it uses the script's own worktree). It sets everything a test needs:
#   DYLD_LIBRARY_PATH     the build's libraries
#   KIS_TEST_PREFIX_PATH  the install (without it Krita aborts in getInstallationPrefix)
#   KRITA_PLUGIN_PATH     the installed plugins (without it no file format loads or saves: .kra tests fail, and Krita
#                         shows a modal "could not open" box that nothing clicks)
#   QT_QPA_PLATFORM       offscreen: no windows on the artist's screen
#   EXTRA_RESOURCE_DIRS   the installed and source resources (colour profiles), as KoTestConfig.h gives Krita's tests
# Each program runs in a new temporary folder, deleted afterwards (tests write files such as emptytest.kra beside
# themselves), at the lowest priority. A program still running at the limit is ended with SIGTERM, which leaves no
# crash report; Qt's own watchdog (QTEST_FUNCTION_TIMEOUT) is set past the limit, because it aborts, and an abort opens
# macOS's "quit unexpectedly" dialog. Functions listed in agent/known-test-failures.txt are skipped unless named.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
limit=300
if [ "${1:-}" = "--timeout" ]; then limit="$2"; shift 2; fi
[ $# -ge 1 ] || { sed -n 2,6p "$0"; exit 2; }

export DYLD_LIBRARY_PATH="$root/_build/bin"
export KIS_TEST_PREFIX_PATH="$root/_install"
export KRITA_PLUGIN_PATH="$root/_install/lib/kritaplugins"
export EXTRA_RESOURCE_DIRS="$root/_install/share;$root/krita/data"   # as KoTestConfig.h: colour profiles and the
                                                                    # rest (without them a colour conversion segfaults)
export QT_QPA_PLATFORM=offscreen
export QTEST_FUNCTION_TIMEOUT=$(( (limit + 60) * 1000 ))
known="$root/agent/known-test-failures.txt"
# Programs upstream itself marks broken: each krita_add_broken_unit_test( ... ) block's binary is its TEST_NAME, or else
# its first .cpp; both names are listed.
upstream_broken=$(cd "$root" && git ls-files '*CMakeLists.txt' | xargs awk '
    /krita_add_broken_unit_test[ ]*\(/ { open = 1; first = 1 }
    open && first && match($0, /[A-Za-z_0-9]+\.cpp/) { print substr($0, RSTART, RLENGTH - 4); first = 0 }
    open && match($0, /TEST_NAME[ ]+[A-Za-z_0-9]+/) { split(substr($0, RSTART, RLENGTH), part, / +/); print part[2] }
    open && /\)/ { open = 0 }' 2>/dev/null)

run() {                                                   # run PROGRAM [FUNCTION...]
    local program="$1"; shift
    local binary="$root/_build/bin/$program"
    [ -x "$binary" ] || { echo "MISSING $program (not built: agent/build-macos.sh --tests)"; return 1; }
    local functions=("$@")
    if [ ${#functions[@]} -eq 0 ] && grep -qx "$program" <<< "$upstream_broken"; then
        echo "SKIP   $program (upstream registers it with krita_add_broken_unit_test; name functions to run them)"; return 0
    fi
    if [ ${#functions[@]} -eq 0 ] && [ -f "$known" ] && grep -q "^$program::\*" "$known"; then
        echo "SKIP   $program (every function, known-test-failures.txt; name functions to run them)"; return 0
    fi
    if [ ${#functions[@]} -eq 0 ] && [ -f "$known" ] && grep -q "^$program::" "$known"; then
        local skip; skip=$(grep "^$program::" "$known" | awk '{ sub(/^[^:]*::/, "", $1); print $1 }')
        while read -r name; do
            name="${name%%(*}"
            grep -qx "$name" <<< "$skip" && echo "SKIP   $program::$name (known-test-failures.txt)" && continue
            functions+=("$name")
        done < <("$binary" -functions 2>/dev/null)
    fi
    local scratch; scratch="$(mktemp -d "${TMPDIR:-/tmp}/krita-test.XXXXXX")"
    ( cd "$scratch" && exec "$binary" "${functions[@]+"${functions[@]}"}" ) > "$scratch.log" 2>&1 &
    local pid=$! waited=0
    renice -n 19 -p "$pid" > /dev/null 2>&1
    while kill -0 "$pid" 2> /dev/null && [ "$waited" -lt "$limit" ]; do sleep 1; waited=$((waited + 1)); done
    local status
    if kill -0 "$pid" 2> /dev/null; then
        kill -TERM "$pid"; wait "$pid" 2> /dev/null
        echo "HUNG   $program after ${limit}s, ended (last lines below)"; tail -5 "$scratch.log"; status=124
    else
        wait "$pid"; status=$?
        grep -E "^(FAIL!|XPASS|Totals)|QFATAL|^QINFO|^   (Loc|Actual|Expected)" "$scratch.log"
        if [ "$status" -eq 143 ]; then echo "ENDED  $program by a SIGTERM from outside the runner: run it again"
        elif [ "$status" -ge 128 ]; then echo "CRASH  $program (signal $((status - 128)); see ~/Library/Logs/DiagnosticReports)"; fi
    fi
    rm -rf "$scratch" "$scratch.log"
    return "$status"
}

if [ $# -ge 2 ] && ! [ -x "$root/_build/bin/$2" ]; then   # PROGRAM FUNCTION...
    run "$@"; exit $?
fi
failed=0
for program in "$@"; do run "$program" || failed=1; done
exit "$failed"
