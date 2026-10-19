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
 * can run beside a stock Krita without reading or writing its settings, resources, caches or logs.
 *
 * With an empty settings folder every function returns stock Krita's value, so code that uses these instead of
 * QStandardPaths directly behaves exactly as before.
 */
namespace KisAppIdentity
{
/// Call first thing in main(), before anything reads a setting or a standard path. Sets the organization name
/// (which moves AppDataLocation and CacheLocation into the settings folder) and KConfig's main config file.
KRITAGLOBAL_EXPORT void initialize();

/// The folder name everything per-user goes under; empty for stock Krita.
KRITAGLOBAL_EXPORT QString settingsFolder();

/// The application name shown to the user ("Krita" for stock Krita).
KRITAGLOBAL_EXPORT QString displayName();

/// The organization domain ("krita.org" for stock Krita).
KRITAGLOBAL_EXPORT QString organizationDomain();

/// Where kritarc, kritadisplayrc and the other config files live: GenericConfigLocation, plus the settings folder.
/// Created if missing.
KRITAGLOBAL_EXPORT QString configLocation();

/// A config file name for KConfig, which resolves relative names against GenericConfigLocation:
/// "kritarc" for stock Krita, "<folder>/kritarc" otherwise.
KRITAGLOBAL_EXPORT QString configFileName(const QString &name);

/// Where krita.log, krita-sysinfo.log and kritacrash.log live: GenericDataLocation, plus the settings folder.
/// Created if missing.
KRITAGLOBAL_EXPORT QString logLocation();
}

#endif // KISAPPIDENTITY_H
