/*
 * SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef KisMacosFullScreen_h
#define KisMacosFullScreen_h

class QWidget;

/**
 * Toska's full screen on macOS (the artist, 2026-10-25: the window looked different after leaving full screen). macOS's
 * own full screen moves the window to a Space of its own; while that Space is not shown, macOS marks the window occluded
 * and Qt stops painting it, so swiping back shows the picture macOS kept, not the canvas as it is. This fills the screen
 * in the current Space instead, as iTerm2, Sublime Text, Photoshop and VLC offer: the window borderless over the whole
 * screen, the menu bar and Dock hidden until the pointer reaches them. Leaving puts back its frame, its title bar and the
 * menu bar exactly as they were. The macOS full screen stays a setting (KisConfig::macosNativeFullscreen).
 */
namespace KisMacosFullScreen
{

/** What View > Full Screen does now. */
enum class Route {
    Ours,     ///< enter or leave Toska's full screen
    Native,   ///< Qt's own (Qt::WindowFullScreen): macOS full screen, a Space of its own
    Nothing   ///< already as asked
};

/**
 * The route for a request: `oursActive`, the window is in Toska's full screen; `nativeActive`, in macOS's;
 * `preferNative`, the setting. A window in one kind of full screen always leaves through that kind, whatever the setting
 * says now, and is never put in the other kind on top of it.
 */
Route route(bool fullScreen, bool oursActive, bool nativeActive, bool preferNative);

/** Toska's full screen on: `window`'s top-level window fills its screen in the current Space. Nothing off the Cocoa platform. */
void enter(QWidget *window);

/** Toska's full screen off: the frame, title bar and menu bar as they were before enter(). */
void leave(QWidget *window);

/** The window is in Toska's full screen. */
bool isActive(const QWidget *window);

}

#endif /* KisMacosFullScreen_h */
