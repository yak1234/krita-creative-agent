/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISSPLASHBANNERLAYOUTTEST_H
#define KISSPLASHBANNERLAYOUTTEST_H

#include <QObject>

class KisSplashBannerLayoutTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testLogoFrameLandsOnTheLayoutNumbers();
    void testWholeViewBoxIsTheLogoWithoutAFrame();
    void testEmptyInputsGiveNoGeometry();
    void testShippedBannerHasALogoFrameAndAPicture();
    void testOwnSplashOnlyInTheBuildNamedToska();
};

#endif // KISSPLASHBANNERLAYOUTTEST_H
