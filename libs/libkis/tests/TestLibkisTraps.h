/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTLIBKISTRAPS_H
#define TESTLIBKISTRAPS_H

#include <QObject>

/// The libkis traps (krita-fork task 2.9): undo for the setters and Filter.apply, Selection.contract and resize, no
/// view needed or leaking, and no call that ends or waits on the artist's open strokes.
class TestLibkisTraps : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void cleanupTestCase();

    void testFilterApplyIsUndoableAndSelectionAware();
    void testFilterApplyInAnAgentMoveIsOneStep();
    void testSetPixelDataIsUndoable();
    void testNodeSettersAreUndoable();
    void testSettersInAnAgentMoveAreOneStep();
    void testSelectionContract();
    void testSelectionResize();
    void testViewStateDoesNotLeakIntoStrokes();
    void testNoCallEndsOrHangsOnAnOpenStroke();
    void testArtistToolStrokesOnOtherLayersDoNotSplitAMove();
    void testArtistToolStrokesOnTheMovesLayerSplitIt();
    void testNonReportingToolStrokeSplitsAMove();
    void testPaintKeepsTheViewsOpacity();
    void testOrphanSetOpacityAddsNoStep();
    void testArtistStrokeDuringAScriptWaitStillEndsOtherStrokes();
    void testOverrideNestsAndEnds();
    void testToolStrokeWithNoScriptKeepsItsBehaviour();
    void testHeldBackOperationsAreCancelled();
    void testLockedImageSettersAreImmediateAndUndoable();
    void testSelectionContractOnAnInvertedSelection();
};

#endif
