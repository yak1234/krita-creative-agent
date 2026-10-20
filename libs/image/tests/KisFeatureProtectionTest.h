/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREPROTECTIONTEST_H
#define KISFEATUREPROTECTIONTEST_H

#include <QObject>

/// Protection (krita-fork 6.5) and spatial queries (6.4) at the level of the feature list: no document, no libkis.
class KisFeatureProtectionTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testNothingProtectedCostsNothing();
    void testRevisionChangesWithTheList();
    void testProtectedMaskIsTheBinarizedUnion();
    void testSuspendedProtectsNothing();
    void testProtectionCommandUndoRedo();
    void testGuardSelectionWithAndWithoutClip();
    void testGuardSelectionEdgeCases();
    void testClipPixelWriteKeepsProtectedPixels();
    void testKeptOutOfNamesOnlyReachedFeatures();
    void testFeaturesAtOverlappingAndTouching();
    void testTouchingTolerance();
    void testExpressionGrammar();
    void testExpressionErrorsAndLimits();
    void testExpressionDoesNotChangeFeatures();
    void testCanvasAlignment();
    void testCanvasAlignmentLooksUpTheAncestors();
    void testProtectionRevisionIgnoresWhatDoesNotChangeTheArea();
    void testClipPixelWriteRefusesShortOrAbsurdData();
};

#endif // KISFEATUREPROTECTIONTEST_H
