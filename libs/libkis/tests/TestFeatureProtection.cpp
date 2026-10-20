/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestFeatureProtection.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QElapsedTimer>
#include <QPointer>
#include <QRandomGenerator>
#include <QScopedPointer>
#include <QSet>
#include <QSemaphore>
#include <QAtomicInt>
#include <QTemporaryDir>

#include <algorithm>
#include <cstring>
#include <functional>
#include <limits>

#include "KritaTransformMaskStubs.h"

#include <Channel.h>
#include <Document.h>
#include <Feature.h>
#include <Filter.h>
#include <Node.h>
#include <Selection.h>
#include <StrokeJob.h>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureList.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <brushengine/kis_paintop_preset.h>
#include <QClipboard>
#include <kis_clipboard.h>
#include <QGuiApplication>
#include <kis_clone_layer.h>
#include <kis_group_layer.h>
#include <KoColorProfile.h>
#include <KoColorSpace.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_painter.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>
#include <kis_simple_stroke_strategy.h>
#include <kis_transform_mask.h>
#include <kundo2stack.h>

namespace {

const QSize canvas(300, 200);

/// "Buildings": four rectangles of the skyline, one name each.
struct Building {
    const char *name;
    QRect rect;
};
const Building buildings[] = {
    {"Tower A", QRect(20, 60, 40, 120)},
    {"Tower B", QRect(90, 80, 50, 100)},
    {"Tower C", QRect(160, 40, 30, 140)},
    {"Tower D", QRect(210, 90, 60, 90)},
};

/**
 * A document registered with KisPart as Krita's own are (so scripts have an undo history), with an undo store, a white
 * "background", and two paint layers "paint" and "paint2" that hold grey where the buildings stand and nothing
 * elsewhere, so that "no pixel inside a building changed" compares real pixels.
 */
struct ProtectDocument {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisPaintLayerSP background, layer, layer2;
    QScopedPointer<Document> doc;
    QScopedPointer<Node> paint, paint2;

    explicit ProtectDocument(const QSize &size = canvas, bool withBuildings = true)
    {
        kisdoc = KisPart::instance()->createDocument();
        kisdoc->setFileBatchMode(true);
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), size.width(), size.height(), cs, "protect");
        background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        background->paintDevice()->fill(image->bounds(), KoColor(Qt::white, cs));
        image->addNode(background);
        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        image->addNode(layer);
        layer2 = new KisPaintLayer(image, "paint2", OPACITY_OPAQUE_U8);
        image->addNode(layer2);
        if (withBuildings) {
            for (const Building &b : buildings) {
                layer->paintDevice()->fill(b.rect, KoColor(Qt::gray, cs));
                layer2->paintDevice()->fill(b.rect, KoColor(Qt::darkGray, cs));
            }
        }
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);
        doc.reset(new Document(kisdoc, false));
        paint.reset(doc->nodeByName("paint"));
        paint2.reset(doc->nodeByName("paint2"));
        image->refreshGraphAsync();
        settle();
        kisdoc->undoStack()->clear();
        kisdoc->setModified(false);
    }

    ~ProtectDocument()
    {
        paint.reset();
        paint2.reset();
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
        for (int i = 0; i < 3; i++) {
            QCoreApplication::sendPostedEvents();
            QCoreApplication::processEvents();
        }
        image->waitForDone();
    }

    /// Adds the buildings as protected features.
    void protectBuildings(bool isProtected = true)
    {
        for (const Building &b : buildings) {
            addFeature(b.name, b.rect, isProtected);
        }
    }

    void addFeature(const QString &name, const QRect &rect, bool isProtected)
    {
        QScopedPointer<Selection> selection(new Selection());
        if (!rect.isEmpty()) selection->select(rect.x(), rect.y(), rect.width(), rect.height(), 255);
        QScopedPointer<Feature> feature(doc->addFeature(name, "building", selection.data(), "artist", "kept", isProtected));
        QVERIFY(feature);
    }

    QByteArray bytes(KisPaintLayerSP l, const QRect &rect) const
    {
        KisPaintDeviceSP device = l->paintDevice();
        QByteArray data(rect.width() * rect.height() * device->pixelSize(), 0);
        device->readBytes(reinterpret_cast<quint8 *>(data.data()), rect);
        return data;
    }

    QByteArray bytes(KisPaintLayerSP l) const { return bytes(l, image->bounds()); }

    /// The number of pixels in \p rect of \p l whose alpha is not zero.
    int opaquePixels(KisPaintLayerSP l, const QRect &rect) const
    {
        const QImage rgba = l->paintDevice()->convertToQImage(nullptr, rect.x(), rect.y(), rect.width(), rect.height());
        int count = 0;
        for (int y = 0; y < rgba.height(); y++) {
            for (int x = 0; x < rgba.width(); x++) count += qAlpha(rgba.pixel(x, y)) > 0 ? 1 : 0;
        }
        return count;
    }

    int undoSteps() const { return kisdoc->undoStack()->count(); }

    void undo()
    {
        kisdoc->undoStack()->undo();
        settle();
    }

    void redo()
    {
        kisdoc->undoStack()->redo();
        settle();
    }

    KisFeatureList *list() const { return image->featureList(); }
};

QString presetName(const QString &shown)
{
    for (const QString &name : {shown, QString(shown).replace(' ', '_')}) {
        KoResourceSP found = KisGlobalResourcesInterface::instance()->source(ResourceType::PaintOpPresets)
                                 .bestMatch(QString(), QString(), name);
        if (found && found->valid()) return name;
    }
    return QString();
}

QString brush()
{
    return presetName("b) Basic-5 Size");
}

QVariantMap line(double x0, double y0, double x1, double y1, double size, const QString &color = "#ff0000")
{
    return QVariantMap{{"points", QVariantList{QVariantList{x0, y0}, QVariantList{x1, y1}}}, {"size", size}, {"color", color}};
}

/// \p count horizontal strokes across the whole width, evenly spread over \p area's height.
QVariantList sweep(int count, const QRect &area, double size = 4)
{
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        const double y = area.top() + (double(i) + 0.5) * area.height() / count;
        strokes << line(area.left() + 1, y, area.right() - 1, y, size);
    }
    return strokes;
}

bool finish(StrokeJob *job, int ms = 30000)
{
    QElapsedTimer clock;
    clock.start();
    while (!job->wait(10)) {
        QCoreApplication::processEvents();
        if (clock.elapsed() > ms) return false;
    }
    QCoreApplication::processEvents();
    return true;
}

QStringList sorted(QStringList names)
{
    std::sort(names.begin(), names.end());
    return names;
}

QStringList allBuildings()
{
    QStringList names;
    for (const Building &b : buildings) names << b.name;
    return sorted(names);
}

struct GateState {
    QSemaphore open;
    QAtomicInt entered;
};

/// A stroke that holds Krita's stroke queue until released: work queued behind it waits.
class GateStroke : public KisSimpleStrokeStrategy
{
public:
    explicit GateStroke(QSharedPointer<GateState> state)
        : KisSimpleStrokeStrategy(QLatin1String("test-gate"))
        , m_state(state)
    {
        enableJob(JOB_INIT, true, KisStrokeJobData::BARRIER, KisStrokeJobData::EXCLUSIVE);
    }
    void initStrokeCallback() override
    {
        m_state->entered.ref();
        m_state->open.tryAcquire(1, 30000); // never hangs a test run
    }

private:
    QSharedPointer<GateState> m_state;
};

class Gate
{
public:
    explicit Gate(KisImageSP image)
        : m_state(new GateState())
    {
        KisStrokeId id = image->startStroke(new GateStroke(m_state));
        image->endStroke(id);
    }
    ~Gate() { release(); }
    void release()
    {
        if (m_released) return;
        m_released = true;
        m_state->open.release();
    }

private:
    QSharedPointer<GateState> m_state;
    bool m_released = false;
};

/// Whether \p l holds, inside \p rect, the same pixels as \p before (the bytes of the whole canvas).
bool sameIn(const ProtectDocument &d, KisPaintLayerSP l, const QByteArray &before, const QRect &rect)
{
    const int pixel = l->paintDevice()->pixelSize();
    const QByteArray now = d.bytes(l);
    const int width = d.image->width();
    for (int y = rect.top(); y <= rect.bottom(); y++) {
        const int offset = (y * width + rect.left()) * pixel;
        if (now.mid(offset, rect.width() * pixel) != before.mid(offset, rect.width() * pixel)) return false;
    }
    return true;
}

/**
 * Whether \p l holds, inside \p rect, the pixels it held before (the bytes of the whole canvas), allowing for the one
 * thing Krita's composite does through a selection: in a group of neighbouring destination pixels (the composite works
 * on several at once) that holds a selected pixel, a pixel whose selection is 0 and whose alpha is 0 can take the brush's
 * colour at alpha 0. Such a pixel is invisible; it lies at most \p reach pixels inside the left or right edge of \p rect.
 * Every other difference is a failure. \p noise gets the number of those pixels.
 */
bool sameExceptEdgeNoise(const ProtectDocument &d, KisPaintLayerSP l, const QByteArray &before, const QRect &rect,
                         int *noise = nullptr, int reach = 3)
{
    const int pixel = l->paintDevice()->pixelSize();
    const QByteArray now = d.bytes(l);
    const int width = d.image->width();
    int count = 0;
    for (int y = rect.top(); y <= rect.bottom(); y++) {
        for (int x = rect.left(); x <= rect.right(); x++) {
            const int at = (y * width + x) * pixel;
            const QByteArray a = now.mid(at, pixel), b = before.mid(at, pixel);
            if (a == b) continue;
            const bool invisible = a.at(pixel - 1) == 0 && b.at(pixel - 1) == 0;
            const bool atEdge = x - rect.left() < reach || rect.right() - x < reach;
            if (!invisible || !atEdge) return false;
            count++;
        }
    }
    if (noise) *noise = count;
    return true;
}

/// A layer with a block of grey, in the document, with its libkis node.
KisPaintLayerSP addLayer(ProtectDocument &d, const QString &name, const QRect &grey, KisNodeSP parent = KisNodeSP())
{
    KisPaintLayerSP layer = new KisPaintLayer(d.image, name, OPACITY_OPAQUE_U8);
    if (!grey.isEmpty()) layer->paintDevice()->fill(grey, KoColor(Qt::gray, layer->paintDevice()->colorSpace()));
    d.image->addNode(layer, parent ? parent : d.image->root());
    d.settle();
    return layer;
}

} // namespace

void TestFeatureProtection::initTestCase()
{
    // A transform mask asks the registry for its parameters' holder: the stubs provide one (without them it aborts).
    TestUtil::registerTransformMaskStubs();
}

void TestFeatureProtection::testWholeCanvasJobLeavesBuildingsAlone()
{
    const QString preset = brush();
    QVERIFY2(!preset.isEmpty(), "Krita's preset b) Basic-5 Size is in the resource database");
    ProtectDocument d;
    QVERIFY(d.paint);
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const int steps = d.undoSteps();

    // "Leave the buildings alone", then a pass over the whole canvas: no selection given.
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY2(job->state() != "failed", qPrintable(job->errorString()));
    QVERIFY(finish(job.data()));
    d.settle();
    QCOMPARE(job->state(), QString("done"));
    QCOMPARE(job->strokesDone(), 70);

    for (const Building &b : buildings) {
        QVERIFY2(sameIn(d, d.layer, before, b.rect), qPrintable(QString("pixels inside %1 changed").arg(b.name)));
    }
    // The painting outside did change: the sky, and the gaps between the buildings.
    QVERIFY(d.opaquePixels(d.layer, QRect(0, 0, 300, 35)) > 1000);
    QVERIFY(d.opaquePixels(d.layer, QRect(62, 60, 26, 120)) > 300);
    QVERIFY(d.opaquePixels(d.layer, QRect(270, 0, 30, 200)) > 300);

    // The result names every building it was kept out of, in the job's status and in the document.
    QCOMPARE(sorted(job->keptOut()), allBuildings());
    QCOMPARE(sorted(job->status().value("keptOut").toStringList()), allBuildings());
    QCOMPARE(sorted(d.doc->lastKeptOut()), allBuildings());
    QCOMPARE(sorted(d.doc->agentMoveKeptOut()), allBuildings());

    // One undo step restores everything.
    QCOMPARE(d.undoSteps(), steps + 1);
    d.undo();
    QCOMPARE(d.bytes(d.layer), before);
}

void TestFeatureProtection::testUnprotectingOrOverridingWritesInside()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const QVariantList strokes = sweep(70, QRect(QPoint(0, 0), canvas));

    // The option "allowProtected": a deliberate edit, written inside the buildings, naming nothing.
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}, {"allowProtected", true}}));
        QVERIFY(finish(job.data()));
        d.settle();
        QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
        QVERIFY(!sameIn(d, d.layer, before, buildings[2].rect));
        QVERIFY(job->keptOut().isEmpty());
        d.undo();
        QCOMPARE(d.bytes(d.layer), before);
    }
    // A wrong type for the option is refused whole.
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}, {"allowProtected", "yes"}}));
        QCOMPARE(job->state(), QString("failed"));
        QVERIFY(job->errorString().contains("allowProtected"));
    }
    // Lifting the protection of one feature: that one is written, the others are not.
    {
        QScopedPointer<Feature> a(d.doc->feature("Tower A"));
        QVERIFY(a);
        QVERIFY(a->setProtected(false));
        QVERIFY(!a->isProtected());
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        d.settle();
        QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
        QVERIFY(sameIn(d, d.layer, before, buildings[1].rect));
        QVERIFY(sameIn(d, d.layer, before, buildings[2].rect));
        QVERIFY(sameIn(d, d.layer, before, buildings[3].rect));
        QCOMPARE(sorted(job->keptOut()), sorted(QStringList({"Tower B", "Tower C", "Tower D"})));
        d.undo();
    }
    // Suspending protection lifts it for every feature, and ending it brings it back.
    {
        QVERIFY(d.doc->beginAgentMove("deliberate"));
        QVERIFY(d.doc->setProtectionSuspended(true));
        QVERIFY(d.doc->protectionSuspended());
        QVERIFY(!d.doc->protectionActive());
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        QVERIFY(d.doc->setProtectionSuspended(false));
        QVERIFY(d.doc->endAgentMove());
        d.settle();
        QVERIFY(!sameIn(d, d.layer, before, buildings[1].rect));
        d.undo();
        QCOMPARE(d.bytes(d.layer), before);
        QScopedPointer<StrokeJob> again(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(again.data()));
        d.settle();
        QVERIFY(sameIn(d, d.layer, before, buildings[1].rect));
    }
}

void TestFeatureProtection::testJobClipAndProtectionCombine()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);

    // A job limited to the left half: it paints there, outside the buildings, and nowhere else.
    QScopedPointer<Selection> left(new Selection());
    left->select(0, 0, 150, 200, 255);
    QScopedPointer<StrokeJob> job(
        d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}, left.data()));
    QVERIFY(finish(job.data()));
    d.settle();
    QVERIFY(d.opaquePixels(d.layer, QRect(62, 60, 26, 120)) > 300);                  // left of 150, between the towers
    QVERIFY(sameIn(d, d.layer, before, buildings[0].rect));
    QVERIFY(sameIn(d, d.layer, before, buildings[1].rect));
    QCOMPARE(d.opaquePixels(d.layer, QRect(152, 0, 148, 40)), 0);                 // outside the clip
    // Tower C (x 160..189) and D lie outside the clip, so the job never reached them: not named.
    QCOMPARE(sorted(job->keptOut()), sorted(QStringList({"Tower A", "Tower B"})));

    // The job's selection can be an inverted one (everything but a hole), and the buildings are still left alone.
    d.undo();
    QScopedPointer<Selection> inverted(new Selection());
    inverted->select(0, 0, 40, 40, 255);
    inverted->invert();
    QScopedPointer<StrokeJob> second(
        d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}, inverted.data()));
    QVERIFY(finish(second.data()));
    d.settle();
    for (const Building &b : buildings) QVERIFY(sameIn(d, d.layer, before, b.rect));
    QCOMPARE(d.opaquePixels(d.layer, QRect(0, 0, 38, 38)), 0);
    QVERIFY(d.opaquePixels(d.layer, QRect(62, 60, 26, 120)) > 300);
}

void TestFeatureProtection::testOtherLayersAndOffsetsAreProtectedToo()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    // paint2 is moved before anything is protected: its content, grey where the buildings were, now sits 13 px right
    // and 7 px down, in front of other parts of the canvas.
    QVERIFY(d.paint2->move(13, 7));
    d.settle();
    d.protectBuildings();
    const QByteArray before2 = d.bytes(d.layer2);

    QScopedPointer<StrokeJob> job(d.paint2->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
    QVERIFY(finish(job.data()));
    d.settle();
    // Where the moved layer is transparent inside a building, Krita's composite can colour pixels at alpha 0 at the
    // building's edge (see testEdgeNoiseIsInvisibleAndAtTheEdge); nothing else changes.
    for (const Building &b : buildings) QVERIFY2(sameExceptEdgeNoise(d, d.layer2, before2, b.rect), b.name);
    QVERIFY(d.opaquePixels(d.layer2, QRect(62, 60, 26, 120)) > 300);

    // A layer whose content was made elsewhere and carried to the canvas position: protection is by canvas position.
    // An empty layer moved by (13, 7) paints in canvas coordinates all the same.
    d.undo();
    KisPaintLayerSP third = new KisPaintLayer(d.image, "third", OPACITY_OPAQUE_U8);
    d.image->addNode(third);
    d.settle();
    QScopedPointer<Node> thirdNode(d.doc->nodeByName("third"));
    QVERIFY(thirdNode);
    QVERIFY(thirdNode->move(13, 7));
    d.settle();
    third->paintDevice()->fill(QRect(10, 70, 5, 5), KoColor(Qt::green, third->paintDevice()->colorSpace()));
    QScopedPointer<StrokeJob> offset(thirdNode->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
    QVERIFY(finish(offset.data()));
    d.settle();
    // No stroke pixel inside any building (the green patch at (10, 70) lies in no building).
    for (const Building &b : buildings) {
        QCOMPARE(d.opaquePixels(third, b.rect), 0);
    }
    QVERIFY(d.opaquePixels(third, QRect(62, 60, 26, 120)) > 300);
}

void TestFeatureProtection::testFeatureProtectedMidJobIsHonouredFromTheNextWindow()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d(canvas, false);
    d.addFeature("Late", QRect(100, 0, 50, 200), false);   // a feature, not protected yet
    QVERIFY(!d.list()->hasProtectedFeatures());
    KisFeatureSP late = d.list()->featureByName("Late");
    QVERIFY(late);

    // Krita's queue is held: the job's first window of strokes (32) is queued but cannot run.
    Gate gate(d.image);
    QVariantList strokes;
    for (int i = 0; i < 200; i++) strokes << line(2, i + 0.5, 298, i + 0.5, 2);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY2(job->state() != "failed", qPrintable(job->errorString()));
    // The feature is protected now, while the job runs.
    late->setProtected(true);
    gate.release();
    QVERIFY(finish(job.data()));
    d.settle();
    QCOMPARE(job->state(), QString("done"));

    // The first window (strokes 0..31, rows 0..31) was queued before: it may have painted inside the feature. Every
    // stroke queued afterwards kept out. So rows from 40 down are clean inside, and clean outside they are painted.
    QCOMPARE(d.opaquePixels(d.layer, QRect(100, 40, 50, 160)), 0);
    QVERIFY(d.opaquePixels(d.layer, QRect(0, 40, 98, 160)) > 5000);
    QVERIFY(d.opaquePixels(d.layer, QRect(152, 40, 146, 160)) > 5000);
    QVERIFY(d.opaquePixels(d.layer, QRect(100, 0, 50, 36)) <= 50 * 36);   // at most the first window
    QVERIFY(job->keptOut().contains("Late"));
}

void TestFeatureProtection::testFillGradientAndEncloseKeepOut()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const QStringList buildingNames = allBuildings();
    const QSet<QString> all(buildingNames.begin(), buildingNames.end());

    // Each tool is first run as a deliberate edit (so the test cannot pass for a tool that never reaches a
    // building), undone, and then run as the agent's.
    auto check = [&](const QString &what, const std::function<bool(bool)> &run) {
        qInfo() << "tool:" << what;
        fflush(stdout);
        fflush(stderr);
        qInfo() << "run allowed";
        fflush(stdout);
        QVERIFY2(run(true), qPrintable(what + " (allowProtected)"));
        qInfo() << "ran allowed";
        fflush(stdout);
        d.settle();
        bool changedInside = false;
        for (const Building &b : buildings) changedInside |= !sameIn(d, d.layer, before, b.rect);
        QVERIFY2(changedInside, qPrintable(what + " must reach the buildings when allowed"));
        QVERIFY(d.doc->lastKeptOut().isEmpty());
        d.undo();
        QCOMPARE(d.bytes(d.layer), before);

        qInfo() << "run protected";
        fflush(stdout);
        QVERIFY2(run(false), qPrintable(what));
        qInfo() << "ran protected";
        fflush(stdout);
        d.settle();
        for (const Building &b : buildings) {
            QVERIFY2(sameIn(d, d.layer, before, b.rect), qPrintable(QString("%1: pixels inside %2 changed").arg(what, b.name)));
        }
        QVERIFY2(d.bytes(d.layer) != before, qPrintable(what + " must still paint outside"));
        const QStringList kept = d.doc->lastKeptOut();
        QVERIFY2(QSet<QString>(kept.begin(), kept.end()) == all, qPrintable(what + " names " + kept.join(",")));
        d.undo();
        QCOMPARE(d.bytes(d.layer), before);
    };

    check("fill whole layer", [&](bool allow) {
        QVariantMap options{{"mode", "selection"}};
        if (allow) options.insert("allowProtected", true);
        return d.paint->fill(5, 5, QColor(Qt::red), options);
    });
    check("gradient", [&](bool allow) {
        QVariantMap options{{"colors", QVariantList{"#ff0000", "#0000ff"}}};
        if (allow) options.insert("allowProtected", true);
        return d.paint->gradient(QPointF(0, 0), QPointF(300, 0), options);
    });
    check("contiguous fill of the sky", [&](bool allow) {
        // The transparent sky and the gaps are one region around the grey buildings; a loose threshold floods into
        // the grey too (transparent against grey is not "similar", so raise it to the top).
        QVariantMap options{{"threshold", 100}};
        if (allow) options.insert("allowProtected", true);
        return d.paint->fill(5, 5, QColor(Qt::red), options);
    });
    check("enclose and fill", [&](bool allow) {
        QScopedPointer<Selection> area(new Selection());
        area->select(10, 30, 270, 160, 255);
        QVariantMap options{{"regions", "all"}, {"includeContourRegions", true}, {"threshold", 100}};
        if (allow) options.insert("allowProtected", true);
        return d.paint->encloseAndFill(area.data(), QColor(Qt::red), options);
    });
    // A fill limited by a selection keeps both limits.
    {
        QScopedPointer<Selection> left(new Selection());
        left->select(0, 0, 100, 200, 255);
        QVERIFY(d.paint->fill(5, 5, QColor(Qt::red), {{"mode", "selection"}}, left.data()));
        d.settle();
        for (const Building &b : buildings) QVERIFY(sameIn(d, d.layer, before, b.rect));
        QVERIFY(d.opaquePixels(d.layer, QRect(62, 0, 28, 200)) > 4000);
        QCOMPARE(d.opaquePixels(d.layer, QRect(160, 0, 140, 40)), 0);
        QCOMPARE(sorted(d.doc->lastKeptOut()), sorted(QStringList({"Tower A", "Tower B"})));
        d.undo();
    }
}

void TestFeatureProtection::testSmartPatchKeepsOut()
{
    ProtectDocument d;
    // A plain background to patch from: opaque light colour everywhere but the buildings.
    const KoColorSpace *cs = d.image->colorSpace();
    d.layer->paintDevice()->fill(QRect(0, 0, 300, 200), KoColor(QColor(200, 220, 255), cs));
    for (const Building &b : buildings) d.layer->paintDevice()->fill(b.rect, KoColor(Qt::gray, cs));
    d.protectBuildings();
    d.settle();
    const QByteArray before = d.bytes(d.layer);

    // An area across the gap and into Tower A and Tower B, marked on the layer with a stripe of another colour.
    const QRect patch(50, 100, 60, 30);
    KisPaintDeviceSP device = d.layer->paintDevice();
    device->fill(QRect(62, 100, 26, 30), KoColor(Qt::red, cs));
    d.settle();
    const QByteArray marked = d.bytes(d.layer);
    QScopedPointer<Selection> area(new Selection());
    area->select(patch.x(), patch.y(), patch.width(), patch.height(), 255);
    QVERIFY(d.paint->smartPatch(area.data(), {{"allowProtected", true}}));
    d.settle();
    QVERIFY2(d.bytes(d.layer) != marked, "the patch changes something when allowed");
    d.undo();
    QCOMPARE(d.bytes(d.layer), marked);

    QVERIFY(d.paint->smartPatch(area.data()));
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, marked, b.rect), b.name);
    QVERIFY(!sameIn(d, d.layer, marked, QRect(62, 100, 26, 30)));  // the stripe in the gap was patched
    QCOMPARE(sorted(d.doc->lastKeptOut()), sorted(QStringList({"Tower A", "Tower B"})));
    d.undo();
    Q_UNUSED(before);
}

void TestFeatureProtection::testMoveUnderProtectedPixelsIsRefused()
{
    ProtectDocument d;
    d.protectBuildings();
    const int steps = d.undoSteps();
    // paint holds grey where the buildings stand: moving it moves pixels out of protected features.
    QVERIFY(!d.paint->move(5, 0));
    QCOMPARE(d.paint->position(), QPoint(0, 0));
    QCOMPARE(d.undoSteps(), steps);
    QVERIFY(!d.doc->lastKeptOut().isEmpty());
    QVERIFY(d.doc->lastKeptOut().contains("Tower A"));

    // A layer with pixels only where no building is can move, even across one.
    KisPaintLayerSP small = new KisPaintLayer(d.image, "small", OPACITY_OPAQUE_U8);
    small->paintDevice()->fill(QRect(0, 0, 10, 10), KoColor(Qt::green, small->paintDevice()->colorSpace()));
    d.image->addNode(small);
    d.settle();
    QScopedPointer<Node> smallNode(d.doc->nodeByName("small"));
    QVERIFY(smallNode);
    QVERIFY(smallNode->move(5, 5));                      // still clear of every building
    QVERIFY(!smallNode->move(25, 100));                  // would land on Tower A
    QCOMPARE(smallNode->position(), QPoint(5, 5));
    QVERIFY(smallNode->move(65, 100));                   // the gap between Tower A and Tower B
    QCOMPARE(smallNode->position(), QPoint(65, 100));
    QVERIFY(smallNode->move(5, 5));                      // away again

    // Suspending protection allows the move.
    QVERIFY(d.doc->beginAgentMove("deliberate move"));
    QVERIFY(d.doc->setProtectionSuspended(true));
    QVERIFY(d.paint->move(5, 0));
    QCOMPARE(d.paint->position(), QPoint(5, 0));
    QVERIFY(d.doc->endAgentMove());
}

void TestFeatureProtection::testSetPixelDataInAnAgentMove()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const int steps = d.undoSteps();
    const int pixel = d.layer->paintDevice()->pixelSize();
    QByteArray red(canvas.width() * canvas.height() * pixel, 0);
    KoColor color(Qt::red, d.image->colorSpace());
    for (int i = 0; i < canvas.width() * canvas.height(); i++) memcpy(red.data() + i * pixel, color.data(), pixel);

    QVERIFY(d.doc->beginAgentMove("paint it red"));
    QVERIFY(d.paint->setPixelData(red, 0, 0, canvas.width(), canvas.height()));
    QVERIFY(d.doc->endAgentMove());
    d.settle();

    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QCOMPARE(d.opaquePixels(d.layer, QRect(0, 0, 300, 40)), 300 * 40);
    QCOMPARE(d.opaquePixels(d.layer, QRect(62, 60, 26, 120)), 26 * 120);
    QCOMPARE(sorted(d.doc->agentMoveKeptOut()), allBuildings());
    QCOMPARE(sorted(d.doc->lastKeptOut()), allBuildings());
    QCOMPARE(d.undoSteps(), steps + 1);
    d.undo();
    QCOMPARE(d.bytes(d.layer), before);

    // A write that changes nothing inside a building names nothing: red only in the gap and the sky.
    QByteArray part = d.bytes(d.layer);
    QVERIFY(d.doc->beginAgentMove("a little red"));
    QByteArray gap(26 * 120 * pixel, 0);
    for (int i = 0; i < 26 * 120; i++) memcpy(gap.data() + i * pixel, color.data(), pixel);
    QVERIFY(d.paint->setPixelData(gap, 62, 60, 26, 120));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    QVERIFY(d.doc->agentMoveKeptOut().isEmpty());
    QVERIFY(d.doc->lastKeptOut().isEmpty());
    d.undo();

    // The same through a feature protected after the agent move began: the pixels are read when the write runs.
    QScopedPointer<Feature> a(d.doc->feature("Tower A"));
    QVERIFY(a->setProtected(false));
    QVERIFY(d.doc->beginAgentMove("late protection"));
    QVERIFY(a->setProtected(true));
    QVERIFY(d.paint->setPixelData(red, 0, 0, canvas.width(), canvas.height()));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
}

void TestFeatureProtection::testSetPixelDataOutsideAgentWorkIsTheScriptsOwn()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const int pixel = d.layer->paintDevice()->pixelSize();
    QByteArray red(canvas.width() * canvas.height() * pixel, 0);
    KoColor color(Qt::red, d.image->colorSpace());
    for (int i = 0; i < canvas.width() * canvas.height(); i++) memcpy(red.data() + i * pixel, color.data(), pixel);

    // Not agent work (no move, no job, setAgentActive off): the script's own write, as the artist's tools are.
    QVERIFY(!d.doc->agentActive());
    QVERIFY(d.paint->setPixelData(red, 0, 0, canvas.width(), canvas.height()));
    d.settle();
    QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
    d.undo();
    QCOMPARE(d.bytes(d.layer), before);

    // setAgentActive(true) makes it the agent's.
    d.doc->setAgentActive(true);
    QVERIFY(d.paint->setPixelData(red, 0, 0, canvas.width(), canvas.height()));
    d.settle();
    d.doc->setAgentActive(false);
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QVERIFY(d.bytes(d.layer) != before);
}

void TestFeatureProtection::testFilterApplyAndStartFilter()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);

    Filter invert;
    invert.setName("invert");
    // Filter.apply in an agent move: a whole-layer invert leaves the buildings as they are.
    QVERIFY(d.doc->beginAgentMove("invert"));
    QVERIFY(invert.apply(d.paint.data(), 0, 0, canvas.width(), canvas.height()));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QVERIFY(d.bytes(d.layer) != before);   // the white-transparent rest changed (its colour channels invert)
    QVERIFY(!d.doc->agentMoveKeptOut().isEmpty());
    d.undo();
    QCOMPARE(d.bytes(d.layer), before);

    // Outside agent work the filter is the script's own and inverts the buildings too.
    QVERIFY(invert.apply(d.paint.data(), 0, 0, canvas.width(), canvas.height()));
    d.settle();
    QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
    d.undo();

    // startFilter in an agent move.
    QVERIFY(d.doc->beginAgentMove("invert 2"));
    QVERIFY(invert.startFilter(d.paint.data(), 0, 0, canvas.width(), canvas.height()));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QVERIFY(d.bytes(d.layer) != before);
}

void TestFeatureProtection::testArtistsWritesAreNeverRestricted()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);

    // The artist's tools paint through Krita's painters and strokes, which know nothing of protection: a painter on
    // the layer's device writes inside a protected building.
    {
        KisPaintDeviceSP device = d.layer->paintDevice();
        KisPainter painter(device);
        painter.setPaintColor(KoColor(Qt::red, device->colorSpace()));
        painter.fill(30, 70, 10, 10, KoColor(Qt::red, device->colorSpace()));
    }
    d.settle();
    QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
    // An agent job that runs afterwards still leaves the (changed) building as it is.
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    const QByteArray artists = d.bytes(d.layer);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
    QVERIFY(finish(job.data()));
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, artists, b.rect), b.name);
}

void TestFeatureProtection::testProtectingIsUndoableAndSaved()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath("protected.kra");
    {
        ProtectDocument d;
        d.protectBuildings(false);
        const int steps = d.undoSteps();
        QScopedPointer<Feature> a(d.doc->feature("Tower A"));
        QScopedPointer<Feature> b(d.doc->feature("Tower B"));
        QVERIFY(a && b);
        QVERIFY(!a->isProtected());
        QVERIFY(a->setProtected(true));
        QVERIFY(a->isProtected());
        QCOMPARE(d.undoSteps(), steps + 1);
        QVERIFY(a->setProtected(true));                 // already: no new step
        QCOMPARE(d.undoSteps(), steps + 1);
        QVERIFY(d.list()->hasProtectedFeatures());
        d.undo();
        QVERIFY(!a->isProtected());
        QVERIFY(!d.list()->hasProtectedFeatures());
        d.redo();
        QVERIFY(a->isProtected());
        QVERIFY(d.list()->hasProtectedFeatures());

        // Inside an agent move it is part of the move's one step.
        const int before = d.undoSteps();
        QVERIFY(d.doc->beginAgentMove("protect b"));
        QVERIFY(b->setProtected(true));
        QVERIFY(d.doc->endAgentMove());
        d.settle();
        QCOMPARE(d.undoSteps(), before + 1);
        d.undo();
        QVERIFY(!b->isProtected());
        d.redo();
        QVERIFY(b->isProtected());
        // No pixel changed by any of it.
        QVERIFY(d.kisdoc->exportDocumentSync(path, d.kisdoc->nativeFormatMimeType()));
    }
    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true);
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY(loaded->loadNativeFormat(path));
    Document doc(loaded.data(), false);
    for (const Building &building : buildings) {
        QScopedPointer<Feature> feature(doc.feature(building.name));
        QVERIFY2(feature, building.name);
        const bool expected = QString(building.name) == "Tower A" || QString(building.name) == "Tower B";
        QCOMPARE(feature->isProtected(), expected);
    }
    // A protected feature of a reopened document protects.
    QVERIFY(loaded->image()->featureList()->hasProtectedFeatures());

    // A removed feature, or a feature that is not in the document, cannot be protected.
    QScopedPointer<Feature> gone(doc.feature("Tower C"));
    QVERIFY(doc.removeFeature("Tower C"));
    QVERIFY(!gone->setProtected(true));
}

void TestFeatureProtection::testEdgeCases()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    const QByteArray before = d.bytes(d.layer);
    const QVariantList strokes = sweep(70, QRect(QPoint(0, 0), canvas));

    // A protected feature with no pixels protects nothing and is never named.
    d.addFeature("Nothing", QRect(), true);
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        d.settle();
        QCOMPARE(job->state(), QString("done"));
        QVERIFY(job->keptOut().isEmpty());
        QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
        d.undo();
    }
    // An empty selection given to a job paints nothing, protected features or not.
    d.protectBuildings();
    {
        QScopedPointer<Selection> none(new Selection());
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}, none.data()));
        QVERIFY(finish(job.data()));
        d.settle();
        QCOMPARE(d.bytes(d.layer), before);
    }
    // The whole canvas protected: the job ends "done" and paints nothing.
    d.addFeature("Everything", QRect(QPoint(0, 0), canvas), true);
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        d.settle();
        QCOMPARE(job->state(), QString("done"));
        QCOMPARE(d.bytes(d.layer), before);
        QVERIFY(job->keptOut().contains("Everything"));
        d.paint->fill(5, 5, QColor(Qt::red), {{"mode", "selection"}});
        d.settle();
        QCOMPARE(d.bytes(d.layer), before);
    }
    // A selection of the document's own does not weaken it: setting one and passing none is still protected.
    {
        QScopedPointer<Feature> everything(d.doc->feature("Everything"));
        QVERIFY(everything->setProtected(false));
        QScopedPointer<Selection> global(new Selection());
        global->select(0, 0, 300, 200, 255);
        d.doc->setSelection(global.data());
        d.settle();
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        d.settle();
        for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    }
}

void TestFeatureProtection::testClonesAndTransformMasksAreRefused()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    d.protectBuildings();

    // A clone shows "paint" somewhere else on the canvas: a write to paint outside the buildings could appear inside
    // one, so it is refused while a feature is protected, and allowed when asked.
    KisCloneLayerSP clone = new KisCloneLayer(d.layer, d.image, "clone", OPACITY_OPAQUE_U8);
    d.image->addNode(clone);
    d.settle();
    const QVariantList strokes = sweep(10, QRect(QPoint(0, 0), canvas));
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QCOMPARE(job->state(), QString("failed"));
        QVERIFY2(job->errorString().contains("clone layer"), qPrintable(job->errorString()));
    }
    QVERIFY(!d.paint->fill(5, 5, QColor(Qt::red), {{"mode", "selection"}}));
    {
        const int pixel = d.layer->paintDevice()->pixelSize();
        QByteArray data(10 * 10 * pixel, 1);
        QVERIFY(d.doc->beginAgentMove("through a clone"));
        QVERIFY(!d.paint->setPixelData(data, 0, 0, 10, 10));
        QVERIFY(d.doc->endAgentMove());
    }
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}, {"allowProtected", true}}));
        QVERIFY(job->state() != "failed");
        QVERIFY(finish(job.data()));
    }
    // paint2 is not cloned: protected as usual.
    {
        QScopedPointer<StrokeJob> job(d.paint2->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(job->state() != "failed");
        QVERIFY(finish(job.data()));
    }
    // Without a protected feature a clone is no obstacle.
    QVERIFY(d.doc->beginAgentMove("suspended"));
    QVERIFY(d.doc->setProtectionSuspended(true));
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        QVERIFY(job->state() != "failed");
        QVERIFY(finish(job.data()));
    }
    QVERIFY(d.doc->setProtectionSuspended(false));
    QVERIFY(d.doc->endAgentMove());
    d.image->removeNode(clone);
    d.settle();

    // A transform mask shows the layer's pixels moved: refused the same way.
    KisTransformMaskSP transform = new KisTransformMask(d.image, "transform");
    d.image->addNode(transform, d.layer2);
    d.settle();
    {
        QScopedPointer<StrokeJob> job(d.paint2->paintStrokes(strokes, {{"preset", preset}}));
        QCOMPARE(job->state(), QString("failed"));
        QVERIFY2(job->errorString().contains("transform mask"), qPrintable(job->errorString()));
    }
}

void TestFeatureProtection::testSuspensionEndsWithTheMove()
{
    ProtectDocument d;
    d.protectBuildings();
    // Outside an open agent move it is refused, so a suspension can never linger.
    QVERIFY(d.doc->protectionActive());
    QVERIFY(!d.doc->setProtectionSuspended(true));
    QVERIFY(!d.doc->protectionSuspended());
    QVERIFY(d.doc->protectionActive());
    QVERIFY(d.doc->setProtectionSuspended(false));   // lifting the suspension is always allowed
    QVERIFY(d.doc->beginAgentMove("deliberate"));
    QVERIFY(d.doc->setProtectionSuspended(true));
    QVERIFY(d.doc->protectionSuspended());
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    QVERIFY2(!d.doc->protectionSuspended(), "a suspension never outlives the move it was made in");
    // The list of what was kept out starts again with each move.
    QVERIFY(d.doc->beginAgentMove("second"));
    QVERIFY(d.doc->agentMoveKeptOut().isEmpty());
    QVERIFY(d.doc->endAgentMove());
}

void TestFeatureProtection::testEdgeNoiseIsInvisibleAndAtTheEdge()
{
    // Root cause of the bytes that differ on a layer that is transparent inside a protected feature: Krita's composite op
    // works on several destination pixels at once through the selection, and where such a group holds a selected pixel
    // it gives a destination pixel whose selection is 0 and whose alpha is 0 the brush's colour, still at alpha 0. That
    // is nothing to the layer or the composite (alpha 0 shows nothing, and the pixel is never selected), so the
    // clip cannot and need not prevent it. It happens only at alpha 0, only within 3 px of the left and right edges of
    // a feature, and never where the destination has alpha: those pixels stay byte for byte.
    QStringList brushes = {brush()};
    for (const QString &candidate : {QString("b) Basic-2 Opacity"), QString("a) Eraser Soft"), QString("c) Pencil-2 Hard")}) {
        if (!presetName(candidate).isEmpty()) brushes << presetName(candidate);
    }
    int variantsRun = 0;
    for (const QString &preset : brushes) {
        for (double size : {4.0, 60.0}) {
            for (int variant = 0; variant < 3; variant++) {
                ProtectDocument d(canvas, variant != 0);   // 0: transparent buildings; 1: grey; 2: grey, layer moved first
                if (variant == 2) QVERIFY(d.paint->move(0, 0));
                d.protectBuildings();
                const QByteArray before = d.bytes(d.layer);
                QVariantList strokes = sweep(70, QRect(QPoint(0, 0), canvas), size);
                QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
                QVERIFY(finish(job.data()));
                d.settle();
                int noise = 0;
                for (const Building &b : buildings) {
                    if (variant == 0) {
                        QVERIFY2(sameExceptEdgeNoise(d, d.layer, before, b.rect, &noise), qPrintable(preset + " " + b.name));
                    } else {
                        QVERIFY2(sameIn(d, d.layer, before, b.rect), qPrintable(QString("%1 size %2 %3: bytes inside changed").arg(preset).arg(size).arg(b.name)));
                    }
                }
                variantsRun++;
            }
        }
    }
    QVERIFY(variantsRun >= 6);
}

void TestFeatureProtection::testNodeTransformsAndConversionsAreRefused()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const int steps = d.undoSteps();
    const QString profile = d.image->colorSpace()->profile()->name();
    const QString profile16 = KoColorSpaceRegistry::instance()->rgb16()->profile()->name();

    // "paint" has pixels in the buildings: every whole-layer rewrite is refused, names the features, and changes nothing.
    auto refused = [&](const QString &what, bool result) {
        QVERIFY2(!result, qPrintable(what + " must be refused"));
        QVERIFY2(!d.doc->lastKeptOut().isEmpty(), qPrintable(what + " must name the features"));
        d.settle();
        QVERIFY2(d.bytes(d.layer) == before, qPrintable(what + " must not change the layer"));
        QCOMPARE(d.undoSteps(), steps);
        QCOMPARE(d.paint->colorDepth(), QString("U8"));
    };
    refused("rotateNode", d.paint->rotateNode(0.2));
    refused("scaleNode", d.paint->scaleNode(QPointF(0, 0), 150, 100, "Bicubic"));
    refused("shearNode", d.paint->shearNode(10, 0));
    refused("cropNode", d.paint->cropNode(0, 0, 150, 100));
    refused("setColorSpace", d.paint->setColorSpace("RGBA", "U16", profile16));
    // Assigning another RGB 8-bit profile really does change how the layer's pixels read: it must be refused too.
    QString otherProfile;
    for (const KoColorProfile *candidate : KoColorSpaceRegistry::instance()->profilesFor(d.image->colorSpace()->id())) {
        if (candidate && candidate->name() != profile) {
            otherProfile = candidate->name();
            break;
        }
    }
    QVERIFY2(!otherProfile.isEmpty(), "the resources hold a second RGB 8-bit profile");
    refused("setColorProfile", d.paint->setColorProfile(otherProfile));
    // Garbage numbers are refused too, not turned into a huge rewrite.
    refused("rotateNode(NaN)", d.paint->rotateNode(std::numeric_limits<double>::quiet_NaN()));
    refused("shearNode(90)", d.paint->shearNode(89.9999, 0));

    // A layer whose pixels stay clear of the buildings, before and after, may be changed.
    KisPaintLayerSP small = addLayer(d, "small", QRect(0, 0, 10, 10));
    QScopedPointer<Node> smallNode(d.doc->nodeByName("small"));
    QVERIFY(smallNode);
    QVERIFY2(smallNode->setColorProfile(otherProfile), "a profile assigned to a layer clear of the buildings");
    QVERIFY(smallNode->setColorProfile(profile));
    QVERIFY(smallNode->rotateNode(0.1));
    QVERIFY(smallNode->scaleNode(QPointF(0, 0), 12, 12, "Bicubic"));
    // ... but not one that would reach a building after the change.
    const QByteArray smallBefore = d.bytes(small);
    QVERIFY(!smallNode->scaleNode(QPointF(0, 0), 250, 250, "Bicubic"));
    QVERIFY(d.bytes(small) == smallBefore);

    // The way out: a deliberate edit inside an agent move with protection suspended.
    QVERIFY(d.doc->beginAgentMove("deliberate transform"));
    QVERIFY(d.doc->setProtectionSuspended(true));
    QVERIFY(d.paint->rotateNode(0.2));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    QVERIFY(d.bytes(d.layer) != before);
}

void TestFeatureProtection::testMergeDownIsRefusedWhenItChangesProtectedPixels()
{
    ProtectDocument d;
    d.protectBuildings();
    const int layers = d.image->root()->childCount();

    // Normal blend, fully opaque: the composite is unchanged, so it merges even across a building.
    {
        addLayer(d, "lowerA", QRect(0, 0, 300, 200));
        addLayer(d, "upperA", QRect(30, 70, 20, 20));
        QScopedPointer<Node> upper(d.doc->nodeByName("upperA"));
        QVERIFY(upper);
        QScopedPointer<Node> merged(upper->mergeDown());
        QVERIFY(merged);
    }
    // A blending mode that is not Normal changes the lower layer's pixels: refused where it reaches a building.
    {
        addLayer(d, "lowerB", QRect(0, 0, 300, 200));
        KisPaintLayerSP upperLayer = addLayer(d, "upperB", QRect(30, 70, 20, 20));
        QScopedPointer<Node> upper(d.doc->nodeByName("upperB"));
        QVERIFY(upper);
        upper->setBlendingMode("multiply");
        d.settle();
        const int count = d.image->root()->childCount();
        QScopedPointer<Node> merged(upper->mergeDown());
        QVERIFY(!merged);
        QCOMPARE(d.image->root()->childCount(), count);
        QVERIFY(d.doc->lastKeptOut().contains("Tower A"));
        // Not reaching a building: allowed.
        upperLayer->paintDevice()->clear();
        upperLayer->paintDevice()->fill(QRect(0, 0, 10, 10), KoColor(Qt::gray, upperLayer->paintDevice()->colorSpace()));
        d.settle();
        QScopedPointer<Node> again(upper->mergeDown());
        QVERIFY(again);
    }
    // Translucent: refused.
    {
        addLayer(d, "lowerC", QRect(0, 0, 300, 200));
        addLayer(d, "upperC", QRect(30, 70, 20, 20));
        QScopedPointer<Node> upper(d.doc->nodeByName("upperC"));
        QVERIFY(upper);
        upper->setOpacity(128);
        d.settle();
        QScopedPointer<Node> merged(upper->mergeDown());
        QVERIFY(!merged);
    }
    Q_UNUSED(layers);
}

void TestFeatureProtection::testTransformMaskOnAGroupOrOnTheParentLayer()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    d.protectBuildings();
    const QVariantList strokes = sweep(10, QRect(QPoint(0, 0), canvas));

    // A layer inside a group that has a transform mask is shown moved.
    KisGroupLayerSP group = new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8);
    d.image->addNode(group);
    KisPaintLayerSP inner = new KisPaintLayer(d.image, "inner", OPACITY_OPAQUE_U8);
    d.image->addNode(inner, group);
    KisTransformMaskSP groupTransform = new KisTransformMask(d.image, "group transform");
    d.image->addNode(groupTransform, group);
    d.settle();
    QScopedPointer<Node> innerNode(d.doc->nodeByName("inner"));
    QVERIFY(innerNode);
    {
        QScopedPointer<StrokeJob> job(innerNode->paintStrokes(strokes, {{"preset", preset}}));
        QCOMPARE(job->state(), QString("failed"));
        QVERIFY2(job->errorString().contains("transform mask"), qPrintable(job->errorString()));
    }
    QVERIFY(!innerNode->fill(5, 5, QColor(Qt::red), {{"mode", "selection"}}));

    // (A mask whose parent layer has a transform mask is in KisFeatureProtectionTest: libkis cannot paint a mask.)
    KisTransformMaskSP transform = new KisTransformMask(d.image, "transform");
    d.image->addNode(transform, d.layer2);
    d.settle();
    QScopedPointer<StrokeJob> onLayer(d.paint2->paintStrokes(strokes, {{"preset", preset}}));
    QCOMPARE(onLayer->state(), QString("failed"));
    QVERIFY2(onLayer->errorString().contains("transform mask"), qPrintable(onLayer->errorString()));
    // A layer with neither is not affected by the others' masks.
    QScopedPointer<StrokeJob> fine(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(fine->state() != "failed");
    QVERIFY(finish(fine.data()));
}

void TestFeatureProtection::testMoveIsRefusedForCloneSourcesAndTransformMasks()
{
    ProtectDocument d;
    d.protectBuildings();
    KisPaintLayerSP small = addLayer(d, "small", QRect(0, 0, 10, 10));
    QScopedPointer<Node> smallNode(d.doc->nodeByName("small"));
    QVERIFY(smallNode->move(5, 5));                      // clear of the buildings and not a clone source: moves

    KisCloneLayerSP clone = new KisCloneLayer(small, d.image, "clone of small", OPACITY_OPAQUE_U8);
    d.image->addNode(clone);
    d.settle();
    QVERIFY2(!smallNode->move(6, 6), "a clone source shows elsewhere: moving it moves the clone's pixels");
    QCOMPARE(smallNode->position(), QPoint(5, 5));
    d.image->removeNode(clone);
    d.settle();

    KisTransformMaskSP transform = new KisTransformMask(d.image, "transform");
    d.image->addNode(transform, small);
    d.settle();
    QVERIFY2(!smallNode->move(6, 6), "a layer under a transform mask is shown moved");
    d.image->removeNode(transform);
    d.settle();
    QVERIFY(smallNode->move(6, 6));
}

void TestFeatureProtection::testKeptOutNamingStaysCheap()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    const QSize size(6000, 4500);
    ProtectDocument d(size, false);
    // A frame round the canvas (its bounds are the whole canvas, its tiles are the edge) and the sky.
    {
        QScopedPointer<Selection> frame(new Selection());
        frame->select(0, 0, 6000, 40, 255);
        frame->select(0, 4460, 6000, 40, 255);
        frame->select(0, 0, 40, 4500, 255);
        frame->select(5960, 0, 40, 4500, 255);
        QScopedPointer<Feature> f(d.doc->addFeature("Frame", "frame", frame.data(), "artist", "kept", true));
        QVERIFY(f);
        QScopedPointer<Selection> sky(new Selection());
        sky->select(0, 0, 6000, 900, 255);
        QScopedPointer<Feature> g(d.doc->addFeature("Sky", "sky", sky.data(), "artist", "kept", true));
        QVERIFY(g);
    }
    QRandomGenerator rng(11);
    auto walks = [&](int count, int points, const QRect &area) {
        QVariantList strokes;
        for (int i = 0; i < count; i++) {
            QVariantList pts;
            double x = area.left() + rng.bounded(area.width()), y = area.top() + rng.bounded(area.height());
            for (int p = 0; p < points; p++) {
                x = qBound<double>(area.left(), x + rng.bounded(41) - 20, area.right());
                y = qBound<double>(area.top(), y + rng.bounded(41) - 20, area.bottom());
                pts << QVariant(QVariantList{x, y});
            }
            strokes << QVariantMap{{"points", pts}, {"size", 6}, {"color", "#ff0000"}};
        }
        return strokes;
    };
    // 64 strokes of 300 points in the middle: they reach neither the frame nor the sky, and every window has to find
    // that out. The call returns after queueing its first window, so its time is the cost on the GUI thread.
    {
        const QVariantList strokes = walks(64, 300, QRect(1000, 1500, 4000, 2500));
        QElapsedTimer clock;
        clock.start();
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        const qint64 callMs = clock.elapsed();
        QVERIFY(job->state() != "failed");
        QVERIFY(finish(job.data(), 120000));
        const qint64 totalMs = clock.elapsed();
        qInfo() << "64 strokes of 300 points at 6000x4500, two big protected features not reached: first window" << callMs
                << "ms, whole job" << totalMs << "ms";
        QVERIFY(job->keptOut().isEmpty());
        QVERIFY2(callMs < 5000, "naming what was kept out must not stall the GUI thread");
        d.settle();
        d.undo();
    }
    // Strokes that cross the sky name it, and just as cheaply.
    {
        const QVariantList strokes = walks(64, 300, QRect(1000, 300, 4000, 1200));
        QElapsedTimer clock;
        clock.start();
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        const qint64 callMs = clock.elapsed();
        QVERIFY(finish(job.data(), 120000));
        qInfo() << "64 strokes of 300 points over the protected sky: first window" << callMs << "ms, whole job" << clock.elapsed() << "ms";
        QVERIFY(job->keptOut().contains("Sky"));
        QVERIFY(!job->keptOut().contains("Frame"));
        QVERIFY2(callMs < 5000, "naming what was kept out must not stall the GUI thread");
    }
}

void TestFeatureProtection::testProtectedSelectionIsACopy()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    {
        ProtectDocument d(canvas, false);
        // Nothing protected: empty, and its inverse is the whole document.
        QScopedPointer<Selection> none(d.doc->protectedSelection());
        QScopedPointer<Selection> all(d.doc->protectedSelection(true));
        QVERIFY(none && all);
        QCOMPARE(quint8(none->pixelData(10, 10, 1, 1).at(0)), quint8(0));
        QCOMPARE(quint8(all->pixelData(10, 10, 1, 1).at(0)), quint8(255));
        QVERIFY(!d.doc->protectionActive());
    }
    ProtectDocument d;
    d.protectBuildings();
    QVERIFY(d.doc->protectionActive());
    QScopedPointer<Selection> protectedSel(d.doc->protectedSelection());
    QScopedPointer<Selection> openSel(d.doc->protectedSelection(true));
    QVERIFY(protectedSel && openSel);
    QCOMPARE(quint8(protectedSel->pixelData(30, 100, 1, 1).at(0)), quint8(255));
    QCOMPARE(quint8(protectedSel->pixelData(5, 5, 1, 1).at(0)), quint8(0));
    QCOMPARE(quint8(openSel->pixelData(30, 100, 1, 1).at(0)), quint8(0));
    QCOMPARE(quint8(openSel->pixelData(5, 5, 1, 1).at(0)), quint8(255));
    // Changing the copies does not unprotect anything: a job still leaves the buildings alone.
    protectedSel->clear();
    openSel->select(0, 0, canvas.width(), canvas.height(), 255);
    const QByteArray before = d.bytes(d.layer);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
    QVERIFY(finish(job.data()));
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QScopedPointer<Selection> again(d.doc->protectedSelection());
    QCOMPARE(quint8(again->pixelData(30, 100, 1, 1).at(0)), quint8(255));
}

void TestFeatureProtection::testChannelSetPixelDataKeepsProtectedPixels()
{
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const QList<Channel *> channels = d.paint->channels();
    Channel *red = nullptr;
    for (Channel *c : channels) {
        if (c->name() == "Red") red = c;
    }
    QVERIFY(red);
    const QRect all(QPoint(0, 0), canvas);
    const QByteArray value(canvas.width() * canvas.height(), char(255));

    // Outside agent work: the script's own write, everywhere.
    red->setPixelData(value, all);
    d.settle();
    QVERIFY(!sameIn(d, d.layer, before, buildings[0].rect));
    // (a channel write has no undo step: the pixels are put back by hand)
    d.layer->paintDevice()->writeBytes(reinterpret_cast<const quint8 *>(before.constData()), 0, 0, canvas.width(), canvas.height());

    QVERIFY(d.doc->beginAgentMove("channel"));
    red->setPixelData(value, all);
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    // Outside the buildings the red channel is 255 (BGRA: byte 2).
    const QByteArray now = d.bytes(d.layer);
    const int pixel = d.layer->paintDevice()->pixelSize();
    QCOMPARE(quint8(now.at((5 * canvas.width() + 5) * pixel + 2)), quint8(255));
    qDeleteAll(channels);
}

void TestFeatureProtection::testRefusedCutLeavesTheClipboard()
{
    ProtectDocument d;
    d.protectBuildings();
    QClipboard *clipboard = QGuiApplication::clipboard();
    if (!clipboard) QSKIP("this runner has no clipboard");
    clipboard->setText("sentinel");
    if (clipboard->text() != "sentinel") QSKIP("this runner's clipboard does not hold text: not testable here");

    // A clone source: its cut is refused (its pixels are shown elsewhere), and the clipboard is as it was.
    KisPaintLayerSP source = addLayer(d, "source", QRect(0, 0, 60, 60));
    KisCloneLayerSP clone = new KisCloneLayer(source, d.image, "clone of source", OPACITY_OPAQUE_U8);
    d.image->addNode(clone);
    d.settle();
    QScopedPointer<Node> sourceNode(d.doc->nodeByName("source"));
    QVERIFY(sourceNode);
    QScopedPointer<Selection> selection(new Selection());
    selection->select(0, 0, 60, 60, 255);
    const QByteArray before = d.bytes(source, QRect(0, 0, 60, 60));
    d.doc->setAgentActive(true);
    selection->cut(sourceNode.data());
    d.doc->setAgentActive(false);
    d.settle();
    QCOMPARE(clipboard->text(), QString("sentinel"));
    QVERIFY(d.bytes(source, QRect(0, 0, 60, 60)) == before);
    d.image->removeNode(clone);
    d.settle();

    // A cut that goes ahead copies, and leaves the buildings alone while the agent works.
    QScopedPointer<Selection> wide(new Selection());
    wide->select(0, 0, canvas.width(), canvas.height(), 255);
    const QByteArray paintBefore = d.bytes(d.layer);
    d.doc->setAgentActive(true);
    wide->cut(d.paint.data());
    d.doc->setAgentActive(false);
    d.settle();
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, paintBefore, b.rect), b.name);
}

void TestFeatureProtection::testPasteKeepsProtectedPixels()
{
    ProtectDocument d;
    QClipboard *clipboard = QGuiApplication::clipboard();
    if (!clipboard) QSKIP("this runner has no clipboard");
    // A red block to copy: on its own layer, before anything is protected.
    KisPaintLayerSP source = addLayer(d, "block", QRect(0, 0, 100, 100));
    source->paintDevice()->fill(QRect(0, 0, 100, 100), KoColor(Qt::red, source->paintDevice()->colorSpace()));
    QScopedPointer<Node> sourceNode(d.doc->nodeByName("block"));
    QVERIFY(sourceNode);
    QScopedPointer<Selection> block(new Selection());
    block->select(0, 0, 100, 100, 255);
    block->copy(sourceNode.data());
    if (!KisClipboard::instance()->hasClip()) QSKIP("this runner's clipboard did not take the copy: not testable here");

    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    QScopedPointer<Selection> wide(new Selection());
    wide->select(0, 0, canvas.width(), canvas.height(), 255);
    d.doc->setAgentActive(true);
    wide->paste(d.paint.data(), 0, 0);
    d.doc->setAgentActive(false);
    d.settle();
    // The block landed where nothing is protected, and not on Tower A (x 20..59, y 60..179), which it overlaps.
    QVERIFY(!d.bytes(d.layer).isEmpty() && d.bytes(d.layer) != before);
    QVERIFY(d.opaquePixels(d.layer, QRect(0, 0, 20, 100)) > 1500);
    for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    QVERIFY(d.doc->lastKeptOut().contains("Tower A"));
}

void TestFeatureProtection::testCancelledAndRefusedJobsReportKeptOut()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    ProtectDocument d;
    d.protectBuildings();
    const QByteArray before = d.bytes(d.layer);
    const int steps = d.undoSteps();

    // A job cancelled before anything painted: the strokes it queued reach the buildings, so it names them, and the
    // names stay after the cancel; nothing was painted, the state is cancelled, the status carries both.
    {
        Gate gate(d.image);
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
        QVERIFY(job);
        QVERIFY(job->state() != "failed");
        QVERIFY(job->cancel());
        gate.release();
        QVERIFY(finish(job.data()));
        d.settle();
        QCOMPARE(job->state(), QString("cancelled"));
        QCOMPARE(job->cancelReason(), QString("script"));
        QCOMPARE(sorted(job->keptOut()), allBuildings());
        QCOMPARE(sorted(job->status().value("keptOut").toStringList()), allBuildings());
        QCOMPARE(job->status().value("cancelReason").toString(), QString("script"));
        QCOMPARE(d.bytes(d.layer), before);
    }
    // A refused job is "failed", names nothing, and leaves the last report alone.
    {
        d.doc->setAgentActive(false);
        QScopedPointer<StrokeJob> bad(d.paint->paintStrokes(sweep(5, QRect(QPoint(0, 0), canvas)), {{"preset", "no such preset"}}));
        QCOMPARE(bad->state(), QString("failed"));
        QVERIFY(bad->keptOut().isEmpty());
        QVERIFY(bad->status().contains("keptOut"));
    }
    // A job that ran, then undone: the report is what it was, the layer is back, one step went and came.
    {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(sweep(70, QRect(QPoint(0, 0), canvas)), {{"preset", preset}}));
        QVERIFY(finish(job.data()));
        d.settle();
        QCOMPARE(d.undoSteps(), steps + 1);
        const QStringList named = sorted(job->keptOut());
        d.undo();
        QCOMPARE(d.bytes(d.layer), before);
        QCOMPARE(sorted(job->keptOut()), named);
        QCOMPARE(named, allBuildings());
        d.redo();
        for (const Building &b : buildings) QVERIFY2(sameIn(d, d.layer, before, b.rect), b.name);
    }
}

void TestFeatureProtection::testOverheadOfProtection()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    const QSize size(1500, 1000);
    ProtectDocument d(size, false);
    const QVariantList strokes = sweep(400, QRect(QPoint(0, 0), size), 6);

    auto timeJob = [&](const QVariantMap &options) {
        qint64 best = std::numeric_limits<qint64>::max();
        for (int run = 0; run < 3; run++) {
            QVariantMap all = options;
            all.insert("preset", preset);
            QElapsedTimer clock;
            clock.start();
            QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, all));
            if (!job || !finish(job.data(), 120000)) return qint64(-1);
            d.settle();
            best = qMin(best, clock.elapsed());
            d.undo();
        }
        return best;
    };

    // The same job three ways: with no features at all (what an unprotected document costs), as a deliberate edit
    // (no enforcement at all, the cost before protection existed), and with 30 protected features.
    const qint64 noFeatures = timeJob({});
    const qint64 allowed = timeJob({{"allowProtected", true}});
    for (int i = 0; i < 30; i++) {
        d.addFeature(QString("Building %1").arg(i), QRect(20 + (i % 10) * 140, 100 + (i / 10) * 300, 90, 200), true);
    }
    const qint64 thirty = timeJob({});
    qInfo() << "stroke job of 400 strokes at 1500x1000 (best of 3):" << noFeatures << "ms with no features,"
            << allowed << "ms with allowProtected, and" << thirty << "ms with 30 protected features";
    QVERIFY(noFeatures > 0 && allowed > 0 && thirty > 0);
    // Recorded, not gated: a loaded machine makes any ratio flaky. The numbers are in the log line above.
    if (noFeatures > allowed * 3 + 500 || thirty > allowed * 6 + 1000) {
        qWarning() << "protection overhead looks high on this run (a loaded machine?):" << noFeatures << allowed << thirty;
    }
}

void TestFeatureProtection::testThirtyProtectedFeaturesAtFullSize()
{
    const QString preset = brush();
    QVERIFY(!preset.isEmpty());
    const QSize size(6000, 4500);
    ProtectDocument d(size, false);
    // Thirty buildings along the skyline, big enough to matter: 30 masks of 80-160 px wide and 600-1600 tall.
    QList<QRect> rects;
    int x = 100;
    for (int i = 0; i < 30; i++) {
        const int w = 80 + (i % 5) * 20;
        const int h = 600 + (i * 137) % 1000;
        rects << QRect(x, 3600 - h, w, h);
        x += w + 40;
    }
    const KoColorSpace *cs = d.image->colorSpace();
    for (const QRect &rect : rects) d.layer->paintDevice()->fill(rect, KoColor(Qt::gray, cs));
    for (int i = 0; i < rects.size(); i++) d.addFeature(QString("Building %1").arg(i), rects[i], false);
    d.settle();
    const QByteArray bandBefore = d.bytes(d.layer, QRect(0, 2000, size.width(), 1700));

    QVariantList strokes;   // 300 strokes across the whole width, over the band the buildings stand in
    for (int i = 0; i < 300; i++) strokes << line(2, 2000 + (i + 0.5) * 1700 / 300, 5998, 2000 + (i + 0.5) * 1700 / 300, 8);
    auto run = [&](const QVariantMap &extra) {
        QVariantMap options{{"preset", preset}};
        for (auto it = extra.constBegin(); it != extra.constEnd(); ++it) options.insert(it.key(), it.value());
        QElapsedTimer clock;
        clock.start();
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, options));
        if (!job || !finish(job.data(), 180000)) return qint64(-1);
        d.settle();
        const qint64 ms = clock.elapsed();
        d.undo();
        return ms;
    };
    const qint64 baseline = run({{"allowProtected", true}});

    // Protecting them all is one rebuild of the protected area, once, when the first protected job needs it.
    for (int i = 0; i < rects.size(); i++) {
        QScopedPointer<Feature> f(d.doc->feature(QString("Building %1").arg(i)));
        QVERIFY(f && f->setProtected(true));
    }
    QElapsedTimer clock;
    clock.start();
    QVERIFY(d.list()->protectedMask());
    const qint64 buildMs = clock.elapsed();
    clock.restart();
    QVERIFY(d.list()->protectedMask());
    const qint64 cachedUs = clock.nsecsElapsed() / 1000;
    const qint64 protectedMs = run({});
    const qint64 protectedAgainMs = run({});
    qInfo() << "6000x4500, 30 protected buildings, 300 strokes of 8 px across them: job" << baseline << "ms as a deliberate edit,"
            << protectedMs << "ms protected (the first also builds the protected area:" << buildMs << "ms; cached lookup"
            << cachedUs << "us)," << protectedAgainMs << "ms protected again";
    QVERIFY(baseline > 0 && protectedMs > 0 && protectedAgainMs > 0);
    if (protectedAgainMs > baseline * 4 + 1000) {   // recorded, not gated
        qWarning() << "protected job looks slow on this run (a loaded machine?):" << baseline << protectedAgainMs;
    }

    // And it holds at this size: the band holds the buildings' grey, none of it painted over.
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(finish(job.data(), 180000));
    d.settle();
    for (const QRect &rect : rects) {
        const QRect inBand = rect & QRect(0, 2000, size.width(), 1700);
        const QByteArray now = d.bytes(d.layer, inBand);
        QByteArray was(now.size(), 0);
        for (int y = 0; y < inBand.height(); y++) {
            const int pixel = d.layer->paintDevice()->pixelSize();
            was.replace(y * inBand.width() * pixel, inBand.width() * pixel,
                        bandBefore.mid(((inBand.top() - 2000 + y) * size.width() + inBand.left()) * pixel, inBand.width() * pixel));
        }
        QVERIFY(now == was);
    }
    QCOMPARE(job->keptOut().size(), 30);
}

KISTEST_TEMPORARY_HOME_MAIN(TestFeatureProtection)
