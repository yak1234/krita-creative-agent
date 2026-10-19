/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "Feature.h"

#include <KoColor.h>

#include <KisFeatureList.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>

#include "Selection.h"

struct Feature::Private {
    KisImageWSP image;
    KisFeatureSP feature;
};

Feature::Feature(KisImageSP image, KisFeatureSP feature, QObject *parent)
    : QObject(parent)
    , d(new Private)
{
    d->image = image;
    d->feature = feature;
}

Feature::~Feature()
{
    delete d;
}

bool Feature::operator==(const Feature &other) const
{
    return d->feature && other.d->feature && d->feature->id() == other.d->feature->id();
}

bool Feature::operator!=(const Feature &other) const
{
    return !(operator==(other));
}

QString Feature::id() const
{
    return d->feature ? d->feature->id().toString() : QString();
}

QString Feature::name() const
{
    return d->feature ? d->feature->name() : QString();
}

QString Feature::kind() const
{
    return d->feature ? d->feature->kind() : QString();
}

QString Feature::author() const
{
    return d->feature ? KisFeature::authorToString(d->feature->author()) : QString();
}

QString Feature::state() const
{
    return d->feature ? KisFeature::stateToString(d->feature->state()) : QString();
}

bool Feature::isProtected() const
{
    return d->feature ? d->feature->isProtected() : false;
}

QRect Feature::bounds() const
{
    return d->feature ? d->feature->bounds() : QRect();
}

qint64 Feature::area() const
{
    return d->feature ? d->feature->area() : 0;
}

QColor Feature::meanColor() const
{
    if (!d->feature) return QColor();
    const KisFeature::Properties properties = d->feature->properties();
    if (!properties.hasMeanColor) return QColor();
    QColor color;
    properties.meanColor.toQColor(&color);
    return color;
}

Selection *Feature::mask() const
{
    if (!d->feature) return nullptr;
    KisPixelSelectionSP source = d->feature->mask();
    // A copy that shares the tiles with the feature's mask until one side changes them.
    KisSelectionSP selection = new KisSelection(KisPaintDeviceSP(source), KritaUtils::CopySnapshot,
                                                source->defaultBounds(), KisImageResolutionProxySP());
    return new Selection(selection);
}

bool Feature::isInDocument() const
{
    KisImageSP image = d->image.toStrongRef();
    return image && d->feature && image->featureList()->feature(d->feature->id()) == d->feature;
}

KisFeatureSP Feature::feature() const
{
    return d->feature;
}
