/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTDOCUMENTHISTORY_H
#define TESTDOCUMENTHISTORY_H

#include <QObject>

/// Undo history in libkis (task 2.7) and agent moves as one undo step each (task 2.5).
class TestDocumentHistory : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void cleanupTestCase();
    void testUndoQueries();
    void testSetUndoIndex();
    void testNamedStrokes();
    void testUndoMacro();
    void testAgentMoveIsOneStep();
    void testStrokesOutsideMoveStaySeparate();
    void testPixelWriteOutsideMoveKeepsUpstreamBehaviour();
    void testRefusals();
    void testCloseMidMove();
    void testBigMoveKeepsUndoLimit();
    void testAgentMoveChangedSignal();
    void testArtistStrokesStaySeparate();
    void testUndoDuringMoveClosesIt();
    void testLateAgentStrokeLandsInMove();
    void testDeviceSplit();
    void testLegacyCommandInMove();
    void testSaveDuringMove();
    void testEmptyMove();
    void testIdleMoveCloses();
    void testMoveIsAgentWork();
    void testHistoryMoveWhileBusyKeepsMove();
    void testImageReplacedWhileStrokesQueued();
    void testLegacyMacroStaysApart();
    void testPixelWriteAfterStrokeOnSameLayer();
    void testExportKeepsMove();
    void testQueuedWorkIsNotIdle();
    void testScriptContinuesAfterSave();
    void testSetUndoIndexWithPenDown();
    void testLandedStepsArePruned();
    void testSelectionJoinsMove();
    void testAgentStrokesWaitBehindHeldPen();
};

#endif // TESTDOCUMENTHISTORY_H
