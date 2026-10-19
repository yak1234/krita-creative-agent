/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATURELISTTEST_H
#define KISFEATURELISTTEST_H

#include <QObject>

class KisFeatureListTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testMeasureHardMask();
    void testMeasureWeightedMeanColor();
    void testMeasureEmptyMaskAndNoColorSource();
    void testPropertiesUpdateWhenMaskChanges();
    void testMeasureInPlaceChange();
    void testInsertRemoveOrderAndLookup();
    void testSignals();
    void testIndexMatchesBruteForce();
    void testIndexFollowsMaskChanges();
    void testImageOwnsListAndClonesCopyIt();
    void testCopyFromImageReplacesFeatures();
    void testAddRemoveRenameCommandsUndo();
    void testStringConversions();
    void testLargeMaskStaysTiled();
    void testMeanColorOfLargeU16Mask();
    void testMeanColorOfLargeFloatMask();
    void testMeanColorOfLargeU16MixedArea();
    void testMeanColorOfLargeU8IsOneMixers();
    void testListDestroyedWhileFeaturesChange();
};

#endif // KISFEATURELISTTEST_H
