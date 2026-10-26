/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISWELCOMEBACKGROUNDLAYOUTTEST_H
#define KISWELCOMEBACKGROUNDLAYOUTTEST_H

#include <QObject>

class KisWelcomeBackgroundLayoutTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testCoverKeepsTheAspectRatioAndStaysInside();
    void testAnchoredRightKeepsTheMoonInView();
    void testEmptyInputsGiveNoRect();
    void testLightThemesGetTheStrongerVeil();
    void testTextIsWhiteOrCharcoal();
    void testShippedPaintingDecodes();
    void testOwnWelcomeOnlyInTheBuildNamedToska();
};

#endif // KISWELCOMEBACKGROUNDLAYOUTTEST_H
