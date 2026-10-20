#!/bin/bash
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Is this safe to make public? Read-only: it looks at what agent/publish.sh would publish (the first-parent history of
# the branch, and its working tree) and prints problems. Nothing leaves the machine.
#
#   agent/prepublish-check.sh [REV]     REV defaults to HEAD
#
# FAIL (exit 1): a secret-shaped string, or a file that must never be published (.env, env.sh, keys, paintings, databases).
# WARN: large files, commit addresses that are not the artist's, files to look at. Warnings never fail the check.
# Known-safe lines (test fixtures with fake keys, documentation) go in agent/prepublish-allow.txt as `path:fixed text`.
set -u
rev="${1:-HEAD}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 2
allow="$root/agent/prepublish-allow.txt"
base="548939fd0e2bbe0310ad687a8e545e3512031008"           # the Krita master commit the fork started from
fail=0

say() { printf '%-5s %s\n' "$1" "$2"; }

allowed() {                                               # allowed "path:text": listed in prepublish-allow.txt?
    [ -f "$allow" ] || return 1
    local line
    while IFS= read -r line; do
        case "$line" in ''|'#'*) continue ;; esac
        case "$1" in *"$line"*) return 0 ;; esac
    done < "$allow"
    return 1
}

# 1. Secret-shaped strings in the working tree (tracked files only; text only).
secret='(sk-[A-Za-z0-9_-]{20,}|pk-lf-[A-Za-z0-9-]{10,}|sk-lf-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(API_KEY|SECRET|TOKEN|PASSWORD)[A-Z_]*[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z_/+=-]*[0-9][A-Za-z0-9_/+=-]{15,})'
hits=0
while IFS= read -r hit; do
    allowed "$hit" && continue
    say FAIL "secret-shaped text: ${hit:0:160}"; hits=$((hits + 1)); fail=1
done < <(git grep -I -n -E "$secret" "$rev" -- . ':!*.po' ':!*.ts' ':!po/' 2>/dev/null | sed "s/^$rev://" | head -40)
[ "$hits" = 0 ] && say PASS "no secret-shaped text in the tree"

# 2. Files that must never be published, in every first-parent tree of the history that would be published.
never='(^|/)(\.env|env\.sh|env\.sh_deactivate|id_rsa|id_ed25519)$|\.(pem|key|p12|kra|sqlite|sqlite-wal|sqlite-shm|db)$|(^|/)\.DS_Store$|(^|/)__pycache__/|(^|/)node_modules/|\.pyc$'
bad=0
upstream_files="$(mktemp "${TMPDIR:-/tmp}/prepublish.XXXXXX")"; trap 'rm -f "$upstream_files"' EXIT
git ls-tree -r --name-only "$base" | sort > "$upstream_files"      # files Krita itself ships are not ours to judge
for commit in $(git rev-list --first-parent "$base..$rev"); do
    while IFS= read -r path; do
        case "$path" in *.env.example|*/.env.example|krita/data/*|plugins/*/tests/*|libs/*/tests/*|*/tests/data/*) continue ;; esac
        allowed "$path" && continue
        say FAIL "never publish: $path (first seen in $(git rev-parse --short "$commit"))"; bad=$((bad + 1)); fail=1
    done < <(git ls-tree -r --name-only "$commit" | grep -E "$never" | sort | comm -23 - "$upstream_files" | head -5)
    [ "$bad" -ge 20 ] && break
done
[ "$bad" = 0 ] && say PASS "no secrets files, databases, caches or paintings in any published commit"

# 3. Secret-shaped strings anywhere in the published history (pickaxe over the first-parent line).
old=$(git log --first-parent -G"$secret" --format='%h %s' "$base..$rev" -- . ':!*.po' 2>/dev/null | head -10)
if [ -n "$old" ]; then say WARN "secret-shaped text was added or removed in these published commits (check each: git show <hash>):"; echo "$old" | sed 's/^/        /'; else say PASS "no secret-shaped text in the history"; fi

# 4. Large and image files our code added (upstream's own test data is not ours to judge).
while IFS= read -r line; do say WARN "large file: $line"; done < <(git ls-tree -r -l "$rev" creative-agent | awk '$4 > 5000000 { print $4 " " $5 }')
while IFS= read -r line; do say WARN "image or video in creative-agent (a painting?): $line"; done < <(git ls-tree -r -l "$rev" creative-agent | awk '$4 > 300000 && tolower($5) ~ /\.(png|jpe?g|webp|gif|mp4|mov|psd|tiff?)$/ { print $4 " " $5 }' | head -20)

# 5. Commit addresses on the published line.
others=$(git log --first-parent --format='%ae%n%ce' "$base..$rev" | sort -u | grep -v '^yakub.rabiutheen@gmail.com$' | grep -v '^noreply@github.com$' | tr '\n' ' ')
if [ -n "$others" ]; then say WARN "commit addresses other than the artist's: $others (agent/publish.sh rewrites them)"; else say PASS "every commit carries the artist's address"; fi

# 6. Things that read like a person's path or name in text we wrote.
while IFS= read -r line; do say WARN "personal path: ${line:0:140}"; done < <(git grep -I -n -E '/Users/[a-z0-9._-]+/' "$rev" -- creative-agent agent AGENT-FORK.md 2>/dev/null | sed "s/^$rev://" | grep -v 'prepublish-check.sh' | head -8)

echo
if [ "$fail" = 0 ]; then say OK "nothing blocks publishing (read the warnings)"; else say STOP "fix the FAIL lines first"; fi
exit $fail
