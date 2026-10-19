#!/bin/zsh
# Fetch KDE's prebuilt Qt6 dependencies for macOS into ./_install and write ./env.sh (an environment snapshot: never
# commit it). Run it through agent/build-macos.sh, which starts it with a clean environment so env.sh captures no keys.
#
# One-time setup it expects (all ignored by git through .git/info/exclude):
#   git clone -b transition.now/qt6 https://invent.kde.org/packaging/krita-deps-management.git
#   git clone https://invent.kde.org/packaging/krita-ci-utilities.git krita-deps-management/ci-utilities
#   uv venv venv --python 3.13 && VIRTUAL_ENV=$PWD/venv uv pip install -r krita-deps-management/requirements.txt
#   venv/bin/python krita-deps-management/tools/download-macos-tools.py          # -> _krita-tools
set -e
cd ${0:A:h}/..
source venv/bin/activate
unset VIRTUAL_ENV
source _krita-tools/activate
python3 -u krita-deps-management/tools/replace-branch-in-seed-file.py krita-deps-management/latest/krita-deps.yml \
  -p -o branch-corrected-deps.yml -d transition.now/qt6
# run-ci-build.py reads the dependency list from .kde-ci.yml (a tracked file): generate it, fetch, then restore it.
python3 -u krita-deps-management/tools/generate-deps-file.py -s branch-corrected-deps.yml -o .kde-ci.yml
export KDECI_BUILD_TYPE=Release
export KDECI_CACHE_PATH=$PWD/cache/artifacts
export EXTERNALS_DOWNLOAD_DIR=$PWD/cache/downloads
export KDECI_CRAFT_DOWNLOADS=$PWD/cache/craft-downloads
export KDECI_GITLAB_SERVER=https://invent.kde.org/
export KDECI_PACKAGE_PROJECT=teams/ci-artifacts/krita-macos
export KDECI_REPO_METADATA_PATH=$PWD/krita-deps-management/repo-metadata
export KDECI_COMPRESS_PACKAGES_ON_DOWNLOAD=False
export MACOSX_DEPLOYMENT_TARGET=12
export QMAKE_MACOSX_DEPLOYMENT_TARGET=12
export CMAKE_TOOLCHAIN_FILE=$PWD/krita-deps-management/tools/macos-toolchain-krita.cmake
mkdir -p $KDECI_CACHE_PATH $EXTERNALS_DOWNLOAD_DIR
python3 -u krita-deps-management/ci-utilities/run-ci-build.py --project krita --branch master \
  --platform MacOS/Qt6/Shared --only-env -e env.sh
git checkout -- .kde-ci.yml
