/*
 *  SPDX-FileCopyrightText: 2026 10zindraws (Krita-Revamp): clipping group rules, from kis_layer_manager.cc / kis_node_manager.cpp
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen: shared helper, clip-to-layer-below planning
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "KisClippingUtils.h"

#include <klocalizedstring.h>

#include <kis_node.h>
#include <kis_image.h>
#include <kis_layer.h>
#include <kis_group_layer.h>
#include <kis_layer_properties_icons.h>

#include <KoCompositeOpRegistry.h>
#include <commands/kis_node_compositeop_command.h>
#include <commands/kis_node_opacity_command.h>

#include "kis_node_juggler_compressed.h"

namespace KisClippingUtils
{

bool hasInheritAlpha(KisNodeSP node)
{
    KisLayer *layer = qobject_cast<KisLayer*>(node.data());
    return layer && layer->alphaChannelDisabled();
}

bool isClippingGroup(KisNodeSP group)
{
    if (!group || !group->inherits("KisGroupLayer")) {
        return false;
    }

    KisNodeSP topChild = group->lastChild();
    return topChild && hasInheritAlpha(topChild);
}

bool isTopClippedLayer(KisNodeSP node)
{
    if (!node || !hasInheritAlpha(node)) {
        return false;
    }

    KisNodeSP parent = node->parent();
    return parent && isClippingGroup(parent) && node == parent->lastChild();
}

bool shouldEnableInheritAlphaForNewLayer(KisNodeSP activeNode, KisNodeSP parent, KisNodeSP above)
{
    if (!activeNode || !parent || !above) {
        return false;
    }

    KisNodeSP group = activeNode->parent();
    if (!group || !isClippingGroup(group) || !hasInheritAlpha(activeNode)) {
        return false;
    }

    if (activeNode == group->lastChild()) {
        return false;
    }

    return parent == group && above == activeNode;
}

bool shouldEnableInheritAlphaForDrop(KisNodeSP parent, KisNodeSP aboveThis)
{
    if (!isClippingGroup(parent)) {
        return false;
    }

    // the node that will sit directly above the dropped ones
    KisNodeSP nodeAbove = aboveThis ? aboveThis->nextSibling() : parent->firstChild();
    return nodeAbove && hasInheritAlpha(nodeAbove);
}

bool adjustDropTarget(KisNodeSP *parent, KisNodeSP *aboveThis)
{
    if (!parent || !aboveThis || !*parent || !isClippingGroup(*parent)) {
        return false;
    }

    KisNodeSP topChild = (*parent)->lastChild();
    if (topChild && *aboveThis == topChild && (*parent)->parent()) {
        *aboveThis = *parent;
        *parent = (*parent)->parent();
    } else if (!*aboveThis && (*parent)->parent()) {
        // below the base: outside, under the group
        *aboveThis = (*parent)->prevSibling();
        *parent = (*parent)->parent();
        return false;
    }

    return shouldEnableInheritAlphaForDrop(*parent, *aboveThis);
}

ClipPlan planClipToLayerBelow(KisNodeSP active, bool joinClippingGroups)
{
    ClipPlan plan;
    plan.active = active;

    if (!active || !qobject_cast<KisLayer*>(active.data())) {
        plan.reason = i18n("Only a layer can be clipped to the layer below.");
        return plan;
    }

    // already clipped: the same action releases it
    if (hasInheritAlpha(active)) {
        plan.action = ClipPlan::Release;
        return plan;
    }

    // the layer directly below, then further down while those are clipped themselves (their base is what we clip to)
    KisNodeSP below = active->prevSibling();
    if (!below || !qobject_cast<KisLayer*>(below.data())) {
        plan.reason = i18n("There is no layer below to clip to.");
        return plan;
    }

    if (joinClippingGroups && isClippingGroup(below)) {
        plan.action = ClipPlan::JoinGroup;
        plan.group = below;
        return plan;
    }

    KisNodeList stack;
    stack << active;
    KisNodeSP base = below;
    while (base && hasInheritAlpha(base)) {
        stack.prepend(base);
        base = base->prevSibling();
    }

    if (!base || !qobject_cast<KisLayer*>(base.data())) {
        // every layer below is clipped and nothing is under them: clipping the active layer would leave it clipped to
        // nothing (invisible)
        plan.reason = i18n("The layers below are all clipped and there is no base layer to clip to.");
        return plan;
    }

    stack.prepend(base);
    plan.base = base;

    KisNodeSP parent = active->parent();
    if (parent && parent->parent() && parent->inherits("KisGroupLayer") && parent->firstChild() == base) {
        // the base is the bottom of a group (not the image root): that group already is the clip stack, and alpha
        // inheritance reaches only the layers below in the same group, so the property is all that is needed
        plan.action = ClipPlan::ClipInPlace;
        return plan;
    }

    plan.stack = stack;
    plan.action = ClipPlan::GroupAndClip;
    return plan;
}

bool applyClipPlan(const ClipPlan &plan, KisImageSP image,
                   const std::function<KisNodeJugglerCompressed*()> &getJuggler)
{
    if (!image || !plan.active) {
        return false;
    }

    switch (plan.action) {
    case ClipPlan::None:
        return false;
    case ClipPlan::Release:
    case ClipPlan::ClipInPlace:
        KisLayerPropertiesIcons::setNodePropertyAutoUndo(plan.active, KisLayerPropertiesIcons::inheritAlpha,
                                                         plan.action == ClipPlan::ClipInPlace, image);
        return true;
    case ClipPlan::JoinGroup: {
        if (!plan.group || !plan.group->lastChild()) {
            return false;
        }
        KisNodeJugglerCompressed *juggler = getJuggler();
        if (!juggler) {
            return false;
        }
        juggler->moveNode(KisNodeList() << plan.active, plan.group, plan.group->lastChild(), true);
        return true;
    }
    case ClipPlan::GroupAndClip: {
        if (plan.stack.size() < 2) {
            return false;
        }
        KisNodeJugglerCompressed *juggler = getJuggler();
        if (!juggler) {
            return false;
        }

        // Photoshop-faithful: a base with a blend mode or opacity keeps its look when it goes into the new (isolated)
        // group by handing both to the group, and the base is reset to Normal 100% (same undo step). A Multiply base
        // would otherwise blend against nothing inside the group.
        KisNodeSP baseNode = plan.stack.first();
        const QString baseOp = baseNode->compositeOpId();
        const quint8 baseOpacity = baseNode->opacity();
        const bool moveLook = qobject_cast<KisLayer*>(baseNode.data()) &&
            (baseOp != COMPOSITE_OVER || baseOpacity != OPACITY_OPAQUE_U8);

        KisGroupLayerSP group = new KisGroupLayer(image.data(),
                                                  image->nextLayerName(i18nc("default name for a clipping group layer", "Clipping Group")),
                                                  OPACITY_OPAQUE_U8);

        // a group above the active layer, the base and the clipped layers moved into it, the active layer last and
        // inheriting alpha
        KisNodeList rest = plan.stack;
        rest.removeLast();

        if (moveLook) {
            // the group is not in the image yet: setting its look needs no undo
            group->setCompositeOpId(baseOp);
            group->setOpacity(baseOpacity);
        }

        juggler->addNode(KisNodeList() << group, plan.active->parent(), plan.active);
        juggler->moveNode(rest, group, KisNodeSP());
        juggler->moveNode(KisNodeList() << plan.active, group, rest.last(), true);

        if (moveLook) {
            if (baseOp != COMPOSITE_OVER) {
                juggler->applyExtraCommand(new KisNodeCompositeOpCommand(baseNode, COMPOSITE_OVER));
            }
            if (baseOpacity != OPACITY_OPAQUE_U8) {
                juggler->applyExtraCommand(new KisNodeOpacityCommand(baseNode, OPACITY_OPAQUE_U8));
            }
        }
        return true;
    }
    }

    return false;
}

}
