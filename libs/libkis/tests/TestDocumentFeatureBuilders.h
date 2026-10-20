/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTDOCUMENTFEATUREBUILDERS_H
#define TESTDOCUMENTFEATUREBUILDERS_H

#include <QObject>

class TestDocumentFeatureBuilders : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testFromSelection();
    void testContiguousStopsAtAnEdge();
    void testThresholdChangesTheArea();
    void testContiguousSeedsAndRefinement();
    void testContiguousWithin();
    void testReferenceLayer();
    void testSimilarColorPicksDisconnectedRegions();
    void testSnapOutlineFollowsEdges();
    void testSegmentSplitsAlongTheBoundary();
    void testSettleMovesARoughEdgeOntoThePainting();
    void testBadInputGivesNothing();
    void testBuildersChangeNothing();
    void testBuildersNeverEndTheArtistsStroke();
    void testASegmentThatRunsOutOfTimeIsCancelled();
    void testInputCapsRefuseGiantInput();
    void testATimeBudgetBoundsTheCall();
    void testSearchRadiusBeyondTheEdgeOfTheImage();
    void testNothingIsLeakedByRepeatedSnaps();
    void testSettleOfAThinMaskKeepsTheMask();
    void testLayerLookup();
    void testWithinNameIsTrimmed();
    void testSkylineRegressionFloor();
    void testSkylineTarget();
};

#endif // TESTDOCUMENTFEATUREBUILDERS_H
