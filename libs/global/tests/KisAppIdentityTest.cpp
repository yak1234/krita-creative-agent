/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "KisAppIdentityTest.h"

#include <QCoreApplication>
#include <QDir>
#include <QStandardPaths>
#include <QTest>
#include <QDebug>

#include <KConfig>
#include <KConfigGroup>
#include <KSharedConfig>

#include "KisAppIdentity.h"
#include "KisTemporaryHomeTest.h"
#include "config-app-identity.h"

namespace
{
const QString testFolder = QStringLiteral("KritaAgentTest");

QString generic(QStandardPaths::StandardLocation location)
{
    return QStandardPaths::writableLocation(location);
}

bool isInside(const QString &path, const QString &folder)
{
    return KisTemporaryHomeTest::isInside(path, folder);
}
}

void KisAppIdentityTest::init()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
    QCoreApplication::setOrganizationName(QString());
}

void KisAppIdentityTest::cleanup()
{
    init();
}

void KisAppIdentityTest::testStockLocationsAreUpstreams()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
    KisAppIdentity::initialize();

    QCOMPARE(KisAppIdentity::settingsFolder(), QString());
    QCOMPARE(QCoreApplication::organizationName(), QString());
    QCOMPARE(KisAppIdentity::configLocation(), generic(QStandardPaths::GenericConfigLocation));
    QCOMPARE(KisAppIdentity::configFileName(QStringLiteral("kritarc")), QStringLiteral("kritarc"));
    QCOMPARE(KisAppIdentity::logLocation(), generic(QStandardPaths::GenericDataLocation));
    // Upstream writes kritacrash.log to the config folder, krita.log to the data folder
    QCOMPARE(KisAppIdentity::crashLogLocation(), generic(QStandardPaths::GenericConfigLocation));
    // Empty: the caller keeps its own platform-dependent location (KisAutoSaveRecoveryDialog::autoSaveLocation())
    QCOMPARE(KisAppIdentity::autosaveLocation(), QString());
    QCOMPARE(generic(QStandardPaths::AppDataLocation),
             generic(QStandardPaths::GenericDataLocation) + QStringLiteral("/krita"));
}

void KisAppIdentityTest::testOwnLocationsAreUnderTheFolder()
{
    KisAppIdentity::setSettingsFolderForTesting(testFolder);
    // Before initialize() the paths are already right (computed, not cached)
    QCOMPARE(KisAppIdentity::configLocation(), generic(QStandardPaths::GenericConfigLocation) + "/" + testFolder);
    KisAppIdentity::initialize();

    QCOMPARE(QCoreApplication::organizationName(), testFolder);
    QCOMPARE(KConfig::mainConfigName(), testFolder + QStringLiteral("/kritarc"));
    QCOMPARE(KisAppIdentity::configFileName(QStringLiteral("kritashortcutsrc")), testFolder + "/kritashortcutsrc");

    struct Location {
        const char *name;
        QString path;
        QString stock;
        QString folder;
    };
    const QString configFolder = generic(QStandardPaths::GenericConfigLocation) + "/" + testFolder;
    const QString dataFolder = generic(QStandardPaths::GenericDataLocation) + "/" + testFolder;
    const QString cacheFolder = generic(QStandardPaths::GenericCacheLocation) + "/" + testFolder;
    const QList<Location> locations = {
        {"config", KisAppIdentity::configLocation(), generic(QStandardPaths::GenericConfigLocation), configFolder},
        {"log", KisAppIdentity::logLocation(), generic(QStandardPaths::GenericDataLocation), dataFolder},
        {"crash log", KisAppIdentity::crashLogLocation(), generic(QStandardPaths::GenericConfigLocation), dataFolder},
        {"autosave", KisAppIdentity::autosaveLocation(), QDir::homePath(), dataFolder},
        {"data", generic(QStandardPaths::AppDataLocation), generic(QStandardPaths::GenericDataLocation) + "/krita",
         dataFolder},
        {"cache", generic(QStandardPaths::CacheLocation), generic(QStandardPaths::GenericCacheLocation) + "/krita",
         cacheFolder},
    };
    for (const Location &location : locations) {
        qDebug() << location.name << location.path;
        QVERIFY2(location.path == location.folder || isInside(location.path, location.folder),
                 qPrintable(QString("%1 %2 is not under %3").arg(location.name, location.path, location.folder)));
        QVERIFY2(QDir::cleanPath(location.path) != QDir::cleanPath(location.stock),
                 qPrintable(QString("%1 %2 is stock Krita's").arg(location.name, location.path)));
    }
}

void KisAppIdentityTest::testOwnAutosaveLocationIsNeverHomeOrTemp()
{
    KisAppIdentity::setSettingsFolderForTesting(testFolder);
    KisAppIdentity::initialize();

    // Stock Krita keeps unsaved documents' autosaves in the home folder (Linux, macOS) or the temporary folder
    // (Windows), and on start offers every krita-*-*-autosave.kra there for recovery, deleting those not recovered.
    // A build with its own identity must look somewhere else, so neither ever deletes the other's.
    const QString autosave = QDir::cleanPath(KisAppIdentity::autosaveLocation());
    QVERIFY(!autosave.isEmpty());
    QVERIFY(autosave != QDir::cleanPath(QDir::homePath()));
    QVERIFY(autosave != QDir::cleanPath(QDir::tempPath()));
    QVERIFY(isInside(autosave, generic(QStandardPaths::GenericDataLocation) + "/" + testFolder));
    QVERIFY(QDir(autosave).exists());
}

void KisAppIdentityTest::testInitializeCreatesTheFoldersOnce()
{
    KisAppIdentity::setSettingsFolderForTesting(testFolder);
    KisAppIdentity::initialize();

    const QString config = KisAppIdentity::configLocation();
    const QString log = KisAppIdentity::logLocation();
    const QString autosave = KisAppIdentity::autosaveLocation();
    QVERIFY(QDir(config).exists());
    QVERIFY(QDir(log).exists());
    QVERIFY(QDir(autosave).exists());

    // The getters return the cached paths: they never create folders again
    QVERIFY(QDir(config).removeRecursively());
    QCOMPARE(KisAppIdentity::configLocation(), config);
    QVERIFY(!QDir(config).exists());
    QVERIFY(QDir(log).removeRecursively());
    QCOMPARE(KisAppIdentity::logLocation(), log);
    QCOMPARE(KisAppIdentity::autosaveLocation(), autosave);
    QVERIFY(!QDir(log).exists());
}

void KisAppIdentityTest::testShippedConfigDefaultsAreRead()
{
    // krita.qrc ships Krita's defaults as :/kconfig/kritarc, which KConfig reads under any user kritarc. With its own
    // identity the main config is "<folder>/kritarc", so KConfig looks for :/kconfig/<folder>/kritarc instead.
    // (The temporary home holds no user kritarc, so a value can only come from the shipped file.)
    {
        KConfig stock(QStringLiteral("kritarc"));
        QCOMPARE(stock.group("advancedColorSelector").readEntry("commonColorsCount", -1), 12);
    }

    const QString configuredFolder = QStringLiteral(KRITA_APP_SETTINGS_FOLDER);
    if (configuredFolder.isEmpty()) {
        QSKIP("This build has no settings folder: the main config is the stock kritarc, checked above");
    }
    KisAppIdentity::setSettingsFolderForTesting(configuredFolder);
    KisAppIdentity::initialize();
    QCOMPARE(KConfig::mainConfigName(), configuredFolder + QStringLiteral("/kritarc"));

    KSharedConfigPtr main = KSharedConfig::openConfig();
    QCOMPARE(main->name(), configuredFolder + QStringLiteral("/kritarc"));
    QCOMPARE(main->group("advancedColorSelector").readEntry("commonColorsCount", -1), 12);
    QDir(KisAppIdentity::configLocation()).removeRecursively();
    QDir(KisAppIdentity::logLocation()).removeRecursively();
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisAppIdentityTest)
