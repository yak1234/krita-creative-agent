/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Document's spatial queries on features (Krita Agent, openspec change krita-fork, task 6.4, capability
// canvas-features). Kept apart from Document.cpp so the upstream file carries only their declarations. The work is in
// libs/image (KisFeatureQueries); this file checks a script's input and wraps the answers for scripts.

#include "Document.h"
#include "Feature.h"
#include "Selection.h"

#include <cmath>

#include <QPointer>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureList.h>
#include <KisFeatureQueries.h>
#include <kis_debug.h>
#include <kis_default_bounds.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>
#include <KisImageResolutionProxy.h>
#include <kis_pointer_utils.h>

namespace
{

/// Numbers beyond this are no pixel of any painting.
const double kMaxCoordinate = 1e9;

KisImageSP imageOf(const QPointer<KisDocument> &document)
{
    return document ? KisImageSP(document->image()) : KisImageSP();
}

QList<Feature *> wrap(KisImageSP image, const QList<KisFeatureSP> &features)
{
    QList<Feature *> result;
    Q_FOREACH (KisFeatureSP feature, features) {
        result << new Feature(image, feature);
    }
    return result;
}

/// The feature \p feature stands for, when it is in \p image; null (with a warning naming \p call) otherwise.
KisFeatureSP featureOf(KisImageSP image, KisFeatureSP found, const char *call)
{
    if (!found || image->featureList()->feature(found->id()) != found) {
        warnScript << call << "refused: the feature is not in this document";
        return KisFeatureSP();
    }
    return found;
}

} // namespace

QList<Feature *> Document::featuresAt(double x, double y) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    if (!std::isfinite(x) || !std::isfinite(y) || std::abs(x) > kMaxCoordinate || std::abs(y) > kMaxCoordinate) {
        warnScript << "Document.featuresAt() refused: the point must be finite and within a billion pixels";
        return QList<Feature *>();
    }
    const QPoint pixel(int(std::floor(x)), int(std::floor(y)));
    if (!image->bounds().contains(pixel)) return QList<Feature *>();
    return wrap(image, KisFeatureQueries::featuresAt(image->featureList(), pixel));
}

QList<Feature *> Document::featuresOverlapping(const QRect &rect) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    return wrap(image, KisFeatureQueries::featuresOverlapping(image->featureList(), rect, image->bounds()));
}

QList<Feature *> Document::featuresOverlapping(Feature *feature) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    KisFeatureSP found = featureOf(image, feature ? feature->feature() : KisFeatureSP(), "Document.featuresOverlapping()");
    if (!found) return QList<Feature *>();
    return wrap(image, KisFeatureQueries::featuresOverlapping(image->featureList(), found));
}

QList<Feature *> Document::featuresOverlapping(Selection *selection) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    if (!selection || !selection->selection()) {
        warnScript << "Document.featuresOverlapping() refused: there is no selection";
        return QList<Feature *>();
    }
    // The selected part within the document (an inverted selection selects out to infinity).
    KisPixelSelectionSP area = KisFeature::boundedMask(selection->selection()->projection(), image->bounds());
    return wrap(image, KisFeatureQueries::featuresOverlapping(image->featureList(), area, image->bounds()));
}

QList<Feature *> Document::featuresTouching(Feature *feature) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    KisFeatureSP found = featureOf(image, feature ? feature->feature() : KisFeatureSP(), "Document.featuresTouching()");
    if (!found) return QList<Feature *>();
    return wrap(image, KisFeatureQueries::featuresTouching(image->featureList(), found));
}

QList<Feature *> Document::featuresTouching(const QString &name) const
{
    KisImageSP image = imageOf(document());
    if (!image) return QList<Feature *>();
    KisFeatureSP found = image->featureList()->featureByName(name.trimmed());
    if (!found) {
        warnScript << "Document.featuresTouching() refused: there is no feature called" << name;
        return QList<Feature *>();
    }
    return wrap(image, KisFeatureQueries::featuresTouching(image->featureList(), found));
}

Selection *Document::selection(const QString &expression) const
{
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    QString error;
    KisPixelSelectionSP mask = KisFeatureQueries::selectionFromExpression(image->featureList(), expression, image->bounds(), &error);
    if (!mask) {
        warnScript << "Document.selection() refused:" << error;
        return nullptr;
    }
    // A selection on the document's bounds that shares the combined mask's tiles.
    KisSelectionSP result = new KisSelection(new KisDefaultBounds(image), toQShared(new KisImageResolutionProxy(image)));
    result->pixelSelection()->applySelection(mask, SELECTION_REPLACE);
    return new Selection(result);
}
