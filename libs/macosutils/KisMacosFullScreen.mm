/*
 * SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#import <AppKit/AppKit.h>

#include "KisMacosFullScreen.h"

#include <QGuiApplication>
#include <QHash>
#include <QObject>
#include <QWidget>

namespace
{

/** What enter() changed, put back by leave(). */
struct Saved {
    NSRect frame;
    NSWindowStyleMask styleMask;
    NSApplicationPresentationOptions options;
};

QHash<const QWidget *, Saved> &saved()
{
    static QHash<const QWidget *, Saved> windows;
    return windows;
}

/** The NSWindow under a widget's top-level window; nil off the Cocoa platform (the tests run offscreen). */
NSWindow *nativeWindow(QWidget *widget)
{
    if (!widget || QGuiApplication::platformName() != QLatin1String("cocoa")) {
        return nil;
    }
    QWidget *top = widget->window();
    NSView *view = (__bridge NSView *)reinterpret_cast<void *>(top->winId());
    return view.window;
}

}

namespace KisMacosFullScreen
{

Route route(bool fullScreen, bool oursActive, bool nativeActive, bool preferNative)
{
    if (oursActive) {
        return fullScreen ? Route::Nothing : Route::Ours;
    }
    if (nativeActive) {
        return fullScreen ? Route::Nothing : Route::Native;
    }
    if (!fullScreen) {
        return Route::Nothing;
    }
    return preferNative ? Route::Native : Route::Ours;
}

void enter(QWidget *widget)
{
    NSWindow *window = nativeWindow(widget);
    QWidget *top = widget ? widget->window() : nullptr;
    if (!window || saved().contains(top)) {
        return;
    }
    NSScreen *screen = window.screen ?: NSScreen.mainScreen;
    saved().insert(top, Saved{window.frame, window.styleMask, NSApp.presentationOptions});
    // A window closed in full screen gives the menu bar back (presentation options belong to the whole app).
    QObject::connect(top, &QObject::destroyed, [top]() {
        const auto it = saved().constFind(top);
        if (it != saved().constEnd()) {
            NSApp.presentationOptions = it->options;
            saved().remove(top);
        }
    });
    // Both auto-hide: the menu bar and Dock appear when the pointer reaches them, as in macOS's own full screen.
    NSApp.presentationOptions = NSApplicationPresentationAutoHideMenuBar | NSApplicationPresentationAutoHideDock;
    // Borderless, so no title bar and nothing keeps the frame below the menu bar. Qt's window accepts key focus without
    // one, and the content view stays: the canvas is not recreated.
    window.styleMask = NSWindowStyleMaskBorderless;
    [window setFrame:screen.frame display:YES];
    [window makeKeyAndOrderFront:nil];
}

void leave(QWidget *widget)
{
    QWidget *top = widget ? widget->window() : nullptr;
    const auto it = saved().constFind(top);
    if (it == saved().constEnd()) {
        return;
    }
    const Saved before = *it;
    saved().remove(top);
    NSWindow *window = nativeWindow(top);
    NSApp.presentationOptions = before.options;
    if (!window) {
        return;
    }
    window.styleMask = before.styleMask;
    [window setFrame:before.frame display:YES];
    [window makeKeyAndOrderFront:nil];
}

bool isActive(const QWidget *widget)
{
    return widget && saved().contains(widget->window());
}

}
