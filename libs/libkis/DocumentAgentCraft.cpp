/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
// Krita Agent: merge kept work (krita-fork 5.2).
//
// Document::mergeGroups() is Krita's own merge, as the layer docker's Merge with Layer Below does on several selected
// layers (KisImage::mergeMultipleLayers) or on one group (KisImage::flattenLayer): each node's projection, with its
// masks and styles, is painted into one new layer in one undo step. Inside a script's macro or agent move, that step
// joins the open one: the merge's applicator sends its undo to the step (KisProcessingApplicator::UndoFacadeOverride).
#include "Document.h"

#include <QHash>
#include <QSet>

#include <KisDocument.h>
#include <kis_debug.h>
#include <kis_image.h>
#include <kis_layer.h>
#include <kis_layer_utils.h>
#include <kis_paint_layer.h>
#include <kis_processing_applicator.h>

#include "DocumentHistory.h"
#include "Node.h"

namespace
{

/// Every node of \p image in stacking order, bottom first (the root first).
QList<KisNodeSP> nodesInOrder(KisImageSP image)
{
    QList<KisNodeSP> nodes;
    KisLayerUtils::recursiveApplyNodes(image->root(), [&nodes](KisNodeSP node) { nodes << node; });
    return nodes;
}

bool isAncestorOf(KisNodeSP ancestor, KisNodeSP node)
{
    for (KisNodeSP parent = node->parent(); parent; parent = parent->parent()) {
        if (parent == ancestor) return true;
    }
    return false;
}

} // namespace

Node *Document::mergeGroups(const QList<Node *> &nodes)
{
    KisDocument *kisDocument = document();
    if (!kisDocument || nodes.isEmpty()) return nullptr;
    KisImageSP image = kisDocument->image();
    if (!image) return nullptr;

    // Every node must be a layer of this image, not the root, and not inside another listed node.
    KisNodeList listed;
    for (Node *node : nodes) {
        if (!node) return nullptr;
        KisNodeSP kisNode = node->node();
        if (!kisNode || !qobject_cast<KisLayer *>(kisNode.data()) || kisNode == image->root()) return nullptr;
        if (!isAncestorOf(image->root(), kisNode)) return nullptr;
        if (!listed.contains(kisNode)) listed << kisNode;
    }
    for (KisNodeSP node : listed) {
        for (KisNodeSP other : listed) {
            if (node != other && isAncestorOf(other, node)) return nullptr;
        }
    }

    // Nothing locked is changed: a listed node that is locked, or inside a locked group, refuses the whole call, as
    // does a visible one inside a hidden group (the artist cannot edit it either). Hidden nodes stay as they are:
    // Krita's merge would delete them.
    KisNodeList merged;
    for (KisNodeSP node : listed) {
        if (!node->isEditable(false) || (node->visible() && !node->isEditable(true))) {
            warnScript << "Document.mergeGroups(): refused," << node->name() << "is locked or inside a locked or hidden group";
            return nullptr;
        }
        if (node->visible()) merged << node;
    }
    if (merged.isEmpty()) return nullptr;

    waitForDone();
    const QList<KisNodeSP> before = nodesInOrder(image);
    QHash<const KisNode *, int> order;
    for (int i = 0; i < before.size(); i++) order[before[i].data()] = i;
    std::sort(merged.begin(), merged.end(),
              [&order](const KisNodeSP &a, const KisNodeSP &b) { return order.value(a.data()) < order.value(b.data()); });

    // Inside an open macro or agent move, the merge's step joins it. The override covers only the merge call, which
    // creates its applicator at once, never the waits (where the artist's own actions may run).
    KisStrokeUndoFacade *scriptStep = DocumentHistory::scriptUndoFacade(image);
    if (merged.size() == 1) {
        KisNodeSP first = merged.first();
        KisLayerSP layer = qobject_cast<KisLayer *>(first.data());
        if (!layer->childCount() && !layer->layerStyle()) {
            // Nothing to flatten: a plain paint layer is merged already.
            return qobject_cast<KisPaintLayer *>(layer.data()) ? Node::createNode(image, layer) : nullptr;
        }
        KisProcessingApplicator::UndoFacadeOverride intoScriptStep(scriptStep);
        image->flattenLayer(layer);
    } else {
        KisProcessingApplicator::UndoFacadeOverride intoScriptStep(scriptStep);
        image->mergeMultipleLayers(merged, merged.last());
    }
    waitForDone();

    // The merged layer is the one layer that was not there before.
    QSet<const KisNode *> existed;
    for (const KisNodeSP &node : before) existed.insert(node.data());
    KisNodeSP result;
    for (KisNodeSP node : nodesInOrder(image)) {
        if (!existed.contains(node.data()) && qobject_cast<KisLayer *>(node.data())) {
            result = node;
            break;
        }
    }
    return result ? Node::createNode(image, result) : nullptr;
}
