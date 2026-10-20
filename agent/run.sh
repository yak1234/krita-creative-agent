#!/bin/zsh
# Start the Toska build from _install (its own bundle id and settings folders: never stock Krita's).
ROOT=${0:A:h:h}
exec "$ROOT/_install/bin/krita.app/Contents/MacOS/krita" "$@"
