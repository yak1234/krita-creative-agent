/*
 *  SPDX-FileCopyrightText: 2017 Bernhard Liebl
 *
 * SPDX-License-Identifier: LGPL-2.0-or-later
 */
extern "C" {
	bool isMouseCoalescingEnabled();
	void setMouseCoalescingEnabled(bool enabled);
	/// Krita Agent: the appearance of the app's native window parts (title bars, native dialogs) for a colour theme
	/// that asks for one: 1 light (Aqua), 2 dark (DarkAqua). 0 gives back the system's appearance if an earlier call
	/// changed it, and otherwise does nothing (libs/ui/thememanager.cpp)
	void setMacosApplicationAppearance(int appearance);
}
