/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef KISAUTOSAVELOCATIONTEST_H
#define KISAUTOSAVELOCATIONTEST_H

#include <QObject>

class KisAutoSaveLocationTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void cleanup();
    void testStockLocationIsUpstreams();
    void testOwnIdentityNeverUsesStocksLocation();
};

#endif // KISAUTOSAVELOCATIONTEST_H
