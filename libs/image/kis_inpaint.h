/*
 *  SPDX-FileCopyrightText: 2017 Eugene Ingerman
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KIS_INPAINT_H
#define KIS_INPAINT_H

#include <QRect>

#include "kis_types.h"
#include "kritaimage_export.h"

/**
 * Inpaints (PatchMatch) the pixels of \p imageDev where \p maskDev (one byte per pixel) is set, from the pixels
 * around them, as the Smart Patch tool does. \p accuracy (0 to 100) sets how much of the surroundings is searched,
 * \p patchRadius the size of the patches compared. With \p selection, only the pixels it selects are written.
 * @return the area read and written
 *
 * Krita Agent (krita-fork 5.3): moved from the Smart Patch tool's plugin into the image library, unchanged, so
 * scripts can patch without the tool.
 */
KRITAIMAGE_EXPORT QRect patchImage(const KisPaintDeviceSP imageDev, const KisPaintDeviceSP maskDev, int patchRadius,
                                   int accuracy, KisSelectionSP selection);

#endif // KIS_INPAINT_H
