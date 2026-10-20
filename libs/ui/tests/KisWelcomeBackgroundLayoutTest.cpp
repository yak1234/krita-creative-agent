/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisWelcomeBackgroundLayoutTest.h"

#include <QColor>
#include <QFileInfo>
#include <QImage>
#include <QList>
#include <QTest>

#include <KisAppIdentity.h>
#include <KisWelcomeBackgroundLayout.h>

namespace
{
// krita/data/welcome/toska/toska-welcome.jpg, and the red moon in it (measured on the artist's source)
const QSize kPainting(1774, 887);
const QRect kMoon(QPoint(1249, 106), QPoint(1305, 160));
}

void KisWelcomeBackgroundLayoutTest::testCoverKeepsTheAspectRatioAndStaysInside()
{
    const QList<QSize> pages = {QSize(1440, 900), QSize(2880, 1800), QSize(1200, 1000), QSize(1800, 520),
                                QSize(800, 1200), QSize(1774, 887), QSize(3548, 1774)};
    for (const QSize &page : pages) {
        const QRect source = KisWelcomeBackgroundLayout::coverSourceRect(kPainting, page);
        QVERIFY2(!source.isEmpty(), qPrintable(QString("%1x%2").arg(page.width()).arg(page.height())));
        QVERIFY(QRect(QPoint(), kPainting).contains(source));
        // the part drawn has the page's aspect ratio (no stretching), within the rounding of one source pixel
        const qreal pageRatio = qreal(page.width()) / page.height();
        QVERIFY(qAbs(qreal(source.width()) / source.height() - pageRatio) < pageRatio * 0.01);
        // it covers: one side of the painting is used whole
        QVERIFY(source.width() == kPainting.width() || source.height() == kPainting.height());
        // anchored right
        QCOMPARE(source.right(), kPainting.width() - 1);
    }
    // a page with the painting's own ratio draws all of it
    QCOMPARE(KisWelcomeBackgroundLayout::coverSourceRect(kPainting, QSize(1774, 887)), QRect(QPoint(), kPainting));
}

void KisWelcomeBackgroundLayoutTest::testAnchoredRightKeepsTheMoonInView()
{
    // from a portrait-ish page to a wide, short one (3.5:1)
    const QList<QSize> pages = {QSize(700, 1000), QSize(1200, 1000), QSize(1440, 900), QSize(1920, 1080),
                                QSize(2560, 1080), QSize(1750, 500)};
    for (const QSize &page : pages) {
        const QRect source = KisWelcomeBackgroundLayout::coverSourceRect(kPainting, page);
        QVERIFY2(source.contains(kMoon), qPrintable(QString("%1x%2").arg(page.width()).arg(page.height())));
    }
    // a narrow page crops the empty left side, never the right
    const QRect narrow = KisWelcomeBackgroundLayout::coverSourceRect(kPainting, QSize(1000, 1000));
    QVERIFY(narrow.left() > 0);
    QCOMPARE(narrow.right(), kPainting.width() - 1);
}

void KisWelcomeBackgroundLayoutTest::testEmptyInputsGiveNoRect()
{
    QVERIFY(KisWelcomeBackgroundLayout::coverSourceRect(QSize(), QSize(100, 100)).isEmpty());
    QVERIFY(KisWelcomeBackgroundLayout::coverSourceRect(kPainting, QSize()).isEmpty());
    QVERIFY(KisWelcomeBackgroundLayout::coverSourceRect(kPainting, QSize(0, 900)).isEmpty());
}

void KisWelcomeBackgroundLayoutTest::testLightThemesGetTheStrongerVeil()
{
    // Toska Night's window #141b25 and Toska Day's #efe8dc
    QCOMPARE(KisWelcomeBackgroundLayout::veilFor(QColor(0x14, 0x1b, 0x25).lightness()), KisWelcomeBackgroundLayout::kVeil);
    QCOMPARE(KisWelcomeBackgroundLayout::veilFor(QColor(0xef, 0xe8, 0xdc).lightness()), KisWelcomeBackgroundLayout::kVeilLight);
    QVERIFY(KisWelcomeBackgroundLayout::kVeil < KisWelcomeBackgroundLayout::kVeilLight);
    QVERIFY(KisWelcomeBackgroundLayout::kVeilLight < 1.0);
    // the left fade stays left of the middle, so the moon and the stroke are only veiled
    QVERIFY(KisWelcomeBackgroundLayout::kLeftFadeEnd < 0.5);
    QVERIFY(KisWelcomeBackgroundLayout::kLeftShade < 1.0);
}

void KisWelcomeBackgroundLayoutTest::testShippedPaintingDecodes()
{
    const QString path = QStringLiteral(TOSKA_WELCOME_DIR "/toska-welcome.jpg");
    QVERIFY2(QFileInfo::exists(path), qPrintable(path));
    QVERIFY(QFileInfo(path).size() <= 600 * 1024);
    const QImage image(path);
    QVERIFY2(!image.isNull(), "Qt cannot decode the welcome page background (is the jpeg image format plugin there?)");
    QCOMPARE(image.size(), kPainting);
    // the moon is where the layout test expects it: red and bright in its middle
    const QColor moon = image.pixelColor(kMoon.center());
    QVERIFY2(moon.red() > 200 && moon.red() > moon.blue() + 60, qPrintable(moon.name()));
    // the left third is dark
    QVERIFY(image.pixelColor(QPoint(80, 400)).lightness() < 60);
}

void KisWelcomeBackgroundLayoutTest::testOwnWelcomeOnlyInTheBuildNamedToska()
{
    // KRITA_APP_OWN_WELCOME is computed by cmake/modules/KritaAppIdentity.cmake with the splash's rule: the settings
    // folder is the string "KritaAgent" (the build named Toska), never on Android
    const bool toskaFolder = KisAppIdentity::settingsFolder() == QStringLiteral("KritaAgent");
#ifdef Q_OS_ANDROID
    QVERIFY(!KisAppIdentity::hasOwnWelcome());
#else
    QCOMPARE(KisAppIdentity::hasOwnWelcome(), toskaFolder);
#endif
    QCOMPARE(KisAppIdentity::hasOwnWelcome(), KisAppIdentity::hasOwnSplash());
}

QTEST_MAIN(KisWelcomeBackgroundLayoutTest)
