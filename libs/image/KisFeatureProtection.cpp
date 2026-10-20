/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureProtection.h"

#include <cstring>

#include <KisImageResolutionProxy.h>

#include "KisFeatureList.h"
#include "kis_clone_layer.h"
#include "kis_default_bounds.h"
#include "kis_image.h"
#include "kis_layer.h"
#include "kis_layer_utils.h"
#include "kis_node.h"
#include "kis_paint_device.h"
#include "kis_pixel_selection.h"
#include "kis_pointer_utils.h"
#include "kis_selection.h"
#include "kis_transform_mask.h"

namespace KisFeatureProtection
{

bool isActive(KisImageSP image)
{
    return image && image->featureList()->hasProtectedFeatures();
}

KisSelectionSP guardSelection(KisImageSP image, KisSelectionSP clip)
{
    if (!isActive(image)) return clip;
    KisFeatureList *list = image->featureList();
    KisPixelSelectionSP protectedMask = list->protectedMask();
    if (!protectedMask) return clip;

    KisSelectionSP result = new KisSelection(new KisDefaultBounds(image), toQShared(new KisImageResolutionProxy(image)));
    if (clip) {
        result->pixelSelection()->applySelection(clip->projection(), SELECTION_REPLACE);
        result->pixelSelection()->applySelection(protectedMask, SELECTION_SUBTRACT);
    } else if (KisPixelSelectionSP unprotected = list->unprotectedMask()) {
        // Shares the cached inverse's tiles until one side changes them.
        result = new KisSelection(KisPaintDeviceSP(unprotected), KritaUtils::CopySnapshot, unprotected->defaultBounds(),
                                  toQShared(new KisImageResolutionProxy(image)));
    }
    return result;
}

QStringList keptOutOf(KisImageSP image, const QRect &area, KisSelectionSP within)
{
    if (!isActive(image)) return QStringList();
    return image->featureList()->protectedFeaturesIn(area, within ? within->pixelSelection() : KisPixelSelectionSP());
}

QString whyNotCanvasAligned(KisImageSP image, KisNodeSP node)
{
    if (!image || !node) return QString();
    // A transform mask on the node itself, on a layer it is a mask of, or on any group above it moves what shows.
    for (KisNodeSP up = node; up; up = up->parent()) {
        for (KisNodeSP child = up->firstChild(); child; child = child->nextSibling()) {
            if (dynamic_cast<KisTransformMask *>(child.data())) {
                return QStringLiteral("\"%1\" is shown through a transform mask (on \"%2\"): its pixels are shown moved, so protected features cannot be kept out exactly")
                    .arg(node->name(), up->name());
            }
        }
    }
    QString why;
    KisLayerUtils::recursiveApplyNodes(KisNodeSP(image->root()), [&](KisNodeSP other) {
        if (!why.isEmpty()) return;
        KisCloneLayer *clone = dynamic_cast<KisCloneLayer *>(other.data());
        if (!clone) return;
        KisLayerSP source = clone->copyFrom();
        for (KisNodeSP up = node; up && source; up = up->parent()) {
            if (up == KisNodeSP(source)) {
                why = QStringLiteral("\"%1\" is shown by the clone layer \"%2\" elsewhere on the canvas, so protected features cannot be kept out exactly")
                          .arg(node->name(), clone->name());
                return;
            }
        }
    });
    return why;
}

QStringList clipPixelWrite(KisImageSP image, KisPaintDeviceSP device, QByteArray &data, const QRect &rect, bool *refused)
{
    QStringList names;
    if (refused) *refused = false;
    if (!isActive(image) || !device || rect.isEmpty()) return names;
    const qint64 pixelSize = device->colorSpace()->pixelSize();
    const qint64 count = qint64(rect.width()) * rect.height();
    // A write is refused whole when its data is short, or so large (a gigabyte) that the buffers below would not fit.
    if (count <= 0 || count * pixelSize > kMaxClippedWriteBytes || qint64(data.size()) < count * pixelSize) {
        if (refused) *refused = true;
        return names;
    }

    KisFeatureList *list = image->featureList();
    const QList<KisFeatureSP> candidates = list->featuresWithBoundsIntersecting(rect);
    if (candidates.isEmpty()) return names;

    QByteArray current(int(count * pixelSize), 0);
    device->readBytes(reinterpret_cast<quint8 *>(current.data()), rect);
    QByteArray mask(int(count), 0);
    QByteArray featureMask(int(count), 0);     // one buffer for every feature
    Q_FOREACH (KisFeatureSP feature, candidates) {
        if (!feature->isProtected()) continue;
        if (feature->bounds().intersected(rect).isEmpty()) continue;
        KisPixelSelectionSP featureSelection = feature->mask();
        if (!featureSelection) continue;
        // The mask is read over the whole rect (zero outside its tiles); the cost follows the rect, not the canvas.
        featureSelection->readBytes(reinterpret_cast<quint8 *>(featureMask.data()), rect);
        bool differs = false;
        const char *newer = data.constData();
        const char *older = current.constData();
        for (qint64 i = 0; i < count; i++) {
            if (featureMask[i] == 0) continue;
            mask[i] = 1;
            if (!differs && memcmp(newer + i * pixelSize, older + i * pixelSize, size_t(pixelSize)) != 0) {
                differs = true;
            }
        }
        if (differs) names << feature->name();
    }
    char *out = data.data();
    const char *older = current.constData();
    for (qint64 i = 0; i < count; i++) {
        if (mask[i] != 0) memcpy(out + i * pixelSize, older + i * pixelSize, size_t(pixelSize));
    }
    return names;
}

} // namespace KisFeatureProtection
