/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureListTest.h"

#include <QElapsedTimer>
#include <QSignalSpy>
#include <QTest>

#include <atomic>
#include <random>
#include <thread>

#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorModelStandardIds.h>
#include <KoMixColorsOp.h>

#include <KisFeature.h>
#include <KisFeatureCommands.h>
#include <KisFeatureList.h>
#include <kis_default_bounds.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_pixel_selection.h>
#include <kis_datamanager.h>
#include <kis_types.h>

#include <KisTemporaryHomeTest.h>
#include <KoTestConfig.h>

namespace {

KisPixelSelectionSP maskWith(const QRect &rect, quint8 value = MAX_SELECTED)
{
    KisPixelSelectionSP mask = new KisPixelSelection();
    if (!rect.isEmpty()) {
        mask->select(rect, value);
    }
    return mask;
}

KisPaintDeviceSP deviceFilled(const QRect &rect, const QColor &color)
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisPaintDeviceSP dev = new KisPaintDevice(cs);
    dev->fill(rect, KoColor(color, cs));
    return dev;
}

QColor toQColor(const KoColor &color)
{
    QColor c;
    color.toQColor(&c);
    return c;
}

bool sameMaskPixels(KisPixelSelectionSP a, KisPixelSelectionSP b, const QRect &rect)
{
    QByteArray pa(rect.width() * rect.height(), 0);
    QByteArray pb(rect.width() * rect.height(), 0);
    a->readBytes(reinterpret_cast<quint8 *>(pa.data()), rect);
    b->readBytes(reinterpret_cast<quint8 *>(pb.data()), rect);
    return pa == pb;
}

QStringList names(const QList<KisFeatureSP> &features)
{
    QStringList result;
    Q_FOREACH (KisFeatureSP f, features) {
        result << f->name();
    }
    return result;
}

} // namespace

void KisFeatureListTest::initTestCase()
{
    // The colour-space plugins (floating-point RGB among them) and the profiles they need, from the build's own
    // folders as KISTEST_MAIN finds them; before the colour-space registry's first use.
    qputenv("EXTRA_RESOURCE_DIRS", QByteArray(KRITA_RESOURCE_DIRS_FOR_TESTS));
    qputenv("KRITA_PLUGIN_PATH", QByteArray(KRITA_PLUGINS_DIR_FOR_TESTS));
}

void KisFeatureListTest::testMeasureHardMask()
{
    KisPixelSelectionSP mask = maskWith(QRect(10, 20, 30, 40));
    KisPaintDeviceSP painting = deviceFilled(QRect(0, 0, 100, 100), QColor(200, 100, 50));

    KisFeatureSP feature = new KisFeature("Sky", "sky", mask, KisFeature::Artist, KisFeature::Kept, true);
    feature->measure(painting);

    QCOMPARE(feature->bounds(), QRect(10, 20, 30, 40));
    QCOMPARE(feature->area(), qint64(30 * 40));
    QVERIFY(feature->properties().hasMeanColor);
    QCOMPARE(toQColor(feature->meanColor()), QColor(200, 100, 50));

    QCOMPARE(feature->name(), QString("Sky"));
    QCOMPARE(feature->kind(), QString("sky"));
    QCOMPARE(feature->author(), KisFeature::Artist);
    QCOMPARE(feature->state(), KisFeature::Kept);
    QVERIFY(feature->isProtected());
    QVERIFY(!feature->id().isNull());
    QCOMPARE(feature->mask(), mask);
}

void KisFeatureListTest::testMeasureWeightedMeanColor()
{
    // 100 red pixels fully selected and 100 blue pixels selected at 85/255: red weighs three times as much.
    KisPixelSelectionSP mask = maskWith(QRect(0, 0, 10, 10));
    mask->select(QRect(10, 0, 10, 10), 85);
    KisPaintDeviceSP painting = deviceFilled(QRect(0, 0, 10, 10), Qt::red);
    painting->fill(QRect(10, 0, 10, 10), KoColor(Qt::blue, painting->colorSpace()));

    const KisFeature::Properties p = KisFeature::measureMask(mask, painting);
    QCOMPARE(p.bounds, QRect(0, 0, 20, 10));
    QCOMPARE(p.area, qint64(200));
    QVERIFY(p.hasMeanColor);
    const QColor mean = toQColor(p.meanColor);
    // 255 * 255 / 340 = 191.25 and 255 * 85 / 340 = 63.75
    QVERIFY2(qAbs(mean.red() - 191) <= 1, qPrintable(QString::number(mean.red())));
    QCOMPARE(mean.green(), 0);
    QVERIFY2(qAbs(mean.blue() - 64) <= 1, qPrintable(QString::number(mean.blue())));
    QCOMPARE(mean.alpha(), 255);
}

void KisFeatureListTest::testMeasureEmptyMaskAndNoColorSource()
{
    KisFeatureSP empty = new KisFeature("Nothing", "none", maskWith(QRect()));
    empty->measure(deviceFilled(QRect(0, 0, 10, 10), Qt::red));
    QVERIFY(empty->bounds().isEmpty());
    QCOMPARE(empty->area(), qint64(0));
    QVERIFY(!empty->properties().hasMeanColor);

    KisFeatureSP noColor = new KisFeature("Shape", "figure", maskWith(QRect(5, 5, 4, 4)));
    noColor->measure();
    QCOMPARE(noColor->bounds(), QRect(5, 5, 4, 4));
    QCOMPARE(noColor->area(), qint64(16));
    QVERIFY(!noColor->properties().hasMeanColor);

    // A null mask becomes an empty mask, never a null pointer.
    KisFeatureSP nullMask = new KisFeature("Null", "none", KisPixelSelectionSP());
    QVERIFY(nullMask->mask());
    QCOMPARE(nullMask->area(), qint64(0));
}

void KisFeatureListTest::testPropertiesUpdateWhenMaskChanges()
{
    KisPaintDeviceSP painting = deviceFilled(QRect(0, 0, 100, 100), Qt::green);
    KisFeatureSP feature = new KisFeature("Moon", "moon", maskWith(QRect(0, 0, 10, 10)));
    feature->measure(painting);
    QCOMPARE(feature->area(), qint64(100));

    feature->setMask(maskWith(QRect(50, 60, 5, 6)), painting);
    QCOMPARE(feature->bounds(), QRect(50, 60, 5, 6));
    QCOMPARE(feature->area(), qint64(30));
    QCOMPARE(toQColor(feature->meanColor()), QColor(Qt::green));

    // Without a colour source the old mean colour, which described the old mask, goes.
    feature->setMask(maskWith(QRect(1, 1, 2, 2)));
    QCOMPARE(feature->bounds(), QRect(1, 1, 2, 2));
    QVERIFY(!feature->properties().hasMeanColor);
}

void KisFeatureListTest::testMeasureInPlaceChange()
{
    KisFeatureSP feature = new KisFeature("Tower 3", "building", maskWith(QRect(0, 0, 10, 10)));
    feature->measure();
    feature->mask()->select(QRect(20, 0, 10, 10));
    // Not measured yet: the snapshot still describes the old mask.
    QCOMPARE(feature->area(), qint64(100));
    feature->measure();
    QCOMPARE(feature->area(), qint64(200));
    QCOMPARE(feature->bounds(), QRect(0, 0, 30, 10));
}

void KisFeatureListTest::testInsertRemoveOrderAndLookup()
{
    KisFeatureList list;
    QVERIFY(list.isEmpty());
    KisFeatureSP sky = new KisFeature("Sky", "sky", maskWith(QRect(0, 0, 100, 40)));
    KisFeatureSP moon = new KisFeature("Moon", "moon", maskWith(QRect(70, 5, 10, 10)));
    KisFeatureSP tower = new KisFeature("Tower 3", "building", maskWith(QRect(20, 30, 10, 70)));

    QVERIFY(list.insertFeature(sky));
    QVERIFY(list.insertFeature(tower));
    QVERIFY(list.insertFeature(moon, 1));
    QVERIFY(!list.insertFeature(sky));            // already there
    QVERIFY(!list.insertFeature(KisFeatureSP())); // null

    QCOMPARE(names(list.features()), QStringList({"Sky", "Moon", "Tower 3"}));
    QCOMPARE(list.count(), 3);
    QCOMPARE(list.indexOf(moon->id()), 1);
    QCOMPARE(list.feature(tower->id()), tower);
    QCOMPARE(list.featureByName("Moon"), moon);
    QVERIFY(!list.featureByName("moon"));

    QCOMPARE(list.removeFeature(moon->id()), moon);
    QVERIFY(!list.removeFeature(moon->id()));
    QCOMPARE(names(list.features()), QStringList({"Sky", "Tower 3"}));
    QCOMPARE(list.indexOf(moon->id()), -1);

    list.clear();
    QVERIFY(list.isEmpty());
    QVERIFY(list.featuresWithBoundsIntersecting(QRect(0, 0, 1000, 1000)).isEmpty());
}

void KisFeatureListTest::testSignals()
{
    KisFeatureList list;
    QSignalSpy added(&list, SIGNAL(sigFeatureAdded(QUuid)));
    QSignalSpy removed(&list, SIGNAL(sigFeatureRemoved(QUuid)));
    QSignalSpy changed(&list, SIGNAL(sigFeatureChanged(QUuid)));

    KisFeatureSP sky = new KisFeature("Sky", "sky", maskWith(QRect(0, 0, 10, 10)));
    list.insertFeature(sky);
    QCOMPARE(added.count(), 1);
    QCOMPARE(added.first().first().value<QUuid>(), sky->id());

    sky->setName("Evening sky");
    sky->setMask(maskWith(QRect(0, 0, 20, 20)));
    QCOMPARE(changed.count(), 2);

    list.removeFeature(sky->id());
    QCOMPARE(removed.count(), 1);

    // A feature out of the list no longer reports to it.
    sky->setName("Gone");
    QCOMPARE(changed.count(), 2);
}

void KisFeatureListTest::testIndexMatchesBruteForce()
{
    KisFeatureList list;
    std::mt19937 random(7);
    std::uniform_int_distribution<int> pos(0, 900);
    std::uniform_int_distribution<int> size(1, 120);
    for (int i = 0; i < 200; i++) {
        KisFeatureSP f = new KisFeature(QString("f%1").arg(i), "test",
                                        maskWith(QRect(pos(random), pos(random), size(random), size(random))));
        f->measure();
        list.insertFeature(f);
    }
    // A feature with an empty mask is in the list but never found by bounds.
    list.insertFeature(new KisFeature("empty", "test", maskWith(QRect())));

    for (int q = 0; q < 300; q++) {
        const QRect rect(pos(random), pos(random), size(random), size(random));
        QStringList expected;
        Q_FOREACH (KisFeatureSP f, list.features()) {
            if (f->bounds().intersects(rect)) expected << f->name();
        }
        QCOMPARE(names(list.featuresWithBoundsIntersecting(rect)), expected);

        const QPoint point = rect.topLeft();
        QStringList expectedAt;
        Q_FOREACH (KisFeatureSP f, list.features()) {
            if (f->bounds().contains(point)) expectedAt << f->name();
        }
        QCOMPARE(names(list.featuresWithBoundsContaining(point)), expectedAt);
    }

    // Edges are inclusive of the last pixel and exclusive past it, as QRect's are.
    KisFeatureList edges;
    KisFeatureSP f = new KisFeature("edge", "test", maskWith(QRect(10, 10, 5, 5)));
    f->measure();
    edges.insertFeature(f);
    QCOMPARE(edges.featuresWithBoundsContaining(QPoint(14, 14)).size(), 1);
    QCOMPARE(edges.featuresWithBoundsContaining(QPoint(15, 14)).size(), 0);
    QCOMPARE(edges.featuresWithBoundsIntersecting(QRect(15, 10, 3, 3)).size(), 0);
    QCOMPARE(edges.featuresWithBoundsIntersecting(QRect(14, 10, 3, 3)).size(), 1);
}

void KisFeatureListTest::testIndexFollowsMaskChanges()
{
    KisFeatureList list;
    KisFeatureSP f = new KisFeature("Moon", "moon", maskWith(QRect(0, 0, 10, 10)));
    f->measure();
    list.insertFeature(f);
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(5, 5)).size(), 1);

    f->setMask(maskWith(QRect(500, 500, 10, 10)));
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(5, 5)).size(), 0);
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(505, 505)).size(), 1);

    f->mask()->clear();
    f->mask()->select(QRect(100, 100, 1, 1));
    f->measure();
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(505, 505)).size(), 0);
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(100, 100)).size(), 1);

    KisFeature::Properties p = f->properties();
    p.bounds = QRect(300, 300, 2, 2);
    f->setProperties(p);
    QCOMPARE(list.featuresWithBoundsContaining(QPoint(301, 301)).size(), 1);
}

void KisFeatureListTest::testImageOwnsListAndClonesCopyIt()
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP image = new KisImage(0, 200, 100, cs, "features");
    QVERIFY(image->featureList());
    QVERIFY(image->featureList()->isEmpty());

    KisFeatureSP sky = new KisFeature("Sky", "sky", maskWith(QRect(0, 0, 200, 40)), KisFeature::Artist,
                                      KisFeature::Kept, true);
    sky->measure();
    image->featureList()->insertFeature(sky);
    // The list gives a mask the image's bounds, so "select all" on it means the document.
    QCOMPARE(sky->mask()->defaultBounds()->bounds(), image->bounds());

    KisImageSP clone = image->clone(true);
    QCOMPARE(clone->featureList()->count(), 1);
    KisFeatureSP copy = clone->featureList()->features().first();
    QVERIFY(copy != sky);
    QCOMPARE(copy->id(), sky->id());
    QCOMPARE(copy->name(), sky->name());
    QCOMPARE(copy->kind(), sky->kind());
    QCOMPARE(copy->author(), sky->author());
    QCOMPARE(copy->state(), sky->state());
    QCOMPARE(copy->isProtected(), sky->isProtected());
    QVERIFY(copy->properties() == sky->properties());
    QVERIFY(copy->mask() != sky->mask());
    QVERIFY(sameMaskPixels(copy->mask(), sky->mask(), image->bounds()));
    QCOMPARE(clone->featureList()->featuresWithBoundsContaining(QPoint(5, 5)).size(), 1);

    // The copies are independent.
    copy->mask()->select(QRect(0, 50, 10, 10));
    copy->setName("Copy");
    QCOMPARE(sky->name(), QString("Sky"));
    QVERIFY(!sameMaskPixels(copy->mask(), sky->mask(), image->bounds()));
}

void KisFeatureListTest::testCopyFromImageReplacesFeatures()
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP source = new KisImage(0, 100, 100, cs, "source");
    source->featureList()->insertFeature(new KisFeature("A", "a", maskWith(QRect(0, 0, 5, 5))));
    KisImageSP target = new KisImage(0, 100, 100, cs, "target");
    target->featureList()->insertFeature(new KisFeature("B", "b", maskWith(QRect(0, 0, 5, 5))));

    target->barrierLock();
    target->copyFromImage(*source);
    target->unlock();
    QCOMPARE(names(target->featureList()->features()), QStringList({"A"}));
}

void KisFeatureListTest::testAddRemoveRenameCommandsUndo()
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP image = new KisImage(0, 100, 100, cs, "commands");
    KisFeatureList *list = image->featureList();

    KisFeatureSP sky = new KisFeature("Sky", "sky", maskWith(QRect(0, 0, 100, 40)));
    KisFeatureSP moon = new KisFeature("Moon", "moon", maskWith(QRect(70, 5, 10, 10)));
    sky->measure();
    moon->measure();
    list->insertFeature(sky);

    KisAddFeatureCommand add(image, moon, 0);
    add.redo();
    QCOMPARE(names(list->features()), QStringList({"Moon", "Sky"}));
    add.undo();
    QCOMPARE(names(list->features()), QStringList({"Sky"}));
    add.redo();

    KisRenameFeatureCommand rename(image, moon->id(), "Full moon");
    rename.redo();
    QCOMPARE(moon->name(), QString("Full moon"));
    rename.undo();
    QCOMPARE(moon->name(), QString("Moon"));
    rename.redo();

    KisRemoveFeatureCommand remove(image, moon->id());
    remove.redo();
    QCOMPARE(names(list->features()), QStringList({"Sky"}));
    remove.undo();
    // Back in its place, the same feature with its mask.
    QCOMPARE(names(list->features()), QStringList({"Full moon", "Sky"}));
    QCOMPARE(list->features().first(), moon);
    QCOMPARE(list->featuresWithBoundsContaining(QPoint(75, 10)).size(), 2);

    // Commands on a feature that is gone do nothing.
    KisRenameFeatureCommand stale(image, QUuid::createUuid(), "x");
    stale.redo();
    stale.undo();
    QCOMPARE(names(list->features()), QStringList({"Full moon", "Sky"}));
}

void KisFeatureListTest::testStringConversions()
{
    QCOMPARE(KisFeature::authorToString(KisFeature::Artist), QString("artist"));
    QCOMPARE(KisFeature::authorToString(KisFeature::Agent), QString("agent"));
    QCOMPARE(KisFeature::authorFromString("artist"), KisFeature::Artist);
    QCOMPARE(KisFeature::authorFromString("agent", KisFeature::Artist), KisFeature::Agent);
    QCOMPARE(KisFeature::authorFromString("robot", KisFeature::Artist), KisFeature::Artist);
    QCOMPARE(KisFeature::stateToString(KisFeature::Proposed), QString("proposed"));
    QCOMPARE(KisFeature::stateToString(KisFeature::Kept), QString("kept"));
    QCOMPARE(KisFeature::stateFromString("kept"), KisFeature::Kept);
    QCOMPARE(KisFeature::stateFromString("?", KisFeature::Kept), KisFeature::Kept);
}

void KisFeatureListTest::testLargeMaskStaysTiled()
{
    // New Moscow's size: a 6000x4500 mask is 27 MB as a dense buffer. A feature covering a corner keeps only the
    // tiles it touches, and a whole-canvas one is measured without a dense copy.
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP image = new KisImage(0, 6000, 4500, cs, "new moscow");

    KisPixelSelectionSP corner = new KisPixelSelection(new KisDefaultBounds(image));
    corner->select(QRect(0, 0, 128, 128));
    QVERIFY(corner->dataManager()->extent().width() <= 192);

    KisPixelSelectionSP whole = new KisPixelSelection(new KisDefaultBounds(image));
    whole->select(image->bounds());
    KisPaintDeviceSP painting = deviceFilled(image->bounds(), QColor(10, 20, 30));

    KisFeatureSP feature = new KisFeature("Everything", "test", whole);
    QElapsedTimer timer;
    timer.start();
    feature->measure(painting);
    qDebug() << "measured a 6000x4500 mask with mean colour in" << timer.elapsed() << "ms";
    QCOMPARE(feature->area(), qint64(6000) * 4500);
    QCOMPARE(feature->bounds(), image->bounds());
    QCOMPARE(toQColor(feature->meanColor()), QColor(10, 20, 30));
}

namespace {

/// A painting of one colour over \p size (its default pixel: no tiles are written) under a fully selected mask of
/// the same size, measured: its mean colour must be that colour.
void checkMeanOfLargeUniformArea(const KoColor &color, const QSize &size)
{
    KisPaintDeviceSP painting = new KisPaintDevice(color.colorSpace());
    painting->setDefaultPixel(color);
    KisPixelSelectionSP mask = maskWith(QRect(QPoint(0, 0), size));

    const KisFeature::Properties p = KisFeature::measureMask(mask, painting);
    QCOMPARE(p.bounds, QRect(QPoint(0, 0), size));
    QCOMPARE(p.area, qint64(size.width()) * size.height());
    QVERIFY(p.hasMeanColor);
    QVERIFY2(p.meanColor == color, qPrintable(p.meanColor.toXML() + " != " + color.toXML()));
}

} // namespace

void KisFeatureListTest::testMeanColorOfLargeU16Mask()
{
    // 16-bit integer channels: the mixer's 64-bit sums of colour x alpha x weight overflow after about 8.4 million
    // opaque, fully selected pixels; 3000 x 3000 is 9 million.
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb16();
    KoColor color(cs);
    quint16 *channels = reinterpret_cast<quint16 *>(color.data());
    channels[0] = 1000;  // blue
    channels[1] = 40000; // green
    channels[2] = 65000; // red
    channels[3] = 65535; // alpha
    checkMeanOfLargeUniformArea(color, QSize(3000, 3000));
}

void KisFeatureListTest::testMeanColorOfLargeFloatMask()
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->colorSpace(RGBAColorModelID.id(),
                                                                         Float32BitsColorDepthID.id());
    QVERIFY(cs);
    KoColor color(cs);
    float *channels = reinterpret_cast<float *>(color.data());
    channels[0] = 0.25f;
    channels[1] = 0.5f;
    channels[2] = 0.75f;
    channels[3] = 1.0f;
    checkMeanOfLargeUniformArea(color, QSize(3000, 3000));
}

namespace {

/// A painting of 1100 x 1000 (over 2^20 pixels): colour A over the top half, colour B over the bottom, each with its
/// own alpha, under a mask whose weight changes with the column (255, 128, 7).
struct MixedArea {
    static constexpr int W = 1100;
    static constexpr int H = 1000;
    KisPaintDeviceSP painting;
    KisPixelSelectionSP mask;

    MixedArea(const KoColor &a, const KoColor &b)
    {
        painting = new KisPaintDevice(a.colorSpace());
        painting->fill(QRect(0, 0, W, H / 2), a);
        painting->fill(QRect(0, H / 2, W, H - H / 2), b);
        mask = new KisPixelSelection();
        for (int x = 0; x < W; x++) {
            mask->select(QRect(x, 0, 1, H), weightOf(x));
        }
    }

    static quint8 weightOf(int x)
    {
        static const quint8 weights[3] = {255, 128, 7};
        return weights[x % 3];
    }
};

} // namespace

void KisFeatureListTest::testMeanColorOfLargeU16MixedArea()
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb16();
    QVERIFY(cs);
    const quint16 a[4] = {1000, 40000, 65000, 60000}; // B, G, R, alpha
    const quint16 b[4] = {64000, 3000, 20000, 20000};
    KoColor colorA(reinterpret_cast<const quint8 *>(a), cs);
    KoColor colorB(reinterpret_cast<const quint8 *>(b), cs);
    MixedArea area(colorA, colorB);

    // The reference in double precision: colour = sum(c * alpha * w) / sum(alpha * w), alpha = sum(alpha * w) / sum(w).
    double columnWeights = 0;
    for (int x = 0; x < MixedArea::W; x++) {
        columnWeights += MixedArea::weightOf(x);
    }
    const double wA = columnWeights * (MixedArea::H / 2);
    const double wB = columnWeights * (MixedArea::H - MixedArea::H / 2);
    const double awA = a[3] * wA, awB = b[3] * wB;
    double expected[4];
    for (int i = 0; i < 3; i++) {
        expected[i] = (a[i] * awA + b[i] * awB) / (awA + awB);
    }
    expected[3] = (awA + awB) / (wA + wB);

    const KisFeature::Properties p = KisFeature::measureMask(area.mask, area.painting);
    QVERIFY(p.hasMeanColor);
    QCOMPARE(p.area, qint64(MixedArea::W) * MixedArea::H);
    const quint16 *mean = reinterpret_cast<const quint16 *>(p.meanColor.data());
    for (int i = 0; i < 4; i++) {
        QVERIFY2(qAbs(double(mean[i]) - expected[i]) <= 1.0,
                 qPrintable(QString("channel %1: %2, expected %3").arg(i).arg(mean[i]).arg(expected[i])));
    }
}

void KisFeatureListTest::testMeanColorOfLargeU8IsOneMixers()
{
    // 8-bit channels cannot overflow the mixer: the mean is exactly what one mixer over all pixels gives.
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KoColor colorA(QColor(200, 30, 90, 230), cs);
    KoColor colorB(QColor(10, 250, 60, 40), cs);
    MixedArea area(colorA, colorB);

    const QRect rect(0, 0, MixedArea::W, MixedArea::H);
    const int n = rect.width() * rect.height();
    QByteArray pixels(n * 4, 0);
    area.painting->readBytes(reinterpret_cast<quint8 *>(pixels.data()), rect);
    QByteArray maskBytes(n, 0);
    area.mask->readBytes(reinterpret_cast<quint8 *>(maskBytes.data()), rect);
    QVector<qint16> weights(n);
    int weightSum = 0;
    for (int i = 0; i < n; i++) {
        weights[i] = quint8(maskBytes[i]);
        weightSum += weights[i];
    }
    QScopedPointer<KoMixColorsOp::Mixer> mixer(cs->mixColorsOp()->createMixer());
    mixer->accumulate(reinterpret_cast<const quint8 *>(pixels.constData()), weights.constData(), weightSum, n);
    KoColor expected(cs);
    mixer->computeMixedColor(expected.data());

    const KisFeature::Properties p = KisFeature::measureMask(area.mask, area.painting);
    QVERIFY(p.hasMeanColor);
    QVERIFY2(p.meanColor == expected, qPrintable(p.meanColor.toXML() + " != " + expected.toXML()));
}

void KisFeatureListTest::testListDestroyedWhileFeaturesChange()
{
    // Features change in one thread (a stroke job) while their list is destroyed in another (an image closed): a
    // feature must never call a list that is gone.
    QVector<KisFeatureSP> features;
    for (int i = 0; i < 8; i++) {
        features << KisFeatureSP(new KisFeature(QString("f%1").arg(i), "test", maskWith(QRect(i, i, 4, 4))));
    }
    std::atomic<bool> stop {false};
    std::atomic<int> changes {0};
    std::thread worker([&]() {
        int n = 0;
        while (!stop) {
            for (KisFeatureSP f : features) {
                f->setName(QString::number(n++));
                f->setProtected(n % 2);
            }
            changes++;
        }
    });

    for (int i = 0; i < 3000; i++) {
        KisFeatureList *list = new KisFeatureList();
        for (KisFeatureSP f : features) {
            list->insertFeature(f);
        }
        delete list;
    }
    stop = true;
    worker.join();
    QVERIFY(changes > 0);
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisFeatureListTest)
