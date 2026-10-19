/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTPYTHONFEATURES_H
#define TESTPYTHONFEATURES_H

#include <QObject>

class TestPythonFeatures : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void initTestCase();
    void testFeaturesFromPython();
};

#endif // TESTPYTHONFEATURES_H
