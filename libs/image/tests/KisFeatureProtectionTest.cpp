/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureProtectionTest.h"

#include <QTest>

#include <cstring>
#include <limits>

#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>

#include <KisFeature.h>
#include <KisFeatureCommands.h>
#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include <KisFeatureQueries.h>
#include <kis_clone_layer.h>
#include <KisImageResolutionProxy.h>
#include <kis_default_bounds.h>
#include <kis_pointer_utils.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>
#include <kis_transform_mask.h>
#include <kis_transparency_mask.h>
#include <kis_types.h>

#include <KisTemporaryHomeTest.h>
#include "KritaTransformMaskStubs.h"
#include <KoTestConfig.h>

namespace {

const QSize imageSize(200, 150);

KisPixelSelectionSP maskWith(const QRect &rect, quint8 value = MAX_SELECTED)
{
    KisPixelSelectionSP mask = new KisPixelSelection();
    if (!rect.isEmpty()) mask->select(rect, value);
    return mask;
}

struct Fixture {
    KisImageSP image;
    KisPaintLayerSP layer;

    Fixture()
    {
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(0, imageSize.width(), imageSize.height(), cs, "protect");
        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        image->addNode(layer);
    }

    KisFeatureList *list() const { return image->featureList(); }

    KisFeatureSP add(const QString &name, const QRect &rect, bool isProtected, quint8 value = MAX_SELECTED)
    {
        KisFeatureSP feature = new KisFeature(name, "building", maskWith(rect, value), KisFeature::Agent, KisFeature::Kept,
                                              isProtected);
        feature->measure();
        list()->insertFeature(feature);
        return feature;
    }

    quint8 maskAt(KisPixelSelectionSP mask, int x, int y) const
    {
        quint8 value = 0;
        mask->readBytes(&value, QRect(x, y, 1, 1));
        return value;
    }
};

QStringList names(const QList<KisFeatureSP> &features)
{
    QStringList result;
    Q_FOREACH (KisFeatureSP f, features) result << f->name();
    return result;
}

KisSelectionSP newSelection(KisImageSP image)
{
    return new KisSelection(new KisDefaultBounds(image), toQShared(new KisImageResolutionProxy(image)));
}

/// The selection's value at a pixel: the projection of a selection with an inverted default reads 255 outside.
quint8 selectedAt(KisSelectionSP selection, int x, int y)
{
    quint8 value = 0;
    selection->projection()->readBytes(&value, QRect(x, y, 1, 1));
    return value;
}

} // namespace

void KisFeatureProtectionTest::initTestCase()
{
    qputenv("EXTRA_RESOURCE_DIRS", QByteArray(KRITA_RESOURCE_DIRS_FOR_TESTS));
    qputenv("KRITA_PLUGIN_PATH", QByteArray(KRITA_PLUGINS_DIR_FOR_TESTS));
    // A transform mask asks the registry for its parameters' holder: the stubs provide one (without them it aborts).
    TestUtil::registerTransformMaskStubs();
}

void KisFeatureProtectionTest::testNothingProtectedCostsNothing()
{
    Fixture f;
    // No feature: nothing protected, no mask built, a selection passes through untouched.
    QVERIFY(!f.list()->hasProtectedFeatures());
    QVERIFY(!f.list()->protectedMask());
    QVERIFY(!f.list()->unprotectedMask());
    QVERIFY(!KisFeatureProtection::isActive(f.image));
    KisSelectionSP clip = new KisSelection();
    QVERIFY(KisFeatureProtection::guardSelection(f.image, clip) == clip);
    QVERIFY(!KisFeatureProtection::guardSelection(f.image, KisSelectionSP()));
    QVERIFY(KisFeatureProtection::keptOutOf(f.image, f.image->bounds()).isEmpty());

    // Features that are not protected change nothing either.
    f.add("Sky", QRect(0, 0, 200, 50), false);
    QVERIFY(!f.list()->hasProtectedFeatures());
    QVERIFY(!f.list()->protectedMask());
    QVERIFY(KisFeatureProtection::guardSelection(f.image, clip) == clip);
}

void KisFeatureProtectionTest::testRevisionChangesWithTheList()
{
    Fixture f;
    const int r0 = f.list()->revision();
    KisFeatureSP tower = f.add("Tower", QRect(10, 10, 20, 60), true);
    const int r1 = f.list()->revision();
    QVERIFY(r1 != r0);
    QVERIFY(f.list()->hasProtectedFeatures());
    KisPixelSelectionSP first = f.list()->protectedMask();
    QVERIFY(first);
    // The same revision gives the same object; any change gives a new one.
    QVERIFY(f.list()->protectedMask() == first);
    QCOMPARE(f.list()->revision(), r1);
    tower->setProtected(false);
    QVERIFY(f.list()->revision() != r1);
    QVERIFY(!f.list()->hasProtectedFeatures());
    QVERIFY(!f.list()->protectedMask());
    tower->setProtected(true);
    QVERIFY(f.list()->hasProtectedFeatures());
    QVERIFY(f.list()->protectedMask() != first);
    // A rename or a new mask also changes the revision (the answer is rebuilt, never stale).
    const int r2 = f.list()->revision();
    tower->setName("Tower 1");
    QVERIFY(f.list()->revision() != r2);
    const int r3 = f.list()->revision();
    tower->setMask(maskWith(QRect(100, 10, 20, 60)));
    QVERIFY(f.list()->revision() != r3);
    QCOMPARE(f.maskAt(f.list()->protectedMask(), 105, 20), quint8(255));
    QCOMPARE(f.maskAt(f.list()->protectedMask(), 15, 20), quint8(0));
    f.list()->removeFeature(tower->id());
    QVERIFY(!f.list()->hasProtectedFeatures());
}

void KisFeatureProtectionTest::testProtectedMaskIsTheBinarizedUnion()
{
    Fixture f;
    f.add("A", QRect(10, 10, 20, 20), true);
    f.add("Soft", QRect(50, 10, 20, 20), true, 30);    // a soft edge: protected whole
    f.add("Open", QRect(100, 10, 20, 20), false);     // not protected
    KisPixelSelectionSP mask = f.list()->protectedMask();
    QVERIFY(mask);
    QCOMPARE(f.maskAt(mask, 15, 15), quint8(255));
    QCOMPARE(f.maskAt(mask, 55, 15), quint8(255));
    QCOMPARE(f.maskAt(mask, 105, 15), quint8(0));
    QCOMPARE(f.maskAt(mask, 5, 5), quint8(0));
    // Its default pixel is unselected and the inverse's selected.
    KisPixelSelectionSP inverse = f.list()->unprotectedMask();
    QVERIFY(inverse);
    QCOMPARE(f.maskAt(inverse, 15, 15), quint8(0));
    QCOMPARE(f.maskAt(inverse, 105, 15), quint8(255));
    QCOMPARE(f.maskAt(inverse, 5, 5), quint8(255));
    // The features' own masks are untouched (the soft one is still soft).
    QCOMPARE(f.maskAt(f.list()->featureByName("Soft")->mask(), 55, 15), quint8(30));
}

void KisFeatureProtectionTest::testSuspendedProtectsNothing()
{
    Fixture f;
    f.add("A", QRect(10, 10, 20, 20), true);
    QVERIFY(KisFeatureProtection::isActive(f.image));
    f.list()->setProtectionSuspended(true);
    QVERIFY(f.list()->protectionSuspended());
    QVERIFY(!KisFeatureProtection::isActive(f.image));
    QVERIFY(!f.list()->protectedMask());
    KisSelectionSP clip = new KisSelection();
    QVERIFY(KisFeatureProtection::guardSelection(f.image, clip) == clip);
    f.list()->setProtectionSuspended(false);
    QVERIFY(KisFeatureProtection::isActive(f.image));
}

void KisFeatureProtectionTest::testProtectionCommandUndoRedo()
{
    Fixture f;
    KisFeatureSP a = f.add("A", QRect(10, 10, 20, 20), false);
    KisSetFeatureProtectedCommand protect(f.image, a->id(), true);
    protect.redo();
    QVERIFY(a->isProtected());
    QVERIFY(f.list()->hasProtectedFeatures());
    protect.undo();
    QVERIFY(!a->isProtected());
    QVERIFY(!f.list()->hasProtectedFeatures());
    protect.redo();
    QVERIFY(a->isProtected());

    // The command for a feature that is gone does nothing, and undoing it does nothing.
    KisSetFeatureProtectedCommand gone(f.image, QUuid::createUuid(), true);
    gone.redo();
    gone.undo();
    QVERIFY(a->isProtected());
}

void KisFeatureProtectionTest::testGuardSelectionWithAndWithoutClip()
{
    Fixture f;
    f.add("Tower", QRect(40, 40, 30, 60), true);

    // No clip: everything but the tower, out past the canvas too.
    KisSelectionSP everywhere = KisFeatureProtection::guardSelection(f.image, KisSelectionSP());
    QVERIFY(everywhere);
    QCOMPARE(selectedAt(everywhere, 10, 10), quint8(255));
    QCOMPARE(selectedAt(everywhere, 50, 50), quint8(0));
    QCOMPARE(selectedAt(everywhere, 69, 99), quint8(0));
    QCOMPARE(selectedAt(everywhere, 70, 99), quint8(255));
    QCOMPARE(selectedAt(everywhere, 50, 100), quint8(255));

    // A clip: its part outside the tower.
    KisSelectionSP clip = newSelection(f.image);
    clip->pixelSelection()->select(QRect(0, 0, 100, 100), MAX_SELECTED);
    KisSelectionSP guarded = KisFeatureProtection::guardSelection(f.image, clip);
    QVERIFY(guarded != clip);
    QCOMPARE(selectedAt(guarded, 10, 10), quint8(255));
    QCOMPARE(selectedAt(guarded, 50, 50), quint8(0));   // protected
    QCOMPARE(selectedAt(guarded, 150, 10), quint8(0));  // outside the clip
    // The clip itself is unchanged.
    QCOMPARE(selectedAt(clip, 50, 50), quint8(255));
}

void KisFeatureProtectionTest::testGuardSelectionEdgeCases()
{
    Fixture f;
    // A protected feature with no pixels protects nothing.
    f.add("Empty", QRect(), true);
    KisSelectionSP clip = newSelection(f.image);
    clip->pixelSelection()->select(QRect(0, 0, 50, 50), MAX_SELECTED);
    KisSelectionSP guarded = KisFeatureProtection::guardSelection(f.image, clip);
    QVERIFY(guarded);
    QCOMPARE(selectedAt(guarded, 10, 10), quint8(255));

    // An empty clip stays empty.
    KisSelectionSP none = newSelection(f.image);
    guarded = KisFeatureProtection::guardSelection(f.image, none);
    QVERIFY(guarded);
    QCOMPARE(selectedAt(guarded, 10, 10), quint8(0));

    // An inverted clip (selected everywhere but a hole) minus a feature inside the selected part.
    f.add("Wall", QRect(100, 100, 30, 30), true);
    KisSelectionSP inverted = newSelection(f.image);
    inverted->pixelSelection()->select(QRect(0, 0, 20, 20), MAX_SELECTED);
    inverted->pixelSelection()->invert();
    guarded = KisFeatureProtection::guardSelection(f.image, inverted);
    QCOMPARE(selectedAt(guarded, 10, 10), quint8(0));    // the hole
    QCOMPARE(selectedAt(guarded, 110, 110), quint8(0));  // protected
    QCOMPARE(selectedAt(guarded, 150, 20), quint8(255));

    // The whole canvas protected: nothing may be written.
    f.add("All", QRect(0, 0, imageSize.width(), imageSize.height()), true);
    guarded = KisFeatureProtection::guardSelection(f.image, KisSelectionSP());
    QCOMPARE(selectedAt(guarded, 10, 10), quint8(0));
    QCOMPARE(selectedAt(guarded, 199, 149), quint8(0));
}

void KisFeatureProtectionTest::testClipPixelWriteKeepsProtectedPixels()
{
    Fixture f;
    f.add("Tower", QRect(10, 10, 10, 10), true);
    f.add("Other", QRect(30, 10, 10, 10), true);
    f.add("Open", QRect(50, 10, 10, 10), false);
    KisPaintDeviceSP device = f.layer->paintDevice();
    const KoColorSpace *cs = device->colorSpace();
    device->fill(QRect(0, 0, 100, 40), KoColor(Qt::gray, cs));

    const QRect rect(0, 0, 100, 40);
    const int pixelSize = cs->pixelSize();
    QByteArray data(rect.width() * rect.height() * pixelSize, 0);
    KoColor red(Qt::red, cs);
    for (int i = 0; i < rect.width() * rect.height(); i++) memcpy(data.data() + i * pixelSize, red.data(), pixelSize);

    QByteArray before(data.size(), 0);
    device->readBytes(reinterpret_cast<quint8 *>(before.data()), rect);
    const QStringList kept = KisFeatureProtection::clipPixelWrite(f.image, device, data, rect);
    QCOMPARE(kept, QStringList({"Tower", "Other"}));
    // Inside the protected features the data is the old pixels; elsewhere (the open feature included) it is as given.
    auto pixel = [&](const QByteArray &bytes, int x, int y) {
        return bytes.mid((y * rect.width() + x) * pixelSize, pixelSize);
    };
    QCOMPARE(pixel(data, 15, 15), pixel(before, 15, 15));
    QCOMPARE(pixel(data, 35, 15), pixel(before, 35, 15));
    QCOMPARE(pixel(data, 55, 15), QByteArray(reinterpret_cast<const char *>(red.data()), pixelSize));
    QCOMPARE(pixel(data, 5, 5), QByteArray(reinterpret_cast<const char *>(red.data()), pixelSize));

    // A write that changes nothing inside a protected feature does not name it.
    QByteArray same(before);
    QVERIFY(KisFeatureProtection::clipPixelWrite(f.image, device, same, rect).isEmpty());
    QCOMPARE(same, before);

    // Too little data: nothing is touched.
    QByteArray tooShort(10, 1);
    QVERIFY(KisFeatureProtection::clipPixelWrite(f.image, device, tooShort, rect).isEmpty());
    QCOMPARE(tooShort, QByteArray(10, 1));
}

void KisFeatureProtectionTest::testKeptOutOfNamesOnlyReachedFeatures()
{
    Fixture f;
    f.add("Tower", QRect(10, 10, 10, 10), true);
    f.add("Far", QRect(150, 100, 10, 10), true);
    f.add("Open", QRect(30, 10, 10, 10), false);
    QCOMPARE(KisFeatureProtection::keptOutOf(f.image, QRect(0, 0, 60, 60)), QStringList({"Tower"}));
    QCOMPARE(KisFeatureProtection::keptOutOf(f.image, f.image->bounds()), QStringList({"Tower", "Far"}));
    QVERIFY(KisFeatureProtection::keptOutOf(f.image, QRect(100, 0, 40, 40)).isEmpty());
    // Within a selection: only where it selects.
    KisSelectionSP left = newSelection(f.image);
    left->pixelSelection()->select(QRect(0, 0, 100, 150), MAX_SELECTED);
    QCOMPARE(KisFeatureProtection::keptOutOf(f.image, f.image->bounds(), left), QStringList({"Tower"}));
}

void KisFeatureProtectionTest::testFeaturesAtOverlappingAndTouching()
{
    Fixture f;
    KisFeatureSP sky = f.add("Sky", QRect(0, 0, 200, 50), false);
    KisFeatureSP moon = f.add("Moon", QRect(150, 10, 20, 20), false);
    KisFeatureSP ground = f.add("Ground", QRect(0, 50, 200, 100), false);
    KisFeatureSP tower = f.add("Tower", QRect(20, 30, 20, 60), false);
    KisFeatureSP soft = f.add("Soft", QRect(100, 100, 10, 10), false, 7);
    KisFeatureSP empty = f.add("Empty", QRect(), false);
    KisFeatureList *list = f.list();

    QCOMPARE(names(KisFeatureQueries::featuresAt(list, QPoint(160, 20))), QStringList({"Sky", "Moon"}));
    QCOMPARE(names(KisFeatureQueries::featuresAt(list, QPoint(25, 45))), QStringList({"Sky", "Tower"}));
    QCOMPARE(names(KisFeatureQueries::featuresAt(list, QPoint(25, 60))), QStringList({"Ground", "Tower"}));
    QCOMPARE(names(KisFeatureQueries::featuresAt(list, QPoint(105, 105))), QStringList({"Ground", "Soft"})); // faint counts
    QVERIFY(KisFeatureQueries::featuresAt(list, QPoint(-5, -5)).isEmpty());
    QVERIFY(KisFeatureQueries::featuresAt(list, QPoint(5000, 5000)).isEmpty());

    QCOMPARE(names(KisFeatureQueries::featuresOverlapping(list, QRect(145, 5, 10, 10), f.image->bounds())), QStringList({"Sky", "Moon"}));
    QVERIFY(KisFeatureQueries::featuresOverlapping(list, QRect(), f.image->bounds()).isEmpty());
    QVERIFY(KisFeatureQueries::featuresOverlapping(list, QRect(1000, 1000, 5, 5), f.image->bounds()).isEmpty());
    // A huge rectangle is cut to the image, without overflow.
    QCOMPARE(KisFeatureQueries::featuresOverlapping(list, QRect(-2000000000, -2000000000, 2000000000, 2000000000), f.image->bounds()).size(), 0);
    QCOMPARE(KisFeatureQueries::featuresOverlapping(list, QRect(-2000000000, -2000000000, std::numeric_limits<int>::max(), std::numeric_limits<int>::max()),
                                                    f.image->bounds()).size(), 5);

    QCOMPARE(names(KisFeatureQueries::featuresOverlapping(list, tower)), QStringList({"Sky", "Ground"}));
    QCOMPARE(names(KisFeatureQueries::featuresOverlapping(list, moon)), QStringList({"Sky"}));
    QVERIFY(KisFeatureQueries::featuresOverlapping(list, empty).isEmpty());

    KisSelectionSP box = newSelection(f.image);
    box->pixelSelection()->select(QRect(100, 95, 20, 10), MAX_SELECTED);
    QCOMPARE(names(KisFeatureQueries::featuresOverlapping(list, box->pixelSelection(), f.image->bounds())), QStringList({"Ground", "Soft"}));
    // Bounds overlap but the pixels do not: an L-shaped feature and a box in its corner.
    KisPixelSelectionSP ell = maskWith(QRect(0, 0, 80, 10));
    ell->select(QRect(0, 0, 10, 80), MAX_SELECTED);
    KisFeatureSP ellFeature = new KisFeature("Ell", "x", ell);
    ellFeature->measure();
    list->insertFeature(ellFeature);
    QVERIFY(!names(KisFeatureQueries::featuresOverlapping(list, QRect(40, 40, 20, 20), f.image->bounds())).contains("Ell"));
    QVERIFY(names(KisFeatureQueries::featuresOverlapping(list, QRect(5, 40, 20, 20), f.image->bounds())).contains("Ell"));

    // Touching: sky and ground meet along y 49/50; the moon is inside the sky.
    QCOMPARE(names(KisFeatureQueries::featuresTouching(list, sky)), QStringList({"Ground"}));
    QVERIFY(KisFeatureQueries::featuresTouching(list, moon).isEmpty());   // inside sky: overlapping, not touching
    QVERIFY(KisFeatureQueries::featuresTouching(list, empty).isEmpty());
    Q_UNUSED(soft);
    Q_UNUSED(ground);
}

void KisFeatureProtectionTest::testTouchingTolerance()
{
    Fixture f;
    KisFeatureSP a = f.add("A", QRect(0, 0, 50, 50), false);
    KisFeatureSP b = f.add("B", QRect(50, 0, 50, 50), false);        // adjacent to A
    KisFeatureSP c = f.add("C", QRect(101, 0, 10, 50), false);       // one empty column (x = 100) after B
    KisFeatureSP d = f.add("D", QRect(113, 0, 10, 50), false);       // two empty columns after C
    KisFeatureSP e = f.add("E", QRect(0, 51, 10, 10), false);        // one empty row below A
    KisFeatureSP g = f.add("G", QRect(50, 50, 5, 5), false);         // diagonal to A, below B
    KisFeatureSP overlapA = f.add("OverlapsA", QRect(40, 40, 20, 20), false);
    KisFeatureSP far = f.add("Far", QRect(0, 120, 5, 5), false);
    KisFeatureList *list = f.list();

    QVERIFY(KisFeatureQueries::touch(a, b));
    QVERIFY(KisFeatureQueries::touch(b, a));
    QVERIFY(KisFeatureQueries::touch(b, c));          // a gap of one pixel
    QVERIFY(!KisFeatureQueries::touch(c, d));         // a gap of two pixels
    QVERIFY(KisFeatureQueries::touch(a, e));
    QVERIFY(KisFeatureQueries::touch(a, g));          // diagonal
    QVERIFY(!KisFeatureQueries::touch(a, overlapA));  // overlapping is not touching
    QVERIFY(!KisFeatureQueries::touch(a, far));
    QVERIFY(!KisFeatureQueries::touch(a, a));
    QVERIFY(!KisFeatureQueries::touch(a, KisFeatureSP()));
    QCOMPARE(names(KisFeatureQueries::featuresTouching(list, c)), QStringList({"B"}));
    QCOMPARE(names(KisFeatureQueries::featuresTouching(list, a)), QStringList({"B", "E", "G"}));
    Q_UNUSED(d);
}

void KisFeatureProtectionTest::testExpressionGrammar()
{
    Fixture f;
    f.add("Sky", QRect(0, 0, 200, 60), false);
    f.add("Moon", QRect(150, 10, 20, 20), false);
    f.add("Cloud", QRect(20, 10, 40, 20), false);
    f.add("Tower 3", QRect(100, 40, 20, 100), false);
    f.add("Tower (north)", QRect(10, 100, 20, 40), false);
    f.add("A - B", QRect(60, 100, 20, 40), false);
    f.add("Sky-2", QRect(170, 100, 20, 40), false);
    f.add("A+B", QRect(140, 100, 20, 40), false);
    f.add("Say \"hi\"", QRect(0, 140, 10, 10), false);
    f.add("Ünïcode", QRect(190, 140, 10, 10), false);
    const QRect bounds = f.image->bounds();
    KisFeatureList *list = f.list();

    auto select = [&](const QString &expression, QString *error = nullptr) {
        return KisFeatureQueries::selectionFromExpression(list, expression, bounds, error);
    };
    auto at = [&](KisPixelSelectionSP mask, int x, int y) { return f.maskAt(mask, x, y); };

    KisPixelSelectionSP m = select("Sky - Moon");
    QVERIFY(m);
    QCOMPARE(at(m, 10, 5), quint8(255));
    QCOMPARE(at(m, 160, 20), quint8(0));
    QCOMPARE(at(m, 10, 80), quint8(0));

    m = select("Sky + Tower 3");
    QCOMPARE(at(m, 110, 130), quint8(255));
    QCOMPARE(at(m, 10, 5), quint8(255));
    m = select("Sky & Tower 3");
    QCOMPARE(at(m, 110, 50), quint8(255));
    QCOMPARE(at(m, 110, 130), quint8(0));
    QCOMPARE(at(m, 10, 5), quint8(0));

    // Left to right, no precedence: (Sky - Moon) + Moon is the sky again.
    m = select("Sky - Moon + Moon");
    QCOMPARE(at(m, 160, 20), quint8(255));
    m = select("Sky - (Moon + Cloud)");
    QCOMPARE(at(m, 160, 20), quint8(0));
    QCOMPARE(at(m, 30, 20), quint8(0));
    QCOMPARE(at(m, 90, 20), quint8(255));
    m = select("(Sky + Tower 3) & (Moon + Tower 3)");
    QCOMPARE(at(m, 160, 20), quint8(255));
    QCOMPARE(at(m, 110, 90), quint8(255));
    QCOMPARE(at(m, 90, 20), quint8(0));

    // Spaces around, between, and inside names.
    m = select("  Sky    -    Moon  ");
    QCOMPARE(at(m, 160, 20), quint8(0));
    QCOMPARE(at(m, 10, 5), quint8(255));
    m = select("Tower 3");
    QCOMPARE(at(m, 110, 90), quint8(255));
    m = select("(Tower 3)");
    QCOMPARE(at(m, 110, 90), quint8(255));
    m = select("((Tower 3))");
    QCOMPARE(at(m, 110, 90), quint8(255));

    // Operator characters without spaces on both sides are part of a name.
    m = select("Sky-2");
    QCOMPARE(at(m, 175, 120), quint8(255));
    m = select("A+B");
    QCOMPARE(at(m, 145, 120), quint8(255));
    m = select("Sky-2 + A+B");
    QCOMPARE(at(m, 175, 120), quint8(255));
    QCOMPARE(at(m, 145, 120), quint8(255));

    // Quoted names: parentheses, operators and quotes inside.
    m = select("\"Tower (north)\"");
    QCOMPARE(at(m, 15, 120), quint8(255));
    m = select("\"A - B\" + \"Tower (north)\"");
    QCOMPARE(at(m, 65, 120), quint8(255));
    QCOMPARE(at(m, 15, 120), quint8(255));
    m = select("\"Say \\\"hi\\\"\"");
    QCOMPARE(at(m, 5, 145), quint8(255));
    m = select("Ünïcode");
    QCOMPARE(at(m, 195, 145), quint8(255));
    m = select("Sky - \"Moon\"");
    QCOMPARE(at(m, 160, 20), quint8(0));

    // Results are masks of their own, cut to the document.
    QVERIFY(m->defaultPixel().data()[0] == 0);
    QCOMPARE(m->selectedExactRect().bottom(), 59);
}

void KisFeatureProtectionTest::testExpressionErrorsAndLimits()
{
    Fixture f;
    f.add("Sky", QRect(0, 0, 200, 60), false);
    f.add("Moon", QRect(150, 10, 20, 20), false);
    const QRect bounds = f.image->bounds();
    KisFeatureList *list = f.list();

    auto fails = [&](const QString &expression, const QString &why) {
        QString error;
        KisPixelSelectionSP mask = KisFeatureQueries::selectionFromExpression(list, expression, bounds, &error);
        if (mask) return QString("accepted \"%1\"").arg(expression);
        if (!error.contains(why)) return QString("\"%1\" failed with \"%2\", expected \"%3\"").arg(expression, error, why);
        return QString();
    };
    QCOMPARE(fails("Sky - Sun", "no feature called \"Sun\""), QString());
    QCOMPARE(fails("", "empty"), QString());
    QCOMPARE(fails("   ", "empty"), QString());
    QCOMPARE(fails("Sky -", "operator at the end"), QString());     // an operator with nothing after it
    QCOMPARE(fails("(Sky +)", "operator at the end"), QString());
    QCOMPARE(fails("Sky - ", "missing"), QString());
    QCOMPARE(fails("Sky -Moon", "no feature called"), QString());   // no space after the operator: one name
    QCOMPARE(fails("Sky - Moon)", "unexpected"), QString());
    QCOMPARE(fails("(Sky - Moon", "closing parenthesis"), QString());
    QCOMPARE(fails("Sky - (Moon", "closing parenthesis"), QString());
    QCOMPARE(fails("()", "missing"), QString());
    QCOMPARE(fails("Sky Moon", "no feature called"), QString());
    QCOMPARE(fails("Sky - Moon (x)", "double quotes"), QString());
    QCOMPARE(fails("Sky - \"Moon", "closing quote"), QString());
    QCOMPARE(fails("\"\"", "empty"), QString());
    QCOMPARE(fails("\"Sky\"+\"Moon\"", "with a space on each side"), QString());
    QCOMPARE(fails("\"Sky\" \"Moon\"", "expected"), QString());
    QCOMPARE(fails("Sky * Moon", "no feature called"), QString());
    QCOMPARE(fails("Sky - Moon - ", "missing"), QString());

    // Limits: length, terms, nesting.
    QCOMPARE(fails(QString("Sky") + QString(2100, ' '), "characters"), QString());
    QStringList many;
    for (int i = 0; i < KisFeatureQueries::kMaxExpressionTerms + 1; i++) many << "Sky";
    QCOMPARE(fails(many.join(" + "), "more than"), QString());
    QStringList enough;
    for (int i = 0; i < KisFeatureQueries::kMaxExpressionTerms; i++) enough << "Sky";
    QVERIFY(KisFeatureQueries::selectionFromExpression(list, enough.join(" + "), bounds, nullptr));
    QString deep = "Sky";
    for (int i = 0; i < KisFeatureQueries::kMaxExpressionDepth + 1; i++) deep = "(" + deep + ")";
    QCOMPARE(fails(deep, "nested deeper"), QString());
    QString fine = "Sky";
    for (int i = 0; i < KisFeatureQueries::kMaxExpressionDepth; i++) fine = "(" + fine + ")";
    QVERIFY(KisFeatureQueries::selectionFromExpression(list, fine, bounds, nullptr));
    // A null error pointer is fine.
    QVERIFY(!KisFeatureQueries::selectionFromExpression(list, "Nothing", bounds, nullptr));
}

void KisFeatureProtectionTest::testExpressionDoesNotChangeFeatures()
{
    Fixture f;
    KisFeatureSP sky = f.add("Sky", QRect(0, 0, 200, 60), false);
    KisFeatureSP moon = f.add("Moon", QRect(150, 10, 20, 20), false);
    const KisFeature::Properties skyBefore = sky->properties();
    const int revision = f.list()->revision();
    KisPixelSelectionSP result = KisFeatureQueries::selectionFromExpression(f.list(), "Sky - Moon", f.image->bounds(), nullptr);
    QVERIFY(result);
    QCOMPARE(f.maskAt(sky->mask(), 160, 20), quint8(255));    // the sky still has the moon's pixels
    QCOMPARE(f.maskAt(moon->mask(), 160, 20), quint8(255));
    QVERIFY(sky->properties() == skyBefore);
    QCOMPARE(f.list()->revision(), revision);
    // Changing the result later does not reach the feature either.
    result->select(QRect(0, 100, 10, 10), MAX_SELECTED);
    QCOMPARE(f.maskAt(sky->mask(), 5, 105), quint8(0));
    // A single name gives a copy, not the feature's own mask.
    KisPixelSelectionSP copy = KisFeatureQueries::selectionFromExpression(f.list(), "Sky", f.image->bounds(), nullptr);
    QVERIFY(copy != sky->mask());
    copy->select(QRect(0, 100, 10, 10), MAX_SELECTED);
    QCOMPARE(f.maskAt(sky->mask(), 5, 105), quint8(0));
}

void KisFeatureProtectionTest::testCanvasAlignment()
{
    Fixture f;
    f.add("Tower", QRect(10, 10, 20, 20), true);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, f.layer).isEmpty());

    // A transform mask shows the layer's pixels moved: protection cannot be exact.
    KisTransformMaskSP transform = new KisTransformMask(f.image, "transform");
    f.image->addNode(transform, f.layer);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, f.layer).contains("transform mask"));
    f.image->removeNode(transform);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, f.layer).isEmpty());

    // A clone shows the layer elsewhere; so does it show a group that holds the layer.
    KisGroupLayerSP group = new KisGroupLayer(f.image, "group", OPACITY_OPAQUE_U8);
    f.image->addNode(group);
    KisPaintLayerSP inner = new KisPaintLayer(f.image, "inner", OPACITY_OPAQUE_U8);
    f.image->addNode(inner, group);
    KisCloneLayerSP clone = new KisCloneLayer(group, f.image, "clone", OPACITY_OPAQUE_U8);
    f.image->addNode(clone);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, inner).contains("clone layer"));
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, group).contains("clone layer"));
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, f.layer).isEmpty());
    // A null node or image has nothing to say.
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(KisImageSP(), f.layer).isEmpty());
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, KisNodeSP()).isEmpty());
}

void KisFeatureProtectionTest::testCanvasAlignmentLooksUpTheAncestors()
{
    Fixture f;
    f.add("Tower", QRect(10, 10, 20, 20), true);
    // A layer inside a group that has a transform mask.
    KisGroupLayerSP group = new KisGroupLayer(f.image, "group", OPACITY_OPAQUE_U8);
    f.image->addNode(group);
    KisPaintLayerSP inner = new KisPaintLayer(f.image, "inner", OPACITY_OPAQUE_U8);
    f.image->addNode(inner, group);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, inner).isEmpty());
    KisTransformMaskSP onGroup = new KisTransformMask(f.image, "on group");
    f.image->addNode(onGroup, group);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, inner).contains("transform mask"));
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, group).contains("transform mask"));
    // A mask of a layer that has a transform mask.
    KisPaintLayerSP layer = new KisPaintLayer(f.image, "masked", OPACITY_OPAQUE_U8);
    f.image->addNode(layer);
    KisTransparencyMaskSP mask = new KisTransparencyMask(f.image, "mask");
    f.image->addNode(mask, layer);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, mask).isEmpty());
    KisTransformMaskSP onLayer = new KisTransformMask(f.image, "on layer");
    f.image->addNode(onLayer, layer);
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, mask).contains("transform mask"));
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, layer).contains("transform mask"));
    // The paint layer next to them is not affected.
    QVERIFY(KisFeatureProtection::whyNotCanvasAligned(f.image, f.layer).isEmpty());
}

void KisFeatureProtectionTest::testProtectionRevisionIgnoresWhatDoesNotChangeTheArea()
{
    Fixture f;
    KisFeatureSP tower = f.add("Tower", QRect(10, 10, 20, 20), true);
    KisPixelSelectionSP built = f.list()->protectedMask();
    const int all = f.list()->revision();
    const int area = f.list()->protectionRevision();
    // Rename, kind, state, author and a re-measure of properties leave the cached area alone.
    tower->setName("Tower 1");
    tower->setKind("tower");
    tower->setState(KisFeature::Proposed);
    tower->setAuthor(KisFeature::Artist);
    tower->setProperties(tower->properties());
    QVERIFY(f.list()->revision() != all);
    QCOMPARE(f.list()->protectionRevision(), area);
    QVERIFY(f.list()->protectedMask() == built);
    // The flag, a mask, an add, a remove and suspension rebuild it.
    tower->setProtected(false);
    QVERIFY(f.list()->protectionRevision() != area);
    tower->setProtected(true);
    int r = f.list()->protectionRevision();
    tower->setMask(maskWith(QRect(50, 10, 20, 20)));
    QVERIFY(f.list()->protectionRevision() != r);
    r = f.list()->protectionRevision();
    KisFeatureSP other = f.add("Other", QRect(100, 10, 10, 10), false);
    QVERIFY(f.list()->protectionRevision() != r);
    r = f.list()->protectionRevision();
    f.list()->removeFeature(other->id());
    QVERIFY(f.list()->protectionRevision() != r);
    r = f.list()->protectionRevision();
    f.list()->setProtectionSuspended(true);
    QVERIFY(f.list()->protectionRevision() != r);
    f.list()->setProtectionSuspended(false);
}

void KisFeatureProtectionTest::testClipPixelWriteRefusesShortOrAbsurdData()
{
    Fixture f;
    f.add("Tower", QRect(10, 10, 10, 10), true);
    KisPaintDeviceSP device = f.layer->paintDevice();
    const int pixelSize = device->colorSpace()->pixelSize();
    bool refused = false;
    // Data shorter than its rectangle is refused, and left alone.
    QByteArray shortData(10 * pixelSize, 1);
    KisFeatureProtection::clipPixelWrite(f.image, device, shortData, QRect(0, 0, 40, 40), &refused);
    QVERIFY(refused);
    QCOMPARE(shortData, QByteArray(10 * pixelSize, 1));
    // A rectangle of billions of pixels is refused without allocating for it.
    refused = false;
    QByteArray tiny(16, 0);
    KisFeatureProtection::clipPixelWrite(f.image, device, tiny, QRect(0, 0, 100000, 100000), &refused);
    QVERIFY(refused);
    // A good write is not refused.
    refused = true;
    QByteArray good(40 * 40 * pixelSize, 1);
    KisFeatureProtection::clipPixelWrite(f.image, device, good, QRect(0, 0, 40, 40), &refused);
    QVERIFY(!refused);
    // No protection: nothing is checked and nothing refused.
    Fixture none;
    refused = true;
    KisFeatureProtection::clipPixelWrite(none.image, none.layer->paintDevice(), shortData, QRect(0, 0, 40, 40), &refused);
    QVERIFY(!refused);
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisFeatureProtectionTest)
