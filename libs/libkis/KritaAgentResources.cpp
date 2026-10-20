/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
// Krita Agent: brush tips and presets made by scripts (krita-fork 5.1).
//
// What the Custom Brush dialog's "Stamp" does (a KisGbrBrush from pixels, saved as a resource), and what the brush
// editor does when it saves a preset with another tip, exposed to scripts. Both go through KisResourceModel, which
// saves the resource in the resource folder, adds it to the resource database and resets the shared models every
// resource chooser shows, so the new resource is listed and usable at once.
#include <KisDocument.h>
#include "ScriptWaits.h"
#include <kis_processing_applicator.h>
#include "Krita.h"

#include <QDir>
#include <QDomDocument>
#include <QFileInfo>
#include <QPainter>
#include <QRegularExpression>

#include <KisBrushModel.h>
#include <KisGlobalResourcesInterface.h>
#include <KisResourceLocator.h>
#include <KisResourceModel.h>
#include <KisResourceTypes.h>
#include <KisTag.h>
#include <KisTagModel.h>
#include <KisTagResourceModel.h>
#include <KisColorfulBrush.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>
#include <kis_brush.h>
#include <kis_debug.h>
#include <kis_gbr_brush.h>
#include <kis_paint_device.h>
#include <KoColorSpaceRegistry.h>
#include <kis_predefined_brush_factory.h>

#include "Document.h"
#include "Resource.h"

namespace
{

/// The tag the agent's resources appear under in the brush and preset choosers (its name and its url).
const QString AgentTag = QStringLiteral("Agent");

/**
 * Resource metadata (kept in the resource database) holding how a tip made here is applied: a .gbr file keeps a
 * colour tip's pixels but not whether it stamps its colours or its lightness, so a tip loaded again from its file
 * would otherwise be a lightness map.
 */
const QString ApplicationMetaData = QStringLiteral("kritaagent_brush_application");

/// \p name as a file name: characters that are not letters, digits, '-', '_' or '.' become '_'.
QString fileNameFor(const QString &name, const QString &extension)
{
    QString base = name.trimmed();
    base.replace(QRegularExpression(QStringLiteral("[^A-Za-z0-9_.-]")), QStringLiteral("_"));
    while (base.startsWith(QLatin1Char('.'))) base.remove(0, 1);
    if (base.isEmpty()) base = QStringLiteral("agent");
    return base + extension;
}

/// Tags the resource \p resourceId of \p resourceType with the agent's tag, creating the tag if needed.
bool tagForAgent(const QString &resourceType, int resourceId)
{
    if (resourceId < 0) return false;

    KisTagModel tags(resourceType);
    tags.setTagFilter(KisTagModel::ShowAllTags);
    KisTagSP tag = tags.tagForUrl(AgentTag);
    if (!tag) {
        tag = tags.addTag(AgentTag, false, {});
    } else if (!tag->active()) {
        tags.setTagActive(tag);
        tag = tags.tagForUrl(AgentTag);
    }
    if (!tag) return false;

    KisTagResourceModel tagged(resourceType);
    return tagged.tagResources(tag, {resourceId});
}

/// Whether the resource \p resourceId of \p resourceType carries the agent's tag.
bool isAgentTagged(const QString &resourceType, int resourceId)
{
    KisResourceModel model(resourceType);
    Q_FOREACH (KisTagSP tag, model.tagsForResource(resourceId)) {
        if (tag && tag->url() == AgentTag) return true;
    }
    return false;
}

/// Whether \p resource lives in the resource folder (the folder storage), not in a bundle or a document.
bool inResourceFolder(KoResourceSP resource)
{
    const QString location = resource->storageLocation();
    return location.isEmpty()
        || QDir::cleanPath(location) == QDir::cleanPath(KisResourceLocator::instance()->resourceLocationBase());
}

/**
 * The resource named \p name that a resource made here may replace: one the agent made (tagged "Agent"), in the
 * resource folder, saved in the same format (\p extension). Null when there is none.
 */
KoResourceSP agentOwned(const QString &resourceType, const QString &name, const QString &extension)
{
    KisResourceModel model(resourceType);
    const QString suffix = extension.startsWith(QLatin1Char('.')) ? extension.mid(1) : extension;
    Q_FOREACH (KoResourceSP resource, model.resourcesForName(name)) {
        if (resource && resource->resourceId() >= 0 && inResourceFolder(resource)
            && QFileInfo(resource->filename()).suffix().compare(suffix, Qt::CaseInsensitive) == 0
            && isAgentTagged(resourceType, resource->resourceId())) {
            return resource;
        }
    }
    return KoResourceSP();
}

/**
 * Adds \p resource to the resource database and the resource folder, and tags it "Agent".
 *
 * A resource the agent made earlier under the same name (agentOwned()) is replaced: \p resource becomes a new version
 * of it, as saving an edited resource does in Krita, so what uses it by name, file name or checksum finds the new one.
 * Any other resource of that name (Krita's own, the artist's, a bundle's or a document's) is never touched: \p resource
 * is then added under the first free name of "name (2)", "name (3)", ..., which it keeps (a later call with the same
 * name replaces that one). Its file name is made unique in the folder.
 */
bool addToDatabase(const QString &resourceType, KoResourceSP resource)
{
    KisResourceModel model(resourceType);
    const QString requested = resource->name();
    const QString extension = resource->defaultFileExtension();
    QString name = requested;
    KoResourceSP old;
    for (int n = 2;; n++) {
        if (model.resourcesForName(name).isEmpty()) break;
        old = agentOwned(resourceType, name, extension);
        if (old) break;
        name = QString("%1 (%2)").arg(requested).arg(n);
    }
    if (name != requested) {
        resource->setName(name);
        resource->setFilename(fileNameFor(name, extension));
    }

    bool added = false;
    if (old) {
        resource->setResourceId(old->resourceId());
        resource->setVersion(old->version());
        resource->setMD5Sum(old->md5Sum());
        resource->setStorageLocation(old->storageLocation());
        resource->setFilename(old->filename());
        resource->setActive(true);
        added = model.updateResource(resource);
    } else {
        added = model.addResourceDeduplicateFileName(resource);
    }
    if (!added || resource->resourceId() < 0) {
        warnScript << "Krita: could not add" << resourceType << resource->name() << "to the resource database";
        return false;
    }
    if (!tagForAgent(resourceType, resource->resourceId())) {
        warnScript << "Krita: could not tag" << resourceType << resource->name() << "for the agent";
    }
    return true;
}

/// \p image as an RGBA paint device, as the brush dialog reads an image.
KisPaintDeviceSP deviceFrom(const QImage &image)
{
    KisPaintDeviceSP device = new KisPaintDevice(KoColorSpaceRegistry::instance()->rgb8());
    device->convertFromQImage(image, nullptr);
    return device;
}

/**
 * A brush tip from \p image, used as \p application says; null for an unknown application. It is made as the
 * Custom Brush dialog makes one, from a paint device (an RGBA tip), then turned into a mask where the application
 * asks for one (KisGbrBrush::makeMaskImage(), the dialog's "Create mask from color").
 */
KisBrushSP makeBrushTip(const QImage &image, const QString &name, const QString &application)
{
    QImage argb = image.convertToFormat(QImage::Format_ARGB32);
    const bool alpha = application == QLatin1String("alpha");
    if (alpha) {
        // Black with the image's alpha: the mask's coverage is then the alpha alone.
        for (int y = 0; y < argb.height(); y++) {
            QRgb *line = reinterpret_cast<QRgb *>(argb.scanLine(y));
            for (int x = 0; x < argb.width(); x++) line[x] = qRgba(0, 0, 0, qAlpha(line[x]));
        }
    } else if (application != QLatin1String("mask") && application != QLatin1String("image")
               && application != QLatin1String("lightness")) {
        return KisBrushSP();
    }

    QSharedPointer<KisGbrBrush> brush(new KisGbrBrush(deviceFrom(argb), 0, 0, argb.width(), argb.height()));
    if (alpha || application == QLatin1String("mask")) {
        brush->makeMaskImage(false);
        brush->setHasColorAndTransparency(false);
    } else {
        brush->setHasColorAndTransparency(!argb.allGray());
        brush->setBrushApplication(application == QLatin1String("image") ? IMAGESTAMP : LIGHTNESSMAP);
    }

    brush->setName(name);
    brush->setFilename(fileNameFor(name, brush->defaultFileExtension()));
    brush->addMetaData(ApplicationMetaData, int(brush->brushApplication()));
    brush->setValid(true);
    return brush;
}

/// The application createBrushTip() recorded for the tip \p resourceId in the resource database, if any.
QVariant tipApplication(int resourceId)
{
    KisResourceModel model(ResourceType::Brushes);
    const QModelIndex index = model.indexForResourceId(resourceId);
    if (!index.isValid()) return QVariant();
    return index.data(Qt::UserRole + KisAbstractResourceModel::MetaData).toMap().value(ApplicationMetaData);
}

/// A preset thumbnail: the tip, fitted into 200x200 on white, as the brush editor shows it.
QImage presetThumbnail(KisBrushSP tip)
{
    QImage thumbnail(200, 200, QImage::Format_ARGB32);
    thumbnail.fill(Qt::white);
    QImage image = tip->brushTipImage();
    if (image.isNull()) return thumbnail;
    if (tip->brushType() != IMAGE && tip->brushType() != PIPE_IMAGE) {
        image = image.convertToFormat(QImage::Format_ARGB32); // grey mask: dark is paint
    }
    const QImage fitted = image.scaled(180, 180, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    QPainter painter(&thumbnail);
    painter.drawImage((200 - fitted.width()) / 2, (200 - fitted.height()) / 2, fitted);
    return thumbnail;
}

/// Makes \p preset (a copy, not in the database) use \p tip, named \p name, and adds it to the database.
Resource *finishPreset(KisPaintOpPresetSP preset, KisBrushSP tip, const QString &name)
{
    KisPaintOpSettingsSP settings = preset->settings();
    if (!settings || !settings->hasProperty("brush_definition")) {
        warnScript << "Krita.createPreset(): the base preset's engine" << preset->paintOp().id() << "has no brush tip";
        return nullptr;
    }

    KisBrushModel::BrushData brush;
    brush.type = KisBrushModel::Predefined;
    KisPredefinedBrushFactory::loadFromBrushResource(brush.common, brush.predefinedBrush, tip);
    brush.predefinedBrush.application = tip->brushApplication();
    const QVariant application = tipApplication(tip->resourceId());
    if (application.isValid() && tip->brushType() == IMAGE) {
        brush.predefinedBrush.application = enumBrushApplication(application.toInt());
    }
    brush.predefinedBrush.scale = 1.0;
    if (KisColorfulBrush *colorful = dynamic_cast<KisColorfulBrush *>(tip.data())) {
        brush.predefinedBrush.hasColorAndTransparency = colorful->hasColorAndTransparency();
        brush.predefinedBrush.adjustmentMidPoint = colorful->adjustmentMidPoint();
        brush.predefinedBrush.brightnessAdjustment = colorful->brightnessAdjustment();
        brush.predefinedBrush.contrastAdjustment = colorful->contrastAdjustment();
        brush.predefinedBrush.autoAdjustMidPoint = colorful->autoAdjustMidPoint();
    }
    brush.write(settings.data());

    // A new resource, not a version of the base: no id, storage or checksum of the base's.
    preset->setResourceId(-1);
    preset->setStorageLocation(QString());
    preset->setMD5Sum(QString());
    preset->setVersion(0);
    preset->setName(name);
    preset->setFilename(fileNameFor(name, preset->defaultFileExtension()));
    preset->setImage(presetThumbnail(tip));
    preset->setValid(true);

    if (!addToDatabase(ResourceType::PaintOpPresets, preset)) return nullptr;
    return new Resource(preset, QStringLiteral("preset"));
}

/// The brush tip \p resource holds, or null.
KisBrushSP brushTipOf(KoResourceSP resource)
{
    return resource ? resource.dynamicCast<KisBrush>() : KisBrushSP();
}

} // namespace

Resource *Krita::createBrushTip(const QImage &image, const QString &name, const QString &application)
{
    if (image.isNull() || image.width() <= 0 || image.height() <= 0 || name.trimmed().isEmpty()) return nullptr;

    KisBrushSP brush = makeBrushTip(image, name, application);
    if (!brush) {
        warnScript << "Krita.createBrushTip(): unknown application" << application;
        return nullptr;
    }
    if (!addToDatabase(ResourceType::Brushes, brush)) return nullptr;
    return new Resource(brush, QStringLiteral("brush"));
}

Resource *Krita::createBrushTip(Document *document, const QRect &rect, const QString &name, const QString &application)
{
    if (!document || document->width() <= 0 || document->height() <= 0) return nullptr;

    const QRect bounds(0, 0, document->width(), document->height());
    const QRect area = rect.isEmpty() ? bounds : rect.intersected(bounds);
    if (area.isEmpty()) return nullptr;

    // the work already queued lands first (nothing here starts a stroke, so nothing is suppressed)
    ScriptWaits::run(document->document()->image(), "Krita.createBrushTip()", []() {});
    const QImage image = document->projection(area.x(), area.y(), area.width(), area.height());
    return createBrushTip(image, name, application);
}

Resource *Krita::createPreset(Resource *basePreset, Resource *brushTip, const QString &name)
{
    if (!basePreset || !brushTip || name.trimmed().isEmpty()) return nullptr;
    KisPaintOpPresetSP base = basePreset->resource().dynamicCast<KisPaintOpPreset>();
    KisBrushSP tip = brushTipOf(brushTip->resource());
    if (!base || !tip) return nullptr;

    KisPaintOpPresetSP preset = base->clone().dynamicCast<KisPaintOpPreset>();
    if (!preset) return nullptr;
    return finishPreset(preset, tip, name);
}

Resource *Krita::createPreset(const QString &baseXml, Resource *brushTip, const QString &name)
{
    if (!brushTip || name.trimmed().isEmpty()) return nullptr;

    KisBrushSP tip = brushTipOf(brushTip->resource());
    if (!tip) return nullptr;

    QDomDocument xml;
    if (!xml.setContent(baseXml)) {
        warnScript << "Krita.createPreset(): the base preset's XML is not valid";
        return nullptr;
    }
    KisPaintOpPresetSP preset(new KisPaintOpPreset());
    preset->fromXML(xml.documentElement(), KisGlobalResourcesInterface::instance());
    if (!preset->valid() || !preset->settings() || preset->paintOp().id().isEmpty()) {
        warnScript << "Krita.createPreset(): the base preset's XML is not a preset";
        return nullptr;
    }
    return finishPreset(preset, tip, name);
}
