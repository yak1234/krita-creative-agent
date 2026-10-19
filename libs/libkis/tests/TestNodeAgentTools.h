/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_NODE_AGENT_TOOLS_H
#define TEST_NODE_AGENT_TOOLS_H

#include <QObject>

/**
 * Krita's tools as functions on a Node (krita-fork 5.3): bucket fill, enclose-and-fill, gradient, smart patch and an
 * undoable move, each without a view, refused on locked layers, and one undo step (or part of an open agent move).
 */
class TestNodeAgentTools : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testFillStopsAtContour();
    void testFillThresholdChangesTheArea();
    void testFillSamplesAllLayers();
    void testFillSimilarColours();
    void testFillInsideSelectionOnly();
    void testEncloseAndFillFillsEnclosedRegions();
    void testLinearGradientEndpoints();
    void testRadialGradientInSelection();
    void testGradientFromResource();
    void testSmartPatchChangesOnlyInsideTheMask();
    void testMoveIsOneUndoStep();
    void testRefusals();
    void testEachJoinsAnAgentMove();

    // Review fixes (fix round 1)
    void testFillKeepsInsideTheSelectionByDefault();
    void testEncloseLeavesContourRegionsByDefault();
    void testNonFiniteInputIsRefused();
    void testDoesNotEndOpenStrokes();
    void testGivesUpBehindAnOpenStroke();
    void testWaitsForItsOwnStrokeOnly();
    void testSmartPatchRefusesLargeAreas();
    void testMoveRefusesRootAndDetachedNodes();
    void testMinorRefusals();
    void testGradientUsesTheSelectionAtRunTime();

    // Rulings and parity
    void testDocumentSelectionIsUsedByDefault();
    void testHiddenLayerIsPainted();
    void testRedo();
    void testArtistStepStaysSeparateDuringAMove();
    void testFillOptions();
    void testEncloseRegionMethods();
    void testGradientRepeatAndDither();
    void benchSmartPatch();
};

#endif
