/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "KisAutoSaveLocationTest.h"

#include <QCoreApplication>
#include <QDir>
#include <QStandardPaths>
#include <QTest>

#include <KisAppIdentity.h>
#include <KisAutoSaveRecoveryDialog.h>

#include "KisTemporaryHomeTest.h"

// KisAutoSaveRecoveryDialog::autoSaveLocation() is where KisDocument writes the autosaves of never-saved documents and
// where KisApplication::checkAutosaveFiles() looks for krita-*-*-autosave.kra on start, deleting those not recovered.

void KisAutoSaveLocationTest::cleanup()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
    QCoreApplication::setOrganizationName(QString());
}

void KisAutoSaveLocationTest::testStockLocationIsUpstreams()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
    KisAppIdentity::initialize();
#if defined(Q_OS_WIN)
    QCOMPARE(KisAutoSaveRecoveryDialog::autoSaveLocation(), QDir::tempPath());
#elif !defined(Q_OS_ANDROID)
    QCOMPARE(KisAutoSaveRecoveryDialog::autoSaveLocation(), QDir::homePath());
#endif
}

void KisAutoSaveLocationTest::testOwnIdentityNeverUsesStocksLocation()
{
    KisAppIdentity::setSettingsFolderForTesting(QStringLiteral("KritaAgentTest"));
    KisAppIdentity::initialize();

    const QString location = QDir::cleanPath(KisAutoSaveRecoveryDialog::autoSaveLocation());
    QCOMPARE(location, QDir::cleanPath(KisAppIdentity::autosaveLocation()));
    QVERIFY(location != QDir::cleanPath(QDir::homePath()));
    QVERIFY(location != QDir::cleanPath(QDir::tempPath()));
    QVERIFY(KisTemporaryHomeTest::isInside(
        location, QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/KritaAgentTest"));
    QVERIFY(QDir(location).exists());
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisAutoSaveLocationTest)
