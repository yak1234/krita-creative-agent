#!/bin/zsh
# Prepare a second git worktree of this fork to build on its own, sharing the main checkout's fetched dependencies
# read-only instead of downloading them again.
#   git -C <main> worktree add ../krita-agent-x -b agent/x krita-agent
#   <worktree>/agent/setup-worktree.sh <main>
#   <worktree>/agent/build-macos.sh --tests
#
# What it does, in the worktree (all ignored or untracked; never commit them):
#   _install      an APFS clone of <main>/_install without the files Krita itself installed there (the paths listed in
#                 <main>/_build/install_manifest.txt), so the worktree's build installs its own Krita over the same
#                 dependencies and never sees the main checkout's Krita headers or libraries;
#   venv, _krita-tools, krita-deps-management
#                 symbolic links to the main checkout's (read-only use: the build only runs them);
#   env.sh, env.sh_deactivate
#                 the main checkout's environment snapshot with its _install replaced by the worktree's.
set -euo pipefail
WT=${0:A:h:h}
MAIN=${1:?usage: agent/setup-worktree.sh <main checkout>}
MAIN=${MAIN:A}
[[ "$MAIN" != "$WT" ]] || { echo "run it in a second worktree, with the main checkout as argument" >&2; exit 1; }
[[ -f "$MAIN/env.sh" && -d "$MAIN/_install" && -f "$MAIN/_build/install_manifest.txt" ]] || {
  echo "$MAIN needs env.sh, _install and _build/install_manifest.txt (build it once with agent/build-macos.sh)" >&2
  exit 1
}

[[ -d "$WT/_install" ]] || cp -cR "$MAIN/_install" "$WT/_install"
# Every time, not only after the clone: whatever Krita files are in the worktree's _install (the main checkout's,
# or an earlier build's of this worktree) go, so its build never compiles or links against another Krita. Its own
# build's install puts them back. A manifest whose paths do not start with the main checkout's _install would
# prune nothing, silently: refuse it.
matched=0 removed=0
while IFS= read -r f; do
  [[ "$f" == "$MAIN/_install/"* ]] || continue
  matched=$((matched + 1))
  f="$WT/_install/${f#$MAIN/_install/}"
  if [[ -e "$f" || -L "$f" ]]; then
    rm -f "$f"
    removed=$((removed + 1))
  fi
done < "$MAIN/_build/install_manifest.txt"
if (( matched == 0 )); then
  echo "no entry of $MAIN/_build/install_manifest.txt lies in $MAIN/_install: nothing pruned" >&2
  exit 1
fi
echo "pruned $removed of $matched Krita files from $WT/_install"

for link in venv _krita-tools krita-deps-management; do
  [[ -e "$WT/$link" ]] || ln -s "$MAIN/$link" "$WT/$link"
done

for f in env.sh env.sh_deactivate; do
  [[ -f "$MAIN/$f" ]] || continue
  # Every path of the main checkout's own folders, the exported PWD included, becomes the worktree's; the shared
  # tools (venv, _krita-tools, krita-deps-management, cache) keep the main checkout's paths.
  sed -e "s#$MAIN/_install#$WT/_install#g" -e "s#$MAIN/env.sh#$WT/env.sh#g" \
      -e "s#^export PWD=.*#export PWD=\"$WT\"#" -e "s#^export OLDPWD=.*#export OLDPWD=\"$WT\"#" "$MAIN/$f" > "$WT/$f"
done
! grep -q "$MAIN/_install" "$WT/env.sh" || { echo "env.sh still names $MAIN/_install" >&2; exit 1; }
echo "ready: $WT/agent/build-macos.sh --tests"
