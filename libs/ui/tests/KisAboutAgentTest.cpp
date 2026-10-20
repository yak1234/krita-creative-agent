/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisAboutAgentTest.h"

#include <QTest>

#include <KisAppIdentity.h>
#include <dialogs/KisAboutAgent.h>

void KisAboutAgentTest::cleanup()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
}

void KisAboutAgentTest::testRecordValue()
{
    // The text agent/package_notices.py writes to Resources/BUILD.txt
    const QString record = QStringLiteral("Toska\nbuild commit: abc123\npublic commit: not published yet\n"
                                          "source: https://example.org/repo\nnotes: none\n");
    QCOMPARE(KisAboutAgent::recordValue(record, QStringLiteral("build commit")), QStringLiteral("abc123"));
    QCOMPARE(KisAboutAgent::recordValue(record, QStringLiteral("source")), QStringLiteral("https://example.org/repo"));
    QCOMPARE(KisAboutAgent::recordValue(record, QStringLiteral("public commit")), QStringLiteral("not published yet"));
    QVERIFY(KisAboutAgent::recordValue(record, QStringLiteral("missing")).isEmpty());
    QVERIFY(KisAboutAgent::recordValue(QString(), QStringLiteral("source")).isEmpty());
}

void KisAboutAgentTest::testStockKritaGetsNothing()
{
    KisAppIdentity::setSettingsFolderForTesting(QString());
    QVERIFY(KisAboutAgent::windowTitle().isEmpty());
    QVERIFY(KisAboutAgent::licenseHtml().isEmpty());
    QVERIFY(KisAboutAgent::aboutActionText().isEmpty());
    QVERIFY(KisAboutAgent::shortDescription().isEmpty());
}

void KisAboutAgentTest::testOwnIdentityGetsATitleAndALicenseBlock()
{
    // Only licenseHtmlFromRecord() is used: licenseHtml() asks KoResourcePaths for the application root, which aborts on macOS
    // in a plain ctest run (nothing sets KIS_TEST_PREFIX_PATH).
    KisAppIdentity::setSettingsFolderForTesting(QStringLiteral("KritaAgentTest"));
    QVERIFY(!KisAboutAgent::windowTitle().isEmpty());

    // The window, the menu entry and the description carry the build's display name (Toska for the Toska build)...
    const QString name = KisAppIdentity::displayName();
    QVERIFY(!name.isEmpty());
    QVERIFY(KisAboutAgent::windowTitle().contains(name));
    QVERIFY(KisAboutAgent::aboutActionText().contains(name));
    QVERIFY(KisAboutAgent::shortDescription().contains(name));
    // ...and say where it comes from
    QVERIFY(KisAboutAgent::shortDescription().contains(QStringLiteral("Krita")));

    // an unpackaged build: no record
    QString html = KisAboutAgent::licenseHtmlFromRecord(QString());
    QVERIFY(html.contains(QStringLiteral("GPL")));
    QVERIFY(html.contains(QStringLiteral("Corresponding source")));
    QVERIFY(!html.contains(QStringLiteral("https://example.org/repo")));
    QVERIFY(html.contains(name));

    // The upstream credit stays: based on Krita, with its link, and the licence
    QVERIFY(html.contains(QStringLiteral("based on")));
    QVERIFY(html.contains(QStringLiteral("<a href=\"https://krita.org\">Krita</a>")));
    QVERIFY(html.contains(QStringLiteral("GNU General Public License")));
    QVERIFY(html.contains(QStringLiteral("Krita is GPL-2.0-or-later")));

    // a packaged, published build: the public commit and the address from BUILD.txt
    const QString record = QStringLiteral("Toska\nbuild commit: aaa111\npublic commit: bbb222\n"
                                          "source: https://example.org/repo\nnotes: none\n");
    html = KisAboutAgent::licenseHtmlFromRecord(record);
    QVERIFY(html.contains(QStringLiteral("bbb222")));
    QVERIFY(html.contains(QStringLiteral("https://example.org/repo")));
    QVERIFY(!html.contains(QStringLiteral("not published yet")));

    // not published yet: the build commit, and it says so
    html = KisAboutAgent::licenseHtmlFromRecord(QStringLiteral("build commit: aaa111\npublic commit: not published yet\n"
                                                               "source: https://example.org/repo\nnotes: stale build\n"));
    QVERIFY(html.contains(QStringLiteral("aaa111")));
    QVERIFY(html.contains(QStringLiteral("not published yet")));
    QVERIFY(html.contains(QStringLiteral("stale build")));
}

QTEST_GUILESS_MAIN(KisAboutAgentTest)
