/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef KISAPPIDENTITYTEST_H
#define KISAPPIDENTITYTEST_H

#include <QObject>

class KisAppIdentityTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void init();
    void cleanup();

    void testStockLocationsAreUpstreams();
    void testOwnLocationsAreUnderTheFolder();
    void testOwnAutosaveLocationIsNeverHomeOrTemp();
    void testInitializeCreatesTheFoldersOnce();
    void testShippedConfigDefaultsAreRead();
};

#endif // KISAPPIDENTITYTEST_H
