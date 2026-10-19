/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONCHANGEEVENTS_H
#define TESTPYTHONCHANGEEVENTS_H

#include <QObject>

/// Notifier's change events as a Python script sees them, through the built krita module.
class TestPythonChangeEvents : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void cleanupTestCase();
    void testKeptNodeReferencesAreSafe();
    void testNodesCompareAcrossEvents();
    void testKeptDocumentReferenceAfterClose();
};

#endif // TESTPYTHONCHANGEEVENTS_H
