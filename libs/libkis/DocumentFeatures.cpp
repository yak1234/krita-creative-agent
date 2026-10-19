/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Document's feature map (Krita Agent, openspec change krita-fork, capability canvas-features). Kept apart from
// Document.cpp so the upstream file carries only their declarations.

#include "Document.h"
#include "DocumentHistory.h"
#include "Feature.h"
#include "Selection.h"

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureCommands.h>
#include <KisFeatureList.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>

namespace {

KisImageSP imageOf(const QPointer<KisDocument> &document)
{
    if (!document) return KisImageSP();
    return document->image();
}

/// Runs \p cmd as one undo step, or as part of the open macro or agent move, the way libkis Node runs its
/// commands, and waits for it. Not through KisProcessingApplicator directly: the history would take it for the
/// artist's work and split an open agent move around it.
void runCommand(KisImageSP image, KUndo2Command *cmd)
{
    DocumentHistory::runCommandStroke(image, cmd);
    image->waitForDone();
}

/// A feature's name has to say something: not empty, not only spaces. Outer spaces are dropped (\ref
/// featureName), so "Sky" and "Sky " are one name.
bool isValidName(const QString &name)
{
    return !name.trimmed().isEmpty();
}

QString featureName(const QString &name)
{
    return name.trimmed();
}

} // namespace

QList<Feature *> Document::features() const
{
    QList<Feature *> result;
    KisImageSP image = imageOf(document());
    if (!image) return result;
    Q_FOREACH (KisFeatureSP feature, image->featureList()->features()) {
        result << new Feature(image, feature);
    }
    return result;
}

Feature *Document::feature(const QString &name) const
{
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    KisFeatureSP feature = image->featureList()->featureByName(name);
    return feature ? new Feature(image, feature) : nullptr;
}

Feature *Document::addFeature(const QString &rawName,
                              const QString &kind,
                              Selection *mask,
                              const QString &author,
                              const QString &state,
                              bool isProtected)
{
    KisImageSP image = imageOf(document());
    if (!image || !mask || !mask->selection() || !isValidName(rawName)) return nullptr;
    const QString name = featureName(rawName);
    if (image->featureList()->featureByName(name)) return nullptr;

    const KisFeature::Author featureAuthor = KisFeature::authorFromString(author, KisFeature::Agent);
    const KisFeature::State featureState = KisFeature::stateFromString(state, KisFeature::Proposed);
    if (KisFeature::authorToString(featureAuthor) != author || KisFeature::stateToString(featureState) != state) {
        return nullptr;
    }

    // A copy of the selection's pixels (sharing its tiles until one side changes), cut to the document: the mask
    // describes the painting, so nothing lies outside it (not even an inverted selection's selected default).
    KisPixelSelectionSP pixels = KisFeature::boundedMask(mask->selection()->projection(), image->bounds());

    KisFeatureSP feature = new KisFeature(name, kind, pixels, featureAuthor, featureState, isProtected);
    // The mean colour is read from the composited painting, after the work already queued.
    image->waitForDone();
    feature->measure(image->projection());

    runCommand(image, new KisAddFeatureCommand(image, feature));
    return new Feature(image, feature);
}

bool Document::renameFeature(const QString &name, const QString &rawNewName)
{
    KisImageSP image = imageOf(document());
    if (!image || !isValidName(rawNewName)) return false;
    const QString newName = featureName(rawNewName);
    KisFeatureSP feature = image->featureList()->featureByName(name);
    if (!feature) return false;
    if (newName == name) return true;
    if (image->featureList()->featureByName(newName)) return false;

    runCommand(image, new KisRenameFeatureCommand(image, feature->id(), newName));
    return true;
}

bool Document::removeFeature(const QString &name)
{
    KisImageSP image = imageOf(document());
    if (!image) return false;
    KisFeatureSP feature = image->featureList()->featureByName(name);
    if (!feature) return false;

    runCommand(image, new KisRemoveFeatureCommand(image, feature->id()));
    return true;
}
