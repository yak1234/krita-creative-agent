/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef KIS_MACOS_FULL_SCREEN_TEST_H
#define KIS_MACOS_FULL_SCREEN_TEST_H

#include <QObject>

class KisMacosFullScreenTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testRoute();
    void testNothingOffTheCocoaPlatform();
};

#endif
