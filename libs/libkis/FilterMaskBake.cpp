/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
// Krita Agent: bake a filter mask into its layer (krita-fork 5.2).
//
// KisImage::flattenLayer() bakes every mask and the layer style of a layer and replaces the layer with a new one
// (renamed "... Merged"). Baking one mask keeps the layer: the mask is applied to the layer's pixels by the same
// call that applies it when Krita renders the layer (KisMask::apply), and then removed, in one undo step: one command
// (the pixels' transaction and the mask's removal as its children) run as a stroke, which joins a script's open macro
// or agent move (DocumentHistory::runCommandStroke).
#include "ScriptWaits.h"
#include <kis_processing_applicator.h>
#include "FilterMask.h"

#include <kis_command_utils.h>
#include <kis_debug.h>
#include <kis_filter_mask.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_painter.h>
#include <filter/kis_filter.h>
#include <filter/kis_filter_configuration.h>
#include <filter/kis_filter_registry.h>
#include <kis_selection_mask.h>
#include <kis_transaction.h>
#include <commands/kis_image_layer_remove_command.h>
#include <kundo2magicstring.h>
#include <klocalizedstring.h>

#include "DocumentHistory.h"

namespace
{

/**
 * @return true when \p mask is the first effect mask \p layer applies when it renders (selection masks apart, which
 * do not change the layer's pixels), so applying it to the layer's own pixels gives what the layer shows
 */
bool appliesFirst(KisLayerSP layer, KisFilterMaskSP mask)
{
    Q_FOREACH (KisEffectMaskSP effect, layer->effectMasks()) {
        if (effect.data() == mask.data()) return true;
        if (dynamic_cast<KisSelectionMask *>(effect.data())) continue;
        return false;
    }
    return false;
}

} // namespace

bool FilterMask::bake()
{
    KisFilterMaskSP mask = qobject_cast<KisFilterMask *>(node().data());
    KisImageSP image = this->image();
    if (!mask || !image) return false;

    KisPaintLayerSP layer = qobject_cast<KisPaintLayer *>(mask->parent().data());
    if (!layer || !layer->paintDevice()) return false;
    if (layer->isAnimated() || !mask->visible()) return false;
    // Nothing locked is changed, and nothing the artist cannot edit: the mask, its layer and their groups are
    // unlocked and shown.
    if (!mask->isEditable(true)) {
        warnScript << "FilterMask.bake(): refused," << mask->name() << "or a layer above it is locked or hidden";
        return false;
    }
    if (!appliesFirst(layer, mask)) return false;

    KisCommandUtils::CompositeCommand *bake = new KisCommandUtils::CompositeCommand();
    bake->setText(kundo2_i18n("Bake Filter Mask"));
    bake->addCommand(new KisCommandUtils::LambdaCommand([image, layer, mask]() mutable -> KUndo2Command * {
        KisPaintDeviceSP device = layer->paintDevice();
        // The layer's content and as far as the filter reaches from it. A filter that changes transparent pixels
        // (needsTransparentPixels) reaches the whole image, as the projection does.
        QRect rect = mask->changeRect(device->extent(), KisNode::N_ABOVE_FILTHY);
        KisFilterConfigurationSP config = mask->filter();
        KisFilterSP filter = config ? KisFilterRegistry::instance()->value(config->name()) : KisFilterSP();
        if (filter && filter->needsTransparentPixels(config, device->colorSpace())) {
            rect |= image->bounds();
        }

        KisPaintDeviceSP filtered = new KisPaintDevice(*device);
        mask->apply(filtered, rect, mask->needRect(rect, KisNode::N_ABOVE_FILTHY), KisNode::N_ABOVE_FILTHY,
                    KisRenderPassFlag::None);

        KisTransaction transaction(device);
        KisPainter::copyAreaOptimized(rect.topLeft(), filtered, device, rect);
        // Tiles the filter left empty are not kept.
        device->purgeDefaultPixels();
        layer->setDirty(rect);
        return transaction.endAndTake();
    }));
    bake->addCommand(new KisImageLayerRemoveCommand(image, mask));

    DocumentHistory::scriptUndoAdapter(image, layer->paintDevice()); // orders the step's work on this layer, if open
    DocumentHistory::runCommandStrokeAndWait(image, bake, "FilterMask.bake()", KisStrokeJobData::SEQUENTIAL, KisStrokeJobData::EXCLUSIVE);
    return true;
}
