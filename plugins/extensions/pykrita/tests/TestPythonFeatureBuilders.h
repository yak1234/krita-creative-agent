/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONFEATUREBUILDERS_H
#define TESTPYTHONFEATUREBUILDERS_H

#include <QObject>

class TestPythonFeatureBuilders : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testBuildersFromPython();
};

#endif // TESTPYTHONFEATUREBUILDERS_H
