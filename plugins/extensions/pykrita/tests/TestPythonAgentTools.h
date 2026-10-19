/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONAGENTTOOLS_H
#define TESTPYTHONAGENTTOOLS_H

#include <QObject>

/// Krita's tools as functions (krita-fork 5.3) as a Python script calls them, through the built module.
class TestPythonAgentTools : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testToolsFromPython();
};

#endif // TESTPYTHONAGENTTOOLS_H
