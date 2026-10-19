/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "KisKraFeatures.h"

#include <QByteArray>
#include <QUuid>

#include <klocalizedstring.h>

#include <KoColor.h>
#include <KoColorProfile.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoStore.h>

#include <KisFeature.h>
#include <KisFeatureList.h>
#include <kis_config.h>
#include <kis_dom_utils.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <kis_store_paintdevice_writer.h>

namespace KisKraFeatures
{
const QString ElementName = QStringLiteral("features");
const QString MasksPath = QStringLiteral("/features/");

namespace
{
const QString FeatureElement = QStringLiteral("feature");
const QString BoundsElement = QStringLiteral("bounds");
const QString MeanColorElement = QStringLiteral("meanColor");

QString maskFileName(const KisFeatureSP feature)
{
    return QStringLiteral("feature-") + feature->id().toString(QUuid::WithoutBraces);
}

QString maskLocation(const QString &imageName, const QString &fileName)
{
    return imageName + MasksPath + fileName;
}

/// File names come from the file: keep them to one plain name inside the masks folder.
bool isPlainFileName(const QString &name)
{
    return !name.isEmpty() && !name.contains(QLatin1Char('/')) && !name.contains(QLatin1Char('\\'))
        && name != QLatin1String(".") && name != QLatin1String("..");
}

void saveMeanColor(QDomDocument &doc, QDomElement &featureElement, const KoColor &color)
{
    const KoColorSpace *cs = color.colorSpace();
    QDomElement e = doc.createElement(MeanColorElement);
    e.setAttribute("colorModel", cs->colorModelId().id());
    e.setAttribute("colorDepth", cs->colorDepthId().id());
    if (cs->profile()) {
        e.setAttribute("profile", cs->profile()->name());
    }
    const QByteArray bytes(reinterpret_cast<const char *>(color.data()), int(cs->pixelSize()));
    e.setAttribute("data", QString::fromLatin1(bytes.toBase64()));
    featureElement.appendChild(e);
}

bool loadMeanColor(const QDomElement &e, KoColor *color)
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->colorSpace(e.attribute("colorModel"),
                                                                           e.attribute("colorDepth"),
                                                                           e.attribute("profile"));
    if (!cs) return false;
    const QByteArray bytes = QByteArray::fromBase64(e.attribute("data").toLatin1());
    if (bytes.size() != int(cs->pixelSize())) return false;
    *color = KoColor(reinterpret_cast<const quint8 *>(bytes.constData()), cs);
    return true;
}

bool readMask(KoStore *store, const QString &location, KisPixelSelectionSP mask)
{
    // As KisKraLoadVisitor::loadPaintDeviceFrame reads a layer's pixel selection: the default pixel first.
    if (store->open(location + ".defaultpixel")) {
        const int pixelSize = int(mask->colorSpace()->pixelSize());
        if (store->size() == pixelSize) {
            KoColor color = KoColor::createTransparent(mask->colorSpace());
            store->read(reinterpret_cast<char *>(color.data()), pixelSize);
            mask->setDefaultPixel(color);
        }
        store->close();
    }
    if (!store->open(location)) return false;
    const bool ok = mask->read(store->device());
    store->close();
    return ok;
}
} // namespace

void saveToXML(QDomDocument &doc, QDomElement &imageElement, KisImageSP image)
{
    if (!image || image->featureList()->isEmpty()) return;

    QDomElement featuresElement = doc.createElement(ElementName);
    featuresElement.setAttribute("version", Version);
    const int sourceVersion = image->featureList()->sourceVersion();
    if (sourceVersion > Version) {
        qWarning("The features were loaded from a .kra of features version %d; they are saved as version %d, "
                 "without what version %d added.",
                 sourceVersion, Version, sourceVersion);
    }

    Q_FOREACH (KisFeatureSP feature, image->featureList()->features()) {
        const KisFeature::Properties properties = feature->properties();

        QDomElement e = doc.createElement(FeatureElement);
        e.setAttribute("id", feature->id().toString());
        e.setAttribute("name", feature->name());
        e.setAttribute("kind", feature->kind());
        e.setAttribute("author", KisFeature::authorToString(feature->author()));
        e.setAttribute("state", KisFeature::stateToString(feature->state()));
        e.setAttribute("protected", feature->isProtected() ? "true" : "false");
        e.setAttribute("mask", maskFileName(feature));
        e.setAttribute("area", QString::number(properties.area));

        QDomElement bounds = doc.createElement(BoundsElement);
        bounds.setAttribute("x", properties.bounds.x());
        bounds.setAttribute("y", properties.bounds.y());
        bounds.setAttribute("width", properties.bounds.width());
        bounds.setAttribute("height", properties.bounds.height());
        e.appendChild(bounds);

        if (properties.hasMeanColor) {
            saveMeanColor(doc, e, properties.meanColor);
        }
        featuresElement.appendChild(e);
    }

    // Appended, never inserted first: stock Krita's loader reads the layers from <IMAGE>'s first child. Elements
    // saveXML() writes after this call (<animation>) follow it.
    imageElement.appendChild(featuresElement);
}

bool saveMasks(KoStore *store, const QString &imageName, KisImageSP image, QStringList *errors)
{
    if (!image || image->featureList()->isEmpty()) return true;

    KisConfig cfg(true);
    store->setCompressionEnabled(cfg.compressKra());
    KisStorePaintDeviceWriter writer(store);

    bool success = true;
    Q_FOREACH (KisFeatureSP feature, image->featureList()->features()) {
        const QString location = maskLocation(imageName, maskFileName(feature));
        KisPixelSelectionSP mask = feature->mask();

        bool written = store->open(location);
        if (written) {
            written = mask->write(writer);
            written = store->close() && written;
        }
        if (written && store->open(location + ".defaultpixel")) {
            const KoColor defaultPixel = mask->defaultPixel();
            const qint64 size = mask->colorSpace()->pixelSize();
            written = store->write(reinterpret_cast<const char *>(defaultPixel.data()), size) == size;
            written = store->close() && written;
        } else {
            written = false;
        }

        if (!written) {
            success = false;
            if (errors) {
                *errors << i18nc("Error message when saving a .kra file", "Could not save the mask of feature %1.",
                                 feature->name());
            }
        }
    }

    store->setCompressionEnabled(true);
    return success;
}

void load(const QDomElement &featuresElement,
          KoStore *store,
          const QString &imageName,
          KisImageSP image,
          QStringList *warnings)
{
    if (featuresElement.isNull() || !image) return;

    auto warn = [warnings](const QString &message) {
        if (warnings) *warnings << message;
    };

    bool versionOk = false;
    const int version = featuresElement.attribute("version").toInt(&versionOk);
    // A later version is read as far as this one understands it: what it adds is ignored.
    if (!versionOk || version < 1) {
        warn(i18nc("Warning when loading a .kra file",
                   "The features in this file have version %1, which this version of Krita cannot read; they were "
                   "not loaded.",
                   featuresElement.attribute("version")));
        return;
    }

    KisFeatureList *list = image->featureList();
    list->setSourceVersion(version);

    for (QDomElement e = featuresElement.firstChildElement(FeatureElement); !e.isNull();
         e = e.nextSiblingElement(FeatureElement)) {
        // The names addFeature() allows: outer spaces dropped, never blank.
        QString name = e.attribute("name").trimmed();
        if (name.isEmpty()) {
            name = QStringLiteral("Feature");
            warn(i18nc("Warning when loading a .kra file", "A feature had no name; it was called %1.", name));
        }
        const QString fileName = e.attribute("mask");
        if (!isPlainFileName(fileName)) {
            warn(i18nc("Warning when loading a .kra file", "Feature %1 has no mask; it was not loaded.", name));
            continue;
        }

        KisPixelSelectionSP mask = new KisPixelSelection(list->defaultBounds());
        if (!readMask(store, maskLocation(imageName, fileName), mask)) {
            warn(i18nc("Warning when loading a .kra file", "Could not load the mask of feature %1; it was not loaded.",
                       name));
            continue;
        }
        // Cut to the document, on an unselected default pixel, as addFeature makes masks.
        mask = KisFeature::boundedMask(mask, image->bounds());

        // Names are unique in a document: a later feature of a name already taken is renamed.
        QString uniqueName = name;
        for (int n = 2; list->featureByName(uniqueName); n++) {
            uniqueName = QStringLiteral("%1 (%2)").arg(name).arg(n);
        }
        if (uniqueName != name) {
            warn(i18nc("Warning when loading a .kra file", "Two features are called %1; the later one was renamed %2.",
                       name, uniqueName));
        }

        KisFeatureSP feature = new KisFeature(uniqueName,
                                              e.attribute("kind"),
                                              mask,
                                              KisFeature::authorFromString(e.attribute("author")),
                                              KisFeature::stateFromString(e.attribute("state")),
                                              e.attribute("protected") == QLatin1String("true"),
                                              QUuid(e.attribute("id")));

        // Bounds and area from the mask itself; the mean colour as saved, measured on the painting when the feature
        // was made or changed (the painting is not composited yet here).
        KisFeature::Properties properties = KisFeature::measureMask(mask, KisPaintDeviceSP());
        const QDomElement colorElement = e.firstChildElement(MeanColorElement);
        if (!colorElement.isNull()) {
            properties.hasMeanColor = loadMeanColor(colorElement, &properties.meanColor);
            if (!properties.hasMeanColor) {
                warn(i18nc("Warning when loading a .kra file", "Could not read the mean colour of feature %1.", name));
            }
        }
        feature->setProperties(properties);

        if (!list->insertFeature(feature)) {
            warn(i18nc("Warning when loading a .kra file",
                       "Feature %1 has the same id as another feature; it was not loaded.", name));
        }
    }
}
} // namespace KisKraFeatures
