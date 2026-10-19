/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestKritaAgentResources.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QApplication>
#include <QClipboard>
#include <QDomDocument>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QScopedPointer>
#include <QTimer>

#include <Document.h>
#include <Krita.h>
#include <Node.h>
#include <Preset.h>
#include <Resource.h>
#include <View.h>

#include <KisDocument.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisResourceLocator.h>
#include <KisResourceModel.h>
#include <KisResourceTypes.h>
#include <KisTag.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KisGlobalResourcesInterface.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <KoCompositeOpRegistry.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_registry.h>
#include <brushengine/kis_paintop_settings.h>
#include <kis_brush.h>
#include <kis_gbr_brush.h>
#include <kis_canvas_resource_provider.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>

namespace {

const QString AgentTagUrl = QStringLiteral("Agent");

/// A tip image with varied colour and alpha in every pixel.
QImage testTipImage(const QSize &size = QSize(32, 24))
{
    QImage image(size, QImage::Format_ARGB32);
    for (int y = 0; y < size.height(); y++) {
        for (int x = 0; x < size.width(); x++) {
            image.setPixel(x, y, qRgba((x * 8) % 256, (y * 10) % 256, 128, (x * 7 + y * 3 + 20) % 256));
        }
    }
    return image;
}

KoResourceSP findResource(const QString &type, const QString &name)
{
    KisResourceModel model(type);
    const QVector<KoResourceSP> found = model.resourcesForName(name);
    return found.isEmpty() ? KoResourceSP() : found.first();
}

bool isAgentTagged(const QString &type, KoResourceSP resource)
{
    KisResourceModel model(type);
    Q_FOREACH (KisTagSP tag, model.tagsForResource(resource->resourceId())) {
        if (tag->url() == AgentTagUrl) return true;
    }
    return false;
}

/// A pixel-brush preset that paints (blending mode Normal) with a brush tip from the resource database (one of Krita's own), as a script would pass it.
KisPaintOpPresetSP basePixelBrushPreset()
{
    KisResourceModel model(ResourceType::PaintOpPresets);
    for (int row = 0; row < model.rowCount(); row++) {
        KisPaintOpPresetSP preset = model.resourceForIndex(model.index(row, 0)).dynamicCast<KisPaintOpPreset>();
        if (preset && preset->valid() && preset->paintOp().id() == "paintbrush"
            && preset->settings()->hasProperty("brush_definition")
            && preset->settings()->paintOpCompositeOp() == COMPOSITE_OVER) {
            return preset;
        }
    }
    return KisPaintOpPresetSP();
}

/// The XML of basePixelBrushPreset(), as Preset.toXML() gives it.
QString defaultPixelBrushXml()
{
    KisPaintOpPresetSP preset = basePixelBrushPreset();
    if (!preset) return QString();
    QDomDocument doc;
    QDomElement root = doc.createElement("Preset");
    preset->toXML(doc, root);
    doc.appendChild(root);
    return doc.toString();
}

/// The brush definition element a preset's settings hold.
QDomElement brushDefinition(KisPaintOpPresetSP preset)
{
    QDomDocument doc;
    doc.setContent(preset->settings()->getString("brush_definition"));
    return doc.firstChildElement("Brush");
}

/// A preset made from Krita's default pixel brush and \p tip, through the API.
Resource *presetFromXml(Resource *tip, const QString &name)
{
    return Krita::instance()->createPreset(defaultPixelBrushXml(), tip, name);
}

} // namespace

void TestKritaAgentResources::testBrushTipFromImageAlphaKeepsTheAlpha()
{
    const QImage source = testTipImage();
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(source, "agent tip alpha"));
    QVERIFY(tip);
    QCOMPARE(tip->type(), QString("brush"));
    QCOMPARE(tip->name(), QString("agent tip alpha"));

    KisBrushSP brush = findResource(ResourceType::Brushes, "agent tip alpha").dynamicCast<KisBrush>();
    QVERIFY(brush);
    QCOMPARE(brush->brushApplication(), ALPHAMASK);
    QCOMPARE(brush->width(), source.width());
    QCOMPARE(brush->height(), source.height());

    // A mask tip: 255 is no coverage, 0 full coverage; the coverage is the source's alpha, whatever its colour.
    const QImage mask = brush->brushTipImage();
    for (int y = 0; y < source.height(); y++) {
        for (int x = 0; x < source.width(); x++) {
            const int coverage = 255 - qGray(mask.pixel(x, y));
            QVERIFY2(coverage == qAlpha(source.pixel(x, y)),
                     qPrintable(QString("pixel %1,%2: coverage %3, source alpha %4")
                                    .arg(x).arg(y).arg(coverage).arg(qAlpha(source.pixel(x, y)))));
        }
    }
}

void TestKritaAgentResources::testBrushTipFromImageStampKeepsThePixels()
{
    const QImage source = testTipImage();
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(source, "agent tip image", "image"));
    QVERIFY(tip);

    KisBrushSP brush = findResource(ResourceType::Brushes, "agent tip image").dynamicCast<KisBrush>();
    QVERIFY(brush);
    QCOMPARE(brush->brushType(), IMAGE);
    // A .gbr file does not keep "stamp the colours": the database does, for the presets made with the tip.
    KisResourceModel model(ResourceType::Brushes);
    const QModelIndex index = model.indexForResourceId(brush->resourceId());
    QCOMPARE(index.data(Qt::UserRole + KisAbstractResourceModel::MetaData).toMap()
                 .value("kritaagent_brush_application").toInt(),
             int(IMAGESTAMP));

    // The tip's pixels as saved, used as a stamp: the image's own colours and alpha.
    KisGbrBrush saved(KisResourceLocator::instance()->filePathForResource(brush));
    QFile file(saved.filename());
    QVERIFY(file.open(QIODevice::ReadOnly));
    QVERIFY(saved.loadFromDevice(&file, KisGlobalResourcesInterface::instance()));
    saved.setBrushApplication(IMAGESTAMP);
    const QImage stamp = saved.brushTipImage().convertToFormat(QImage::Format_ARGB32);
    QCOMPARE(stamp.size(), source.size());
    for (int y = 0; y < source.height(); y++) {
        for (int x = 0; x < source.width(); x++) {
            QVERIFY2(stamp.pixel(x, y) == source.pixel(x, y),
                     qPrintable(QString("pixel %1,%2: %3 instead of %4")
                                    .arg(x).arg(y).arg(stamp.pixel(x, y), 8, 16).arg(source.pixel(x, y), 8, 16)));
        }
    }
}

void TestKritaAgentResources::testBrushTipIsSavedAndListedAtOnce()
{
    const QImage source = testTipImage(QSize(17, 9));
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(source, "agent tip / saved: 1"));
    QVERIFY(tip);

    // Listed by the scripting API and the resource model at once, without a restart, under the agent's tag.
    QString type("brush");
    QMap<QString, Resource *> listed = Krita::instance()->resources(type);
    const bool isListed = listed.contains("agent tip / saved: 1");
    qDeleteAll(listed);
    QVERIFY(isListed);

    KoResourceSP resource = findResource(ResourceType::Brushes, "agent tip / saved: 1");
    QVERIFY(resource);
    QVERIFY(resource->active());
    QVERIFY(isAgentTagged(ResourceType::Brushes, resource));

    // Saved in the resource folder as a .gbr whose pixels load back the same.
    const QString path = KisResourceLocator::instance()->filePathForResource(resource);
    QVERIFY2(QFile::exists(path), qPrintable(path));
    QVERIFY2(path.endsWith(".gbr"), qPrintable(path));
    QVERIFY2(!QFileInfo(path).fileName().contains('/') && !QFileInfo(path).fileName().contains(':'), qPrintable(path));

    KisGbrBrush loaded(path);
    QFile file(path);
    QVERIFY(file.open(QIODevice::ReadOnly));
    QVERIFY(loaded.loadFromDevice(&file, KisGlobalResourcesInterface::instance()));
    QCOMPARE(loaded.width(), source.width());
    const QImage mask = loaded.brushTipImage();
    for (int y = 0; y < source.height(); y++) {
        for (int x = 0; x < source.width(); x++) {
            QCOMPARE(255 - qGray(mask.pixel(x, y)), qAlpha(source.pixel(x, y)));
        }
    }

    // A second tip of the same name replaces the first: one resource of that name, with the new pixels.
    QScopedPointer<Resource> again(Krita::instance()->createBrushTip(testTipImage(QSize(5, 5)), "agent tip / saved: 1"));
    QVERIFY(again);
    KisResourceModel model(ResourceType::Brushes);
    QCOMPARE(model.resourcesForName("agent tip / saved: 1").size(), 1);
    QCOMPARE(model.resourcesForName("agent tip / saved: 1").first().dynamicCast<KisBrush>()->width(), 5);
}

void TestKritaAgentResources::testBrushTipFromDocumentArea()
{
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    KisImageSP image = new KisImage(kisdoc->createUndoStore(), 40, 30, KoColorSpaceRegistry::instance()->rgb8(), "tip");
    KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
    // Opaque black in 10,5 8x6, half-transparent black beside it in 18,5 4x6, transparent elsewhere.
    KoColor black(Qt::black, layer->colorSpace());
    layer->paintDevice()->fill(QRect(10, 5, 8, 6), black);
    black.setOpacity(quint8(128));
    layer->paintDevice()->fill(QRect(18, 5, 4, 6), black);
    image->addNode(layer);
    image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
    kisdoc->setCurrentImage(image);
    image->refreshGraphAsync();
    image->waitForDone();
    Document doc(kisdoc.data(), false);

    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(&doc, QRect(10, 5, 12, 6), "agent tip from area"));
    QVERIFY(tip);
    KisBrushSP brush = findResource(ResourceType::Brushes, "agent tip from area").dynamicCast<KisBrush>();
    QVERIFY(brush);
    QCOMPARE(brush->width(), 12);
    QCOMPARE(brush->height(), 6);
    const QImage mask = brush->brushTipImage();
    QCOMPARE(255 - qGray(mask.pixel(0, 0)), 255);
    QCOMPARE(255 - qGray(mask.pixel(7, 5)), 255);
    QVERIFY(qAbs(255 - qGray(mask.pixel(8, 0)) - 128) <= 1);

    // An empty rect takes the whole image.
    QScopedPointer<Resource> whole(Krita::instance()->createBrushTip(&doc, QRect(), "agent tip whole image"));
    QVERIFY(whole);
    brush = findResource(ResourceType::Brushes, "agent tip whole image").dynamicCast<KisBrush>();
    QVERIFY(brush);
    QCOMPARE(brush->width(), 40);
    QCOMPARE(brush->height(), 30);

    KisPart::instance()->removeDocument(kisdoc.data(), false);
}

void TestKritaAgentResources::testBrushTipRejectsBadInput()
{
    QVERIFY(!Krita::instance()->createBrushTip(QImage(), "agent tip null"));
    QVERIFY(!Krita::instance()->createBrushTip(testTipImage(), ""));
    QVERIFY(!Krita::instance()->createBrushTip(testTipImage(), "agent tip bad mode", "sparkle"));
    QVERIFY(!Krita::instance()->createBrushTip(static_cast<Document *>(nullptr), QRect(), "agent tip no doc"));
    QVERIFY(!findResource(ResourceType::Brushes, "agent tip bad mode"));
}

void TestKritaAgentResources::testPresetIsInTheResourceModelAtOnce()
{
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(), "agent cloud tip"));
    QVERIFY(tip);

    // The base is a preset from the resource database, as a script would pass it.
    KisPaintOpPresetSP basePreset = basePixelBrushPreset();
    QVERIFY(basePreset);
    QScopedPointer<Resource> base(new Resource(basePreset, "preset"));

    QScopedPointer<Resource> preset(Krita::instance()->createPreset(base.data(), tip.data(), "agent cloud"));
    QVERIFY(preset);
    QCOMPARE(preset->type(), QString("preset"));
    QCOMPARE(preset->name(), QString("agent cloud"));

    KisPaintOpPresetSP stored = findResource(ResourceType::PaintOpPresets, "agent cloud").dynamicCast<KisPaintOpPreset>();
    QVERIFY(stored);
    QVERIFY(stored->valid());
    QVERIFY(isAgentTagged(ResourceType::PaintOpPresets, stored));
    QVERIFY(!stored->image().isNull());

    QString type("preset");
    QMap<QString, Resource *> listed = Krita::instance()->resources(type);
    const bool isListed = listed.contains("agent cloud");
    qDeleteAll(listed);
    QVERIFY(isListed);

    // Its tip is the new one, at its own size, used as an alpha mask.
    const QDomElement brush = brushDefinition(stored);
    QCOMPARE(brush.attribute("type"), QString("gbr_brush"));
    KoResourceSP tipResource = findResource(ResourceType::Brushes, "agent cloud tip");
    QCOMPARE(brush.attribute("md5sum"), tipResource->md5Sum());
    QCOMPARE(brush.attribute("brushApplication").toInt(), int(ALPHAMASK));
    QCOMPARE(brush.attribute("scale").toDouble(), 1.0);

    // The preset's linked tip resolves through the resource database.
    bool tipLinked = false;
    Q_FOREACH (KoResourceLoadResult linked, stored->linkedResources(KisGlobalResourcesInterface::instance())) {
        if (linked.resource() && linked.resource()->md5Sum() == tipResource->md5Sum()) tipLinked = true;
    }
    QVERIFY(tipLinked);
}

void TestKritaAgentResources::testPresetFromXml()
{
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(), "agent stamp tip", "image"));
    QVERIFY(tip);
    QScopedPointer<Resource> preset(presetFromXml(tip.data(), "agent stamp"));
    QVERIFY(preset);
    KisPaintOpPresetSP stored = findResource(ResourceType::PaintOpPresets, "agent stamp").dynamicCast<KisPaintOpPreset>();
    QVERIFY(stored);
    QCOMPARE(stored->paintOp().id(), QString("paintbrush"));
    QCOMPARE(brushDefinition(stored).attribute("brushApplication").toInt(), int(IMAGESTAMP));
}

void TestKritaAgentResources::testPresetRejectsBadInput()
{
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(), "agent reject tip"));
    QVERIFY(tip);
    QScopedPointer<Resource> preset(presetFromXml(tip.data(), "agent reject base"));
    QVERIFY(preset);

    QVERIFY(!Krita::instance()->createPreset(static_cast<Resource *>(nullptr), tip.data(), "agent no base"));
    QVERIFY(!Krita::instance()->createPreset(preset.data(), nullptr, "agent no tip"));
    QVERIFY(!Krita::instance()->createPreset(preset.data(), tip.data(), ""));
    // The tip and the base swapped: wrong types.
    QVERIFY(!Krita::instance()->createPreset(tip.data(), preset.data(), "agent swapped"));
    QVERIFY(!Krita::instance()->createPreset(QString("<not a preset"), tip.data(), "agent bad xml"));
    QVERIFY(!findResource(ResourceType::PaintOpPresets, "agent swapped"));
}

void TestKritaAgentResources::testPresetPaintsAStrokeThroughNodePaintLine()
{
    // A tip no base tip can make: two 4x4 squares 32 pixels apart, with nothing between them.
    QImage twoDots(40, 4, QImage::Format_ARGB32);
    twoDots.fill(Qt::transparent);
    for (int y = 0; y < 4; y++) {
        for (int x = 0; x < 4; x++) {
            twoDots.setPixel(x, y, qRgba(0, 0, 0, 255));
            twoDots.setPixel(36 + x, y, qRgba(0, 0, 0, 255));
        }
    }
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(twoDots, "agent two dots tip"));
    QVERIFY(tip);
    QScopedPointer<Resource> preset(presetFromXml(tip.data(), "agent paint"));
    QVERIFY(preset);

    // A main window (offscreen, never shown) with a view, so Node.paintLine() finds the view's brush, as in Krita.
    QApplication::clipboard()->setText(QString()); // offscreen has no clipboard data, which Krita's clipboard reads
    KisDocument *viewDoc = KisPart::instance()->createDocument();
    KisImageSP viewImage = new KisImage(0, 16, 16, KoColorSpaceRegistry::instance()->rgb8(), "view");
    viewImage->addNode(new KisPaintLayer(viewImage, "layer", OPACITY_OPAQUE_U8));
    viewDoc->setCurrentImage(viewImage);
    KisPart::instance()->addDocument(viewDoc, false);
    KisMainWindow *mainWindow = KisPart::instance()->createMainWindow();
    QVERIFY(mainWindow);
    QPointer<KisView> kisView = new KisView(viewDoc, mainWindow->viewManager(), mainWindow);
    KisPart::instance()->addView(kisView);
    mainWindow->showView(kisView);
    QApplication::processEvents();

    // The script selects the new preset in the view, as View.setCurrentBrushPreset() does.
    View view(kisView);
    view.setCurrentBrushPreset(preset.data());
    QApplication::processEvents();
    QScopedPointer<Resource> current(view.currentBrushPreset());
    QVERIFY(current);
    QCOMPARE(current->name(), QString("agent paint"));

    // A document of the script's, with a layer to paint on.
    KisDocument *kisdoc = KisPart::instance()->createDocument();
    KisImageSP image = new KisImage(kisdoc->createUndoStore(), 120, 80, KoColorSpaceRegistry::instance()->rgb8(), "paint");
    KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
    image->addNode(layer);
    kisdoc->setCurrentImage(image);
    KisPart::instance()->addDocument(kisdoc, false);

    QScopedPointer<Node> node(Node::createNode(image, layer));
    QCOMPARE(node->paintAbility(), QString("PAINT"));
    node->paintLine(QPointF(60, 10), QPointF(60, 70), 1.0, 1.0);
    image->waitForDone();

    // A vertical line with the two-dot tip: two stripes, 16 pixels left and right of the line, and nothing on it.
    auto paintedIn = [&layer](int left, int right) {
        const QRect band(left, 25, right - left + 1, 30);
        QByteArray bytes(band.width() * band.height() * 4, 0);
        layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(bytes.data()), band);
        int count = 0;
        for (int i = 3; i < bytes.size(); i += 4) {
            if (quint8(bytes[i]) > 0) count++;
        }
        return count;
    };
    const QRect painted = layer->paintDevice()->exactBounds();
    const QString where =
        QString("painted %1,%2 %3x%4").arg(painted.x()).arg(painted.y()).arg(painted.width()).arg(painted.height());
    QVERIFY2(!painted.isEmpty(), "the stroke painted nothing");
    QVERIFY2(paintedIn(36, 46) > 0, qPrintable("no left stripe; " + where));
    QVERIFY2(paintedIn(74, 84) > 0, qPrintable("no right stripe; " + where));
    QVERIFY2(paintedIn(50, 70) == 0, qPrintable("paint between the stripes; " + where));
    QVERIFY2(painted.left() >= 34 && painted.right() <= 86, qPrintable(where));

    KisPart::instance()->removeView(kisView);
    delete kisView.data();
    delete mainWindow;
    KisPart::instance()->removeDocument(kisdoc, false);
    delete kisdoc;
    KisPart::instance()->removeDocument(viewDoc, false);
    delete viewDoc;
}

void TestKritaAgentResources::testSameNameAsABuiltInPresetLeavesItAlone()
{
    KisPaintOpPresetSP builtIn = basePixelBrushPreset();
    QVERIFY(builtIn);
    QVERIFY(!isAgentTagged(ResourceType::PaintOpPresets, builtIn));
    const QString name = builtIn->name();
    const int id = builtIn->resourceId();
    const QString md5 = builtIn->md5Sum();
    const QString filename = builtIn->filename();
    const QString storage = builtIn->storageLocation();

    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(), "agent built-in name tip"));
    QVERIFY(tip);
    QScopedPointer<Resource> base(new Resource(builtIn, "preset"));
    QScopedPointer<Resource> preset(Krita::instance()->createPreset(base.data(), tip.data(), name));
    QVERIFY(preset);

    // The built-in preset is as it was; the new one has a name of its own, and is the agent's.
    QVERIFY2(preset->name() != name, qPrintable(preset->name()));
    QVERIFY2(preset->name().startsWith(name), qPrintable(preset->name()));
    KisResourceModel model(ResourceType::PaintOpPresets);
    KoResourceSP still = model.resourceForId(id);
    QVERIFY(still);
    QCOMPARE(still->name(), name);
    QCOMPARE(still->md5Sum(), md5);
    QCOMPARE(still->filename(), filename);
    QCOMPARE(still->storageLocation(), storage);
    QVERIFY(!isAgentTagged(ResourceType::PaintOpPresets, still));
    KoResourceSP made = findResource(ResourceType::PaintOpPresets, preset->name());
    QVERIFY(made);
    QVERIFY(made->resourceId() != id);
    QVERIFY(isAgentTagged(ResourceType::PaintOpPresets, made));

    // The same call again replaces the agent's own preset, not the built-in one.
    QScopedPointer<Resource> again(Krita::instance()->createPreset(base.data(), tip.data(), name));
    QVERIFY(again);
    QCOMPARE(again->name(), preset->name());
    QCOMPARE(model.resourcesForName(preset->name()).size(), 1);
    QCOMPARE(model.resourceForId(id)->md5Sum(), md5);
}

void TestKritaAgentResources::testSameNameAsAnArtistTipLeavesItAlone()
{
    // The artist's own tip in the resource folder, not tagged for the agent.
    QSharedPointer<KisGbrBrush> artist(new KisGbrBrush(QImage(testTipImage(QSize(9, 9))), "artist tip"));
    artist->setFilename("artist_tip.gbr");
    artist->setValid(true);
    KisResourceModel model(ResourceType::Brushes);
    QVERIFY(model.addResourceDeduplicateFileName(artist));
    const int id = artist->resourceId();
    const QString md5 = artist->md5Sum();

    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(QSize(5, 5)), "artist tip"));
    QVERIFY(tip);
    QVERIFY2(tip->name() != QString("artist tip"), qPrintable(tip->name()));
    KoResourceSP still = model.resourceForId(id);
    QCOMPARE(still->md5Sum(), md5);
    QCOMPARE(still.dynamicCast<KisBrush>()->width(), 9);
    QVERIFY(!isAgentTagged(ResourceType::Brushes, still));
}

void TestKritaAgentResources::testReplacingAnAgentTipKeepsOneResource()
{
    QScopedPointer<Resource> first(Krita::instance()->createBrushTip(testTipImage(QSize(11, 11)), "agent replaced tip"));
    QVERIFY(first);
    KoResourceSP before = findResource(ResourceType::Brushes, "agent replaced tip");
    QVERIFY(before);
    const int id = before->resourceId();
    const QString path = KisResourceLocator::instance()->filePathForResource(before);

    QScopedPointer<Resource> second(Krita::instance()->createBrushTip(testTipImage(QSize(6, 6)), "agent replaced tip", "image"));
    QVERIFY(second);
    QCOMPARE(second->name(), QString("agent replaced tip"));
    KisResourceModel model(ResourceType::Brushes);
    QCOMPARE(model.resourcesForName("agent replaced tip").size(), 1);
    KoResourceSP after = model.resourceForId(id);
    QVERIFY(after);
    QCOMPARE(after.dynamicCast<KisBrush>()->width(), 6);
    QVERIFY(after->version() > before->version());
    QVERIFY(isAgentTagged(ResourceType::Brushes, after));
    // A new version of the same file, in the resource folder.
    QCOMPARE(QFileInfo(KisResourceLocator::instance()->filePathForResource(after)).dir(), QFileInfo(path).dir());
    QVERIFY(KisResourceLocator::instance()->filePathForResource(after).endsWith(".gbr"));
}

void TestKritaAgentResources::testReplacingATipChangesItsPresets()
{
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(QSize(20, 20)), "agent shared tip"));
    QVERIFY(tip);
    QScopedPointer<Resource> preset(presetFromXml(tip.data(), "agent shared tip user"));
    QVERIFY(preset);

    // The tip replaced: the preset made with it now finds the new tip.
    QScopedPointer<Resource> replaced(Krita::instance()->createBrushTip(testTipImage(QSize(7, 7)), "agent shared tip"));
    QVERIFY(replaced);
    KisPaintOpPresetSP stored =
        findResource(ResourceType::PaintOpPresets, "agent shared tip user").dynamicCast<KisPaintOpPreset>();
    QVERIFY(stored);
    KisBrushSP linked;
    Q_FOREACH (KoResourceLoadResult result, stored->linkedResources(KisGlobalResourcesInterface::instance())) {
        if (KisBrushSP brush = result.resource().dynamicCast<KisBrush>()) linked = brush;
    }
    QVERIFY(linked);
    QCOMPARE(linked->name(), QString("agent shared tip"));
    QCOMPARE(linked->width(), 7);
}

void TestKritaAgentResources::testTipApplicationLivesInTheDatabase()
{
    QScopedPointer<Resource> tip(Krita::instance()->createBrushTip(testTipImage(), "agent database tip", "image"));
    QVERIFY(tip);
    QScopedPointer<Resource> stamped(presetFromXml(tip.data(), "agent database stamp"));
    QVERIFY(stamped);

    // The tip's file does not say "stamp the colours": without the database's record a preset made from it
    // uses it as a lightness map.
    KisResourceModel model(ResourceType::Brushes);
    KoResourceSP resource = findResource(ResourceType::Brushes, "agent database tip");
    QVERIFY(model.setResourceMetaData(resource, QMap<QString, QVariant>()));
    QScopedPointer<Resource> fallback(presetFromXml(tip.data(), "agent database lightness"));
    QVERIFY(fallback);
    KisPaintOpPresetSP lightness =
        findResource(ResourceType::PaintOpPresets, "agent database lightness").dynamicCast<KisPaintOpPreset>();
    QCOMPARE(brushDefinition(lightness).attribute("brushApplication").toInt(), int(LIGHTNESSMAP));

    // A preset made while the record was there keeps the application in its own file.
    KisPaintOpPresetSP made =
        findResource(ResourceType::PaintOpPresets, "agent database stamp").dynamicCast<KisPaintOpPreset>();
    KisPaintOpPresetSP fromFile(new KisPaintOpPreset(KisResourceLocator::instance()->filePathForResource(made)));
    QVERIFY(fromFile->load(KisGlobalResourcesInterface::instance()));
    QCOMPARE(brushDefinition(fromFile).attribute("brushApplication").toInt(), int(IMAGESTAMP));
}

// Offscreen: the painting test makes a main window, never shown.
static const bool s_offscreen = (qputenv("QT_QPA_PLATFORM", QByteArray("offscreen")), true);

KISTEST_TEMPORARY_HOME_MAIN(TestKritaAgentResources)
