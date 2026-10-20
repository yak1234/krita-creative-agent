/*
 *  SPDX-FileCopyrightText: 2020 Scott Petrovic <scottpetrovic@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "PaintingResources.h"

#include "KisView.h"
#include "KisPart.h"
#include "kis_canvas_resource_provider.h"
#include "KisViewManager.h"
#include "KisMainWindow.h"
#include "kis_image.h"
#include "KisToolShapeUtils.h"
#include "DocumentHistory.h"
#include <KoCanvasResourceProvider.h>
#include <kis_processing_applicator.h>
#include <brushengine/kis_paintop_preset.h>
#include <kis_paintop_settings.h>
#include <kis_resources_snapshot.h>


const QStringList StrokeStyle = {
    "None",             // 0 = KisToolShapeUtils::StrokeStyle::StrokeStyleNone
    "ForegroundColor",  //     KisToolShapeUtils::StrokeStyle::StrokeStyleForeground
    "BackgroundColor"   //     KisToolShapeUtils::StrokeStyle::StrokeStyleBackground
};

const QStringList FillStyle = {
    "None",             // 0 = KisToolShapeUtils::FillStyle::FillStyleNone
    "ForegroundColor",  //     KisToolShapeUtils::FillStyle::FillStyleForegroundColor
    "BackgroundColor",  //     KisToolShapeUtils::FillStyle::FillStyleBackgroundColor
    "Pattern"           //     KisToolShapeUtils::FillStyle::FillStylePattern
};

KoCanvasResourceProvider *PaintingResources::viewResources()
{
    KisMainWindow *window = KisPart::instance()->currentMainwindow();
    KisView *view = window ? window->activeView() : nullptr;
    if (!view || !view->viewManager() || !view->viewManager()->canvasResourceProvider()) return nullptr;
    return view->viewManager()->canvasResourceProvider()->resourceManager();
}

bool PaintingResources::hasView()
{
    return viewResources() != nullptr;
}

KisFigurePaintingToolHelper PaintingResources::createHelper(KisImageWSP image,
                                                            KisNodeSP node,
                                                            const QString strokeStyleString,
                                                            const QString fillStyleString,
                                                            const QString &name)
{
    // The brush and colours come from the active view; callers check hasView() first (Krita Agent: it was
    // dereferenced unchecked).
    KoCanvasResourceProvider *resourceManager = viewResources();
    if (!resourceManager) {
        warnScript << "PaintingResources::createHelper(): no active view";
    }

    int strokeIndex = StrokeStyle.indexOf(strokeStyleString);
    if (strokeIndex == -1) {
        dbgScript << "Script tried to paint with invalid strokeStyle" << strokeStyleString << ", ignoring and using" << defaultStrokeStyle << ".";
        strokeIndex = StrokeStyle.indexOf(defaultStrokeStyle);
        if (strokeIndex == -1) {
            warnScript << "PaintingResources::createHelper(): defaultStrokeStyle" << defaultStrokeStyle << "is invalid!";
            strokeIndex = 1;
        }
    }
    KisToolShapeUtils::StrokeStyle strokeStyle = (KisToolShapeUtils::StrokeStyle) strokeIndex;

    int fillIndex = FillStyle.indexOf(fillStyleString);
    if (fillIndex == -1) {
        dbgScript << "Script tried to paint with invalid fillStyle" << fillStyleString << ", ignoring and using" << defaultFillStyle << ".";
        fillIndex = FillStyle.indexOf(defaultFillStyle);
        if (fillIndex == -1) {
            warnScript << "PaintingResources::createHelper(): defaultFillStyle" << defaultFillStyle << " is invalid!";
            fillIndex = 0;
        }
    }
    KisToolShapeUtils::FillStyle fillStyle = (KisToolShapeUtils::FillStyle) fillIndex;

    // Krita Agent: the step is named by the script, or after the open agent move, and joins the open macro or
    // agent move (its commands go to that step's undo adapter instead of the document's history).
    // A script's stroke never ends the artist's open strokes, and takes its mirror, blending mode and alpha lock
    // from itself (the preset's own blending mode, no mirror, no alpha lock; the opacity stays the view's Opacity), never from the view's toolbar.
    KisProcessingApplicator::NoEndRequestsOverride noEndRequests;
    KisFigurePaintingToolHelper helper(
        DocumentHistory::scriptedStrokeName(image, name),
        image,
        node, resourceManager,
        strokeStyle,
        fillStyle,
        QTransform(),
        DocumentHistory::scriptUndoAdapter(image, node ? node->paintDevice() : KisPaintDeviceSP()),
        [](KisResourcesSnapshotSP resources) {
            resources->setMirroring(false, false);
            resources->setGlobalAlphaLock(false);
            KisPaintOpPresetSP preset = resources->currentPaintOpPreset();
            if (preset && preset->settings()) {
                resources->setCompositeOpId(preset->settings()->paintOpCompositeOp());
            }
        }
    );

    return helper;
}
