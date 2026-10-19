/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentRegionRefresh.h"

#include <simpletest.h>
#include <testui.h>

#include <QColor>
#include <QImage>
#include <QMutex>
#include <QScopedPointer>
#include <QVector>

#include <Document.h>
#include <Node.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_fill_painter.h>
#include <kis_image.h>
#include <kis_paint_layer.h>
#include <KisGlobalResourcesInterface.h>
#include <filter/kis_filter.h>
#include <filter/kis_filter_configuration.h>
#include <filter/kis_filter_registry.h>
#include <kis_adjustment_layer.h>
#include <kis_clone_layer.h>
#include <kis_filter_mask.h>
#include <kis_group_layer.h>
#include <kis_psd_layer_style.h>
#include <kis_transparency_mask.h>
#include <kis_selection.h>
#include <kis_pixel_selection.h>

namespace {

const QSize imageSize(200, 150);

/// A document with a paint layer filled with red under an empty one, its projection composited.
struct RedDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;

    RedDocument()
        : kisdoc(KisPart::instance()->createDocument())
    {
        image = new KisImage(0, imageSize.width(), imageSize.height(), KoColorSpaceRegistry::instance()->rgb8(), "test");
        layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        KisFillPainter gc(layer->paintDevice());
        gc.fillRect(0, 0, imageSize.width(), imageSize.height(), KoColor(Qt::red, layer->colorSpace()));
        gc.end();
        image->addNode(layer);
        // An empty layer above, so the image composites into its own projection. With a single opaque layer the
        // root shares that layer's device: every write would show at once without any refresh, which would hide
        // refresh bugs (a refresh that did nothing would pass).
        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        doc.reset(new Document(kisdoc.data(), false));
        doc->refreshProjection();
    }

    ~RedDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    /// Paints the whole layer blue straight into its device, without marking anything dirty.
    void paintLayerBlueSilently()
    {
        KisFillPainter gc(layer->paintDevice());
        gc.fillRect(0, 0, imageSize.width(), imageSize.height(), KoColor(Qt::blue, layer->colorSpace()));
        gc.end();
    }
};

/// The rects the image reports as updated while it is alive.
struct UpdateRecorder {
    QMutex mutex;
    QVector<QRect> rects;
    QMetaObject::Connection connection;

    explicit UpdateRecorder(KisImageSP image)
    {
        connection = QObject::connect(image.data(), &KisImage::sigImageUpdated, image.data(),
                                      [this](const QRect &rc) {
                                          QMutexLocker l(&mutex);
                                          rects.append(rc);
                                      },
                                      Qt::DirectConnection);
    }
    ~UpdateRecorder() { QObject::disconnect(connection); }

    QRect united()
    {
        QMutexLocker l(&mutex);
        QRect r;
        for (const QRect &rc : std::as_const(rects)) r |= rc;
        return r;
    }
};

/// Checks every pixel of the projection: \p inside colour within \p rect, \p outside colour elsewhere.
bool projectionIs(Document &doc, const QRect &rect, const QColor &inside, const QColor &outside, QString *failure)
{
    const QImage p = doc.projection(0, 0, imageSize.width(), imageSize.height());
    if (p.size() != imageSize) {
        *failure = QString("projection size %1x%2").arg(p.width()).arg(p.height());
        return false;
    }
    for (int y = 0; y < p.height(); ++y) {
        for (int x = 0; x < p.width(); ++x) {
            const QColor expected = rect.contains(x, y) ? inside : outside;
            const QColor actual = p.pixelColor(x, y);
            if (actual != expected) {
                *failure = QString("pixel (%1, %2) is %3, expected %4").arg(x).arg(y).arg(actual.name(QColor::HexArgb), expected.name(QColor::HexArgb));
                return false;
            }
        }
    }
    return true;
}


/// What sits next to the edited layer, spreading an edit beyond its own area.
enum Effect { EffectBlurMask, EffectBlurAdjustmentLayer, EffectDropShadow, EffectCloneLayer, EffectPassThroughGroup };

KisFilterConfigurationSP blurConfiguration()
{
    KisFilterSP filter = KisFilterRegistry::instance()->value("blur");
    if (!filter) return KisFilterConfigurationSP();
    KisFilterConfigurationSP config = filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
    config->setProperty("halfWidth", 6);
    config->setProperty("halfHeight", 6);
    return config->cloneWithResourcesSnapshot();
}

/**
 * A white background, an "edited" layer with a red square, the effect, and an empty layer on top (see
 * RedDocument). The edit is a blue rect inside the area, written straight into the edited layer's device.
 */
struct EffectDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisPaintLayerSP edited;
    QScopedPointer<Document> doc;
    bool ok = true;

    explicit EffectDocument(Effect effect)
        : kisdoc(KisPart::instance()->createDocument())
    {
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(0, imageSize.width(), imageSize.height(), cs, "effects");
        KisPaintLayerSP background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        background->paintDevice()->fill(image->bounds(), KoColor(Qt::white, cs));
        image->addNode(background);

        edited = new KisPaintLayer(image, "edited", OPACITY_OPAQUE_U8);
        edited->paintDevice()->fill(QRect(20, 20, 40, 40), KoColor(Qt::red, cs));

        KisNodeSP parent = image->root();
        if (effect == EffectPassThroughGroup) {
            KisGroupLayerSP group = new KisGroupLayer(image, "group", OPACITY_OPAQUE_U8);
            group->setPassThroughMode(true);
            image->addNode(group);
            parent = group;
        }
        image->addNode(edited, parent);

        switch (effect) {
        case EffectBlurMask: {
            KisFilterConfigurationSP config = blurConfiguration();
            if (!config) { ok = false; break; }
            KisFilterMaskSP mask = new KisFilterMask(image, "blur mask");
            mask->initSelection(edited);
            mask->setFilter(config);
            image->addNode(mask, edited);
            break;
        }
        case EffectBlurAdjustmentLayer:
        case EffectPassThroughGroup: {
            KisFilterConfigurationSP config = blurConfiguration();
            if (!config) { ok = false; break; }
            image->addNode(new KisAdjustmentLayer(image, "blur", config, KisSelectionSP()), parent);
            break;
        }
        case EffectDropShadow: {
            KisPSDLayerStyleSP style(new KisPSDLayerStyle());
            style->context()->keep_original = true;
            style->dropShadow()->setEffectEnabled(true);
            style->dropShadow()->setDistance(12);
            style->dropShadow()->setSpread(100);
            style->dropShadow()->setSize(6);
            style->dropShadow()->setNoise(0);
            style->dropShadow()->setKnocksOut(false);
            style->dropShadow()->setOpacity(90);
            style->dropShadow()->setAngle(0);
            edited->setLayerStyle(style);
            break;
        }
        case EffectCloneLayer: {
            KisCloneLayerSP clone = new KisCloneLayer(edited, image, "clone", OPACITY_OPAQUE_U8);
            clone->setX(70);
            clone->setY(10);
            image->addNode(clone);
            break;
        }
        }

        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        doc.reset(new Document(kisdoc.data(), false));
        doc->refreshProjection();
    }

    ~EffectDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    QImage view() { return doc->projection(0, 0, imageSize.width(), imageSize.height()); }
};

/**
 * Where two views differ by more than \p tolerance in a channel: how many pixels, the largest difference and the
 * first such pixel; empty when they match. Fully transparent pixels match whatever their colour.
 */
QString difference(const QImage &a, const QImage &b, int tolerance = 0)
{
    if (a.size() != b.size()) return QString("sizes differ");
    int count = 0;
    int largest = 0;
    QPoint first(-1, -1);
    for (int y = 0; y < a.height(); ++y) {
        for (int x = 0; x < a.width(); ++x) {
            const QRgb p = a.pixel(x, y);
            const QRgb q = b.pixel(x, y);
            if (!qAlpha(p) && !qAlpha(q)) continue; // fully transparent: the colour does not matter
            const int d = qMax(qMax(qAbs(qRed(p) - qRed(q)), qAbs(qGreen(p) - qGreen(q))),
                               qMax(qAbs(qBlue(p) - qBlue(q)), qAbs(qAlpha(p) - qAlpha(q))));
            if (d > tolerance) {
                if (!count) first = QPoint(x, y);
                ++count;
                largest = qMax(largest, d);
            }
        }
    }
    if (!count) return QString();
    return QString("%1 pixels differ by more than %2, up to %3; first at (%4, %5): %6 instead of %7")
        .arg(count).arg(tolerance).arg(largest).arg(first.x()).arg(first.y())
        .arg(QColor::fromRgba(a.pixel(first)).name(QColor::HexArgb), QColor::fromRgba(b.pixel(first)).name(QColor::HexArgb));
}

} // namespace

void TestDocumentRegionRefresh::testRefreshProjectionRectGrowsByEffects_data()
{
    QTest::addColumn<int>("effect");
    QTest::newRow("blur filter mask") << int(EffectBlurMask);
    QTest::newRow("blur adjustment layer") << int(EffectBlurAdjustmentLayer);
    QTest::newRow("drop shadow") << int(EffectDropShadow);
    QTest::newRow("clone layer") << int(EffectCloneLayer);
    QTest::newRow("pass-through group with adjustment") << int(EffectPassThroughGroup);
}

void TestDocumentRegionRefresh::testRefreshProjectionRectGrowsByEffects()
{
    QFETCH(int, effect);
    EffectDocument d{Effect(effect)};
    if (!d.ok) QSKIP("the blur filter plugin is not loaded");

    // The edit touches the area's right and bottom edges, so blur, shadow and clone all reach past them.
    const QRect area(60, 50, 40, 30);
    d.edited->paintDevice()->fill(area, KoColor(Qt::blue, d.edited->colorSpace()));
    d.doc->refreshProjection(area);
    const QImage regionRefreshed = d.view();

    d.doc->refreshProjection();
    const QImage fullyRefreshed = d.view();

    // Blur rounds differently by a level where its patches are split differently: allow 1.
    const QString found = difference(regionRefreshed, fullyRefreshed, 1);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestDocumentRegionRefresh::testSetPixelDataOnTransparencyMask()
{
    RedDocument d;
    KisTransparencyMaskSP mask = new KisTransparencyMask(d.image, "transparency");
    mask->initSelection(KisLayerSP(dynamic_cast<KisLayer *>(d.layer.data())));
    d.image->addNode(mask, d.layer);
    d.doc->refreshProjection();

    QScopedPointer<Node> node(d.doc->nodeByName("transparency"));
    QVERIFY(node);
    const QRect area(30, 20, 50, 40);
    QByteArray clear(area.width() * area.height(), char(0)); // alpha 0: hide the layer there
    QVERIFY(node->setPixelData(clear, area.x(), area.y(), area.width(), area.height()));
    d.doc->waitForDone();
    const QImage afterWrite = d.doc->projection(0, 0, imageSize.width(), imageSize.height());

    d.doc->refreshProjection();
    const QImage fullyRefreshed = d.doc->projection(0, 0, imageSize.width(), imageSize.height());
    QVERIFY2(qAlpha(fullyRefreshed.pixel(area.center())) == 0, "the mask write did not hide the layer");
    const QString found = difference(afterWrite, fullyRefreshed);
    QVERIFY2(found.isEmpty(), qPrintable(found));
}

void TestDocumentRegionRefresh::testRefreshProjectionRectUpdatesOnlyThatRect()
{
    RedDocument d;
    QString failure;
    QVERIFY2(projectionIs(*d.doc, QRect(), Qt::red, Qt::red, &failure), qPrintable(failure));

    d.paintLayerBlueSilently();
    // Nothing was marked dirty, so the projection is still red.
    QVERIFY2(projectionIs(*d.doc, QRect(), Qt::red, Qt::red, &failure), qPrintable(failure));

    const QRect area(40, 30, 80, 60);
    UpdateRecorder updates(d.image);
    d.doc->refreshProjection(area);

    // Synchronous: the area is recomposited when the call returns, and nothing outside it.
    QVERIFY2(projectionIs(*d.doc, area, Qt::blue, Qt::red, &failure), qPrintable(failure));
    const QRect updated = updates.united();
    QVERIFY2(!updated.isEmpty(), "no update was reported");
    QVERIFY2(area.contains(updated), qPrintable(QString("updated %1,%2 %3x%4 is outside the area")
                                                 .arg(updated.x()).arg(updated.y()).arg(updated.width()).arg(updated.height())));
}

void TestDocumentRegionRefresh::testRefreshProjectionRectIsClippedToTheImage()
{
    RedDocument d;
    d.paintLayerBlueSilently();

    d.doc->refreshProjection(QRect(-10, -20, 40, 50));

    QString failure;
    QVERIFY2(projectionIs(*d.doc, QRect(0, 0, 30, 30), Qt::blue, Qt::red, &failure), qPrintable(failure));
}

void TestDocumentRegionRefresh::testRefreshProjectionEmptyRectChangesNothing()
{
    RedDocument d;
    d.paintLayerBlueSilently();

    UpdateRecorder updates(d.image);
    d.doc->refreshProjection(QRect());
    d.doc->refreshProjection(QRect(500, 500, 10, 10)); // entirely outside the image
    d.doc->waitForDone();

    QString failure;
    QVERIFY2(projectionIs(*d.doc, QRect(), Qt::red, Qt::red, &failure), qPrintable(failure));
    QVERIFY(updates.united().isEmpty());
}

void TestDocumentRegionRefresh::testSetPixelDataDirtiesOnlyItsRect()
{
    RedDocument d;
    QScopedPointer<Node> node(d.doc->nodeByName("layer"));
    QVERIFY(node);

    const QRect area(30, 20, 50, 40);
    QByteArray blue;
    blue.reserve(area.width() * area.height() * 4);
    for (int i = 0; i < area.width() * area.height(); ++i) {
        blue.append(char(255)); // B
        blue.append(char(0));   // G
        blue.append(char(0));   // R
        blue.append(char(255)); // A
    }

    UpdateRecorder updates(d.image);
    QVERIFY(node->setPixelData(blue, area.x(), area.y(), area.width(), area.height()));
    // No refreshProjection(): setPixelData itself marks its rect dirty; waiting is enough.
    d.doc->waitForDone();

    QString failure;
    QVERIFY2(projectionIs(*d.doc, area, Qt::blue, Qt::red, &failure), qPrintable(failure));
    const QRect updated = updates.united();
    QVERIFY2(!updated.isEmpty(), "setPixelData reported no update");
    QVERIFY2(area.contains(updated), qPrintable(QString("updated %1,%2 %3x%4 is outside the written rect")
                                                 .arg(updated.x()).arg(updated.y()).arg(updated.width()).arg(updated.height())));
}

KISTEST_MAIN(TestDocumentRegionRefresh)
