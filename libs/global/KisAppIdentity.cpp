/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "KisAppIdentity.h"

#include <QCoreApplication>
#include <QDir>
#include <QStandardPaths>

#include <KConfig>

#include "config-app-identity.h"

namespace
{
QString withFolder(const QString &base)
{
    const QString folder = KisAppIdentity::settingsFolder();
    if (folder.isEmpty()) {
        return base;
    }
    const QString path = base + QLatin1Char('/') + folder;
    QDir().mkpath(path);
    return path;
}
}

void KisAppIdentity::initialize()
{
    const QString folder = settingsFolder();
    if (folder.isEmpty()) {
        return;
    }
    // Qt puts AppDataLocation and CacheLocation under <organization>/<application> (the application stays "krita",
    // so installed data, translations and xmlgui files are found as before).
    QCoreApplication::setOrganizationName(folder);
    // KSharedConfig::openConfig() with no name, i.e. Krita's main config, resolves this against GenericConfigLocation.
    KConfig::setMainConfigName(configFileName(QStringLiteral("kritarc")));
    QDir().mkpath(configLocation());
}

QString KisAppIdentity::settingsFolder()
{
    return QStringLiteral(KRITA_APP_SETTINGS_FOLDER);
}

QString KisAppIdentity::displayName()
{
    const QString name = QStringLiteral(KRITA_APP_DISPLAY_NAME);
    return name.isEmpty() ? QStringLiteral("Krita") : name;
}

QString KisAppIdentity::organizationDomain()
{
    const QString domain = QStringLiteral(KRITA_APP_ORGANIZATION_DOMAIN);
    return domain.isEmpty() ? QStringLiteral("krita.org") : domain;
}

QString KisAppIdentity::configLocation()
{
    return withFolder(QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation));
}

QString KisAppIdentity::configFileName(const QString &name)
{
    const QString folder = settingsFolder();
    return folder.isEmpty() ? name : folder + QLatin1Char('/') + name;
}

QString KisAppIdentity::logLocation()
{
    return withFolder(QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation));
}
