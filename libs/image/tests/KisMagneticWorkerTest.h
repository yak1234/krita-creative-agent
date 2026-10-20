/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISMAGNETICWORKERTEST_H
#define KISMAGNETICWORKERTEST_H

#include <QObject>

class KisMagneticWorkerTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testNothingIsLeaked();
    void testPathFollowsAnEdge();
    void testCorridorKeepsThePathNearTheLine();
    void testGivingUpAnswersWithTheStartOnly();
    void testSearchRadiusBeyondTheImageIsSafe();
    void testSearchRadiusBeyondALargeImageIsSafe();
    void testIntensityAfterAnEdge();
};

#endif // KISMAGNETICWORKERTEST_H
