#!/bin/bash
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Publish the fork to its public repository (github.com/yak1234/krita-creative-agent, branch main), as a replay.
#
#   agent/publish.sh                 dry run: build the public history in the local ref refs/publish/main, report, push nothing
#   agent/publish.sh --push          the same, then push main (only new commits after the first push)
#   agent/publish.sh --push --first  the first push: keeps the repository's current main as the branch `plugin-only`, then
#                                    replaces main (a forced update guarded by --force-with-lease on the old main)
#   --skip-ci                        do not run agent/ci.sh first (it runs by default; a push needs it green)
#   --remote NAME / --branch NAME    default `public` and `main`
#
# WHY A REPLAY: Krita's own history is about 10 GB on GitHub, too much to put in the public repository. The public history
# is a root commit holding Krita's tree at the commit the fork started from (the snapshot), then one commit per
# first-parent commit of the local branch, with its tree, message, author and dates, so merges of agent branches show as
# one commit. The local repository stays the truth (full history, upstream merges): the public one is derived from it, and
# nothing in it is rewritten: later runs only append the commits that are not published yet (the map is
# <git-dir>/publish-map). The one rewrite is addresses: authors who are not the artist get the artist's address.
#
# SAFETY: it refuses a dirty tree, runs agent/ci.sh and agent/prepublish-check.sh (both must pass), and never pushes unless
# --push is given. Run it yourself or let the lead run it after a merge passes.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
base="548939fd0e2bbe0310ad687a8e545e3512031008"
remote=public; branch=main; push=0; first=0; ci=1; rev=krita-agent
while [ $# -gt 0 ]; do
    case "$1" in
        --push) push=1 ;; --first) first=1 ;; --skip-ci) ci=0 ;;
        --remote) remote="$2"; shift ;; --branch) branch="$2"; shift ;;
        -h|--help) sed -n 2,22p "$0"; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
artist_name="Yakub Rabiutheen"; artist_email="yakub.rabiutheen@gmail.com"
gitdir="$(git rev-parse --git-common-dir)"; map="$gitdir/publish-map"; touch "$map"

[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "tracked files have uncommitted changes: commit or stash them first" >&2; exit 1; }
git rev-parse --verify -q "$rev" > /dev/null || { echo "no branch $rev" >&2; exit 1; }
if [ "$ci" = 1 ]; then echo "== agent/ci.sh"; agent/ci.sh || { echo "CI failed: nothing published" >&2; exit 1; }; fi
echo "== agent/prepublish-check.sh"; agent/prepublish-check.sh "$rev" || { echo "the pre-publication check failed: nothing published" >&2; exit 1; }

public_commit() {                                          # public_commit LOCAL PARENT|"" -> prints the new public hash
    local c="$1" parent="$2" msg an ae ad
    msg="$(mktemp)"; git log -1 --format=%B "$c" > "$msg"
    an="$(git log -1 --format=%an "$c")"; ae="$(git log -1 --format=%ae "$c")"; ad="$(git log -1 --format=%aI "$c")"
    case "$ae" in "$artist_email") ;; *) an="$artist_name"; ae="$artist_email" ;; esac
    GIT_AUTHOR_NAME="$an" GIT_AUTHOR_EMAIL="$ae" GIT_AUTHOR_DATE="$ad" \
    GIT_COMMITTER_NAME="$artist_name" GIT_COMMITTER_EMAIL="$artist_email" GIT_COMMITTER_DATE="$(git log -1 --format=%cI "$c")" \
        git commit-tree "$c^{tree}" ${parent:+-p "$parent"} -F "$msg"
    rm -f "$msg"
}

echo "== building the public history (local ref only)"
tip=""
if git rev-parse --verify -q refs/publish/main > /dev/null; then tip="$(git rev-parse refs/publish/main)"; fi
if [ -z "$tip" ]; then
    snapshot_msg="$(mktemp)"
    printf 'Krita master at %s (upstream snapshot)\n\nThe tree of https://invent.kde.org/graphics/krita at the commit this fork started from.\nKrita'"'"'s own history is not repeated here (it is about 10 GB); it stays at that address. Toska'"'"'s\ncommits follow, one per merge or change on the main line.\n' "$(git rev-parse --short "$base")" > "$snapshot_msg"
    tip="$(GIT_AUTHOR_NAME="$artist_name" GIT_AUTHOR_EMAIL="$artist_email" GIT_AUTHOR_DATE="$(git log -1 --format=%aI "$base")" \
           GIT_COMMITTER_NAME="$artist_name" GIT_COMMITTER_EMAIL="$artist_email" GIT_COMMITTER_DATE="$(git log -1 --format=%cI "$base")" \
           git commit-tree "$base^{tree}" -F "$snapshot_msg")"
    rm -f "$snapshot_msg"; echo "$base $tip" >> "$map"
fi
added=0
for c in $(git rev-list --first-parent --reverse "$base..$rev"); do
    grep -q "^$c " "$map" && { tip="$(grep "^$c " "$map" | cut -d' ' -f2)"; continue; }
    tip="$(public_commit "$c" "$tip")"; echo "$c $tip" >> "$map"; added=$((added + 1))
done
git update-ref refs/publish/main "$tip"
total=$(git rev-list --count refs/publish/main)
echo "public history: $total commits ($added new), tip $(git rev-parse --short "$tip") for $(git rev-parse --short "$rev")"
if [ "$(git rev-parse "$rev^{tree}")" != "$(git rev-parse refs/publish/main^{tree})" ]; then
    echo "the public tip's tree differs from $rev: not publishing" >&2; exit 1
fi
echo "tree check: the public tip has exactly the files of $rev"
echo "size to send: $(git rev-list --objects --missing=allow-any --disk-usage refs/publish/main 2> /dev/null | awk '{ printf "%.0f MB", $1 / 1048576 }')"

if [ "$push" = 0 ]; then
    echo "dry run: nothing pushed. To publish: agent/publish.sh --push$([ "$first" = 1 ] && echo ' --first')"
    exit 0
fi
git remote get-url "$remote" > /dev/null 2>&1 || { echo "no remote '$remote' (git remote add $remote https://github.com/yak1234/krita-creative-agent.git)" >&2; exit 1; }
export GIT_TERMINAL_PROMPT=0
# Use the GitHub CLI's login for this push only (no change to the repository's or the artist's git configuration).
if command -v gh > /dev/null 2>&1; then
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0='!gh auth git-credential'
fi
if [ "$first" = 1 ]; then
    old="$(git ls-remote "$remote" "refs/heads/$branch" | cut -f1)"
    if [ -n "$old" ]; then
        echo "== keeping the current $branch as plugin-only ($old)"
        git fetch -q "$remote" "refs/heads/$branch:refs/publish/old-$branch"
        git push "$remote" "refs/publish/old-$branch:refs/heads/plugin-only"
        echo "== replacing $branch (guarded by the old tip)"
        git push --force-with-lease="refs/heads/$branch:$old" "$remote" "refs/publish/main:refs/heads/$branch"
    else
        git push "$remote" "refs/publish/main:refs/heads/$branch"
    fi
else
    git push "$remote" "refs/publish/main:refs/heads/$branch"
fi
echo "published $(git rev-parse --short refs/publish/main) to $remote/$branch"
