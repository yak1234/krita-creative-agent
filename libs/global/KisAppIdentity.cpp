/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "KisAppIdentity.h"

#include <QCoreApplication>
#include <QDir>
#include <QGlobalStatic>
#include <QStandardPaths>

#include <KConfig>

#include "config-app-identity.h"

namespace
{
struct Identity {
    QString folder = QStringLiteral(KRITA_APP_SETTINGS_FOLDER);
    // Cached by initialize(), which creates the folders once
    QString configLocation;
    QString logLocation;
    QString autosaveLocation;
};

Q_GLOBAL_STATIC(Identity, s_identity)

QString inFolder(QStandardPaths::StandardLocation base, const QString &subfolder = QString())
{
    QString path = QStandardPaths::writableLocation(base) + QLatin1Char('/') + s_identity->folder;
    if (!subfolder.isEmpty()) {
        path += QLatin1Char('/') + subfolder;
    }
    return path;
}

QString ownConfigLocation()
{
    return inFolder(QStandardPaths::GenericConfigLocation);
}

QString ownLogLocation()
{
    return inFolder(QStandardPaths::GenericDataLocation);
}

QString ownAutosaveLocation()
{
    return inFolder(QStandardPaths::GenericDataLocation, QStringLiteral("autosave"));
}

QString cached(const QString &value, QString (*compute)())
{
    return value.isEmpty() ? compute() : value;
}
}

void KisAppIdentity::initialize()
{
    Identity *identity = s_identity;
    if (identity->folder.isEmpty()) {
        return;
    }
    // Qt puts AppDataLocation and CacheLocation under <organization>/<application>. The application stays "krita",
    // so installed data, translations and xmlgui files are found where upstream finds them (tested on macOS only).
    QCoreApplication::setOrganizationName(identity->folder);
    // KSharedConfig::openConfig() with no name, i.e. Krita's main config, resolves this against GenericConfigLocation.
    // Its shipped defaults are found as :/kconfig/<folder>/kritarc (cmake/modules/KritaAppIdentity.cmake).
    KConfig::setMainConfigName(configFileName(QStringLiteral("kritarc")));

    identity->configLocation = ownConfigLocation();
    identity->logLocation = ownLogLocation();
    identity->autosaveLocation = ownAutosaveLocation();
    QDir().mkpath(identity->configLocation);
    QDir().mkpath(identity->logLocation);
    QDir().mkpath(identity->autosaveLocation);
}

QString KisAppIdentity::settingsFolder()
{
    return s_identity->folder;
}

QString KisAppIdentity::displayName()
{
    const QString name = QStringLiteral(KRITA_APP_DISPLAY_NAME);
    return name.isEmpty() ? QStringLiteral("Krita") : name;
}

bool KisAppIdentity::hasOwnSplash()
{
    return KRITA_APP_OWN_SPLASH != 0;
}

QString KisAppIdentity::organizationDomain()
{
    const QString domain = QStringLiteral(KRITA_APP_ORGANIZATION_DOMAIN);
    return domain.isEmpty() ? QStringLiteral("krita.org") : domain;
}

QString KisAppIdentity::configLocation()
{
    if (s_identity->folder.isEmpty()) {
        return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation);
    }
    return cached(s_identity->configLocation, ownConfigLocation);
}

QString KisAppIdentity::configFileName(const QString &name)
{
    const QString folder = settingsFolder();
    return folder.isEmpty() ? name : folder + QLatin1Char('/') + name;
}

QString KisAppIdentity::logLocation()
{
    if (s_identity->folder.isEmpty()) {
        return QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation);
    }
    return cached(s_identity->logLocation, ownLogLocation);
}

QString KisAppIdentity::crashLogLocation()
{
    if (s_identity->folder.isEmpty()) {
        return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation);
    }
    return logLocation();
}

QString KisAppIdentity::autosaveLocation()
{
    if (s_identity->folder.isEmpty()) {
        return QString();
    }
    return cached(s_identity->autosaveLocation, ownAutosaveLocation);
}

void KisAppIdentity::setSettingsFolderForTesting(const QString &folder)
{
    Identity *identity = s_identity;
    *identity = Identity();
    identity->folder = folder;
}
