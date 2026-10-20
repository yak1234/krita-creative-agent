/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisSplashBannerLayoutTest.h"

#include <QFileInfo>
#include <QImage>
#include <QPainter>
#include <QSvgRenderer>
#include <QTest>

#include <KisAppIdentity.h>
#include <KisSplashBannerLayout.h>

namespace
{
// The splash KisSplashScreen(480) makes from Toska's 2:1 painting
const QSize kSplash(960, 480);
// krita/data/splash/toska/banner.svg: the view box and its "toska-logo" frame
const QRectF kViewBox(0, 0, 1182, 458);
const QRectF kLogo(48, 48, 1086, 362);
}

void KisSplashBannerLayoutTest::testLogoFrameLandsOnTheLayoutNumbers()
{
    const QRect banner = KisSplashBannerLayout::identityBannerGeometry(kSplash, kViewBox, kLogo);
    QVERIFY(!banner.isEmpty());
    const qreal scale = banner.width() / kViewBox.width();
    // the logo frame, not the halo around it, sits at 3.5 % / 30 % and is 36 % of the splash wide (within a pixel)
    QVERIFY(qAbs(banner.x() + kLogo.x() * scale - 0.035 * kSplash.width()) <= 1.0);
    QVERIFY(qAbs(banner.y() + kLogo.y() * scale - 0.30 * kSplash.height()) <= 1.0);
    QVERIFY(qAbs(kLogo.width() * scale - 0.36 * kSplash.width()) <= 1.0);
    // the aspect ratio of the view box is kept
    QVERIFY(qAbs(banner.width() / qreal(banner.height()) - kViewBox.width() / kViewBox.height()) < 0.02);
    // it stays inside the splash (left third, above the dark bottom band)
    QVERIFY(QRect(QPoint(), kSplash).contains(banner));
    QVERIFY(banner.right() < kSplash.width() / 2);
}

void KisSplashBannerLayoutTest::testWholeViewBoxIsTheLogoWithoutAFrame()
{
    const QRect expected(qRound(0.035 * 960), qRound(0.30 * 480), qRound(0.36 * 960), qRound(0.36 * 960 / 3.0));
    QCOMPARE(KisSplashBannerLayout::identityBannerGeometry(kSplash, QRectF(0, 0, 300, 100), QRectF()), expected);
    // a frame outside the view box is ignored the same way
    QCOMPARE(KisSplashBannerLayout::identityBannerGeometry(kSplash, QRectF(0, 0, 300, 100), QRectF(250, 0, 100, 50)),
             expected);
}

void KisSplashBannerLayoutTest::testEmptyInputsGiveNoGeometry()
{
    QVERIFY(KisSplashBannerLayout::identityBannerGeometry(QSize(), kViewBox, kLogo).isEmpty());
    QVERIFY(KisSplashBannerLayout::identityBannerGeometry(QSize(0, 480), kViewBox, kLogo).isEmpty());
    QVERIFY(KisSplashBannerLayout::identityBannerGeometry(kSplash, QRectF(), kLogo).isEmpty());
    QVERIFY(KisSplashBannerLayout::identityBannerGeometry(kSplash, QRectF(0, 0, 0, 10), QRectF()).isEmpty());
}

void KisSplashBannerLayoutTest::testShippedBannerHasALogoFrameAndAPicture()
{
    const QString path = QStringLiteral(TOSKA_SPLASH_DIR "/banner.svg");
    QVERIFY2(QFileInfo::exists(path), qPrintable(path));
    QSvgRenderer renderer(path);
    QVERIFY(renderer.isValid());
    QCOMPARE(renderer.viewBoxF(), kViewBox);
    QVERIFY(renderer.elementExists(QStringLiteral("toska-logo")));
    const QRectF logo = renderer.boundsOnElement(QStringLiteral("toska-logo"));
    QVERIFY(qAbs(logo.x() - kLogo.x()) < 0.5 && qAbs(logo.y() - kLogo.y()) < 0.5);
    QVERIFY(qAbs(logo.width() - kLogo.width()) < 0.5 && qAbs(logo.height() - kLogo.height()) < 0.5);

    // the embedded PNG decodes: the middle of the logo is opaque, the corners (halo padding) are clear
    QImage image(kViewBox.size().toSize() / 2, QImage::Format_ARGB32_Premultiplied);
    image.fill(Qt::transparent);
    {
        QPainter painter(&image);
        renderer.render(&painter);
    }
    int opaque = 0;
    for (int y = 0; y < image.height(); y += 4) {
        for (int x = 0; x < image.width(); x += 4) {
            opaque += qAlpha(image.pixel(x, y)) > 200 ? 1 : 0;
        }
    }
    QVERIFY2(opaque > 100, qPrintable(QString::number(opaque)));
    QCOMPARE(qAlpha(image.pixel(0, 0)), 0);
    QCOMPARE(qAlpha(image.pixel(image.width() - 1, image.height() - 1)), 0);
}

void KisSplashBannerLayoutTest::testOwnSplashOnlyInTheBuildNamedToska()
{
    // KRITA_APP_OWN_SPLASH is computed by cmake/modules/KritaAppIdentity.cmake: the build named Toska, never Android
#ifdef Q_OS_ANDROID
    QVERIFY(!KisAppIdentity::hasOwnSplash());
#else
    QCOMPARE(KisAppIdentity::hasOwnSplash(), KisAppIdentity::displayName() == QStringLiteral("Toska"));
#endif
}

QTEST_MAIN(KisSplashBannerLayoutTest)
