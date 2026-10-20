/*
 *  SPDX-FileCopyrightText: 2017 Bernhard Liebl
 *
 * SPDX-License-Identifier: LGPL-2.0-or-later
 */
#import <AppKit/AppKit.h>

extern "C" {
    bool isMouseCoalescingEnabled();
    void setMouseCoalescingEnabled(bool enabled);
    void setMacosApplicationAppearance(int appearance);
}

bool isMouseCoalescingEnabled() {
    return NSEvent.isMouseCoalescingEnabled;
}

void setMouseCoalescingEnabled(bool enabled) {
    NSEvent.mouseCoalescingEnabled = enabled;
}

// Krita Agent: see osx.h. NSApp.appearance is inherited by every window that has no appearance of its own (Qt sets
// none), so the title bars follow at once, also on a live theme switch. It is only ever set here: nil (the system's)
// is what the app had before the first change, so that is what 0 gives back.
void setMacosApplicationAppearance(int appearance) {
    if (@available(macOS 10.14, *)) {
        static bool s_changed = false;
        if (!NSApp) {
            return;
        }
        if (appearance != 1 && appearance != 2) {
            if (s_changed) {
                NSApp.appearance = nil;
                s_changed = false;
            }
            return;
        }
        NSAppearanceName name = appearance == 2 ? NSAppearanceNameDarkAqua : NSAppearanceNameAqua;
        if (NSApp.appearance && [NSApp.appearance.name isEqualToString:name]) {
            return;
        }
        NSApp.appearance = [NSAppearance appearanceNamed:name];
        s_changed = true;
    }
}
