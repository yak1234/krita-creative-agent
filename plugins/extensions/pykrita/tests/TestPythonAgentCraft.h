/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONAGENTCRAFT_H
#define TESTPYTHONAGENTCRAFT_H

#include <QObject>

/// Brush tips, presets, merge and bake (krita-fork 5.1, 5.2) as a Python script calls them, through the built module.
class TestPythonAgentCraft : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testBrushTipAndPreset();
    void testMergeGroupsAndBake();
};

#endif // TESTPYTHONAGENTCRAFT_H
