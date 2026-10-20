/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONTRAPS_H
#define TESTPYTHONTRAPS_H

#include <QObject>

/// The libkis traps fixed (krita-fork 2.9) as a Python script meets them, through the built module.
class TestPythonTraps : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testNoViewRefusesPainting();
    void testUndoableCallsFromPython();
    void testSelectionContractAndResizeFromPython();
    void testCallsReturnWhileTheArtistHoldsTheStroke();
};

#endif // TESTPYTHONTRAPS_H
