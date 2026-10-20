#!/bin/zsh
# Build Toska (the Krita fork with the Creative Agent) for macOS on Qt6 with only the Command Line Tools (no Xcode), one architecture.
#   agent/build-macos.sh            fetch dependencies if needed, configure if needed, build and install into _install
#   agent/build-macos.sh --deps     fetch dependencies again
#   agent/build-macos.sh --tests    configure with Krita's tests (BUILD_TESTING=ON; only when _build is configured anew)
# A second worktree can share the main checkout's fetched dependencies: see agent/setup-worktree.sh.
# Result: _install/bin/krita.app (bundle id and settings folders from cmake/modules/KritaAppIdentity.cmake).
# Launch: agent/run.sh
# CMAKE_BUILD_PARALLEL_LEVEL=N caps the build at N parallel jobs (ninja's own default otherwise); run it under
# `nice -n 19` to leave the Mac usable.
set -euo pipefail
ROOT=${0:A:h:h}
cd "$ROOT"
deps=0 tests=OFF
for arg in "$@"; do
  case $arg in
    --deps) deps=1 ;;
    --tests) tests=ON ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done
if [[ ! -f env.sh || $deps == 1 ]]; then
  env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" LANG=en_US.UTF-8 TMPDIR="$TMPDIR" SHELL=/bin/zsh \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin /bin/zsh agent/fetch-deps.sh
fi

# The CI's environment files save variables that may be unset before setting their own: load them without -u.
set +u
source venv/bin/activate
unset VIRTUAL_ENV
source _krita-tools/activate
source env.sh
set -u
# env.sh exports the PWD it was written in: never build or install paths from $PWD after this point.
cd "$ROOT"
export MACOSX_DEPLOYMENT_TARGET=12

# Without Xcode, Krita's CMake cannot ask `xcodebuild` for the SDK version. A stand-in answers from the Command Line
# Tools, capped below 26 so the Xcode-only asset compiler (actool) is never needed.
if ! /usr/bin/xcodebuild -version > /dev/null 2>&1; then
  mkdir -p _stand-ins
  cat > _stand-ins/xcodebuild <<'STANDIN'
#!/bin/sh
version=$(xcrun --show-sdk-version 2>/dev/null || echo 15.0)
case "$version" in 2[6-9]*|[3-9][0-9]*) echo 25.0 ;; *) echo "$version" ;; esac
STANDIN
  chmod +x _stand-ins/xcodebuild
  export PATH="$ROOT/_stand-ins:$PATH"
fi

if [[ ! -f _build/build.ninja ]]; then
  cmake -S . -B _build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=$tests -DHIDE_SAFE_ASSERTS=ON \
    -DBUILD_WITH_QT6=ON -DALLOW_UNSTABLE=QT6 -DKRITA_ENABLE_PCH=OFF -DFOUNDATION_BUILD=ON \
    -DKRITA_BUILD_MACOS_INTEGRATION=OFF \
    -DCMAKE_INSTALL_PREFIX="$ROOT/_install" -DCMAKE_PREFIX_PATH="$ROOT/_install" \
    -DCMAKE_OSX_ARCHITECTURES="$(uname -m)" -DCMAKE_OSX_DEPLOYMENT_TARGET=12 \
    -DCMAKE_TOOLCHAIN_FILE="$ROOT/krita-deps-management/tools/macos-toolchain-krita.cmake"
fi
# Never install into another checkout's folder (a worktree configured with a foreign PWD once did).
grep -qx "CMAKE_INSTALL_PREFIX:PATH=$ROOT/_install" _build/CMakeCache.txt || {
  echo "_build installs outside $ROOT/_install: remove _build and configure again" >&2
  exit 1
}
ninja ${CMAKE_BUILD_PARALLEL_LEVEL:+-j "$CMAKE_BUILD_PARALLEL_LEVEL"} -C _build install
