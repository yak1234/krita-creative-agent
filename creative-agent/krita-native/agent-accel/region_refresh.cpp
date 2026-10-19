/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "region_refresh.h"

#include <QHash>
#include <QVector>

#include <kis_abstract_projection_plane.h>
#include <kis_clone_layer.h>
#include <kis_image.h>
#include <kis_layer.h>
#include <kis_node.h>
#include <kis_projection_leaf.h>

namespace {

/**
 * One pass over the graph. Every layer is treated as possibly changed inside `rect` (the caller does not say which
 * one), so the result is the union over all of them: never smaller than what any one change spreads to, sometimes
 * larger. The rects come from the nodes' own changeRect(), the numbers the merge walker (setDirty) grows by.
 */
struct Pass {
    QRect rect;
    const QHash<const KisNode *, QRect> *before;         // each layer's change found by the previous pass
    QHash<const KisNode *, QRect> after;                 // and by this one
    bool clones = false;                                 // a clone read its source's change from `before`
};

QRect layerChange(const KisProjectionLeafSP &leaf, Pass &pass);

/// What changes in the composite of `parent`'s child layers, bottom to top as Krita composites them: each layer adds
/// its own change, and spreads what changed below it as a layer above a filthy one does (N_ABOVE_FILTHY: an adjustment
/// layer's filter reaches past it; a plain layer passes it on as it is). Projection leaves list a pass-through group's
/// children among the group's siblings, as the walkers composite them, so they are walked there.
QRect childrenChange(const KisProjectionLeafSP &parent, Pass &pass)
{
    QVector<KisProjectionLeafSP> children;
    for (KisProjectionLeafSP child = parent->lastChild(); child; child = child->prevSibling()) {
        children.prepend(child);                         // lastChild and prevSibling: the order the walkers use
    }
    QRect changed;
    for (const KisProjectionLeafSP &child : children) {
        if (!child->isLayer()) continue;                 // a mask is in its layer's own change rect
        const QRect own = layerChange(child, pass);      // walked even when hidden: a clone may show it
        if (!child->shouldBeRendered()) continue;
        if (!changed.isEmpty()) changed |= child->projectionPlane()->changeRect(changed, KisNode::N_ABOVE_FILTHY);
        changed |= own;
    }
    return changed;
}

/// What changes in `leaf`'s projection plane (what its parent composites) when its own content changed inside the rect:
/// its changeRect() as a filthy layer, which holds its effect masks (filter, transform, transparency) and its layer
/// style. A group's content is its children's composite. A clone's content is its source's: it changes where the
/// source changed (the previous pass's answer), moved by the clone's offset, and where its own masks changed.
QRect layerChange(const KisProjectionLeafSP &leaf, Pass &pass)
{
    const KisAbstractProjectionPlaneSP plane = leaf->projectionPlane();
    QRect content = pass.rect;
    if (leaf->canHaveChildLayers()) content |= childrenChange(leaf, pass);
    QRect change = content | plane->changeRect(content, KisNode::N_FILTHY);
    if (const KisCloneLayer *clone = qobject_cast<const KisCloneLayer *>(leaf->node().data())) {
        // changeRect moves a clone's rect by its offset: unmoved, the rect is where its own masks' pixels changed. Krita
        // adds the clone's projection where it meets the rect it is given (KisLayer::changeRect), so this can grow the
        // area by some of the clone's picture at the unmoved place: more than needed, never less.
        change |= plane->changeRect(pass.rect.translated(-clone->x(), -clone->y()), KisNode::N_FILTHY);
        const KisLayerSP source = clone->copyFrom();
        const QRect sourceChange = source ? pass.before->value(source.data()) : QRect();
        if (!sourceChange.isEmpty()) change |= plane->changeRect(sourceChange, KisNode::N_FILTHY);
        pass.clones = true;
    }
    pass.after.insert(leaf->node().data(), change);
    return change;
}

const int PASSES = 8;                                    // clones of clones settle in one pass per level

}

namespace AgentRegion {

QRect changeArea(KisNodeSP root, const QRect &rect, bool *settled)
{
    if (settled) *settled = true;
    if (!root || rect.isEmpty()) return rect;
    QHash<const KisNode *, QRect> before;
    for (int i = 0; i < PASSES; i++) {
        Pass pass{rect, &before, {}, false};
        const QRect area = layerChange(root->projectionLeaf(), pass);
        // Without clones one pass is the answer; with them, until no clone's source changed more than the last pass said.
        if (!pass.clones || pass.after == before) return area;
        before = pass.after;
    }
    if (settled) *settled = false;
    return rect;
}

QRect refresh(KisImageSP image, const QRect &rect)
{
    if ((rect & image->bounds()).isEmpty()) return QRect();
    image->waitForDone();                                // the graph holds still while its rects are read
    bool settled = true;
    const QRect area = changeArea(image->root(), rect, &settled) & image->bounds();
    const QRect refreshed = settled ? area : image->bounds();
    image->refreshGraphAsync(nullptr, refreshed);
    image->waitForDone();
    return refreshed;
}

}
