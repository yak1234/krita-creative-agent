/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AGENT_REGION_REFRESH_H
#define AGENT_REGION_REFRESH_H

#include <QRect>
#include <kis_types.h>

/**
 * refreshRect's area (agent_accel.h): recompositing part of an image after pixels changed inside a rect, the way a
 * whole-image refresh would leave it.
 *
 * KisImage::refreshGraphAsync(root, rect) recomposites every node in exactly `rect` (KisFullRefreshWalker runs with
 * DontAdjustChangeRect): the halo an effect spreads outside it (a filter mask's blur, a layer style's shadow, an
 * adjustment layer's neighbourhood, a transform mask's moved copy, a clone's offset copy) stays stale. setDirty() does
 * not have that flaw because the merge walker grows the rect by each node's changeRect(), but it needs the node that
 * changed, and the caller only knows a rect.
 */
namespace AgentRegion {

/// The area of `root`'s projection that may differ from before when anything inside `rect` changed on any node under
/// it: every layer's changeRect() united bottom to top through its parent (masks and layer styles included), adjustment
/// layers spreading what changed below them, pass-through groups walked in their parent as Krita composites them, and
/// clone layers carrying their source's change to their own place (clones of clones take a pass each; `settled` is
/// false when they had not settled after eight). Not cut to the image.
QRect changeArea(KisNodeSP root, const QRect &rect, bool *settled = nullptr);

/// Wait for Krita, recomposite changeArea(image root, rect) cut to the image (the whole image if it did not settle) and
/// wait for that. Returns the rect recomposited (empty when `rect` has nothing inside the image; nothing is done then).
QRect refresh(KisImageSP image, const QRect &rect);

}

#endif
