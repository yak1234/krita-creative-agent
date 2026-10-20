#!/bin/zsh
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Package the fork's install tree as one self-contained "Toska.app" that can be opened from the Desktop or
# /Applications, without the build tree. It never writes into the install tree and never builds.
#
#   agent/package-app.sh [INSTALL_DIR] [--out DIR] [--packages DIR] [--source DIR] [--release DIR] [--source-url URL]
#                        [--allow-dirty] [--allow-stale-build] [--allow-unpublished] [--no-sign]
#   agent/package-app.sh --check BUNDLE        self-containment and layout checks on a bundle (also: --verify, --sizes, --smoke: headless imports from a temporary copy)
#
#   INSTALL_DIR   the finished build (default: the main checkout's _install, next to this worktree's folder)
#   --out DIR     where "Toska.app" is made (default: ./_package; never /Applications: agent/install-app.sh does that)
#   --packages    a folder with numpy, OpenCV, psutil and xxhash for the bundle's Python (default: installed with uv from
#                 creative-agent/krita-mcp/krita-plugin/python-packages.txt, for the Python version found in the bundle)
#   --source DIR  the git checkout the install was built from (default: INSTALL_DIR's parent). The commit the Krita executable
#                 reports is THE commit of the app (Info.plist, Resources/BUILD.txt, README, About box). Refused unless that
#                 commit is the checkout's HEAD (--allow-stale-build), the trees are clean (--allow-dirty) and the commit is in
#                 public/main (--allow-unpublished); each allowance is written into the notices.
#   --release DIR a krita-creative-agent release (scripts/build-release.py) whose Node companion goes into the app
#                 (default: one is built from this checkout)
#   --overlay-plugin DIR  use that checkout's kritamcp folder instead of the installed plugin (before `ninja install` brings it up
#                 to date; stamped into the notices)
#   --source-url  the public repository named in the source offer (default: https://github.com/yak1234/krita-creative-agent)
#
# Signing: with KRITA_AGENT_SIGN_IDENTITY set to a keychain identity name the bundle is signed with it (hardened runtime);
# otherwise ad hoc. A stable identity is what lets macOS remember "allow access to Documents" across rebuilds: see
# AGENT-FORK.md, "Packaging", for making one.
#
# Layout, first-run default and licences: AGENT-FORK.md, "Packaging". The work is in agent/package_app.py.
set -euo pipefail
ROOT=${0:A:h:h}
PY=/usr/bin/python3

case "${1:-}" in
  --smoke) shift; exec $PY -I "$ROOT/agent/package_app.py" smoke "$@" ;;       # BUNDLE [--deny FOLDER ...]
  --check) exec $PY -I "$ROOT/agent/package_app.py" check "${2:?--check needs a bundle}" ;;
  --verify) codesign --verify --deep --strict --verbose=2 "${2:?--verify needs a bundle}"; exit $? ;;
  --sizes) du -sh "${2:?--sizes needs a bundle}"/Contents/* | sort -h; exit 0 ;;
  -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

install=""
out="$PWD/_package"
extra=()
while (( $# )); do
  case $1 in
    --out) out=${2:?--out needs a folder}; shift 2 ;;
    --packages|--source|--release|--source-url|--overlay-plugin) extra+=("$1" "${2:?$1 needs a value}"); shift 2 ;;
    --no-sign|--allow-dirty|--allow-stale-build|--allow-unpublished) extra+=("$1"); shift ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) install=$1; shift ;;
  esac
done
install=${install:-${ROOT:h}/krita-master/_install}
# A build that is installing into INSTALL_DIR would be packaged half-written: wait for it (or package a copy of the tree).
# Compare the executable of each process (ninja) and its working folder, not any command line that mentions ninja.
if ps -axo pid=,comm= | awk '$2 ~ /(^|\/)ninja$/ {print $1}' | while read -r pid; do lsof -a -p "$pid" -d cwd -Fn 2>/dev/null; done | grep -q "^n${install:h}/"; then
  echo "a build is running for $install (ninja): wait for it to finish, or package a copy of the tree" >&2
  exit 2
fi
# Every other check on the output folder (Applications, system folders, home, the install tree) is made by package_app.py
# before anything is written. The folder is made there, not here.
# A clean environment: nothing of the build shell (DYLD_*, PYTHONPATH, PATH tools) leaks into the bundle's tools.
# uv is needed on PATH for the Python packages (unless --packages is given); sandbox-exec and codesign are system tools.
exec env -i HOME="$HOME" USER="${USER:-}" TMPDIR="${TMPDIR:-/tmp}" LANG=en_US.UTF-8 \
  PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$HOME/.local/bin" \
  ${KRITA_AGENT_SIGN_IDENTITY:+KRITA_AGENT_SIGN_IDENTITY="$KRITA_AGENT_SIGN_IDENTITY"} \
  ${KRITA_AGENT_SOURCE_URL:+KRITA_AGENT_SOURCE_URL="$KRITA_AGENT_SOURCE_URL"} \
  ${KRITA_AGENT_APPLICATIONS_DIR:+KRITA_AGENT_APPLICATIONS_DIR="$KRITA_AGENT_APPLICATIONS_DIR"} \
  $PY -I "$ROOT/agent/package_app.py" package "$install" --out "$out" "${extra[@]}"
