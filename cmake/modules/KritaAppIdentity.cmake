# SPDX-FileCopyrightText: 2026 Krita Agent contributors
# SPDX-License-Identifier: BSD-3-Clause
#
# The identity this build runs under, so it can live beside a stock Krita on the same machine without sharing its
# settings, resources, caches, logs, autosaves, single-instance channel, macOS bundle identifier or file types.
#
# KRITA_APP_SETTINGS_FOLDER is the one folder name everything per-user goes under:
#   config (kritarc, kritadisplayrc, kritashortcutsrc, ...)  <GenericConfigLocation>/<folder>/
#   resources and resource database                          <GenericDataLocation>/<folder>/krita/
#   caches                                                   <GenericCacheLocation>/<folder>/krita/
#   krita.log, krita-sysinfo.log, kritacrash.log             <GenericDataLocation>/<folder>/
#   autosaves of never-saved documents                       <GenericDataLocation>/<folder>/autosave/
# On macOS that is ~/Library/Preferences/<folder>, ~/Library/Application Support/<folder> and ~/Library/Caches/<folder>.
#
# Leave it empty for stock Krita: every other value below then defaults to upstream's (org.krita, krita.org, "Krita",
# the macOS integration extensions on), and the code behaves exactly as upstream.
#
# This file also provides krita_app_identity_info_plist() for krita/CMakeLists.txt, and, run as a script
# (cmake -DINFO_PLIST=<built Info.plist> [-DBUNDLE_ID=<id>] -P KritaAppIdentity.cmake), checks a built Info.plist.

# A built Info.plist (or its template) for a build with its own identity: it must never claim Krita's file types.
#   - no LSHandlerRank Owner or Default (the app opens Krita files only as an alternate app);
#   - no UTExportedTypeDeclarations (exporting declares the app as the types' owner: stock Krita is);
#   - at most one UTImportedTypeDeclarations.
function(krita_app_identity_check_plist plist where)
    set(problems)
    if (plist MATCHES "<key>LSHandlerRank</key>[ \t\r\n]*<string>(Owner|Default)</string>")
        list(APPEND problems "an LSHandlerRank of ${CMAKE_MATCH_1}")
    endif()
    if (plist MATCHES "UTExportedTypeDeclarations")
        list(APPEND problems "UTExportedTypeDeclarations")
    endif()
    string(REGEX MATCHALL "<key>UTImportedTypeDeclarations</key>" imported "${plist}")
    list(LENGTH imported imported_count)
    if (imported_count GREATER 1)
        list(APPEND problems "${imported_count} UTImportedTypeDeclarations keys")
    endif()
    if (problems)
        string(REPLACE ";" ", " problems "${problems}")
        message(FATAL_ERROR "${where} still claims Krita's file types (${problems}). A build with its own identity "
                            "must not: has upstream's Info.plist.template changed? Update krita_app_identity_info_plist() "
                            "in cmake/modules/KritaAppIdentity.cmake.")
    endif()
endfunction()

if (CMAKE_SCRIPT_MODE_FILE)
    if (NOT INFO_PLIST)
        message(FATAL_ERROR "Usage: cmake -DINFO_PLIST=<Info.plist> [-DBUNDLE_ID=<id>] -P KritaAppIdentity.cmake")
    endif()
    if (NOT EXISTS "${INFO_PLIST}")
        message(FATAL_ERROR "${INFO_PLIST} does not exist: build the krita target first")
    endif()
    file(READ "${INFO_PLIST}" plist)
    krita_app_identity_check_plist("${plist}" "${INFO_PLIST}")
    if (BUNDLE_ID AND NOT plist MATCHES "<key>CFBundleIdentifier</key>[ \t\r\n]*<string>${BUNDLE_ID}</string>")
        message(FATAL_ERROR "${INFO_PLIST}: CFBundleIdentifier is not ${BUNDLE_ID}")
    endif()
    find_program(PLUTIL plutil)
    if (PLUTIL)
        execute_process(COMMAND "${PLUTIL}" -lint "${INFO_PLIST}" RESULT_VARIABLE lint_result)
        if (NOT lint_result EQUAL 0)
            message(FATAL_ERROR "${INFO_PLIST} is not a valid property list")
        endif()
    endif()
    message(STATUS "${INFO_PLIST}: claims none of Krita's file types")
    return()
endif()

set(KRITA_APP_SETTINGS_FOLDER "KritaAgent" CACHE STRING
    "Folder name this build keeps its own settings, resources, caches, logs and autosaves in (empty: stock Krita's)")
if (KRITA_APP_SETTINGS_FOLDER MATCHES "[/\\\\\"]" OR KRITA_APP_SETTINGS_FOLDER MATCHES "^\\.\\.?$")
    message(FATAL_ERROR "KRITA_APP_SETTINGS_FOLDER '${KRITA_APP_SETTINGS_FOLDER}' must be a single folder name, "
                        "without '/', '\\' or '\"'")
endif()

# The other values default from the folder (empty cache value: derived). "KritaAgent" gives "Toska" (see below),
# kritaagent.local and local.kritaagent; no folder gives upstream's "Krita", krita.org and org.krita.
set(KRITA_APP_DISPLAY_NAME "" CACHE STRING "Application name shown to the user (empty: from the settings folder)")
set(KRITA_APP_ORGANIZATION_DOMAIN "" CACHE STRING "Organization domain (empty: from the settings folder)")
set(KRITA_MACOS_BUNDLE_ID "" CACHE STRING "macOS bundle identifier (empty: from the settings folder)")
set(KRITA_MACOS_BUNDLE_NAME "" CACHE STRING "macOS bundle name shown in the menu bar (empty: the display name)")
set(KRITA_BUILD_MACOS_INTEGRATION "AUTO" CACHE STRING
    "macOS Quick Look, thumbnail and Spotlight extensions (need Xcode, claim Krita's types): ON, OFF or AUTO (ON for stock Krita, OFF with a settings folder)")

# The build named Toska: the settings folder "KritaAgent" (see the display name below). Compared as a string, never by
# the truthiness of a folder name (CMake reads "Off", "No", "False", ... as false).
set(_identity_is_toska FALSE)
if (DEFINED KRITA_APP_SETTINGS_FOLDER AND "${KRITA_APP_SETTINGS_FOLDER}" STREQUAL "KritaAgent")
    set(_identity_is_toska TRUE)
endif()

# One-time migration of build folders configured before the rename: an older version of this file wrote its derived
# name "Krita Agent" into the cache, and CMake keeps a cache value, so those folders stayed "Krita Agent" (window
# titles, the About box, KAboutData, the menu bar) while KRITA_APP_OWN_SPLASH said Toska. Only that exact old default,
# and only for the folder named Toska, is reset to empty (derived again: Toska); any other value someone set is kept.
if (_identity_is_toska)
    set(_identity_reset_names)
    if ("$CACHE{KRITA_APP_DISPLAY_NAME}" STREQUAL "Krita Agent")
        set(KRITA_APP_DISPLAY_NAME "" CACHE STRING "Application name shown to the user (empty: from the settings folder)" FORCE)
        unset(KRITA_APP_DISPLAY_NAME)
        list(APPEND _identity_reset_names KRITA_APP_DISPLAY_NAME)
    endif()
    if ("$CACHE{KRITA_MACOS_BUNDLE_NAME}" STREQUAL "Krita Agent")
        set(KRITA_MACOS_BUNDLE_NAME "" CACHE STRING "macOS bundle name shown in the menu bar (empty: the display name)" FORCE)
        unset(KRITA_MACOS_BUNDLE_NAME)
        list(APPEND _identity_reset_names KRITA_MACOS_BUNDLE_NAME)
    endif()
    if (_identity_reset_names)
        string(REPLACE ";" ", " _identity_reset_names "${_identity_reset_names}")
        message(STATUS "App identity: reset the old derived name \"Krita Agent\" in the cache (${_identity_reset_names}); "
                       "this build is named Toska")
    endif()
endif()

# KRITA_APP_OWN_SPLASH (0 or 1) is the one value that decides Toska's splash screen: krita/CMakeLists.txt picks
# krita/data/splash/splash-toska.qrc by it, and config-app-identity.h hands it to KisAppIdentity::hasOwnSplash(), which
# every splash branch in libs/ui/kis_splash_screen.cpp reads. Only the build named Toska, and never Android (whose
# splash-android.qrc has no Toska art): any other build keeps upstream's splash.
set(KRITA_APP_OWN_SPLASH 0)
if (_identity_is_toska AND NOT ANDROID)
    set(KRITA_APP_OWN_SPLASH 1)
endif()

# KRITA_APP_OWN_WELCOME (0 or 1) decides Toska's welcome page background the same way: krita/CMakeLists.txt compiles
# krita/data/welcome/welcome-toska.qrc into the app by it, and config-app-identity.h hands it to
# KisAppIdentity::hasOwnWelcome(), which libs/ui/KisWelcomePageWidget.cpp reads. Only the build named Toska, and never
# Android (whose welcome page keeps upstream's donation banner): any other build has no :/welcome resource at all.
set(KRITA_APP_OWN_WELCOME 0)
if (_identity_is_toska AND NOT ANDROID)
    set(KRITA_APP_OWN_WELCOME 1)
endif()

# KRITA_APP_DEFAULT_THEME is the colour theme a new install opens with, by the theme's name ([General] Name in a
# krita/data/themes/*.colors file). Empty: the shipped krita/data/kritarc's own [theme] Theme ("Krita dark"), which stock
# Krita and every other identity keep. The build named Toska opens with "Toska Night"; the value goes into the identity's
# own copy of kritarc below, read under the artist's kritarc, so a theme the artist has chosen (saved) always wins.
set(KRITA_APP_DEFAULT_THEME "")
if (_identity_is_toska)
    set(KRITA_APP_DEFAULT_THEME "Toska Night")
endif()

if (KRITA_APP_SETTINGS_FOLDER)
    string(REGEX REPLACE "([a-z0-9])([A-Z])" "\\1 \\2" _identity_display_name "${KRITA_APP_SETTINGS_FOLDER}")
    # The product the artist sees is Toska (named 2026-10-20). Its settings folder and bundle id are still the ones it
    # started with, "KritaAgent" and local.kritaagent: renaming them moves the artist's profile, a later migration
    # (AGENT-FORK.md, "Product name: Toska"). So this folder, and only this one, shows as Toska. Any other folder keeps
    # the name derived from it, which is what a differently named build or a test identity wants.
    if (_identity_is_toska)
        set(_identity_display_name "Toska")
    endif()
    string(TOLOWER "${KRITA_APP_SETTINGS_FOLDER}" _identity_id)
    string(REGEX REPLACE "[^a-z0-9-]" "" _identity_id "${_identity_id}")
    if (NOT _identity_id)
        set(_identity_id "kritaapp")
    endif()
    set(_identity_domain "${_identity_id}.local")
    set(_identity_bundle_id "local.${_identity_id}")
    set(_identity_integration OFF)
else()
    set(_identity_display_name "Krita")
    set(_identity_domain "krita.org")
    set(_identity_bundle_id "org.krita")
    set(_identity_integration ON)
endif()

# Normal variables shadow the cache entries for the rest of the configure run.
if (NOT KRITA_APP_DISPLAY_NAME)
    set(KRITA_APP_DISPLAY_NAME "${_identity_display_name}")
endif()
if (NOT KRITA_APP_ORGANIZATION_DOMAIN)
    set(KRITA_APP_ORGANIZATION_DOMAIN "${_identity_domain}")
endif()
if (NOT KRITA_MACOS_BUNDLE_ID)
    set(KRITA_MACOS_BUNDLE_ID "${_identity_bundle_id}")
endif()
if (NOT KRITA_MACOS_BUNDLE_NAME)
    set(KRITA_MACOS_BUNDLE_NAME "${KRITA_APP_DISPLAY_NAME}")
endif()
if (KRITA_BUILD_MACOS_INTEGRATION STREQUAL "AUTO" OR KRITA_BUILD_MACOS_INTEGRATION STREQUAL "")
    set(KRITA_BUILD_MACOS_INTEGRATION ${_identity_integration})
elseif (KRITA_BUILD_MACOS_INTEGRATION)
    set(KRITA_BUILD_MACOS_INTEGRATION ON)
else()
    set(KRITA_BUILD_MACOS_INTEGRATION OFF)
endif()

# Krita ships its config defaults as :/kconfig/kritarc (krita/krita.qrc). With its own identity the main config is
# "<folder>/kritarc", and KConfig looks for its shipped defaults at :/kconfig/<folder>/kritarc: give it that alias.
# Compiled into the krita target (krita/CMakeLists.txt) and KisAppIdentityTest.
# With a KRITA_APP_DEFAULT_THEME the alias points at a copy of krita/data/kritarc in the build folder that differs in
# that one line; stock Krita's :/kconfig/kritarc is always the source file itself, unchanged.
set(KRITA_APP_IDENTITY_QRC "")
set(KRITA_APP_IDENTITY_KRITARC "")
if (KRITA_APP_SETTINGS_FOLDER)
    # The source tree from this file's place (cmake/modules), so cmake -P harnesses find it too
    get_filename_component(_identity_source_dir "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
    set(KRITA_APP_IDENTITY_KRITARC "${_identity_source_dir}/krita/data/kritarc")
    if (NOT KRITA_APP_DEFAULT_THEME STREQUAL "")
        if (KRITA_APP_DEFAULT_THEME MATCHES "[\r\n]")
            message(FATAL_ERROR "KRITA_APP_DEFAULT_THEME must be one line")
        endif()
        set(KRITA_APP_IDENTITY_KRITARC "${CMAKE_BINARY_DIR}/krita-app-identity-kritarc")
        # configure_file() makes a change to the source kritarc re-run CMake
        configure_file("${_identity_source_dir}/krita/data/kritarc" "${KRITA_APP_IDENTITY_KRITARC}.source" COPYONLY)
        file(READ "${KRITA_APP_IDENTITY_KRITARC}.source" _identity_kritarc)
        # Either line ending (a Windows checkout may have CRLF); the copy keeps the file's own
        string(REGEX MATCHALL "\n\\[theme\\]\r?\nTheme=[^\r\n]*\r?\n" _identity_theme_lines "\n${_identity_kritarc}")
        list(LENGTH _identity_theme_lines _identity_theme_count)
        if (NOT _identity_theme_count EQUAL 1)
            message(FATAL_ERROR "krita/data/kritarc must have exactly one '[theme]' group starting with a 'Theme=' line "
                                "(found ${_identity_theme_count}): KritaAppIdentity.cmake sets the default theme there")
        endif()
        string(REGEX REPLACE "\n\\[theme\\](\r?\n)Theme=[^\r\n]*(\r?\n)" "\n[theme]\\1Theme=${KRITA_APP_DEFAULT_THEME}\\2"
               _identity_kritarc "\n${_identity_kritarc}")
        string(SUBSTRING "${_identity_kritarc}" 1 -1 _identity_kritarc)
        # file(READ) drops the CR of CRLF line endings: write them back when the source has them
        file(READ "${KRITA_APP_IDENTITY_KRITARC}.source" _identity_kritarc_hex HEX)
        string(FIND "${_identity_kritarc_hex}" "0d0a" _identity_crlf_at)
        math(EXPR _identity_crlf_odd "${_identity_crlf_at} % 2")
        if (_identity_crlf_at GREATER -1 AND _identity_crlf_odd EQUAL 0)
            if (_identity_kritarc MATCHES "@")
                message(FATAL_ERROR "krita/data/kritarc has CRLF line endings and an '@', which the CRLF copy in "
                                    "KritaAppIdentity.cmake (file(CONFIGURE @ONLY)) would substitute")
            endif()
            file(CONFIGURE OUTPUT "${KRITA_APP_IDENTITY_KRITARC}.in" CONTENT "${_identity_kritarc}" @ONLY NEWLINE_STYLE CRLF)
        else()
            file(WRITE "${KRITA_APP_IDENTITY_KRITARC}.in" "${_identity_kritarc}")
        endif()
        configure_file("${KRITA_APP_IDENTITY_KRITARC}.in" "${KRITA_APP_IDENTITY_KRITARC}" COPYONLY)
    endif()
    set(KRITA_APP_IDENTITY_QRC "${CMAKE_BINARY_DIR}/krita-app-identity.qrc")
    file(WRITE "${KRITA_APP_IDENTITY_QRC}.in"
        "<!-- Generated by cmake/modules/KritaAppIdentity.cmake -->\n"
        "<RCC>\n"
        "    <qresource prefix=\"/kconfig/${KRITA_APP_SETTINGS_FOLDER}\">\n"
        "        <file alias=\"kritarc\">${KRITA_APP_IDENTITY_KRITARC}</file>\n"
        "    </qresource>\n"
        "</RCC>\n")
    configure_file("${KRITA_APP_IDENTITY_QRC}.in" "${KRITA_APP_IDENTITY_QRC}" COPYONLY)
endif()

# krita_app_identity_info_plist(<template> <output variable>)
# Sets <output variable> to the Info.plist template the krita bundle uses: the template itself for stock Krita;
# with a settings folder, a copy in the build folder that never claims Krita's file types (see
# krita_app_identity_check_plist()). Configuring fails if the rewrite leaves a claim behind, and re-runs when the
# template changes.
function(krita_app_identity_info_plist template output)
    if (NOT KRITA_APP_SETTINGS_FOLDER)
        set(${output} "${template}" PARENT_SCOPE)
        return()
    endif()
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${template}")
    file(READ "${template}" plist)
    # Opens Krita files only when asked: never their default app
    string(REGEX REPLACE "(<key>LSHandlerRank</key>[ \t\r\n]*<string>)(Owner|Default)(</string>)"
           "\\1Alternate\\3" plist "${plist}")
    # Krita's own types (.kra, .krz, .kpp, .ora) are stock Krita's to declare: import them, as the template already
    # imports GIMP's. The template lists the exported declarations right before the imported ones, so the two arrays
    # merge into one.
    set(exported_key "<key>UTExportedTypeDeclarations</key>")
    set(imported_key "<key>UTImportedTypeDeclarations</key>")
    string(FIND "${plist}" "${exported_key}" exported_at)
    string(FIND "${plist}" "${imported_key}" imported_at)
    if (NOT exported_at EQUAL -1 AND imported_at EQUAL -1)
        string(REPLACE "${exported_key}" "${imported_key}" plist "${plist}")
    elseif (NOT exported_at EQUAL -1)
        string(LENGTH "${exported_key}" exported_length)
        string(LENGTH "${imported_key}" imported_length)
        math(EXPR between_at "${exported_at} + ${exported_length}")
        math(EXPR between_length "${imported_at} - ${between_at}")
        math(EXPR tail_at "${imported_at} + ${imported_length}")
        if (between_length LESS 0)
            message(FATAL_ERROR "${template}: UTImportedTypeDeclarations now comes before UTExportedTypeDeclarations. "
                                "Update krita_app_identity_info_plist() in cmake/modules/KritaAppIdentity.cmake.")
        endif()
        string(SUBSTRING "${plist}" 0 ${exported_at} head)
        string(SUBSTRING "${plist}" ${between_at} ${between_length} between)
        string(SUBSTRING "${plist}" ${tail_at} -1 tail)
        # Only type declarations may lie between the two keys
        string(REGEX REPLACE "<key>(UTType[A-Za-z]*|public\\.[a-z.-]*)</key>" "" between_other_keys "${between}")
        if (between_other_keys MATCHES "<key>")
            message(FATAL_ERROR "${template}: something other than type declarations lies between "
                                "UTExportedTypeDeclarations and UTImportedTypeDeclarations. "
                                "Update krita_app_identity_info_plist() in cmake/modules/KritaAppIdentity.cmake.")
        endif()
        string(REGEX REPLACE "</array>[ \t\r\n]*$" "" between "${between}")
        string(REGEX REPLACE "^[ \t\r\n]*<array>" "" tail "${tail}")
        set(plist "${head}${imported_key}${between}${tail}")
    endif()
    krita_app_identity_check_plist("${plist}" "The Info.plist made from ${template}")
    set(rewritten "${CMAKE_CURRENT_BINARY_DIR}/Info.plist.template")
    file(WRITE "${rewritten}.in" "${plist}")
    configure_file("${rewritten}.in" "${rewritten}" COPYONLY)
    find_program(PLUTIL plutil)
    if (PLUTIL)
        execute_process(COMMAND "${PLUTIL}" -lint "${rewritten}" RESULT_VARIABLE lint_result OUTPUT_QUIET)
        if (NOT lint_result EQUAL 0)
            message(FATAL_ERROR "${rewritten} is not a valid property list: see krita_app_identity_info_plist()")
        endif()
    endif()
    set(${output} "${rewritten}" PARENT_SCOPE)
endfunction()

if (KRITA_APP_SETTINGS_FOLDER)
    message(STATUS "App identity: ${KRITA_APP_DISPLAY_NAME}, settings folder '${KRITA_APP_SETTINGS_FOLDER}', "
                   "organization domain ${KRITA_APP_ORGANIZATION_DOMAIN}, bundle id ${KRITA_MACOS_BUNDLE_ID}, "
                   "macOS integration ${KRITA_BUILD_MACOS_INTEGRATION}")
endif()
