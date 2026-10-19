/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONAGENTMOVE_H
#define TESTPYTHONAGENTMOVE_H

#include <QObject>

/// The krita module's Document.agentMove(name) context manager (Krita Agent, task 2.5).
class TestPythonAgentMove : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testClosesAtTheEndOfTheBlock();
    void testClosesOnAnException();
    void testRefusedBeginRaises();
    void testOldBlockLeavesNewMove();
};

#endif // TESTPYTHONAGENTMOVE_H
