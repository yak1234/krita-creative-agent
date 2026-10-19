#!/usr/bin/env bash
# Enable the Krita MCP Bridge plugin in Krita's config.
#
# MUST run while Krita is CLOSED — Krita rewrites kritarc on exit and would
# clobber this change. Quit Krita first, run this, then reopen Krita.
#
# Key/group confirmed from Krita's own bundled krita_script_starter plugin:
#   Application.writeSetting('python', 'enable_<X-KDE-Library>', 'true')
set -euo pipefail

KRITARC="$HOME/Library/Application Support/krita/kritarc"
LIBRARY="kritamcp"

if pgrep -x "krita" >/dev/null 2>&1 || pgrep -f "MacOS/krita" >/dev/null 2>&1; then
  echo "ERROR: Krita is still running. Quit Krita first, then re-run this script."
  echo "       (Krita flushes kritarc on exit and would overwrite this change.)"
  exit 1
fi

mkdir -p "$(dirname "$KRITARC")"
touch "$KRITARC"

if grep -q '^\[python\]' "$KRITARC"; then
  # Section exists — set or replace the enable key within it.
  if grep -q "^enable_${LIBRARY}=" "$KRITARC"; then
    sed -i '' "s|^enable_${LIBRARY}=.*|enable_${LIBRARY}=true|" "$KRITARC"
    echo "Updated existing enable_${LIBRARY}=true in [python]"
  else
    awk -v key="enable_${LIBRARY}=true" '
      /^\[python\]/ { print; print key; next }
      { print }
    ' "$KRITARC" > "$KRITARC.tmp" && mv "$KRITARC.tmp" "$KRITARC"
    echo "Added enable_${LIBRARY}=true to existing [python] section"
  fi
else
  printf '\n[python]\nenable_%s=true\n' "$LIBRARY" >> "$KRITARC"
  echo "Created [python] section with enable_${LIBRARY}=true"
fi

echo
echo "Done. Reopen Krita — the bridge should listen on 127.0.0.1:5678."
echo "Verify with:  curl -s http://127.0.0.1:5678/health"
