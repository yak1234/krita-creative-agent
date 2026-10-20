/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONSTROKEJOBS_H
#define TESTPYTHONSTROKEJOBS_H

#include <QObject>

/// Node.paintStrokes() and StrokeJob from Python (Krita Agent, task 2.4).
class TestPythonStrokeJobs : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testPaintsAPressureStrokeFromPython();
    void testPollsStatusAndCancels();
    void testCancelReasonsFromPython();
    void testDroppingTheJobKeepsPainting();
    void testWaitFromAnotherPythonThread();
    void testAgentMoveJobsAreOneStep();
    void testRefusedJobIsFailedNotAnException();
};

#endif // TESTPYTHONSTROKEJOBS_H
