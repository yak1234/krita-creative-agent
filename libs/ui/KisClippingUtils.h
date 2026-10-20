/*
 *  SPDX-FileCopyrightText: 2026 10zindraws (Krita-Revamp): clipping group rules, from kis_layer_manager.cc / kis_node_manager.cpp
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen: shared helper, clip-to-layer-below planning
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef KISCLIPPINGUTILS_H
#define KISCLIPPINGUTILS_H

#include <functional>

#include <QString>

#include "kis_types.h"
#include "kritaui_export.h"

class KisNodeJugglerCompressed;

/**
 * Rules of the layers docker's "clipping mask" view, shared by the layer manager (new layers), the node manager (drops)
 * and the clip action. A clipping mask is Krita's own alpha inheritance (a layer with "inherit alpha" is clipped to the
 * composition of the layers below it in the same group); nothing here changes compositing or the .kra format.
 *
 * A "clipping group" is a group whose TOP child inherits alpha: its children are one stack, the base at the bottom and
 * the clipped layers above it.
 */
namespace KisClippingUtils
{

/// True if the node is a layer that inherits alpha (is clipped to the layers below it).
KRITAUI_EXPORT bool hasInheritAlpha(KisNodeSP node);

/// True if the node is a group whose top child inherits alpha.
KRITAUI_EXPORT bool isClippingGroup(KisNodeSP group);

/// True if the node inherits alpha and is the top child of a clipping group.
KRITAUI_EXPORT bool isTopClippedLayer(KisNodeSP node);

/**
 * A new layer inserted directly above activeNode (parent, above) inherits alpha when activeNode is a clipped layer in the
 * middle of a clipping group (not its top one): the new layer joins the clip stack.
 */
KRITAUI_EXPORT bool shouldEnableInheritAlphaForNewLayer(KisNodeSP activeNode, KisNodeSP parent, KisNodeSP above);

/**
 * Drop target rules for moved, copied and added nodes. Dropping above the top clipped layer of a clipping group lands
 * outside the group (parent and aboveThis are changed to the group's parent and the group); so does dropping below the
 * base, the bottom of the group (the clipped layers would otherwise inherit from the dropped layer too): the drop goes
 * under the group instead. Returns true if the dropped layers should inherit alpha: the drop is into a clipping group,
 * directly below a clipped layer.
 */
KRITAUI_EXPORT bool adjustDropTarget(KisNodeSP *parent, KisNodeSP *aboveThis);

/// The same test as the second half of adjustDropTarget(), without changing the target.
KRITAUI_EXPORT bool shouldEnableInheritAlphaForDrop(KisNodeSP parent, KisNodeSP aboveThis);

/**
 * What "clip this layer to the layer below" has to do.
 */
struct KRITAUI_EXPORT ClipPlan
{
    enum Action {
        None,        ///< nothing to do (no layer below, a mask, ...)
        Release,     ///< the layer is clipped already: turn inherit alpha off
        ClipInPlace, ///< the base is the bottom of its (non-root) group already, or has no layer under it to clip to: turn inherit alpha on
        GroupAndClip,///< make a group of the base and the layers above it up to the active one, clip the active one
        JoinGroup    ///< the layer below is a clipping group (clipping mask view): move the active layer into it, on top, clipped
    };

    Action action {None};
    KisNodeSP active;
    KisNodeSP base;        ///< the layer the stack is clipped to (the first layer below that does not inherit alpha)
    KisNodeList stack;     ///< base first, then the layers above it up to and including the active layer (GroupAndClip)
    KisNodeSP group;       ///< the clipping group to join (JoinGroup)
    QString reason;        ///< why nothing can be done (None), for a message to the artist
};

/**
 * joinClippingGroups: in the clipping mask view the hidden clip group below the layer is its stack, so the layer joins it
 * (JoinGroup) instead of being clipped to the group's whole composition.
 */
KRITAUI_EXPORT ClipPlan planClipToLayerBelow(KisNodeSP active, bool joinClippingGroups = false);

/**
 * Carries a plan out: the property changes through the image's undo (Release, ClipInPlace), the grouping and moves
 * through the juggler that getJuggler() returns (GroupAndClip, JoinGroup; one undo step, the juggler is asked for only when
 * it is needed). Returns false when there was nothing to do.
 */
KRITAUI_EXPORT bool applyClipPlan(const ClipPlan &plan, KisImageSP image,
                                  const std::function<KisNodeJugglerCompressed*()> &getJuggler);

}

#endif // KISCLIPPINGUTILS_H
