/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREPROTECTION_H
#define KISFEATUREPROTECTION_H

#include <QByteArray>
#include <QRect>
#include <QString>
#include <QStringList>

#include "kis_types.h"
#include "kritaimage_export.h"

/**
 * Protection of features (krita-fork task 6.5, capability canvas-features): the functions the agent's write paths call
 * to keep their writes out of the protected features of an image (KisFeature::isProtected()).
 *
 * Protection is a matter of canvas position, not of layers: a protected feature's mask is in image coordinates, and so
 * are the paint devices of every layer and mask (a layer's offset is part of its device), so one selection covers a
 * write to any layer. A write is kept out by clipping its selection, which is how Krita's painters already limit
 * themselves; the artist's own tools never call these functions.
 *
 * An image without protected features pays nothing: every function first asks KisFeatureList::hasProtectedFeatures(),
 * a cached atomic read.
 */
namespace KisFeatureProtection
{

/// Whether the image has protected features that are enforced now (some feature is protected, and protection is not
/// suspended).
KRITAIMAGE_EXPORT bool isActive(KisImageSP image);

/**
 * The selection a write limited to \p clip (null: the whole canvas) may use, with the protected features taken out:
 * \p clip when nothing is protected (the same object), else a new selection on the image's bounds, \p clip minus the
 * union of the protected features, or the whole canvas minus it. It is built from the features as they are now:
 * a caller that must honour a feature protected later builds it again when KisFeatureList::revision() has changed.
 */
KRITAIMAGE_EXPORT KisSelectionSP guardSelection(KisImageSP image, KisSelectionSP clip);

/**
 * The names of the protected features that have a pixel in \p area (and, when given, in \p within), in list order:
 * what a write to \p area is kept out of. Empty when protection is not active.
 */
KRITAIMAGE_EXPORT QStringList keptOutOf(KisImageSP image, const QRect &area, KisSelectionSP within = KisSelectionSP());

/**
 * Whether a write to \p node's pixels lands where the composite shows it. It does not when the node has a transform
 * mask (its pixels are shown moved, scaled or warped) or when the node, or a group it is in, is the source of a clone
 * layer (the clone shows it somewhere else): the canvas positions a protected feature is in are then not the
 * positions of the node's own pixels, and a clip cannot be made exact. An empty string when it does, else why not.
 */
KRITAIMAGE_EXPORT QString whyNotCanvasAligned(KisImageSP image, KisNodeSP node);

/**
 * For a raw pixel write: replaces, in \p data (the pixels about to be written into \p rect of \p device, in the
 * device's pixel format), every pixel inside a protected feature with the pixel the device holds now, so writing the
 * result changes nothing inside a protected feature. @return the names of the protected features in which the write
 * would have changed a pixel (the ones it was kept out of), in list order. Does nothing when protection is not active.
 */
KRITAIMAGE_EXPORT QStringList clipPixelWrite(KisImageSP image, KisPaintDeviceSP device, QByteArray &data, const QRect &rect,
                                             bool *refused = nullptr);

/// The most bytes of one raw write that clipPixelWrite() takes: 1 GiB. A larger write, or one whose data is shorter
/// than its rectangle, sets \p refused and is not clipped; the caller then does not write at all.
const qint64 kMaxClippedWriteBytes = qint64(1) << 30;

} // namespace KisFeatureProtection

#endif // KISFEATUREPROTECTION_H
