/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTLIBKISNOVIEW_H
#define TESTLIBKISNOVIEW_H

#include <QObject>

/// libkis painting calls with no main window and no view at all (krita-fork task 2.9). A program of its own, so no
/// other test's window can exist, whatever the order tests run in.
class TestLibkisNoView : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testPaintWithoutAViewIsRefused();
};

#endif
