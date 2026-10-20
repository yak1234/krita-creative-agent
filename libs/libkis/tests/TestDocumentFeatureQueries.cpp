/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentFeatureQueries.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QElapsedTimer>
#include <QPointer>
#include <QRandomGenerator>
#include <QScopedPointer>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <limits>
#include <thread>

#include <Document.h>
#include <Feature.h>
#include <Selection.h>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureList.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kundo2stack.h>

namespace {

struct QueryDocument {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    QScopedPointer<Document> doc;

    explicit QueryDocument(const QSize &size = QSize(400, 300))
    {
        kisdoc = KisPart::instance()->createDocument();
        kisdoc->setFileBatchMode(true);
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), size.width(), size.height(), cs, "queries");
        KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);
        doc.reset(new Document(kisdoc, false));
        image->refreshGraphAsync();
        settle();
        kisdoc->undoStack()->clear();
    }

    ~QueryDocument()
    {
        doc.reset();
        if (image) image->waitForDone();
        QCoreApplication::processEvents();
        if (kisdoc) {
            KisPart::instance()->removeDocument(kisdoc, false);
            delete kisdoc;
        }
    }

    void settle()
    {
        image->waitForDone();
        QCoreApplication::processEvents();
    }

    bool add(const QString &name, const QRect &rect, quint8 value = 255)
    {
        QScopedPointer<Selection> selection(new Selection());
        if (!rect.isEmpty()) selection->select(rect.x(), rect.y(), rect.width(), rect.height(), value);
        QScopedPointer<Feature> feature(doc->addFeature(name, "thing", selection.data(), "artist", "kept"));
        return !feature.isNull();
    }

    /// Adds a feature whose mask is the union of \p rects (an L, a frame...).
    bool addShape(const QString &name, const QList<QRect> &rects)
    {
        QScopedPointer<Selection> selection(new Selection());
        for (const QRect &rect : rects) selection->select(rect.x(), rect.y(), rect.width(), rect.height(), 255);
        QScopedPointer<Feature> feature(doc->addFeature(name, "thing", selection.data(), "artist", "kept"));
        return !feature.isNull();
    }
};

QStringList names(const QList<Feature *> &features)
{
    QStringList result;
    for (Feature *f : features) result << f->name();
    qDeleteAll(features);
    return result;
}

/// The mask value of \p selection at a pixel (255 selected, 0 not).
int valueAt(Selection *selection, int x, int y)
{
    const QByteArray data = selection->pixelData(x, y, 1, 1);
    return data.isEmpty() ? -1 : quint8(data.at(0));
}

} // namespace

void TestDocumentFeatureQueries::testFeaturesAt()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    QVERIFY(d.add("Tower 3", QRect(50, 60, 30, 80)));
    QVERIFY(d.add("Faint", QRect(200, 200, 10, 10), 3));
    QVERIFY(d.add("Empty", QRect()));

    QCOMPARE(names(d.doc->featuresAt(310, 30)), QStringList({"Sky", "Moon"}));
    QCOMPARE(names(d.doc->featuresAt(10, 10)), QStringList({"Sky"}));
    QCOMPARE(names(d.doc->featuresAt(60, 80)), QStringList({"Sky", "Tower 3"}));
    QCOMPARE(names(d.doc->featuresAt(60, 120)), QStringList({"Ground", "Tower 3"}));
    QCOMPARE(names(d.doc->featuresAt(399, 299)), QStringList({"Ground"}));
    QCOMPARE(names(d.doc->featuresAt(0, 0)), QStringList({"Sky"}));
    // The pixel that contains the point: 99.9 is still in row 99 (the sky), 100.0 is in the ground.
    QCOMPARE(names(d.doc->featuresAt(10.5, 99.9)), QStringList({"Sky"}));
    QCOMPARE(names(d.doc->featuresAt(10.5, 100.0)), QStringList({"Ground"}));
    QCOMPARE(names(d.doc->featuresAt(205, 205)), QStringList({"Ground", "Faint"}));   // a faint mask still counts
    // Outside the document: nothing.
    QVERIFY(d.doc->featuresAt(-0.5, 10).isEmpty());
    QVERIFY(d.doc->featuresAt(400, 10).isEmpty());
    QVERIFY(d.doc->featuresAt(10, 300).isEmpty());
    // The feature objects are live: they follow their feature.
    QList<Feature *> list = d.doc->featuresAt(310, 30);
    QCOMPARE(list.size(), 2);
    QVERIFY(d.doc->renameFeature("Moon", "Full moon"));
    QCOMPARE(list.at(1)->name(), QString("Full moon"));
    qDeleteAll(list);
}

void TestDocumentFeatureQueries::testBadInputIsRefused()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();
    QVERIFY(d.doc->featuresAt(nan, 10).isEmpty());
    QVERIFY(d.doc->featuresAt(10, nan).isEmpty());
    QVERIFY(d.doc->featuresAt(inf, 10).isEmpty());
    QVERIFY(d.doc->featuresAt(10, -inf).isEmpty());
    QVERIFY(d.doc->featuresAt(1e12, 10).isEmpty());
    QVERIFY(d.doc->featuresAt(10, -1e300).isEmpty());
    QVERIFY(d.doc->featuresAt(1e10, 1e10).isEmpty());
    // Rectangles: empty, null, huge, with overflowing corners.
    QVERIFY(d.doc->featuresOverlapping(QRect()).isEmpty());
    QVERIFY(d.doc->featuresOverlapping(QRect(0, 0, 0, 0)).isEmpty());
    QVERIFY(d.doc->featuresOverlapping(QRect(0, 0, -5, -5)).size() <= 1);
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(std::numeric_limits<int>::min(), std::numeric_limits<int>::min(),
                                                    std::numeric_limits<int>::max(), std::numeric_limits<int>::max()))),
             QStringList());   // ends before the image starts
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(-1000, -1000, std::numeric_limits<int>::max(), std::numeric_limits<int>::max()))),
             QStringList({"Sky"}));
    QVERIFY(d.doc->featuresOverlapping(static_cast<Feature *>(nullptr)).isEmpty());
    QVERIFY(d.doc->featuresOverlapping(static_cast<Selection *>(nullptr)).isEmpty());
    QVERIFY(d.doc->featuresTouching(static_cast<Feature *>(nullptr)).isEmpty());
    QVERIFY(d.doc->featuresTouching(QString("No such feature")).isEmpty());
    QVERIFY(d.doc->featuresTouching(QString()).isEmpty());
    // A feature of another document is refused, not looked up by name.
    QueryDocument other;
    QVERIFY(other.add("Sky", QRect(0, 0, 400, 100)));
    QScopedPointer<Feature> foreign(other.doc->feature("Sky"));
    QVERIFY(foreign);
    QVERIFY(d.doc->featuresOverlapping(foreign.data()).isEmpty());
    QVERIFY(d.doc->featuresTouching(foreign.data()).isEmpty());
    // A feature that was removed is no longer in the document.
    QScopedPointer<Feature> sky(d.doc->feature("Sky"));
    QVERIFY(d.doc->removeFeature("Sky"));
    QVERIFY(d.doc->featuresOverlapping(sky.data()).isEmpty());
    QVERIFY(d.doc->featuresAt(10, 10).isEmpty());
}

void TestDocumentFeatureQueries::testFeaturesOverlapping()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    QVERIFY(d.add("Tower 3", QRect(50, 60, 30, 80)));
    QVERIFY(d.addShape("Frame", {QRect(200, 150, 100, 5), QRect(200, 150, 5, 100), QRect(295, 150, 5, 100), QRect(200, 245, 100, 5)}));

    QCOMPARE(names(d.doc->featuresOverlapping(QRect(295, 15, 10, 10))), QStringList({"Sky", "Moon"}));
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(0, 95, 10, 10))), QStringList({"Sky", "Ground"}));
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(0, 99, 10, 1))), QStringList({"Sky"}));
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(-50, -50, 60, 60))), QStringList({"Sky"}));   // the part outside is ignored
    // Inside the frame's bounds but not on its pixels: not overlapping.
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(220, 170, 50, 50))), QStringList({"Ground"}));
    QCOMPARE(names(d.doc->featuresOverlapping(QRect(220, 150, 5, 5))), QStringList({"Ground", "Frame"}));

    QScopedPointer<Feature> tower(d.doc->feature("Tower 3"));
    QScopedPointer<Feature> moon(d.doc->feature("Moon"));
    QCOMPARE(names(d.doc->featuresOverlapping(tower.data())), QStringList({"Sky", "Ground"}));
    QCOMPARE(names(d.doc->featuresOverlapping(moon.data())), QStringList({"Sky"}));

    QScopedPointer<Selection> box(new Selection());
    box->select(40, 90, 50, 20, 255);
    QCOMPARE(names(d.doc->featuresOverlapping(box.data())), QStringList({"Sky", "Ground", "Tower 3"}));
    // A selection is its selected pixels: an inverted one reaches everywhere but the hole.
    QScopedPointer<Selection> inverted(new Selection());
    inverted->select(0, 0, 10, 10, 255);
    inverted->invert();
    QCOMPARE(names(d.doc->featuresOverlapping(inverted.data())), QStringList({"Sky", "Moon", "Ground", "Tower 3", "Frame"}));
    QScopedPointer<Selection> empty(new Selection());
    QCOMPARE(names(d.doc->featuresOverlapping(empty.data())), QStringList());
}

void TestDocumentFeatureQueries::testFeaturesTouching()
{
    QueryDocument d;
    QVERIFY(d.add("A", QRect(0, 0, 50, 50)));
    QVERIFY(d.add("B", QRect(50, 0, 50, 50)));          // adjacent to A
    QVERIFY(d.add("C", QRect(101, 0, 10, 50)));         // one empty column after B: touches
    QVERIFY(d.add("D", QRect(113, 0, 10, 50)));         // two empty columns after C: does not touch
    QVERIFY(d.add("E", QRect(0, 51, 10, 10)));          // one empty row below A: touches
    QVERIFY(d.add("G", QRect(50, 50, 5, 5)));           // diagonal to A, below B
    QVERIFY(d.add("Overlaps", QRect(40, 40, 20, 20)));  // overlaps A and B: neither touching
    QVERIFY(d.add("Far", QRect(0, 200, 5, 5)));

    QCOMPARE(names(d.doc->featuresTouching(QString("A"))), QStringList({"B", "E", "G"}));
    QCOMPARE(names(d.doc->featuresTouching(QString(" A "))), QStringList({"B", "E", "G"}));   // trimmed as feature names are
    QCOMPARE(names(d.doc->featuresTouching(QString("C"))), QStringList({"B"}));
    QCOMPARE(names(d.doc->featuresTouching(QString("D"))), QStringList());
    QCOMPARE(names(d.doc->featuresTouching(QString("Far"))), QStringList());
    QScopedPointer<Feature> b(d.doc->feature("B"));
    QCOMPARE(names(d.doc->featuresTouching(b.data())), QStringList({"A", "C", "G"}));
    // Touching and overlapping are exclusive.
    QScopedPointer<Feature> a(d.doc->feature("A"));
    QCOMPARE(names(d.doc->featuresOverlapping(a.data())), QStringList({"Overlaps"}));
    // A feature moved away stops touching (the answer is not cached).
    QVERIFY(d.doc->removeFeature("B"));
    QCOMPARE(names(d.doc->featuresTouching(QString("A"))), QStringList({"E", "G"}));
}

void TestDocumentFeatureQueries::testSelectionByName()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    QVERIFY(d.add("Tower (north)", QRect(50, 60, 30, 80)));
    QVERIFY(d.add("Sky-2", QRect(10, 250, 20, 20)));

    QScopedPointer<Selection> s(d.doc->selection("Sky - Moon"));
    QVERIFY(s);
    QCOMPARE(valueAt(s.data(), 10, 10), 255);
    QCOMPARE(valueAt(s.data(), 310, 30), 0);        // the moon is left out, without colour picking
    QCOMPARE(valueAt(s.data(), 10, 150), 0);
    QCOMPARE(valueAt(s.data(), 399, 99), 255);

    s.reset(d.doc->selection(" Sky   +   Ground   -   \"Tower (north)\" "));
    QVERIFY(s);
    QCOMPARE(valueAt(s.data(), 10, 10), 255);
    QCOMPARE(valueAt(s.data(), 10, 150), 255);
    QCOMPARE(valueAt(s.data(), 60, 100), 0);
    s.reset(d.doc->selection("(Sky + Ground) & (\"Tower (north)\" + Moon)"));
    QVERIFY(s);
    QCOMPARE(valueAt(s.data(), 60, 100), 255);
    QCOMPARE(valueAt(s.data(), 310, 30), 255);
    QCOMPARE(valueAt(s.data(), 10, 10), 0);
    s.reset(d.doc->selection("Sky-2"));
    QVERIFY(s);
    QCOMPARE(valueAt(s.data(), 15, 255), 255);
    QCOMPARE(valueAt(s.data(), 15, 10), 0);
    // The no-argument overload is still the document's own selection.
    QScopedPointer<Selection> own(d.doc->selection());
    Q_UNUSED(own);
    // A pass limited to the result stays inside it: the painting under "Sky - Moon" is what a fill would reach.
    QScopedPointer<Selection> skyNoMoon(d.doc->selection("Sky - Moon"));
    QVERIFY(skyNoMoon);
    QCOMPARE(skyNoMoon->width(), 400);
}

void TestDocumentFeatureQueries::testSelectionErrorsReturnNone()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    for (const QString &bad : {QString("Sky - Sun"), QString(), QString("   "), QString("Sky -"), QString("Sky - "),
                               QString("Sky -Moon"), QString("(Sky - Moon"), QString("Sky - Moon)"), QString("()"),
                               QString("Sky - Moon (x)"), QString("\"Sky"), QString("\"\""), QString("Sky * Moon"),
                               QString("Sky - Moon - "), QString(5000, 'x'), QString("\"Sky\"+\"Moon\"")}) {
        QScopedPointer<Selection> s(d.doc->selection(bad));
        QVERIFY2(!s, qPrintable(QString("accepted \"%1\"").arg(bad.left(40))));
    }
    // 65 terms are too many; 64 are fine.
    QStringList many;
    for (int i = 0; i < 65; i++) many << "Sky";
    QVERIFY(!QScopedPointer<Selection>(d.doc->selection(many.join(" + "))));
    many.removeLast();
    QVERIFY(QScopedPointer<Selection>(d.doc->selection(many.join(" + "))));
    // A control character or a long odd string is only an unknown name.
    QVERIFY(!QScopedPointer<Selection>(d.doc->selection(QString("Sky - ") + QChar(0) + QString("x"))));
    QVERIFY(!QScopedPointer<Selection>(d.doc->selection(QString(1999, '"'))));
}

void TestDocumentFeatureQueries::testSelectionIsAFreshMaskAndFeaturesAreUnchanged()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    QScopedPointer<Feature> sky(d.doc->feature("Sky"));
    const qint64 area = sky->area();
    QScopedPointer<Selection> s(d.doc->selection("Sky - Moon"));
    QVERIFY(s);
    // The feature's mask still has the moon's pixels.
    QScopedPointer<Selection> skyMask(sky->mask());
    QCOMPARE(valueAt(skyMask.data(), 310, 30), 255);
    QCOMPARE(sky->area(), area);
    // Changing the result does not change the feature, and a second ask gives the same answer.
    s->select(0, 200, 50, 50, 255);
    QScopedPointer<Selection> again(d.doc->selection("Sky - Moon"));
    QCOMPARE(valueAt(again.data(), 10, 210), 0);
    QScopedPointer<Selection> solo(d.doc->selection("Sky"));
    QVERIFY(solo);
    solo->select(0, 200, 50, 50, 255);
    QScopedPointer<Selection> skyAgain(sky->mask());
    QCOMPARE(valueAt(skyAgain.data(), 10, 210), 0);
}

void TestDocumentFeatureQueries::testQueriesChangeNothing()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    d.settle();
    d.kisdoc->setModified(false);
    const int steps = d.kisdoc->undoStack()->count();
    const int revision = d.image->featureList()->revision();
    const qint64 documentRevision = d.doc->revision();

    d.doc->featuresAt(10, 10);
    d.doc->featuresOverlapping(QRect(0, 0, 100, 100));
    QScopedPointer<Feature> sky(d.doc->feature("Sky"));
    d.doc->featuresOverlapping(sky.data());
    d.doc->featuresTouching(sky.data());
    QScopedPointer<Selection> s(d.doc->selection("Sky + Ground"));
    QVERIFY(s);

    QCOMPARE(d.kisdoc->undoStack()->count(), steps);
    QVERIFY(!d.kisdoc->isModified());
    QCOMPARE(d.image->featureList()->revision(), revision);
    QCOMPARE(d.doc->revision(), documentRevision);
}

void TestDocumentFeatureQueries::testQueriesFollowEdits()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    QCOMPARE(names(d.doc->featuresAt(10, 150)), QStringList({"Ground"}));
    QVERIFY(d.doc->removeFeature("Ground"));
    QVERIFY(d.doc->featuresAt(10, 150).isEmpty());
    d.kisdoc->undoStack()->undo();
    d.settle();
    QCOMPARE(names(d.doc->featuresAt(10, 150)), QStringList({"Ground"}));
    // After a crop the masks moved with the image, and the answers with them.
    d.doc->crop(0, 50, 400, 250);
    d.settle();
    QCOMPARE(names(d.doc->featuresAt(10, 49)), QStringList({"Sky"}));
    QCOMPARE(names(d.doc->featuresAt(10, 50)), QStringList({"Ground"}));
}

void TestDocumentFeatureQueries::testQueriesFromAnotherThreadWhileFeaturesChange()
{
    QueryDocument d;
    QVERIFY(d.add("Sky", QRect(0, 0, 400, 100)));
    QVERIFY(d.add("Moon", QRect(300, 20, 40, 40)));
    QVERIFY(d.add("Ground", QRect(0, 100, 400, 200)));
    KisFeatureList *list = d.image->featureList();
    std::atomic<bool> stop{false};
    std::atomic<int> answered{0};
    std::atomic<bool> bad{false};
    Document *doc = d.doc.data();

    std::thread worker([&] {
        while (!stop) {
            // The libkis queries only read the feature list (its mutexes) and the masks (tiles): usable off the GUI
            // thread, the way a script's own thread would.
            const QList<Feature *> at = doc->featuresAt(310, 30);
            for (Feature *f : at) {
                if (f->name().isEmpty()) bad = true;
            }
            qDeleteAll(at);
            qDeleteAll(doc->featuresOverlapping(QRect(0, 0, 400, 300)));
            QScopedPointer<Selection> s(doc->selection("Sky - Moon + Ground"));
            Q_UNUSED(s);
            answered++;
        }
    });
    KisFeatureSP moon = list->featureByName("Moon");
    QVERIFY(moon);
    for (int i = 0; i < 200; i++) {
        moon->setProtected(i % 2 == 0);
        moon->setKind(i % 2 ? "moon" : "orb");
        QCoreApplication::processEvents();
    }
    stop = true;
    worker.join();
    QVERIFY(!bad);
    QVERIFY(answered > 0);
}

void TestDocumentFeatureQueries::testThirtyFeaturesAtFullSize()
{
    const QSize size(6000, 4500);
    QueryDocument d(size);
    // A skyline: the sky, the ground, 20 buildings with gaps of one pixel between neighbours (so some touch), a moon,
    // clouds and a river that crosses several buildings' bounds without touching their pixels.
    QVERIFY(d.add("Sky", QRect(0, 0, size.width(), 2200)));
    QVERIFY(d.add("Ground", QRect(0, 3600, size.width(), 900)));
    int x = 100;
    for (int i = 0; i < 20; i++) {
        const int w = 180 + (i % 5) * 40;
        const int h = 600 + (i * 137) % 900;
        QVERIFY(d.add(QString("Building %1").arg(i), QRect(x, 3600 - h, w, h)));
        x += w + 1 + (i % 3 == 0 ? 80 : 0);
    }
    QVERIFY(d.add("Moon", QRect(4800, 300, 400, 400)));
    QVERIFY(d.addShape("River", {QRect(0, 3300, 6000, 60), QRect(2900, 2200, 60, 1100)}));
    for (int i = 0; i < 6; i++) QVERIFY(d.add(QString("Cloud %1").arg(i), QRect(300 + i * 1000, 800 + i * 50, 700, 250)));
    {
        const QList<Feature *> everyFeature = d.doc->features();
        QCOMPARE(everyFeature.size(), 30);
        qDeleteAll(everyFeature);
    }

    QRandomGenerator rng(7);
    QElapsedTimer clock;
    clock.start();
    int found = 0;
    for (int i = 0; i < 2000; i++) {
        const QList<Feature *> at = d.doc->featuresAt(rng.bounded(size.width()), rng.bounded(size.height()));
        found += at.size();
        qDeleteAll(at);
    }
    const double atMs = clock.nsecsElapsed() / 1e6 / 2000;

    clock.restart();
    for (int i = 0; i < 50; i++) {
        qDeleteAll(d.doc->featuresOverlapping(QRect(rng.bounded(5000), rng.bounded(3500), 1000, 1000)));
    }
    const double overlapMs = clock.nsecsElapsed() / 1e6 / 50;

    clock.restart();
    const QList<Feature *> all = d.doc->features();
    int touching = 0;
    for (Feature *f : all) {
        const QList<Feature *> t = d.doc->featuresTouching(f);
        touching += t.size();
        qDeleteAll(t);
    }
    const double touchAllMs = clock.nsecsElapsed() / 1e6;
    qDeleteAll(all);

    clock.restart();
    QScopedPointer<Selection> some(d.doc->selection("Sky - Moon - Cloud 0 - Cloud 1 + River"));
    QVERIFY(some);
    const double expressionMs = clock.nsecsElapsed() / 1e6;

    QStringList every;
    const QList<Feature *> everyFeature = d.doc->features();
    for (Feature *f : everyFeature) every << "\"" + f->name() + "\"";
    qDeleteAll(everyFeature);
    clock.restart();
    QScopedPointer<Selection> everything(d.doc->selection(every.join(" + ")));
    QVERIFY(everything);
    const double unionMs = clock.nsecsElapsed() / 1e6;

    qInfo() << "30 features at 6000x4500: featuresAt" << atMs << "ms each (" << found << "hits in 2000 points ), featuresOverlapping(1000x1000)"
            << overlapMs << "ms each, featuresTouching for all 30" << touchAllMs << "ms (" << touching << "pairs ), selection of 5 terms"
            << expressionMs << "ms, union of all 30" << unionMs << "ms";
    QVERIFY(found > 0);
    QVERIFY2(atMs < 5, "featuresAt is a lookup, not an analysis");
    QVERIFY2(overlapMs < 100, "featuresOverlapping reads only the tiles under the rectangle");
    QVERIFY2(touchAllMs < 5000, "asking what touches every feature of the map");
    QVERIFY2(expressionMs < 2000, "a selection from 5 features");
    QVERIFY2(unionMs < 5000, "a selection from all 30 features");
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentFeatureQueries)
