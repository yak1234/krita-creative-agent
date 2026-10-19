/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREIMAGECOMMANDTEST_H
#define KISFEATUREIMAGECOMMANDTEST_H

#include <QObject>

class KisFeatureImageCommandTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testCrop();
    void testCanvasResizeGrows();
    void testCanvasResizeShrinks();
    void testScale();
    void testRotate90();
    void testRotateFreeAngle();
    void testShear();
    void testMirror();
    void testMirrorOfSelectedAreaLeavesMasks();
    void testColorSpaceConversionMeasuresAgain();
    void testImageWithoutFeatures();
    void testCropAfterQueuedUndoOfRemove();
    void testLayerRotateAndShearLeaveMasks();
    void testUndoAfterALaterStep();
    void testConvertedMeanIsTheMixOfConvertedColors();
};

#endif // KISFEATUREIMAGECOMMANDTEST_H
