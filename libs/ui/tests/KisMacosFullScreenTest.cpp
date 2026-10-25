/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "KisMacosFullScreenTest.h"

#include <QTest>
#include <QWidget>

#include <KisMacosFullScreen.h>

using KisMacosFullScreen::Route;

void KisMacosFullScreenTest::testRoute()
{
    using KisMacosFullScreen::route;
    // By default, Toska's full screen: in the current Space, never a Space of its own.
    QCOMPARE(route(true, false, false, false), Route::Ours);
    QCOMPARE(route(false, true, false, false), Route::Ours);
    // The setting asks for macOS's own.
    QCOMPARE(route(true, false, false, true), Route::Native);
    QCOMPARE(route(false, false, true, true), Route::Native);
    // A window leaves through the kind it is in, whatever the setting says now.
    QCOMPARE(route(false, true, false, true), Route::Ours);
    QCOMPARE(route(false, false, true, false), Route::Native);
    // Already as asked, and never one kind on top of the other.
    QCOMPARE(route(true, true, false, true), Route::Nothing);
    QCOMPARE(route(true, false, true, false), Route::Nothing);
    QCOMPARE(route(false, false, false, false), Route::Nothing);
    QCOMPARE(route(false, false, false, true), Route::Nothing);
}

void KisMacosFullScreenTest::testNothingOffTheCocoaPlatform()
{
    // The tests run offscreen (agent/run-tests.sh): no NSWindow, so nothing changes and nothing crashes.
    QWidget window;
    window.resize(320, 200);
    window.show();
    const QRect before = window.geometry();
    KisMacosFullScreen::enter(&window);
    QVERIFY(!KisMacosFullScreen::isActive(&window));
    QCOMPARE(window.geometry(), before);
    KisMacosFullScreen::leave(&window);
    QVERIFY(!KisMacosFullScreen::isActive(nullptr));
}

QTEST_MAIN(KisMacosFullScreenTest)
