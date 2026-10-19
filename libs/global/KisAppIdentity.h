/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef KISAPPIDENTITY_H
#define KISAPPIDENTITY_H

#include <QString>

#include "kritaglobal_export.h"

/**
 * The identity this build runs under, so that a differently named build (KRITA_APP_SETTINGS_FOLDER at configure time)
 * can run beside a stock Krita without reading or writing its settings, resources, caches, logs or autosaves.
 *
 * With an empty settings folder every function returns stock Krita's value, so code that uses these instead of
 * QStandardPaths directly behaves exactly as before.
 */
namespace KisAppIdentity
{
/// Call first thing in main(), before anything reads a setting or a standard path. With a settings folder it sets the
/// organization name (which moves AppDataLocation and CacheLocation into the settings folder) and KConfig's main
/// config file, and creates the config, log and autosave folders once. With an empty folder it does nothing.
KRITAGLOBAL_EXPORT void initialize();

/// The folder name everything per-user goes under; empty for stock Krita.
KRITAGLOBAL_EXPORT QString settingsFolder();

/// The application name shown to the user ("Krita" for stock Krita).
KRITAGLOBAL_EXPORT QString displayName();

/// The organization domain ("krita.org" for stock Krita).
KRITAGLOBAL_EXPORT QString organizationDomain();

/// Where kritarc, kritadisplayrc and the other config files live: GenericConfigLocation, plus the settings folder.
KRITAGLOBAL_EXPORT QString configLocation();

/// A config file name for KConfig, which resolves relative names against GenericConfigLocation:
/// "kritarc" for stock Krita, "<folder>/kritarc" otherwise.
KRITAGLOBAL_EXPORT QString configFileName(const QString &name);

/// Where krita.log and krita-sysinfo.log live: GenericDataLocation, plus the settings folder.
KRITAGLOBAL_EXPORT QString logLocation();

/// Where kritacrash.log lives: GenericConfigLocation for stock Krita (as upstream), the log folder otherwise.
KRITAGLOBAL_EXPORT QString crashLogLocation();

/// Where autosaves of never-saved documents go, and where the crash recovery looks for them: the settings folder's
/// "autosave" folder under GenericDataLocation. Empty for stock Krita, whose location is platform dependent
/// (KisAutoSaveRecoveryDialog::autoSaveLocation()). Never the home folder or the temporary folder, so a build with
/// its own identity never recovers or deletes stock Krita's autosaves, nor stock Krita its.
KRITAGLOBAL_EXPORT QString autosaveLocation();

/// For tests only: run as if configured with this settings folder (empty: stock Krita). Forgets the paths cached by
/// initialize(); call initialize() again to cache and create them.
KRITAGLOBAL_EXPORT void setSettingsFolderForTesting(const QString &folder);
}

#endif // KISAPPIDENTITY_H
