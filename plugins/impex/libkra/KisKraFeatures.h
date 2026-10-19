/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef KISKRAFEATURES_H
#define KISKRAFEATURES_H

#include <QDomDocument>
#include <QDomElement>
#include <QString>
#include <QStringList>

#include <kis_types.h>

#include "kritalibkra_export.h"

class KoStore;

/**
 * The feature map in a .kra (krita-fork, capability canvas-features). KisKraSaver and KisKraLoader call these, the
 * way they save storyboards and assistants: the list is an element of maindoc.xml, and each mask a file in the
 * image's folder of the zip, written by Krita's paint-device writer as selection masks are.
 *
 * In maindoc.xml, a child of <IMAGE> appended after the layers and the other elements saveXML() writes before it
 * (never the first child: stock Krita's loader reads the layers from the first child; <animation> follows it), and
 * only when the image has features:
 *
 * @code{.xml}
 * <features version="1">
 *   <feature id="{uuid}" name="Sky" kind="sky" author="artist" state="kept" protected="true"
 *            mask="feature-<uuid>" area="270000">
 *     <bounds x="0" y="0" width="6000" height="1800"/>
 *     <meanColor colorModel="RGBA" colorDepth="U8" profile="..." data="<base64 pixel>"/>
 *   </feature>
 *   ...
 * </features>
 * @endcode
 *
 * The mask of each feature is `<image name>/features/<mask>` with its default pixel in `<mask>.defaultpixel`, both as
 * KisKraSaveVisitor writes a layer's pixel selection. Stock Krita ignores the element and the files.
 *
 * Loading never fails a document: a features element without a readable version (1 or later), a missing mask or a
 * bad attribute gives a warning, and the painting opens without that part. A later version is read as far as this
 * one understands it: unknown attributes and elements are ignored. Bounds and area are measured from the mask on
 * load (the saved ones are for other readers); the mean colour is the saved one, since the painting is not
 * composited yet. Names lose their outer spaces, a blank one becomes "Feature", and two features of one name keep
 * both, the later renamed "<name> (2)", with a warning. Masks are cut to the document on an unselected default
 * pixel (KisFeature::boundedMask()).
 *
 * Saving always writes this build's version. A list loaded from a later version (KisFeatureList::sourceVersion())
 * loses what that version added, and the save logs a warning saying so.
 */
namespace KisKraFeatures
{
/// The version this build writes; it reads this one and later ones.
const int Version = 1;
/// The element in maindoc.xml.
KRITALIBKRA_EXPORT extern const QString ElementName;
/// The folder of the masks, inside the image's folder of the zip.
KRITALIBKRA_EXPORT extern const QString MasksPath;

/// Appends the <features> element to \p imageElement when \p image has features.
KRITALIBKRA_EXPORT void saveToXML(QDomDocument &doc, QDomElement &imageElement, KisImageSP image);

/**
 * Writes the masks of \p image's features into \p store.
 * @return false, with a message in \p errors, if a mask could not be written
 */
KRITALIBKRA_EXPORT bool saveMasks(KoStore *store, const QString &imageName, KisImageSP image, QStringList *errors);

/**
 * Adds the features described by \p featuresElement to \p image's list, with their masks read from \p store, their
 * bounds and area measured, and their saved mean colours. Problems go to \p warnings. A null element does nothing.
 */
KRITALIBKRA_EXPORT void load(const QDomElement &featuresElement,
                             KoStore *store,
                             const QString &imageName,
                             KisImageSP image,
                             QStringList *warnings);
}

#endif // KISKRAFEATURES_H
