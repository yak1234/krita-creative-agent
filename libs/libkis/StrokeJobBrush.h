/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_STROKEJOBBRUSH_H
#define LIBKIS_STROKEJOBBRUSH_H

// Internal to libkis (and its tests): which brush Node::paintStrokes paints with (NodeStrokeJobs.cpp).

#include <kis_types.h>

#include "kritalibkis_export.h"

namespace StrokeJobBrush
{
/// For tests only: use \p preset as the active view's current preset in paintStrokes (null: the real view's). A test
/// has no main window, so this is how it gives paintStrokes a view preset carrying the artist's tweak.
KRITALIBKIS_EXPORT void setViewPresetForTesting(KisPaintOpPresetSP preset);

/// The preset as its storage holds it, without the unsaved tweaks the cached object carries (the artist's, in memory or
/// loaded from the session storage); the preset itself when it is not in a storage or cannot be loaded from it. GUI
/// thread. The copies are kept per resource id, MD5 and version.
KRITALIBKIS_EXPORT KisPaintOpPresetSP savedPreset(KisPaintOpPresetSP preset);
}

#endif
