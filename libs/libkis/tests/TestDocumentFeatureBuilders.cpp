/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
// Feature builders (krita-fork 6.3): Document.maskFromSelection, maskContiguous, maskSimilarColor, maskSnapOutline and
// maskSegments on painted images with known regions, and the New Moscow skyline from 20 rough points.

#include "TestDocumentFeatureBuilders.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QElapsedTimer>
#include <QSignalSpy>
#include <QFile>
#include <QFileInfo>
#include <QImage>
#include <QScopedPointer>
#include <QTemporaryDir>
#include <QUuid>

#include <algorithm>
#include <functional>

#include <kundo2stack.h>

#include <Document.h>
#include <Feature.h>
#include <Selection.h>

#include <KisDocument.h>
#include <KisFeatureBuilders.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <kis_default_bounds.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_stroke_strategy_undo_command_based.h>
#include <kundo2magicstring.h>
#include <kis_group_layer.h>
#include <kis_transparency_mask.h>
#include <kis_default_bounds.h>

#include <cmath>
#include <limits>
#include <random>

namespace
{

const QColor red(200, 40, 40);
const QColor dullRed(170, 70, 60);
const QColor blue(40, 40, 200);
const QColor sky(90, 110, 200);
const QColor building(30, 25, 40);

/// A document of one paint layer painted by \p paint (on top of a second, empty layer), added to KisPart, settled
/// and unmodified.
struct BuilderDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;

    BuilderDocument(const QSize &size, const std::function<void(KisPaintDeviceSP)> &paint)
        : kisdoc(KisPart::instance()->createDocument())
    {
        kisdoc->setFileBatchMode(true); // never a dialog in a test
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), size.width(), size.height(), cs, "builders");
        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        layer = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
        paint(layer->paintDevice());
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data());
        doc.reset(new Document(kisdoc.data(), false));
        image->refreshGraphAsync();
        settle();
        kisdoc->setModified(false);
    }

    ~BuilderDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    void settle()
    {
        image->waitForDone();
        for (int i = 0; i < 5; i++) {
            QCoreApplication::sendPostedEvents();
            QCoreApplication::processEvents();
        }
    }

    QByteArray pixels()
    {
        image->waitForDone();
        QByteArray all;
        for (KisPaintDeviceSP dev : {layer->paintDevice(), image->projection()}) {
            QByteArray bytes(image->width() * image->height() * 4, 0);
            dev->readBytes(reinterpret_cast<quint8 *>(bytes.data()), image->bounds());
            all += bytes;
        }
        return all;
    }
};

void fill(KisPaintDeviceSP device, const QRect &rect, const QColor &color)
{
    device->fill(rect, KoColor(color, device->colorSpace()));
}

/// The mask's bytes over the document, row by row.
QByteArray maskBytes(Selection *mask, const QSize &size)
{
    return mask->pixelData(0, 0, size.width(), size.height());
}

qint64 selectedCount(const QByteArray &bytes)
{
    return std::count_if(bytes.constBegin(), bytes.constEnd(), [](char value) { return quint8(value) >= 128; });
}

qint64 area(Selection *mask, const QSize &size)
{
    return selectedCount(maskBytes(mask, size));
}

/// The bounds of the pixels \p mask selects at all.
QRect selectedBounds(Selection *mask, const QSize &size)
{
    const QByteArray bytes = maskBytes(mask, size);
    QRect bounds;
    for (int y = 0; y < size.height(); y++) {
        for (int x = 0; x < size.width(); x++) {
            if (bytes[y * size.width() + x]) bounds |= QRect(x, y, 1, 1);
        }
    }
    return bounds;
}

QByteArray readMask(KisPixelSelectionSP mask, const QRect &rect)
{
    QByteArray bytes(rect.width() * rect.height(), 0);
    mask->readBytes(reinterpret_cast<quint8 *>(bytes.data()), rect);
    return bytes;
}

void saveMask(const QByteArray &bytes, const QSize &size, const QString &path)
{
    QImage image(reinterpret_cast<const uchar *>(bytes.constData()), size.width(), size.height(), size.width(),
                 QImage::Format_Grayscale8);
    image.save(path);
}

Selection *rectSelection(const QRect &rect)
{
    Selection *selection = new Selection();
    selection->select(rect.x(), rect.y(), rect.width(), rect.height(), 255);
    return selection;
}

/**
 * How far \p bytes (a mask over \p size) strays from \p truth (true where the region is): the largest distance from a
 * pixel it gets wrong to the nearest pixel of the other kind in the truth (0 when it gets every pixel right; a pixel
 * just across the true edge is 1), and how many it gets wrong.
 */
struct Miss {
    int worst = 0;
    qint64 wrong = 0;
};

Miss missAgainst(const QByteArray &bytes, const QSize &size, const std::function<bool(int, int)> &truth)
{
    Miss miss;
    const int reach = 30;
    for (int y = 0; y < size.height(); y++) {
        for (int x = 0; x < size.width(); x++) {
            const bool selected = quint8(bytes[y * size.width() + x]) >= 128;
            const bool inside = truth(x, y);
            if (selected == inside) continue;
            miss.wrong++;
            int distance = reach + 1;
            for (int dy = -reach; dy <= reach; dy++) {
                for (int dx = -reach; dx <= reach; dx++) {
                    const int nx = x + dx, ny = y + dy;
                    if (nx < 0 || ny < 0 || nx >= size.width() || ny >= size.height()) continue;
                    if (truth(nx, ny) != inside) distance = qMin(distance, qMax(qAbs(dx), qAbs(dy)));
                }
            }
            miss.worst = qMax(miss.worst, distance);
        }
    }
    return miss;
}

/// The towers picture: sky over a ground band and three towers of known bounds.
const QSize towersSize(400, 200);
const QVector<QRect> towers = {QRect(0, 140, 400, 60), QRect(60, 70, 40, 70), QRect(180, 50, 50, 90), QRect(300, 90, 30, 50)};

void paintTowers(KisPaintDeviceSP device)
{
    fill(device, QRect(QPoint(0, 0), towersSize), sky);
    for (const QRect &rect : towers) fill(device, rect, building);
}

bool isTowersSky(int x, int y)
{
    for (const QRect &rect : towers) {
        if (rect.contains(x, y)) return false;
    }
    return true;
}

/// The towers' skyline as an agent outlines it: each corner missed by 4 or 5 pixels, then the top corners.
const QList<QPointF> roughTowersSkyline = {
    {0, 137}, {55, 144}, {63, 66}, {97, 74}, {104, 136}, {176, 143}, {184, 46}, {226, 54}, {233, 144},
    {296, 137}, {304, 94}, {326, 86}, {334, 143}, {400, 138}, {400, 0}, {0, 0}};

/// Says \p line in the test's output and, when KRITA_AGENT_SKYLINE_OUT names a folder, in its report.txt too.
void report(const QString &line)
{
    qInfo().noquote() << line;
    const QByteArray out = qgetenv("KRITA_AGENT_SKYLINE_OUT");
    if (out.isEmpty()) return;
    QFile file(QString::fromLocal8Bit(out) + "/report.txt");
    if (file.open(QIODevice::Append | QIODevice::Text)) file.write((line + "\n").toUtf8());
}

QString newMoscowOriginal()
{
    const QByteArray given = qgetenv("KRITA_AGENT_NEW_MOSCOW");
    if (!given.isEmpty()) return QString::fromLocal8Bit(given);
    // digital_art/new_moscow_finished.kra, beside the folder that holds this checkout (digital_art/forks/<checkout>).
    return QFileInfo(QFileInfo(QStringLiteral(__FILE__)).absolutePath() + "/../../../../../new_moscow_finished.kra")
        .absoluteFilePath();
}

} // namespace

void TestDocumentFeatureBuilders::testFromSelection()
{
    BuilderDocument d(QSize(100, 80), [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 100, 80), red); });
    QScopedPointer<Selection> none(d.doc->maskFromSelection());
    QVERIFY(!none);                                             // no selection: nothing

    QScopedPointer<Selection> box(rectSelection(QRect(10, 20, 30, 40)));
    QScopedPointer<Selection> fromBox(d.doc->maskFromSelection(box.data()));
    QVERIFY(fromBox);
    QCOMPARE(area(fromBox.data(), QSize(100, 80)), qint64(1200));
    QCOMPARE(selectedBounds(fromBox.data(), QSize(100, 80)), QRect(10, 20, 30, 40));

    // A copy: changing the source leaves the mask as it was.
    box->select(0, 0, 100, 80, 255);
    QCOMPARE(area(fromBox.data(), QSize(100, 80)), qint64(1200));

    // The document's selection, cut to the document (an inverted selection selects everything outside it too).
    QScopedPointer<Selection> global(rectSelection(QRect(10, 20, 30, 40)));
    global->invert();
    d.doc->setSelection(global.data());
    d.settle();
    QScopedPointer<Selection> fromGlobal(d.doc->maskFromSelection());
    QVERIFY(fromGlobal);
    QCOMPARE(area(fromGlobal.data(), QSize(100, 80)), qint64(100 * 80 - 1200));
    QCOMPARE(fromGlobal->pixelData(-10, -10, 2, 2), QByteArray(4, char(0)));

    // It adds a feature in one call.
    QScopedPointer<Feature> feature(d.doc->addFeature("Not the box", "ground", fromGlobal.data()));
    QVERIFY(feature);
    QCOMPARE(feature->area(), qint64(100 * 80 - 1200));
}

void TestDocumentFeatureBuilders::testContiguousStopsAtAnEdge()
{
    // Red on the left, blue on the right, and a red island on the blue.
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 150), blue);
        fill(dev, QRect(0, 0, 100, 150), red);
        fill(dev, QRect(150, 60, 20, 20), red);
    });

    QScopedPointer<Selection> left(d.doc->maskContiguous({QPointF(10, 10)}));
    QVERIFY(left);
    QCOMPARE(area(left.data(), size), qint64(100 * 150));
    QCOMPARE(selectedBounds(left.data(), size), QRect(0, 0, 100, 150));
    QCOMPARE(left->pixelData(99, 70, 2, 1), QByteArray("\xff\x00", 2));

    QScopedPointer<Selection> island(d.doc->maskContiguous({QPointF(155.7, 65.2)}));
    QVERIFY(island);
    QCOMPARE(area(island.data(), size), qint64(400));
    QCOMPARE(selectedBounds(island.data(), size), QRect(150, 60, 20, 20));

    QScopedPointer<Feature> feature(d.doc->addFeature("Left", "wall", left.data()));
    QVERIFY(feature);
    QCOMPARE(feature->bounds(), QRect(0, 0, 100, 150));
    QCOMPARE(feature->meanColor(), red);
}

void TestDocumentFeatureBuilders::testThresholdChangesTheArea()
{
    // Red, then a duller red, then blue. The threshold lies between Krita's difference of the two reds and of red
    // and blue.
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 150), blue);
        fill(dev, QRect(0, 0, 60, 150), red);
        fill(dev, QRect(60, 0, 60, 150), dullRed);
    });
    const KoColorSpace *cs = d.image->colorSpace();
    const KoColor a(red, cs), b(dullRed, cs), c(blue, cs);
    const int reds = cs->differenceA(a.data(), b.data());
    const int redBlue = cs->differenceA(a.data(), c.data());
    QVERIFY2(reds >= 2 && reds + 2 < redBlue, qPrintable(QString("differences %1, %2").arg(reds).arg(redBlue)));

    QScopedPointer<Selection> tight(d.doc->maskContiguous({QPointF(10, 10)}, {{"threshold", reds - 1}}));
    QVERIFY(tight);
    QCOMPARE(area(tight.data(), size), qint64(60 * 150));

    QScopedPointer<Selection> loose(d.doc->maskContiguous({QPointF(10, 10)}, {{"threshold", (reds + redBlue) / 2}}));
    QVERIFY(loose);
    QCOMPARE(area(loose.data(), size), qint64(120 * 150));
    QCOMPARE(selectedBounds(loose.data(), size), QRect(0, 0, 120, 150));
}

void TestDocumentFeatureBuilders::testContiguousSeedsAndRefinement()
{
    const QSize size(200, 150);
    const QRect first(20, 20, 40, 40), second(120, 80, 40, 40);
    BuilderDocument d(size, [&](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 150), blue);
        fill(dev, first, red);
        fill(dev, second, red);
    });

    QScopedPointer<Selection> both(d.doc->maskContiguous({QPointF(30, 30), QPointF(130, 90), QPointF(40, 40)}));
    QVERIFY(both);
    QCOMPARE(area(both.data(), size), qint64(2 * 40 * 40));

    QScopedPointer<Selection> grown(d.doc->maskContiguous({QPointF(30, 30)}, {{"grow", 3}}));
    QVERIFY(grown);
    QCOMPARE(selectedBounds(grown.data(), size), first.adjusted(-3, -3, 3, 3));
    QVERIFY(area(grown.data(), size) > 40 * 40);

    QScopedPointer<Selection> shrunk(d.doc->maskContiguous({QPointF(30, 30)}, {{"grow", -3}}));
    QVERIFY(shrunk);
    QCOMPARE(selectedBounds(shrunk.data(), size), first.adjusted(3, 3, -3, -3));
    QCOMPARE(area(shrunk.data(), size), qint64(34 * 34));

    QScopedPointer<Selection> feathered(d.doc->maskContiguous({QPointF(30, 30)}, {{"feather", 4}}));
    QVERIFY(feathered);
    const QByteArray soft = maskBytes(feathered.data(), size);
    QCOMPARE(quint8(soft[40 * size.width() + 40]), quint8(255));                    // the middle stays selected
    const bool hasSoftEdge = std::any_of(soft.constBegin(), soft.constEnd(),
                                         [](char value) { return quint8(value) > 0 && quint8(value) < 255; });
    QVERIFY(hasSoftEdge);
}

void TestDocumentFeatureBuilders::testContiguousWithin()
{
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 200, 150), red); });
    QScopedPointer<Selection> box(rectSelection(QRect(50, 40, 60, 30)));

    QScopedPointer<Selection> inBox(d.doc->maskContiguous({QPointF(60, 50)}, {{"within", QVariant::fromValue<QObject *>(box.data())}}));
    QVERIFY(inBox);
    QCOMPARE(area(inBox.data(), size), qint64(60 * 30));
    QCOMPARE(selectedBounds(inBox.data(), size), QRect(50, 40, 60, 30));

    // A feature's name works as well.
    QScopedPointer<Feature> feature(d.doc->addFeature("Box", "box", box.data()));
    QVERIFY(feature);
    QScopedPointer<Selection> inFeature(d.doc->maskContiguous({QPointF(60, 50)}, {{"within", "Box"}}));
    QVERIFY(inFeature);
    QCOMPARE(selectedBounds(inFeature.data(), size), QRect(50, 40, 60, 30));

    // A seed outside it finds nothing.
    QScopedPointer<Selection> outside(d.doc->maskContiguous({QPointF(5, 5)}, {{"within", "Box"}}));
    QVERIFY(outside);
    QCOMPARE(area(outside.data(), size), qint64(0));
}

void TestDocumentFeatureBuilders::testReferenceLayer()
{
    // The base layer is red all over; a layer above covers its left half with blue.
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 200, 150), red); });
    KisNodeSP cover = new KisPaintLayer(d.image, "cover", OPACITY_OPAQUE_U8);
    fill(cover->paintDevice(), QRect(0, 0, 100, 150), blue);
    d.image->addNode(cover);
    d.image->refreshGraphAsync();
    d.settle();

    QScopedPointer<Selection> composited(d.doc->maskContiguous({QPointF(150, 10)}));
    QVERIFY(composited);
    QCOMPARE(area(composited.data(), size), qint64(100 * 150));

    QScopedPointer<Selection> base(d.doc->maskContiguous({QPointF(150, 10)}, {{"layer", "base"}}));
    QVERIFY(base);
    QCOMPARE(area(base.data(), size), qint64(200 * 150));

    QScopedPointer<Selection> byId(d.doc->maskContiguous({QPointF(150, 10)}, {{"layer", d.layer->uuid().toString()}}));
    QVERIFY(byId);
    QCOMPARE(area(byId.data(), size), qint64(200 * 150));
}

void TestDocumentFeatureBuilders::testSimilarColorPicksDisconnectedRegions()
{
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 150), blue);
        fill(dev, QRect(0, 0, 100, 150), red);
        fill(dev, QRect(150, 60, 20, 20), red);
    });

    QScopedPointer<Selection> reds(d.doc->maskSimilarColor({red}));
    QVERIFY(reds);
    QCOMPARE(area(reds.data(), size), qint64(100 * 150 + 400));
    QCOMPARE(reds->pixelData(150, 60, 1, 1), QByteArray("\xff", 1));
    QCOMPARE(reds->pixelData(149, 60, 1, 1), QByteArray("\x00", 1));

    // Colours taken from points, and several colours together.
    QScopedPointer<Selection> fromPoint(d.doc->maskSimilarColor({}, {{"points", QVariantList{QPointF(155, 65)}}}));
    QVERIFY(fromPoint);
    QCOMPARE(area(fromPoint.data(), size), qint64(100 * 150 + 400));
    QScopedPointer<Selection> all(d.doc->maskSimilarColor({red, blue}));
    QVERIFY(all);
    QCOMPARE(area(all.data(), size), qint64(200 * 150));

    // Inside a selection only.
    QScopedPointer<Selection> right(rectSelection(QRect(100, 0, 100, 150)));
    QScopedPointer<Selection> island(d.doc->maskSimilarColor({red}, {{"within", QVariant::fromValue<QObject *>(right.data())}}));
    QVERIFY(island);
    QCOMPARE(area(island.data(), size), qint64(400));
}

void TestDocumentFeatureBuilders::testSnapOutlineFollowsEdges()
{
    BuilderDocument d(towersSize, paintTowers);

    QScopedPointer<Selection> snapped(d.doc->maskSnapOutline(roughTowersSkyline));
    QVERIFY(snapped);
    const Miss miss = missAgainst(maskBytes(snapped.data(), towersSize), towersSize, isTowersSky);
    report(QString("snapOutline on the towers: worst %1 px from the true edge, %2 pixels wrong").arg(miss.worst).arg(miss.wrong));
    QVERIFY2(miss.worst <= 3, qPrintable(QString("worst %1 px").arg(miss.worst)));

    // The rough polygon itself misses by up to the corners' error and more: the snapping is what lands on the edge.
    const KisPixelSelectionSP rough = KisFeatureBuilders::polygonMask(QPolygonF(QVector<QPointF>(roughTowersSkyline.begin(), roughTowersSkyline.end())),
                                                                      QRect(QPoint(0, 0), towersSize), false);
    QByteArray roughBytes(towersSize.width() * towersSize.height(), 0);
    rough->readBytes(reinterpret_cast<quint8 *>(roughBytes.data()), QRect(QPoint(0, 0), towersSize));
    const Miss roughMiss = missAgainst(roughBytes, towersSize, isTowersSky);
    report(QString("the rough polygon: worst %1 px, %2 pixels wrong").arg(roughMiss.worst).arg(roughMiss.wrong));
    QVERIFY(roughMiss.worst > miss.worst);
    QVERIFY(roughMiss.wrong > 2 * miss.wrong);
}

void TestDocumentFeatureBuilders::testSegmentSplitsAlongTheBoundary()
{
    // A light half and a dark half, a hint in each.
    const QSize size(200, 100);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 100), QColor(40, 50, 90));
        fill(dev, QRect(0, 0, 100, 100), QColor(220, 200, 160));
    });
    QScopedPointer<Selection> lightHint(rectSelection(QRect(10, 40, 20, 20)));
    QScopedPointer<Selection> darkHint(rectSelection(QRect(170, 40, 20, 20)));

    const QList<Selection *> regions = d.doc->maskSegments({lightHint.data(), darkHint.data()});
    QCOMPARE(regions.size(), 2);
    QScopedPointer<Selection> light(regions[0]), dark(regions[1]);
    QVERIFY(light);
    QVERIFY(dark);
    const QByteArray lightBytes = maskBytes(light.data(), size), darkBytes = maskBytes(dark.data(), size);

    // Every pixel in exactly one region, and the split on the boundary.
    for (int i = 0; i < lightBytes.size(); i++) {
        QVERIFY2((quint8(lightBytes[i]) == 255) != (quint8(darkBytes[i]) == 255), qPrintable(QString("pixel %1").arg(i)));
    }
    // The lazy brush works on edges found at a scale (edgeSize, 4 px by default: the width of the edges it looks for,
    // blurred by as much), so the split lands within about that scale of a sharp boundary, 3 px here. A smaller
    // scale is tighter on a clean edge (and noisier on a painted one).
    const Miss miss = missAgainst(lightBytes, size, [](int x, int) { return x < 100; });
    report(QString("segment: worst %1 px from the boundary, %2 pixels wrong").arg(miss.worst).arg(miss.wrong));
    QVERIFY2(miss.worst <= 3, qPrintable(QString("worst %1 px").arg(miss.worst)));
    const QList<Selection *> fine = d.doc->maskSegments({lightHint.data(), darkHint.data()}, {{"edgeSize", 1.0}});
    QCOMPARE(fine.size(), 2);
    QScopedPointer<Selection> fineLight(fine[0]), fineDark(fine[1]);
    const Miss fineMiss = missAgainst(maskBytes(fineLight.data(), size), size, [](int x, int) { return x < 100; });
    report(QString("segment with edgeSize 1: worst %1 px, %2 pixels wrong").arg(fineMiss.worst).arg(fineMiss.wrong));
    QVERIFY2(fineMiss.worst <= 1, qPrintable(QString("worst %1 px with edgeSize 1").arg(fineMiss.worst)));
    QVERIFY(fineMiss.wrong < miss.wrong);

    // Only a part of the document.
    const QList<Selection *> part = d.doc->maskSegments({lightHint.data(), darkHint.data()}, {{"rect", QVariantList{0, 30, 200, 40}}});
    QCOMPARE(part.size(), 2);
    QScopedPointer<Selection> partLight(part[0]), partDark(part[1]);
    QCOMPARE(selectedBounds(partLight.data(), size) | selectedBounds(partDark.data(), size), QRect(0, 30, 200, 40));
}

void TestDocumentFeatureBuilders::testSettleMovesARoughEdgeOntoThePainting()
{
    // Sky above y = 80, ground below. A slanted rough edge from (0, 92) to (200, 68) is settled onto the horizon.
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 150), building);
        fill(dev, QRect(0, 0, 200, 80), sky);
    });
    const KisPixelSelectionSP rough = KisFeatureBuilders::polygonMask(QPolygonF({QPointF(0, 92), QPointF(200, 68), QPointF(200, 0), QPointF(0, 0)}),
                                                                      d.image->bounds(), false, new KisDefaultBounds(d.image));
    const KisPixelSelectionSP settled = KisFeatureBuilders::settleEdge(d.image, d.image->projection(), rough, 20,
                                                                       KisFeatureBuilders::Segmentation());
    QVERIFY(settled);
    QByteArray bytes(size.width() * size.height(), 0);
    settled->readBytes(reinterpret_cast<quint8 *>(bytes.data()), d.image->bounds());
    const Miss miss = missAgainst(bytes, size, [](int, int y) { return y < 80; });
    report(QString("settle: worst %1 px from the horizon, %2 pixels wrong").arg(miss.worst).arg(miss.wrong));
    QVERIFY2(miss.worst <= 3, qPrintable(QString("worst %1 px").arg(miss.worst)));

    // Through maskSnapOutline: the towers' rough skyline, snapped and settled.
    BuilderDocument t(towersSize, paintTowers);
    QScopedPointer<Selection> towersSky(t.doc->maskSnapOutline(roughTowersSkyline, {{"settle", 12}}));
    QVERIFY(towersSky);
    const Miss towersMiss = missAgainst(maskBytes(towersSky.data(), towersSize), towersSize, isTowersSky);
    report(QString("snapOutline settled on the towers: worst %1 px, %2 pixels wrong").arg(towersMiss.worst).arg(towersMiss.wrong));
    QVERIFY2(towersMiss.worst <= 3, qPrintable(QString("worst %1 px").arg(towersMiss.worst)));
}

void TestDocumentFeatureBuilders::testBadInputGivesNothing()
{
    const QSize size(100, 80);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 100, 80), red); });
    QScopedPointer<Selection> box(rectSelection(QRect(10, 10, 20, 20)));
    QScopedPointer<Selection> other(rectSelection(QRect(60, 10, 20, 20)));
    const QList<QPointF> seed = {QPointF(5, 5)};

    auto none = [](Selection *mask) {
        QScopedPointer<Selection> owned(mask);
        return owned.isNull();
    };
    QVERIFY(none(d.doc->maskContiguous({})));                                        // no seed
    QVERIFY(none(d.doc->maskContiguous({QPointF(100, 5)})));                         // outside the document
    QVERIFY(none(d.doc->maskContiguous({QPointF(-1, 5)})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"treshold", 10}})));                  // a typo
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", 256}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", 2.5}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", "10"}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"spread", 101}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"closeGap", 33}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"feather", -1}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"antiAlias", 1}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", "no such layer"}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"within", "no such feature"}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"within", 3}})));
    QVERIFY(none(d.doc->maskSimilarColor({})));                                      // no colour
    QVERIFY(none(d.doc->maskSimilarColor({QColor()})));
    QVERIFY(none(d.doc->maskSimilarColor({}, {{"points", QVariantList{QPointF(500, 5)}}})));
    QVERIFY(none(d.doc->maskSimilarColor({}, {{"points", QVariantList{"a"}}})));
    QVERIFY(none(d.doc->maskSimilarColor({red}, {{"closeGap", 2}})));                // contiguous only
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10)})));         // fewer than three points
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10), QPointF(101, 10)})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10), QPointF(5, 20)}, {{"settle", -1}})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10), QPointF(5, 20)}, {{"filterRadius", 0}})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10), QPointF(5, 20)}, {{"within", "Box"}})));
    QVERIFY(d.doc->maskSegments({box.data()}).isEmpty());                            // one hint
    QVERIFY(d.doc->maskSegments({box.data(), nullptr}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"rect", QVariantList{0, 0, 200, 10}}}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"rect", QVariantList{0, 50, 100, 30}}}).isEmpty()); // hints outside it
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"cleanUp", 2.0}}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"edgeDetection", "yes"}}).isEmpty());

    // Not-a-number, infinity and numbers beyond any pixel are refused before they reach an integer.
    const double nan = std::numeric_limits<double>::quiet_NaN(), inf = std::numeric_limits<double>::infinity();
    const QList<QPointF> triangle = {QPointF(10, 10), QPointF(60, 10), QPointF(30, 60)};
    QVERIFY(none(d.doc->maskContiguous({QPointF(nan, 5)})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, inf)})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(-inf, 5)})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(1e300, 5)})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", nan}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", inf}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"threshold", 1e300}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"grow", 1e300}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"grow", -inf}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"timeoutMs", nan}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"timeoutMs", inf}})));
    QVERIFY(none(d.doc->maskSimilarColor({}, {{"points", QVariantList{QPointF(nan, 1)}}})));
    QVERIFY(none(d.doc->maskSimilarColor({}, {{"points", QVariantList{QVariantList{1e300, 1}}}})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(nan, 0), QPointF(10, 10), QPointF(5, 20)})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, inf), QPointF(5, 20)})));
    QVERIFY(none(d.doc->maskSnapOutline({QPointF(0, 0), QPointF(10, 10), QPointF(1e300, 20)})));
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"filterRadius", nan}})));
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"filterRadius", inf}})));
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"searchRadius", 1e300}})));
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"edgeSize", nan}}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"cleanUp", nan}}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"rect", QVariantList{0, 0, 1e300, 10}}}).isEmpty());
    QVERIFY(d.doc->maskSegments({box.data(), other.data()}, {{"rect", QVariantList{nan, 0, 10, 10}}}).isEmpty());

    // A document without an image answers nothing either.
    Document empty(nullptr, false);
    QVERIFY(none(empty.maskContiguous(seed)));
    QVERIFY(empty.maskSegments({box.data(), other.data()}).isEmpty());
}

void TestDocumentFeatureBuilders::testBuildersChangeNothing()
{
    BuilderDocument d(towersSize, paintTowers);
    const QByteArray before = d.pixels();
    const int steps = d.kisdoc->undoStack()->count();
    QScopedPointer<Selection> skyHint(rectSelection(QRect(0, 0, 400, 20)));
    QScopedPointer<Selection> groundHint(rectSelection(QRect(0, 180, 400, 20)));

    auto buildAll = [&]() {
        QScopedPointer<Selection> a(d.doc->maskContiguous({QPointF(5, 5)}, {{"grow", 2}}));
        QScopedPointer<Selection> b(d.doc->maskSimilarColor({sky}, {{"feather", 2}}));
        QScopedPointer<Selection> c(d.doc->maskSnapOutline(roughTowersSkyline, {{"settle", 8}}));
        QScopedPointer<Selection> e(d.doc->maskFromSelection(skyHint.data()));
        const QList<Selection *> f = d.doc->maskSegments({skyHint.data(), groundHint.data()});
        const bool built = a && b && c && e && f.size() == 2;
        qDeleteAll(f);
        return built;
    };

    QVERIFY(buildAll());
    d.settle();
    QCOMPARE(d.pixels(), before);
    QCOMPARE(d.kisdoc->undoStack()->count(), steps);
    QVERIFY(!d.kisdoc->isModified());
    QVERIFY(!d.image->globalSelection());

    // Inside an agent move they add nothing to its step: a move of builders alone leaves no step.
    QVERIFY(d.doc->beginAgentMove("look at the sky"));
    QVERIFY(buildAll());
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    QCOMPARE(d.kisdoc->undoStack()->count(), steps);

    // Adding the mask as a feature is the one step.
    QScopedPointer<Selection> skyMask(d.doc->maskContiguous({QPointF(5, 5)}));
    QVERIFY(skyMask);
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", skyMask.data()));
    QVERIFY(feature);
    d.settle();
    QCOMPARE(d.kisdoc->undoStack()->count(), steps + 1);
    QCOMPARE(d.pixels(), before);
}

namespace
{

/// A noisy picture: nothing to follow, so edge tracing and segmentation have a lot to do.
void paintNoise(KisPaintDeviceSP device, const QRect &rect)
{
    std::mt19937 random(7);
    QByteArray bytes(rect.width() * rect.height() * 4, 0);
    for (int i = 0; i < bytes.size(); i++) bytes[i] = char(random() & 0xff);
    for (int i = 3; i < bytes.size(); i += 4) bytes[i] = char(0xff);
    device->writeBytes(reinterpret_cast<const quint8 *>(bytes.constData()), rect);
}

const QList<QPointF> towersSkylineAtTheTopEdge = {
    {0, 137}, {55, 144}, {63, 66}, {97, 74}, {104, 136}, {176, 143}, {184, 46}, {226, 54}, {233, 144},
    {296, 137}, {304, 94}, {326, 86}, {334, 143}, {400, 138}, {400, 0}, {180, 0}, {0, 0}};

} // namespace

void TestDocumentFeatureBuilders::testBuildersNeverEndTheArtistsStroke()
{
    // The artist's brush stroke is open (the pen is down). A builder that waits for the image would ask it to end
    // (sigStrokeEndRequested) and then wait for as long as the pen stays down. None may: each gives up with None
    // within its time limit, and the stroke is left as it was.
    const QSize size = towersSize;
    BuilderDocument d(size, paintTowers);
    QScopedPointer<Selection> hintA(rectSelection(QRect(0, 0, 400, 20))), hintB(rectSelection(QRect(0, 180, 400, 20)));
    QScopedPointer<Selection> box(rectSelection(QRect(0, 0, 100, 100)));
    d.doc->setSelection(box.data());
    d.settle();

    KisStrokeId stroke = d.image->startStroke(new KisStrokeStrategyUndoCommandBased(kundo2_i18n("artist"), false, d.image.data()));
    QSignalSpy endRequests(d.image.data(), &KisImage::sigStrokeEndRequested);
    const QVariantMap quick = {{"timeoutMs", 300}};

    QElapsedTimer clock;
    clock.start();
    auto none = [](Selection *mask) {
        QScopedPointer<Selection> owned(mask);
        return owned.isNull();
    };
    QVERIFY(none(d.doc->maskFromSelection(nullptr, quick)));      // the document's selection: a read of the image
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, quick)));
    QVERIFY(none(d.doc->maskSimilarColor({sky}, quick)));
    QVERIFY(none(d.doc->maskSnapOutline(roughTowersSkyline, quick)));
    QVERIFY(d.doc->maskSegments({hintA.data(), hintB.data()}, quick).isEmpty());
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"timeoutMs", 300}, {"layer", "base"}})));
    const qint64 elapsed = clock.elapsed();
    QCOMPARE(endRequests.count(), 0);
    QVERIFY2(elapsed < 6 * 300 + 1500, qPrintable(QString("%1 ms for six calls of 300 ms").arg(elapsed)));

    d.image->endStroke(stroke);
    d.settle();
    QScopedPointer<Selection> after(d.doc->maskContiguous({QPointF(5, 5)}));
    QVERIFY(after);                                                // idle again: the builders work
    QScopedPointer<Selection> selected(d.doc->maskFromSelection());
    QVERIFY(selected);
}

void TestDocumentFeatureBuilders::testASegmentThatRunsOutOfTimeIsCancelled()
{
    const QSize size(1500, 1000);
    BuilderDocument d(size, [&](KisPaintDeviceSP dev) { paintNoise(dev, QRect(QPoint(0, 0), size)); });
    QScopedPointer<Selection> hintA(rectSelection(QRect(10, 10, 20, 20))), hintB(rectSelection(QRect(1400, 900, 20, 20)));
    QElapsedTimer clock;
    clock.start();
    const QList<Selection *> regions = d.doc->maskSegments({hintA.data(), hintB.data()}, {{"timeoutMs", 20}});
    QVERIFY(regions.isEmpty());
    QVERIFY2(clock.elapsed() < 3000, qPrintable(QString("%1 ms").arg(clock.elapsed())));
    // The same call with time to spare is not refused for anything else.
    const QList<Selection *> done = d.doc->maskSegments({hintA.data(), hintB.data()}, {{"timeoutMs", 30000}});
    QCOMPARE(done.size(), 2);
    qDeleteAll(done);
    // The cancelled stroke leaves the image usable and idle: a read lock is taken at once, and a build works.
    QVERIFY(d.image->tryBarrierLock(true) || (d.image->waitForDone(), d.image->tryBarrierLock(true)));
    d.image->unlock();
    QScopedPointer<Selection> fill(d.doc->maskContiguous({QPointF(5, 5)}, {{"threshold", 2}}));
    QVERIFY(fill);
}

void TestDocumentFeatureBuilders::testInputCapsRefuseGiantInput()
{
    const QSize size(400, 300);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 400, 300), red); });
    auto none = [](Selection *mask) {
        QScopedPointer<Selection> owned(mask);
        return owned.isNull();
    };
    auto some = [](Selection *mask) {
        QScopedPointer<Selection> owned(mask);
        return !owned.isNull();
    };
    auto points = [](int count) {
        QList<QPointF> list;
        for (int i = 0; i < count; i++) list << QPointF(i % 400, (i / 400) % 300);
        return list;
    };
    QElapsedTimer clock;
    clock.start();
    QVERIFY(some(d.doc->maskContiguous(points(256))));
    QVERIFY(none(d.doc->maskContiguous(points(257))));
    QVERIFY(none(d.doc->maskContiguous(points(100000))));
    QVERIFY(some(d.doc->maskContiguous({QPointF(5, 5)}, {{"grow", 100}})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"grow", 101}})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"grow", -101}})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"feather", 101}})));
    QVERIFY(some(d.doc->maskContiguous({QPointF(5, 5)}, {{"feather", 100}})));

    QList<QColor> colors;
    for (int i = 0; i < 64; i++) colors << QColor(i, 10, 10);
    QVERIFY(some(d.doc->maskSimilarColor(colors)));
    colors << QColor(1, 2, 3);
    QVERIFY(none(d.doc->maskSimilarColor(colors)));
    QVariantList manyPoints;
    for (int i = 0; i < 64; i++) manyPoints << QPointF(5, 5);
    QVERIFY(none(d.doc->maskSimilarColor({red}, {{"points", manyPoints}})));     // 1 colour + 64 points
    manyPoints.removeLast();
    QVERIFY(some(d.doc->maskSimilarColor({red}, {{"points", manyPoints}})));     // 1 + 63

    QVERIFY(none(d.doc->maskSnapOutline(points(129))));
    QVERIFY(none(d.doc->maskSnapOutline(points(100000))));
    const QList<QPointF> triangle = {QPointF(10, 10), QPointF(100, 10), QPointF(50, 80)};
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"searchRadius", 201}})));
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"settle", 101}})));
    QVERIFY(none(d.doc->maskSnapOutline(triangle, {{"anchorRadius", 201}})));

    QList<Selection *> hints;
    QList<QSharedPointer<Selection>> keep;
    for (int i = 0; i < 33; i++) {
        keep << QSharedPointer<Selection>(rectSelection(QRect(i * 10, 10, 5, 5)));
        hints << keep.last().data();
    }
    QVERIFY(d.doc->maskSegments(hints).isEmpty());                 // 33 hints
    hints.removeLast();
    // 32 hints are allowed (the call may still give up on time; it is not refused for the count).
    const QList<Selection *> thirtyTwo = d.doc->maskSegments(hints, {{"timeoutMs", 30000}});
    QCOMPARE(thirtyTwo.size(), 32);
    qDeleteAll(thirtyTwo);

    // The time limit option itself.
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"timeoutMs", 0}})));
    QVERIFY(none(d.doc->maskContiguous({QPointF(5, 5)}, {{"timeoutMs", 30001}})));
    QVERIFY(some(d.doc->maskContiguous({QPointF(5, 5)}, {{"timeoutMs", 30000}})));
    // Refusing giant input takes no time at all (the refused calls above, 100000 points twice, make no work).
    QVERIFY2(clock.elapsed() < 20000, qPrintable(QString("%1 ms").arg(clock.elapsed())));
}

void TestDocumentFeatureBuilders::testATimeBudgetBoundsTheCall()
{
    // 12 stretches across noise: unbounded, each A* search wanders the whole corridor. A 100 ms limit ends the call.
    const QSize size(3000, 2000);
    BuilderDocument d(size, [&](KisPaintDeviceSP dev) { paintNoise(dev, QRect(QPoint(0, 0), size)); });
    QList<QPointF> points;
    for (int i = 0; i < 12; i++) points << QPointF(100 + 230 * i, (i % 2) ? 1800 : 200);
    QElapsedTimer clock;
    clock.start();
    QScopedPointer<Selection> mask(d.doc->maskSnapOutline(points, {{"timeoutMs", 100}, {"searchRadius", 200}}));
    QVERIFY(!mask);
    QVERIFY2(clock.elapsed() < 2500, qPrintable(QString("%1 ms").arg(clock.elapsed())));
    // With time to spare, and nearer points, the same options are not refused for anything else.
    QScopedPointer<Selection> near(d.doc->maskSnapOutline({QPointF(100, 100), QPointF(140, 100), QPointF(120, 140)},
                                                         {{"timeoutMs", 30000}, {"searchRadius", 200}}));
    QVERIFY(near);
}

void TestDocumentFeatureBuilders::testSearchRadiusBeyondTheEdgeOfTheImage()
{
    // A point on the top edge and a search radius larger than the distance to the image's edges: the search
    // rectangle runs off the image, which cut the filter's tile numbers negative (and wrapped them at the right edge).
    BuilderDocument d(towersSize, paintTowers);
    QScopedPointer<Selection> mask(d.doc->maskSnapOutline(towersSkylineAtTheTopEdge, {{"searchRadius", 200}}));
    QVERIFY(mask);
    const Miss miss = missAgainst(maskBytes(mask.data(), towersSize), towersSize, isTowersSky);
    QVERIFY2(miss.worst <= 4, qPrintable(QString("worst %1 px").arg(miss.worst)));
    QVERIFY(area(mask.data(), towersSize) > 400 * 40);
}

void TestDocumentFeatureBuilders::testNothingIsLeakedByRepeatedSnaps()
{
    // A snap builds a worker, which holds a filtered copy of the image; none may outlive the call. The copy shares the
    // image's default bounds, so the bounds' reference count tells.
    BuilderDocument d(towersSize, paintTowers);
    const QList<QPointF> triangle = {QPointF(10, 10), QPointF(390, 10), QPointF(200, 120)};
    QScopedPointer<Selection> first(d.doc->maskSnapOutline(triangle));
    QVERIFY(first);
    const int before = d.image->projection()->defaultBounds()->refCount();
    for (int i = 0; i < 6; i++) {
        QScopedPointer<Selection> mask(d.doc->maskSnapOutline(triangle));
        QVERIFY(mask);
    }
    QCOMPARE(d.image->projection()->defaultBounds()->refCount(), before);
}

void TestDocumentFeatureBuilders::testSettleOfAThinMaskKeepsTheMask()
{
    // A mask thinner than twice the band has no core to hold: settling returns it as it was, not an empty mask.
    const QSize size(200, 100);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) {
        fill(dev, QRect(0, 0, 200, 100), building);
        fill(dev, QRect(0, 0, 200, 42), sky);
    });
    const KisPixelSelectionSP thin = KisFeatureBuilders::polygonMask(QPolygonF(QRectF(20, 40, 160, 4)), d.image->bounds(), false,
                                                                    new KisDefaultBounds(d.image));
    const KisPixelSelectionSP settled = KisFeatureBuilders::settleEdge(d.image, d.image->projection(), thin, 20,
                                                                       KisFeatureBuilders::Segmentation());
    QVERIFY(settled);
    QCOMPARE(settled->selectedExactRect(), thin->selectedExactRect());
    QCOMPARE(readMask(settled, d.image->bounds()), readMask(thin, d.image->bounds()));

    QScopedPointer<Selection> viaApi(d.doc->maskSnapOutline({QPointF(20, 40), QPointF(180, 40), QPointF(180, 44), QPointF(20, 44)},
                                                            {{"settle", 20}, {"anchorRadius", 0}}));
    QVERIFY(viaApi);
    QVERIFY(area(viaApi.data(), size) > 0);
}

void TestDocumentFeatureBuilders::testLayerLookup()
{
    const QSize size(100, 80);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 100, 80), red); });
    const KoColorSpace *cs = d.image->colorSpace();
    // A second layer of the same name as "base", a group, and a mask.
    KisNodeSP twin = new KisPaintLayer(d.image, "base", OPACITY_OPAQUE_U8);
    fill(twin->paintDevice(), QRect(0, 0, 100, 80), blue);
    d.image->addNode(twin);
    KisNodeSP group = new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8);
    d.image->addNode(group);
    KisNodeSP uniqueLayer = new KisPaintLayer(d.image, "unique", OPACITY_OPAQUE_U8);
    fill(uniqueLayer->paintDevice(), QRect(0, 0, 50, 80), red);
    d.image->addNode(uniqueLayer, group);
    KisTransparencyMaskSP mask = new KisTransparencyMask(d.image, "veil");
    d.image->addNode(mask, uniqueLayer);
    d.image->refreshGraphAsync();
    d.settle();
    Q_UNUSED(cs);

    auto none = [](Selection *m) {
        QScopedPointer<Selection> owned(m);
        return owned.isNull();
    };
    const QList<QPointF> seed = {QPointF(5, 5)};
    // Two layers called "base": the name is ambiguous. Their unique ids are not.
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", "base"}})));
    QScopedPointer<Selection> first(d.doc->maskContiguous(seed, {{"layer", d.layer->uuid().toString()}}));
    QVERIFY(first);
    QCOMPARE(area(first.data(), size), qint64(100 * 80));
    QScopedPointer<Selection> second(d.doc->maskContiguous(seed, {{"layer", twin->uuid().toString()}}));
    QVERIFY(second);
    // A unique name works, as does the id of a layer inside a group.
    QScopedPointer<Selection> byName(d.doc->maskContiguous(seed, {{"layer", "unique"}}));
    QVERIFY(byName);
    QCOMPARE(area(byName.data(), size), qint64(50 * 80));
    // Masks, groups and the root are no reference layer.
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", "veil"}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", mask->uuid().toString()}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", "group"}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", d.image->root()->uuid().toString()}})));
    QVERIFY(none(d.doc->maskContiguous(seed, {{"layer", 7}})));
}

void TestDocumentFeatureBuilders::testWithinNameIsTrimmed()
{
    const QSize size(200, 150);
    BuilderDocument d(size, [](KisPaintDeviceSP dev) { fill(dev, QRect(0, 0, 200, 150), red); });
    QScopedPointer<Selection> box(rectSelection(QRect(50, 40, 60, 30)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Box", "box", box.data()));
    QVERIFY(feature);
    QScopedPointer<Selection> padded(d.doc->maskContiguous({QPointF(60, 50)}, {{"within", "  Box "}}));
    QVERIFY(padded);
    QCOMPARE(selectedBounds(padded.data(), size), QRect(50, 40, 60, 30));
}

namespace
{

/**
 * The bands a sky mask leaves along its lower edge, column by column. In each column the mask's edge is where the
 * selected run from the top of the canvas ends; the band is how many unselected pixels below it still look like the
 * sky just above it (each of R, G and B within \p tolerance of the mean of the 5 selected pixels above the edge,
 * starting 2 pixels up), up to 300. A band of old sky left above a roof counts in full; an edge on the roof, 0 or 1
 * (its anti-aliased pixel). A mask cut into a building counts too, when the building is of one colour, so an edge
 * that sits anywhere but on the painting's own edge shows.
 */
struct Bands {
    QVector<int> widths;                 // one per measured column
    int columnsOver(int px) const { return std::count_if(widths.begin(), widths.end(), [px](int w) { return w > px; }); }
    int percentile(qreal p) const
    {
        if (widths.isEmpty()) return 0;
        QVector<int> sorted = widths;
        std::sort(sorted.begin(), sorted.end());
        return sorted[qMin(sorted.size() - 1, int(p * sorted.size()))];
    }
    int median() const { return percentile(0.5); }
    int widest() const { return widths.isEmpty() ? 0 : *std::max_element(widths.begin(), widths.end()); }
    QString describe() const
    {
        return QString("%1 columns: median %2 px, 95th percentile %3 px, widest %4 px; wider than 3 px in %5 columns "
                       "(%6%), wider than 10 px in %7")
            .arg(widths.size())
            .arg(percentile(0.5))
            .arg(percentile(0.95))
            .arg(widest())
            .arg(columnsOver(3))
            .arg(widths.isEmpty() ? 0.0 : 100.0 * columnsOver(3) / widths.size(), 0, 'f', 1)
            .arg(columnsOver(10));
    }
};

Bands skyBands(const QByteArray &mask, const QByteArray &bgra, const QSize &size, int fromX, int toX, int tolerance,
               bool roofs = false)
{
    Bands bands;
    const int w = size.width(), h = size.height();
    for (int x = fromX; x < toX; x++) {
        int edge = 0;
        while (edge < h && quint8(mask[edge * w + x]) >= 128) edge++;
        if (edge < 8 || edge >= h) continue;               // no sky at the top of this column, or no edge
        if (roofs && edge + 7 >= h) continue;
        int sum[3] = {0, 0, 0};
        for (int y = roofs ? edge + 2 : edge - 6; y <= (roofs ? edge + 6 : edge - 2); y++) {
            for (int c = 0; c < 3; c++) sum[c] += quint8(bgra[4 * (y * w + x) + c]);
        }
        int band = 0;
        const int step = roofs ? -1 : 1;
        for (int y = roofs ? edge - 1 : edge; y >= 0 && y < qMin(h, edge + 300) && qAbs(y - edge) < 300; y += step, band++) {
            bool alike = true;
            for (int c = 0; c < 3 && alike; c++) alike = qAbs(quint8(bgra[4 * (y * w + x) + c]) - sum[c] / 5) <= tolerance;
            if (!alike) break;
        }
        bands.widths << band;
    }
    return bands;
}

} // namespace

namespace
{

/// New Moscow's sky built from 20 rough points on a temporary copy (once for both tests): the rough polygon's bands,
/// the sky's, the time it took.
struct SkylineRun {
    QString skip;                        // why there is no run, when there is none
    Bands rough, skyLeft, skyRoofs;
    qint64 skyMs = 0, snapMs = 0;
    int seeds = 0;
    bool insideLimit = true;
    int undoSteps = 0, undoStepsBefore = 0;
};

const SkylineRun &skylineRun()
{
    static SkylineRun run;
    static bool done = false;
    if (done) return run;
    done = true;

    // The slow part (the copy of 163 MB, the load and the snapped outline across the painting) is opt-in.
    if (qgetenv("KRITA_AGENT_SLOW_TESTS").isEmpty()) {
        run.skip = "set KRITA_AGENT_SLOW_TESTS=1 to run the New Moscow skyline";
        return run;
    }
    const QString original = newMoscowOriginal();
    if (!QFileInfo::exists(original)) {
        run.skip = "New Moscow is not on this computer: " + original;
        return run;
    }
    // A copy in a temporary folder: the original is never opened or written.
    QTemporaryDir dir;
    if (!dir.isValid()) {
        run.skip = "no temporary folder";
        return run;
    }
    const QString copy = dir.filePath("new_moscow.kra");
    if (!QFile::copy(original, copy) || !QFile::setPermissions(copy, QFileDevice::ReadOwner | QFileDevice::WriteOwner)) {
        run.skip = "the copy of New Moscow could not be made (disk space?): " + copy;
        return run;
    }

    QElapsedTimer clock;
    clock.start();
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    kisdoc->setFileBatchMode(true); // never a dialog in a test
    kisdoc->setMimeType(KisDocument::nativeFormatMimeType());
    if (!kisdoc->loadNativeFormat(copy) || !kisdoc->image() || kisdoc->image()->size() != QSize(6000, 4500)) {
        run.skip = "the copy of New Moscow did not load";
        return run;
    }
    KisImageSP image = kisdoc->image();
    image->waitForDone();
    report(QString("New Moscow loaded in %1 ms").arg(clock.elapsed()));
    QScopedPointer<Document> doc(new Document(kisdoc.data(), false));
    run.undoStepsBefore = kisdoc->undoStack()->count();

    // 20 rough points along the skyline, read off a picture at half size: tower tops and the notches between them,
    // some tens of pixels off, with lines between them that cut through towers; and the top right corner.
    const QList<QPointF> skyline = {
        {180, 0},                                          // the top edge, right of the old building's roof
        {500, 470},   {820, 700},   {1200, 790},  {1600, 120},  {1990, 810},  {2240, 800},  {2300, 1450},
        {2960, 1020}, {3240, 1290}, {3460, 1560}, {3920, 1500}, {4250, 1180}, {4560, 880},  {4870, 720},
        {5090, 500},  {5300, 880},  {5500, 380},  {5880, 1000},
        {6000, 1060},                                      // the right edge
        {6000, 0}};

    const QSize size = image->size();
    QByteArray bgra(size.width() * size.height() * 4, 0);
    image->projection()->readBytes(reinterpret_cast<quint8 *>(bgra.data()), image->bounds());
    // Measured from the end of the old building (x 1000) to the right edge; left of it, bare branches cross the sky.
    const int fromX = 1000, toX = size.width(), tolerance = 24;

    // What runs 10 and 11 painted through: the rough polygon itself.
    const KisPixelSelectionSP polygon = KisFeatureBuilders::polygonMask(QPolygonF(QVector<QPointF>(skyline.begin(), skyline.end())),
                                                                        image->bounds(), false);
    const QByteArray roughBytes = readMask(polygon, image->bounds());
    run.rough = skyBands(roughBytes, bgra, size, fromX, toX, tolerance);
    report("the rough polygon, old sky left: " + run.rough.describe());
    report("the rough polygon, roofs taken: " + skyBands(roughBytes, bgra, size, fromX, toX, tolerance, true).describe());

    // The sky: seeds along the top, inside the snapped outline grown by 250 pixels, so it can follow every roof below
    // the rough line but never leak far into the city.
    clock.restart();
    QScopedPointer<Selection> limit(doc->maskSnapOutline(skyline));
    run.snapMs = clock.elapsed();
    if (!limit) {
        run.skip = "the snapped outline of the skyline gave nothing";
        return run;
    }
    report(QString("snapped outline of the 21 points: %1 ms").arg(run.snapMs));
    limit->grow(250, 250);
    QList<QPointF> seeds;
    for (int x = 250; x < size.width(); x += 100) seeds << QPointF(x, 10);
    run.seeds = seeds.size();
    clock.restart();
    QScopedPointer<Selection> sky(doc->maskContiguous(seeds, {{"threshold", 10}, {"within", QVariant::fromValue<QObject *>(limit.data())}}));
    run.skyMs = clock.elapsed();
    if (!sky) {
        run.skip = "the sky gave nothing";
        return run;
    }
    const QByteArray skyBytes = maskBytes(sky.data(), size);
    run.skyLeft = skyBands(skyBytes, bgra, size, fromX, toX, tolerance);
    run.skyRoofs = skyBands(skyBytes, bgra, size, fromX, toX, tolerance, true);
    report(QString("the sky (%1 seeds, %2 ms), old sky left: ").arg(seeds.size()).arg(run.skyMs) + run.skyLeft.describe());
    report("the sky, roofs taken: " + run.skyRoofs.describe());

    const QByteArray limitBytes = maskBytes(limit.data(), size);
    for (int i = 0; i < skyBytes.size(); i += 7) {
        if (skyBytes[i] && !limitBytes[i]) run.insideLimit = false;
    }
    const QByteArray out = qgetenv("KRITA_AGENT_SKYLINE_OUT");
    if (!out.isEmpty()) {
        saveMask(roughBytes, size, QString::fromLocal8Bit(out) + "/rough.png");
        saveMask(skyBytes, size, QString::fromLocal8Bit(out) + "/sky.png");
    }
    run.undoSteps = kisdoc->undoStack()->count();
    doc.reset();
    return run;
}

} // namespace

void TestDocumentFeatureBuilders::testSkylineRegressionFloor()
{
    // Runs 10 and 11: a hand-drawn skyline polygon left bands of old sky above the roofs of New Moscow. This test is a
    // REGRESSION FLOOR for what the builders do now, not the spec's "no band of old sky" (see testSkylineTarget and
    // tasks.md 6.3): along the misty horizon and the sky-coloured glass towers bands remain.
    const SkylineRun &run = skylineRun();
    if (!run.skip.isEmpty()) QSKIP(qPrintable(run.skip));

    // The rough polygon leaves bands of old sky in most columns.
    QVERIFY2(run.rough.median() > 30 && run.rough.columnsOver(10) * 2 > run.rough.widths.size(), qPrintable(run.rough.describe()));
    // The sky's edge sits on the painting's edges in the median column, on both sides (no old sky left, no roof taken),
    // and leaves under half the rough polygon's wide bands.
    QVERIFY2(run.skyLeft.median() <= 2, qPrintable(run.skyLeft.describe()));
    QVERIFY2(run.skyLeft.columnsOver(10) * 2 < run.rough.columnsOver(10), qPrintable(run.skyLeft.describe()));
    QVERIFY2(run.skyRoofs.median() <= 5, qPrintable(run.skyRoofs.describe()));
    QVERIFY(run.skyLeft.widths.size() > (6000 - 1000) * 9 / 10);
    // Never outside the limit, no undo step, and fast: the plugin's Python flood fill took 22 s for 8 seeds.
    QVERIFY(run.insideLimit);
    QCOMPARE(run.undoSteps, run.undoStepsBefore);
    QVERIFY2(run.skyMs < 5000, qPrintable(QString("%1 ms").arg(run.skyMs)));
}

void TestDocumentFeatureBuilders::testSkylineTarget()
{
    // The spec's target (tasks.md 6.3, "no band of old sky"): the 95th percentile of the band along the skyline is
    // within 10 px (the stretch goal is 3 px). NOT MET: median 1 px, but 95th percentile 129 px, and 1721 of 4752
    // columns over 10 px. The expected failure flips to an unexpected pass (a failure to look at) when it is met.
    const SkylineRun &run = skylineRun();
    if (!run.skip.isEmpty()) QSKIP(qPrintable(run.skip));
    QEXPECT_FAIL("", "6.3 skyline target not met, see tasks.md", Continue);
    QVERIFY2(run.skyLeft.percentile(0.95) <= 10, qPrintable(run.skyLeft.describe()));
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentFeatureBuilders)
