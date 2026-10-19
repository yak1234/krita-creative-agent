#!/bin/zsh
# Build the native helper against the exact Krita it will load into.
#
# KRITA_SRC is a Krita source checkout at the installed app's commit (Krita 5.3.3 is tag v6.0.3 built with Qt5), with
# KDE's prebuilt dependencies fetched into it the way Krita's macOS CI does (run-ci-build.py --only-env, which writes
# env.sh). This script links this folder in as plugins/extensions/agentaccel, configures Krita once with the CI's
# options, builds only the helper target and what it links to, then builds and runs the four self-tests, no Krita needed:
# the selection builders' (selection_selftest.cpp; --bench also times buildSelection's builders at 6000x4500) and the
# stroke points' (stroke_points_selftest.cpp: pressure, tilt, rotation, speed and time as KisPaintInformation reads them)
# and the background save's file side (background_save_selftest.cpp: temporary file, atomic rename, status JSON) and
# refreshRect's area (region_refresh_selftest.cpp: small images with effects that spread a change, against a whole refresh).
# Output: $KRITA_SRC/_build/.../kritaagentaccel.so
set -euo pipefail
HERE=${0:A:h}
KRITA_SRC=${KRITA_SRC:-${HERE}/../../../forks/krita-5.3.3}
KRITA_SRC=${KRITA_SRC:A}
cd "$KRITA_SRC"
[[ -f env.sh ]] || { echo "No env.sh in $KRITA_SRC: fetch the dependencies first (run-ci-build.py --only-env -e env.sh)."; exit 1; }

# The helper joins Krita's plugin tree in this checkout only (never in our repository's copy of anything).
ln -sfn "$HERE" plugins/extensions/agentaccel
grep -q 'add_subdirectory( agentaccel )' plugins/extensions/CMakeLists.txt || echo 'add_subdirectory( agentaccel )' >> plugins/extensions/CMakeLists.txt

# The CI's environment files save variables that may be unset before setting their own: load them without -u.
set +u
source venv/bin/activate
source _krita-tools/activate
source env.sh
set -u
export MACOSX_DEPLOYMENT_TARGET=10.15

# Without Xcode (command line tools only), Krita's CMake cannot ask `xcodebuild` for the SDK version it uses to choose
# how to build the app icon. A stand-in answers from the command line tools, capped below 26 so the Xcode-only icon
# compiler (actool) is never needed: the helper does not need the app icon.
if ! xcodebuild -version > /dev/null 2>&1; then
  mkdir -p _stand-ins
  cat > _stand-ins/xcodebuild <<'STANDIN'
#!/bin/sh
version=$(xcrun --show-sdk-version 2>/dev/null || echo 15.0)
case "$version" in 2[6-9]*|[3-9][0-9]*) echo 25.0 ;; *) echo "$version" ;; esac
STANDIN
  chmod +x _stand-ins/xcodebuild
  export PATH="$PWD/_stand-ins:$PATH"
fi
ARCH=${ARCH:-$(uname -m)}                         # one architecture: the Mac it runs on

if [[ ! -f _build/build.ninja ]]; then
  cmake -S . -B _build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DHIDE_SAFE_ASSERTS=ON \
    -DKRITA_ENABLE_PCH=OFF -DFOUNDATION_BUILD=ON -DCMAKE_INSTALL_PREFIX="$PWD/_install" -DCMAKE_OSX_ARCHITECTURES="$ARCH" \
    -DCMAKE_TOOLCHAIN_FILE="$PWD/krita-deps-management/tools/macos-toolchain-krita.cmake"
fi
ninja -C _build kritaagentaccel kritaagentaccel_selftest kritaagentaccel_pointtest kritaagentaccel_savetest kritaagentaccel_regiontest
_build/bin/kritaagentaccel_selftest
_build/bin/kritaagentaccel_pointtest
_build/bin/kritaagentaccel_savetest
_build/bin/kritaagentaccel_regiontest
find _build -name 'kritaagentaccel.so' -newer "$HERE/agent_accel.cpp" -print
