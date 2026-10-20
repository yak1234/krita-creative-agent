#!/bin/zsh
# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Put a packaged "Krita Agent.app" (agent/package-app.sh) in place, replacing an older copy.
#
#   agent/install-app.sh [--to DIR] [--dry-run] [BUNDLE]
#
#   BUNDLE      the app to install (default: ./_package/Krita Agent.app)
#   --to DIR    where to put it (default: /Applications if you can write there, else ~/Applications)
#   --dry-run   say what would happen and change nothing
#
# - Never installs into Documents, Desktop, Downloads, iCloud Drive or ~/Library/CloudStorage (macOS asks for access each
#   time an app in them is opened), into another app, or into a system folder. Every check is made on the canonical path and
#   without regard to case (APFS is case-insensitive).
# - Never touches the stock Krita: the app is always "Krita Agent.app"; a folder that holds a krita.app is refused unless
#   it is /Applications or ~/Applications, and that krita.app is never read or changed.
# - Refuses while the installed copy is running. The old copy is moved aside and only deleted after the new one is in
#   place; if the second move fails, the old app is put back.
# - Removes the quarantine attribute (com.apple.quarantine) from the installed copy.
set -euo pipefail
NAME="Krita Agent.app"
bundle="" to="" dry=0
while (( $# )); do
  case $1 in
    --to) to=${2:?--to needs a folder}; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) bundle=$1; shift ;;
  esac
done
bundle=${bundle:-$PWD/_package/$NAME}
[[ -d $bundle && ${bundle:t} == $NAME ]] || { echo "not a packaged $NAME: $bundle" >&2; exit 2; }

home=${HOME:A}
apps_user=$home/Applications
if [[ -z $to ]]; then
  if [[ -w /Applications ]]; then to=/Applications; else to=$apps_user; fi
fi
to=${to:A}
lower=${(L)to}

die() { echo "refusing to install into $to: $1" >&2; exit 2; }
# any path component that is an app bundle: nothing is installed inside another app
for part in ${(s:/:)to}; do
  [[ ${(L)part} == *.app ]] && die "it is inside the app bundle $part"
done
case $lower in
  /|/system|/system/*|/usr|/usr/*|/bin|/bin/*|/sbin|/sbin/*|/library|/library/*|/private/etc|/private/etc/*|/private/var/db|/private/var/db/*)
    die "it is a system folder" ;;
esac
for protected in Documents Desktop Downloads "Library/Mobile Documents" Library/CloudStorage; do
  p=${(L)home}/${(L)protected}
  [[ $lower == "$p" || $lower == "$p"/* ]] && die "macOS asks for access to ~/$protected each time an app in it is opened"
done
[[ $lower == /volumes || $lower == /volumes/* ]] && echo "warning: $to is on another volume; macOS may ask for access to removable volumes" >&2
# a folder with a krita.app in it is the stock Krita's: only the real Applications folders may hold it, and it is not touched
if [[ -e $to/krita.app && $to != /Applications && $to != $apps_user ]]; then
  die "it holds a krita.app (the stock Krita's folder)"
fi
target="$to/$NAME"

# running? Compare the executable path of every process with the installed copy's (a fixed string, not a pattern)
if [[ -e $target ]]; then
  ps -axo command= | while IFS= read -r line; do
    # /var, /tmp and /etc are links to /private/...: a process may have been started by either name
    # (APFS does not tell Krita Agent.app from KRITA AGENT.APP: neither do we)
    if [[ ${(L)line#/private} == "${(L)target#/private}/contents/macos/"* ]]; then
      echo "$target is running: quit Krita Agent first" >&2
      exit 3
    fi
  done
fi
echo "installing $bundle -> $target"
(( dry )) && exit 0

mkdir -p "$to"
# An install that was killed between its two moves leaves the old app in a hidden folder: put it back before anything else.
for leftover in "$to"/.krita-agent-install.*(N/); do
  pid=${leftover##*.}
  if kill -0 "$pid" 2>/dev/null; then continue; fi                 # another install is running right now
  if [[ ! -e $target && -d $leftover/old.app ]]; then
    mv "$leftover/old.app" "$target" && echo "restored the previous $NAME from an interrupted install" >&2
  fi
  [[ -d $leftover/old.app ]] || rm -rf "$leftover"
done
[[ -w $to ]] || { echo "$to is not writable" >&2; exit 2; }
work="$to/.krita-agent-install.$$"             # holds the new copy (named *.app so codesign treats it as a bundle)
staging="$work/$NAME"                          # and, for a moment, the old one
old="$work/old.app"
cleanup() {
  # An interrupted install puts the old app back before anything is deleted.
  if [[ -e $old && ! -e $target ]]; then
    mv "$old" "$target" 2>/dev/null || { echo "could not restore the old app: it is at $old" >&2; return; }
  fi
  rm -rf "$work"
}
trap cleanup EXIT
rm -rf "$work"; mkdir -p "$work"
/usr/bin/ditto "$bundle" "$staging"            # keeps symlinks, modes, extended attributes and the signature
/usr/bin/xattr -dr com.apple.quarantine "$staging" 2>/dev/null || true
codesign --verify --deep --strict "$staging" 2> /dev/null || { echo "the copy does not verify: not installing" >&2; exit 4; }

if [[ -e $target ]]; then
  mv "$target" "$old"
  if ! mv "$staging" "$target"; then
    mv "$old" "$target"
    echo "could not move the new copy into place: the old app was restored" >&2
    exit 5
  fi
else
  mv "$staging" "$target"
fi
echo "installed $target"
