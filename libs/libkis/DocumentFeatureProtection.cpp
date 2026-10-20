/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Document's protection report and override (Krita Agent, openspec change krita-fork, task 6.5). The enforcement
// itself is in the write paths (see Feature::setProtected() for the list); this file is what scripts read and set.

#include "Document.h"

#include <QPointer>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include <KisImageResolutionProxy.h>
#include <kis_default_bounds.h>
#include <kis_pixel_selection.h>
#include <kis_pointer_utils.h>
#include <kis_selection.h>
#include <kis_debug.h>
#include "DocumentHistory.h"
#include "Selection.h"
#include <kis_image.h>

namespace
{
KisImageSP imageOf(const QPointer<KisDocument> &document)
{
    return document ? KisImageSP(document->image()) : KisImageSP();
}
}

QStringList Document::lastKeptOut() const
{
    KisImageSP image = imageOf(document());
    return image ? image->featureList()->lastKeptOut() : QStringList();
}

QStringList Document::agentMoveKeptOut() const
{
    KisImageSP image = imageOf(document());
    return image ? image->featureList()->moveKeptOut() : QStringList();
}

bool Document::setProtectionSuspended(bool suspended)
{
    KisImageSP image = imageOf(document());
    if (!image) return false;
    if (suspended && !DocumentHistory::isAgentMoveOpen(image.data())) {
        warnScript << "Document.setProtectionSuspended(True) refused: it is allowed inside an open agent move only"
                   << "(so that it can never outlast its edit); begin a move, or pass allowProtected to the call";
        return false;
    }
    image->featureList()->setProtectionSuspended(suspended);
    return true;
}

bool Document::protectionSuspended() const
{
    KisImageSP image = imageOf(document());
    return image && image->featureList()->protectionSuspended();
}

bool Document::protectionActive() const
{
    KisImageSP image = imageOf(document());
    return image && KisFeatureProtection::isActive(image);
}

Selection *Document::protectedSelection(bool inverted) const
{
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    KisFeatureList *list = image->featureList();
    KisSelectionSP result = new KisSelection(new KisDefaultBounds(image), toQShared(new KisImageResolutionProxy(image)));
    KisPixelSelectionSP source = inverted ? list->unprotectedMask() : list->protectedMask();
    if (source) {
        // A copy: the cached union is shared by every caller and must not change.
        result->pixelSelection()->applySelection(KisFeature::boundedMask(source, image->bounds()), SELECTION_REPLACE);
    } else if (inverted) {
        result->pixelSelection()->select(image->bounds(), MAX_SELECTED);
    }
    return new Selection(result);
}
