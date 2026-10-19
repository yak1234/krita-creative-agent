# SPDX-FileCopyrightText: 2026 Krita Agent contributors
# SPDX-License-Identifier: BSD-3-Clause
#
# The identity this build runs under, so it can live beside a stock Krita on the same machine without sharing its
# settings, resources, caches, logs, single-instance channel or macOS bundle identifier.
#
# KRITA_APP_SETTINGS_FOLDER is the one folder name everything per-user goes under:
#   config (kritarc, kritadisplayrc, kritashortcutsrc, ...)  <GenericConfigLocation>/<folder>/
#   resources and resource database                          <GenericDataLocation>/<folder>/krita/
#   caches                                                   <GenericCacheLocation>/<folder>/krita/
#   krita.log, krita-sysinfo.log, kritacrash.log             <GenericDataLocation>/<folder>/
# On macOS that is ~/Library/Preferences/<folder>, ~/Library/Application Support/<folder> and ~/Library/Caches/<folder>.
# Leave it empty to get stock Krita's locations.

set(KRITA_APP_SETTINGS_FOLDER "KritaAgent" CACHE STRING
    "Folder name this build keeps its own settings, resources, caches and logs in (empty: stock Krita's folders)")
set(KRITA_APP_DISPLAY_NAME "Krita Agent" CACHE STRING "Application name shown to the user")
set(KRITA_APP_ORGANIZATION_DOMAIN "kritaagent.local" CACHE STRING "Organization domain (stock Krita: krita.org)")
set(KRITA_MACOS_BUNDLE_ID "local.kritaagent" CACHE STRING "macOS bundle identifier (stock Krita: org.krita)")
set(KRITA_MACOS_BUNDLE_NAME "${KRITA_APP_DISPLAY_NAME}" CACHE STRING "macOS bundle name shown in the menu bar")
option(KRITA_BUILD_MACOS_INTEGRATION
    "Build the macOS Quick Look, thumbnail and Spotlight extensions (needs Xcode)" ON)

if (KRITA_APP_SETTINGS_FOLDER)
    message(STATUS "App identity: ${KRITA_APP_DISPLAY_NAME}, settings folder '${KRITA_APP_SETTINGS_FOLDER}', "
                   "bundle id ${KRITA_MACOS_BUNDLE_ID}")
endif()
