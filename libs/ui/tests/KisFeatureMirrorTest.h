/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREMIRRORTEST_H
#define KISFEATUREMIRRORTEST_H

#include <QObject>

class KisFeatureMirrorTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void cleanupTestCase();
    void testMirrorImageMovesMasks();
    void testMirrorOfSelectedAreaOrLayerLeavesMasks();
};

#endif // KISFEATUREMIRRORTEST_H
