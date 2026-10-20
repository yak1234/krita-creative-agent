/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISABOUTAGENTTEST_H
#define KISABOUTAGENTTEST_H

#include <QObject>

class KisAboutAgentTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void cleanup();
    void testRecordValue();
    void testStockKritaGetsNothing();
    void testOwnIdentityGetsATitleAndALicenseBlock();
};

#endif // KISABOUTAGENTTEST_H
