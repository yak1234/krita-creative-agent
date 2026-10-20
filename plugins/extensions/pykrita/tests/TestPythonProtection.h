/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONPROTECTION_H
#define TESTPYTHONPROTECTION_H

#include <QObject>

/// The queries and protection of the feature map from Python (Krita Agent, tasks 6.4 and 6.5).
class TestPythonProtection : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testQueriesFromPython();
    void testProtectedJobFromPython();
    void testProtectedSelectionAndSuspensionFromPython();
};

#endif // TESTPYTHONPROTECTION_H
