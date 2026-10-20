/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTSTROKEJOBS_H
#define TESTSTROKEJOBS_H

#include <QObject>

/// Node.paintStrokes() and StrokeJob: asynchronous stroke jobs with pen input (task 2.4).
class TestStrokeJobs : public QObject
{
    Q_OBJECT
private:
    void washRound(int round);

private Q_SLOTS:
    void testPaintsWithoutAView();
    void testRefusesCleanly();
    void testPressureTapers();
    void testTiltWidensATiltPreset();
    void testSpeedThinsASpeedPreset();
    void testCubicSegmentsAndPerPointLists();
    void testChangedRectAndSignals();
    void testSelectionClipsOrNone();
    void testWaitIsPerJob();
    void testCancelLeavesAPrefix();
    void testJobIsOneNamedUndoStep();
    void testAgentMoveOf1400StrokesIsOneStep();
    void testNothingLostWhenBusy();
    void testWindowRespondsWhileAJobPaints();
    void testWashBrushLandsBeforeTheJobEnds();
    void testKritasCancellationLeavesJobsAlone();
    void testClosingTheDocumentStopsAJob();
    void testGuiThreadWaitIsBounded();
    void testJobsNeverAskArtistStrokesToEnd();
    void testRefusesFarPointsAndOversizedJobs();
    void testArtistStrokeRunsBeforeTheJobEnds();
    void testArtistUndoStopsTheJobThenUndoes();
    void testEraseOpacityAndFlow();
    void testCancelReasons();
    void testBrushIsFixedAtTheCall();
    void testUndoBetweenTopUpsUndoesTheJob();
    void testOffGuiThreadRefusedAndALoneStartDabs();
};

#endif
