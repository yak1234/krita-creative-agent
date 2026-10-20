/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTFEATUREPROTECTION_H
#define TESTFEATUREPROTECTION_H

#include <QObject>

/**
 * Protection as a feature property that Krita enforces on the agent's writes (krita-fork 6.5): "leave the buildings
 * alone" over a whole-canvas pass by stroke jobs, the tool functions and script pixel writes in an agent move.
 */
class TestFeatureProtection : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testWholeCanvasJobLeavesBuildingsAlone();
    void testUnprotectingOrOverridingWritesInside();
    void testJobClipAndProtectionCombine();
    void testOtherLayersAndOffsetsAreProtectedToo();
    void testFeatureProtectedMidJobIsHonouredFromTheNextWindow();
    void testFillGradientAndEncloseKeepOut();
    void testSmartPatchKeepsOut();
    void testMoveUnderProtectedPixelsIsRefused();
    void testSetPixelDataInAnAgentMove();
    void testSetPixelDataOutsideAgentWorkIsTheScriptsOwn();
    void testFilterApplyAndStartFilter();
    void testArtistsWritesAreNeverRestricted();
    void testProtectingIsUndoableAndSaved();
    void testEdgeCases();
    void testClonesAndTransformMasksAreRefused();
    void testSuspensionEndsWithTheMove();
    void testEdgeNoiseIsInvisibleAndAtTheEdge();
    void testNodeTransformsAndConversionsAreRefused();
    void testMergeDownIsRefusedWhenItChangesProtectedPixels();
    void testTransformMaskOnAGroupOrOnTheParentLayer();
    void testMoveIsRefusedForCloneSourcesAndTransformMasks();
    void testKeptOutNamingStaysCheap();
    void testProtectedSelectionIsACopy();
    void testChannelSetPixelDataKeepsProtectedPixels();
    void testRefusedCutLeavesTheClipboard();
    void testPasteKeepsProtectedPixels();
    void testCancelledAndRefusedJobsReportKeptOut();
    void testOverheadOfProtection();
    void testThirtyProtectedFeaturesAtFullSize();
};

#endif // TESTFEATUREPROTECTION_H
