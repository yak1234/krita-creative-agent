#!/bin/zsh
# Start the installed Krita with the native helper loaded, leaving the app bundle untouched.
#
# Krita loads its C++ plugins from one flat folder; KRITA_PLUGIN_PATH replaces the bundle's (libs/koplugin/KoJsonTrader).
# This script makes that folder beside the shared Node runtime and Python packages: links to every plugin in the app,
# plus kritaagentaccel.so built for this exact Krita (build.sh). Krita.app allows outside native code
# (com.apple.security.cs.disable-library-validation). Start Krita normally to run it without the helper.
set -euo pipefail
APP=${KRITA_APP:-/Applications/krita.app}
HELPER=${1:?Give the kritaagentaccel.so that build.sh made for this Krita}
VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null || plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist")
FOLDER="$HOME/Library/Application Support/Creative Agent/krita-plugins/$VERSION"

if pgrep -f "$APP/Contents/MacOS/krita" > /dev/null; then
  echo "Krita is running: quit it first (this script never closes your work)."; exit 1
fi
rm -rf "$FOLDER"; mkdir -p "$FOLDER"
for plugin in "$APP"/Contents/PlugIns/*.so; do ln -s "$plugin" "$FOLDER/"; done
cp "$HELPER" "$FOLDER/kritaagentaccel.so"
open -a "$APP" --env "KRITA_PLUGIN_PATH=$FOLDER"
echo "Started $APP ($VERSION) with $(ls "$FOLDER" | wc -l | tr -d ' ') plugins from $FOLDER"
