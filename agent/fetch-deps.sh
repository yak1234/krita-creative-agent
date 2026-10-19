#!/bin/zsh
# Fetch KDE's prebuilt Qt6 dependencies for macOS into ./_install and write ./env.sh (an environment snapshot: never
# commit it). Run it through agent/build-macos.sh, which starts it with a clean environment so env.sh captures no keys.
#
# One-time setup it expects (all ignored by git through the fork's block in .gitignore):
#   git clone -b transition.now/qt6 https://invent.kde.org/packaging/krita-deps-management.git
#   git clone https://invent.kde.org/packaging/krita-ci-utilities.git krita-deps-management/ci-utilities
#   uv venv venv --python 3.13 && VIRTUAL_ENV=$PWD/venv uv pip install -r krita-deps-management/requirements.txt
#   venv/bin/python krita-deps-management/tools/download-macos-tools.py          # -> _krita-tools
set -e
cd ${0:A:h}/..

# env.sh is a snapshot of this environment: refuse to run in one that holds anything beyond the clean basics
# (keys, tokens, secrets, LANGFUSE_*, ...). agent/build-macos.sh starts this script with exactly these.
allowed=(HOME USER LOGNAME LANG TMPDIR SHELL PATH SHLVL PWD OLDPWD _)
unexpected=()
for name in ${(k)parameters[(R)*export*]}; do
  if (( ! ${allowed[(Ie)$name]} )); then
    unexpected+=($name)
  fi
done
if (( ${#unexpected} )); then
  echo "fetch-deps.sh: refusing to run: the environment is not clean (env.sh would capture it)." >&2
  echo "Unexpected variables: ${(j:, :)${(@o)unexpected}}" >&2
  echo "Run agent/build-macos.sh --deps, which starts this script with a clean environment." >&2
  exit 1
fi

# run-ci-build.py reads the dependency list from .kde-ci.yml (a tracked file): it is generated below and restored
# whatever happens.
trap 'git checkout -- .kde-ci.yml' EXIT
source venv/bin/activate
unset VIRTUAL_ENV
source _krita-tools/activate
python3 -u krita-deps-management/tools/replace-branch-in-seed-file.py krita-deps-management/latest/krita-deps.yml \
  -p -o branch-corrected-deps.yml -d transition.now/qt6
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
