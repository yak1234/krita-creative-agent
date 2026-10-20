/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestLibkisTraps.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>
#include <testutil.h>

#include <QElapsedTimer>
#include <QTimer>
#include <functional>
#include <QPainterPath>
#include <QPointer>
#include <QScopedPointer>
#include <QSignalSpy>

#include <Document.h>
#include <Feature.h>
#include <DocumentHistory.h>
#include <Filter.h>
#include <InfoObject.h>
#include <Node.h>
#include <Selection.h>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KoCanvasResourceProvider.h>
#include <KoCanvasResourcesIds.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <brushengine/kis_paintop_preset.h>
#include <kis_canvas_resource_provider.h>
#include <kis_image.h>
#include <kis_command_utils.h>
#include <kis_layer_utils.h>
#include <kis_paint_layer.h>
#include <kis_paintop_settings.h>
#include <kis_processing_applicator.h>
#include <kis_stroke_strategy_undo_command_based.h>
#include <KoColorProfile.h>
#include <kis_transaction.h>
#include <kundo2stack.h>
#include <processing/KisToolFunctions.h>

namespace {

const int imageWidth = 120;
const int imageHeight = 90;

/// One main window (never shown) with one view, made on first use, as TestDocumentHistory does: libkis's brush
/// comes from the active view. Before it exists, no view exists.
struct Painter {
    QPointer<KisDocument> kisdoc;
    KisMainWindow *mainWindow = nullptr;
    QPointer<KisView> view;

    static Painter *&instance()
    {
        static Painter *painter = nullptr;
        return painter;
    }

    static void ensure()
    {
        if (!instance()) instance() = new Painter();
    }

    Painter()
    {
        kisdoc = KisPart::instance()->createDocument();
        KisImageSP image = new KisImage(0, 16, 16, KoColorSpaceRegistry::instance()->rgb8(), "brush");
        image->addNode(new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);

        mainWindow = KisPart::instance()->createMainWindow();
        view = new KisView(kisdoc, mainWindow->viewManager(), mainWindow);
        KisPart::instance()->addView(view);
        mainWindow->showView(view);

        KisPaintOpPresetSP preset(new KisPaintOpPreset(TestUtil::fetchDataFileLazy("autobrush_300px.kpp")));
        const bool loaded = preset->load(KisGlobalResourcesInterface::instance());
        Q_ASSERT(loaded);
        Q_UNUSED(loaded);
        preset->settings()->setPaintOpSize(4.0);
        resources()->setResource(KoCanvasResource::CurrentPaintOpPreset, QVariant::fromValue(preset));
        resources()->setForegroundColor(KoColor(Qt::blue, image->colorSpace()));
    }

    KoCanvasResourceProvider *resources() const
    {
        return view->viewManager()->canvasResourceProvider()->resourceManager();
    }

    ~Painter()
    {
        if (view) {
            KisPart::instance()->removeView(view);
            delete view;
        }
        delete mainWindow;
        if (kisdoc) {
            KisPart::instance()->removeDocument(kisdoc, false);
            delete kisdoc;
        }
    }
};

/// A document registered with KisPart (so it has an undo history for scripts), with a red layer "paint" over a
/// transparent layer "other", and libkis wrappers.
struct TrapDocument {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    KisNodeSP other;
    QScopedPointer<Document> doc;
    QScopedPointer<Node> paint;
    QScopedPointer<Node> otherNode;

    explicit TrapDocument(bool fillRed = true)
    {
        kisdoc = KisPart::instance()->createDocument();
        image = new KisImage(0, imageWidth, imageHeight, KoColorSpaceRegistry::instance()->rgb8(), "traps");
        other = new KisPaintLayer(image, "other", OPACITY_OPAQUE_U8);
        image->addNode(other);
        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        if (fillRed) {
            layer->paintDevice()->fill(image->bounds(), KoColor(Qt::red, image->colorSpace()));
        }
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);
        doc.reset(new Document(kisdoc, false));
        paint.reset(doc->nodeByName("paint"));
        otherNode.reset(doc->nodeByName("other"));
        image->waitForDone();
        kisdoc->undoStack()->clear();
    }

    bool valid() const { return kisdoc && image && layer && other && doc && paint && otherNode; }

    ~TrapDocument()
    {
        paint.reset();
        otherNode.reset();
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
        for (int i = 0; i < 3; i++) {
            doc->waitForDone();
            QCoreApplication::processEvents();
        }
    }

    int undoCount() const { return kisdoc->undoStack()->count(); }

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

    QStringList steps() const
    {
        QStringList names;
        for (int i = 0; i < undoCount(); i++) names << doc->undoText(i);
        return names;
    }

    /// The layer's pixel at (x, y).
    QColor at(KisNodeSP node, int x, int y) const
    {
        QColor c;
        node->paintDevice()->pixel(x, y, &c);
        return c;
    }

    QColor at(int x, int y) const { return at(layer, x, y); }

    QByteArray bytes(KisNodeSP node) const
    {
        QByteArray data(imageWidth * imageHeight * node->paintDevice()->pixelSize(), 0);
        node->paintDevice()->readBytes(reinterpret_cast<quint8 *>(data.data()), image->bounds());
        return data;
    }

    int selectedAt(Selection &selection, int x, int y) const
    {
        const QByteArray one = selection.pixelData(x, y, 1, 1);
        return one.isEmpty() ? -1 : quint8(one.at(0));
    }
};

/// Sets the tool functions' wait limit for one test and restores it however the test ends.
struct WaitLimit {
    const int previous = KisToolFunctions::waitLimit();
    explicit WaitLimit(int milliseconds) { KisToolFunctions::setWaitLimit(milliseconds); }
    ~WaitLimit() { KisToolFunctions::setWaitLimit(previous); }
};

/// The artist's pen down: a stroke started and not ended holds every later stroke back.
struct HeldStroke {
    KisImageSP image;
    KisStrokeId id;
    explicit HeldStroke(KisImageSP image)
        : image(image)
        , id(image->startStroke(new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("held"), false, image.data())))
    {
    }
    void end()
    {
        if (id) image->endStroke(id);
        id = KisStrokeId();
    }
    ~HeldStroke() { end(); }
};

bool nearColor(const QColor &a, const QColor &b, int tolerance = 2)
{
    return qAbs(a.red() - b.red()) <= tolerance && qAbs(a.green() - b.green()) <= tolerance
        && qAbs(a.blue() - b.blue()) <= tolerance && qAbs(a.alpha() - b.alpha()) <= tolerance;
}

Selection *rectangle(int x, int y, int w, int h)
{
    Selection *selection = new Selection();
    selection->select(x, y, w, h, 255);
    return selection;
}

} // namespace

void TestLibkisTraps::cleanupTestCase()
{
    delete Painter::instance();
    Painter::instance() = nullptr;
}

void TestLibkisTraps::testFilterApplyIsUndoableAndSelectionAware()
{
    TrapDocument d;
    QVERIFY(d.valid());
    const QByteArray before = d.bytes(d.layer);

    Filter invert;
    invert.setName("invert");

    // Without a selection: the whole rectangle, one undo step.
    QVERIFY(invert.apply(d.paint.data(), 0, 0, imageWidth, imageHeight));
    d.settle();
    QVERIFY(nearColor(d.at(10, 10), QColor(0, 255, 255)));
    QVERIFY(nearColor(d.at(110, 80), QColor(0, 255, 255)));
    QCOMPARE(d.undoCount(), 1);
    QVERIFY2(d.steps().first().contains("invert", Qt::CaseInsensitive), qPrintable(d.steps().first()));
    d.undo();
    QVERIFY(d.bytes(d.layer) == before);
    d.redo();
    QVERIFY(nearColor(d.at(10, 10), QColor(0, 255, 255)));
    d.undo();
    QVERIFY(d.bytes(d.layer) == before);

    // With the document's selection: only the selected pixels change.
    QScopedPointer<Selection> box(rectangle(20, 20, 40, 30));
    d.doc->setSelection(box.data());
    d.settle();
    const int stepsBefore = d.undoCount();
    QVERIFY(invert.apply(d.paint.data(), 0, 0, imageWidth, imageHeight));
    d.settle();
    QVERIFY(nearColor(d.at(30, 30), QColor(0, 255, 255)));
    QVERIFY(nearColor(d.at(59, 49), QColor(0, 255, 255)));
    QVERIFY(nearColor(d.at(10, 10), QColor(Qt::red)));
    QVERIFY(nearColor(d.at(60, 50), QColor(Qt::red)));
    QVERIFY(nearColor(d.at(100, 80), QColor(Qt::red)));
    QCOMPARE(d.undoCount(), stepsBefore + 1);
    const QByteArray filtered = d.bytes(d.layer);
    d.undo();
    QVERIFY(nearColor(d.at(30, 30), QColor(Qt::red)));
    d.redo();
    QVERIFY(d.bytes(d.layer) == filtered);

    // A locked layer is refused, as before.
    d.paint->setLocked(true);
    QVERIFY(!invert.apply(d.paint.data(), 0, 0, 10, 10));
}

void TestLibkisTraps::testFilterApplyInAnAgentMoveIsOneStep()
{
    TrapDocument d;
    QVERIFY(d.valid());
    const QByteArray before = d.bytes(d.layer);
    Filter invert;
    invert.setName("invert");

    QVERIFY(d.doc->beginAgentMove("filters"));
    QVERIFY(invert.apply(d.paint.data(), 0, 0, 60, imageHeight));
    QVERIFY(invert.apply(d.paint.data(), 60, 0, 60, imageHeight));
    QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0xff)), 0, 0, 4, 4));
    QVERIFY(d.doc->endAgentMove());
    d.settle();

    QCOMPARE(d.undoCount(), 1);
    QCOMPARE(d.doc->undoText(0), QString("Agent: filters"));
    QVERIFY(nearColor(d.at(70, 70), QColor(0, 255, 255)));
    d.undo();
    QVERIFY(d.bytes(d.layer) == before);
}

void TestLibkisTraps::testSetPixelDataIsUndoable()
{
    TrapDocument d(false);
    QVERIFY(d.valid());
    const QByteArray before = d.bytes(d.layer);
    QByteArray green(10 * 10 * 4, 0);
    for (int i = 0; i < 100; i++) {
        green[i * 4 + 0] = 0;
        green[i * 4 + 1] = char(255);
        green[i * 4 + 2] = 0;
        green[i * 4 + 3] = char(255);
    }
    QVERIFY(d.paint->setPixelData(green, 30, 30, 10, 10));
    d.settle();
    QVERIFY(nearColor(d.at(35, 35), QColor(Qt::green)));
    QCOMPARE(d.undoCount(), 1);
    d.undo();
    QVERIFY(d.bytes(d.layer) == before);
    QCOMPARE(d.at(35, 35).alpha(), 0);
    d.redo();
    QVERIFY(nearColor(d.at(35, 35), QColor(Qt::green)));
    // Not enough data is still refused, and adds no step.
    QVERIFY(!d.paint->setPixelData(QByteArray(8, 0), 0, 0, 10, 10));
    QCOMPARE(d.undoCount(), 1);
}

void TestLibkisTraps::testNodeSettersAreUndoable()
{
    TrapDocument d(false);
    QVERIFY(d.valid());
    QCOMPARE(d.paint->opacity(), 255);

    d.paint->setOpacity(100);
    QCOMPARE(d.paint->opacity(), 100);
    QCOMPARE(d.undoCount(), 1);
    d.undo();
    QCOMPARE(d.paint->opacity(), 255);
    d.redo();
    QCOMPARE(d.paint->opacity(), 100);

    d.paint->setName("renamed");
    QCOMPARE(d.paint->name(), QString("renamed"));
    QCOMPARE(d.undoCount(), 2);
    d.undo();
    QCOMPARE(d.paint->name(), QString("paint"));

    d.paint->setVisible(false);
    QVERIFY(!d.paint->visible());
    d.undo();
    QVERIFY(d.paint->visible());

    d.paint->setBlendingMode("multiply");
    QCOMPARE(d.paint->blendingMode(), QString("multiply"));
    const int count = d.undoCount();
    d.undo();
    QCOMPARE(d.undoCount(), count);
    QVERIFY(d.paint->blendingMode() != QString("multiply"));

    // Setting what is already set adds no step.
    const int steps = d.undoCount();
    d.paint->setOpacity(d.paint->opacity());
    d.paint->setVisible(d.paint->visible());
    QCOMPARE(d.undoCount(), steps);
}

void TestLibkisTraps::testSettersInAnAgentMoveAreOneStep()
{
    TrapDocument d(false);
    QVERIFY(d.valid());
    QVERIFY(d.doc->beginAgentMove("setters"));
    d.paint->setOpacity(40);
    d.paint->setName("moved");
    d.paint->setVisible(false);
    QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0xff)), 0, 0, 4, 4));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    QCOMPARE(d.undoCount(), 1);
    QCOMPARE(d.doc->undoText(0), QString("Agent: setters"));
    QCOMPARE(d.paint->opacity(), 40);
    d.undo();
    QCOMPARE(d.paint->opacity(), 255);
    QCOMPARE(d.paint->name(), QString("paint"));
    QVERIFY(d.paint->visible());
    QCOMPARE(d.at(1, 1).alpha(), 0);
}

void TestLibkisTraps::testSelectionContract()
{
    TrapDocument d(false);
    QVERIFY(d.valid());

    // A rectangle: narrower and lower by the value, same top-left; what was outside is really deselected.
    Selection box;
    box.select(10, 10, 40, 30, 255);
    box.contract(10);
    QCOMPARE(box.x(), 10);
    QCOMPARE(box.y(), 10);
    QCOMPARE(box.width(), 30);
    QCOMPARE(box.height(), 20);
    QCOMPARE(d.selectedAt(box, 20, 20), 255);
    QCOMPARE(d.selectedAt(box, 45, 20), 0);
    QCOMPARE(d.selectedAt(box, 20, 35), 0);

    // An L-shape keeps its shape (the gap stays a gap) inside the smaller box.
    Selection shape;
    shape.select(0, 0, 40, 10, 255);
    shape.select(0, 10, 10, 30, 255);
    shape.contract(10);
    QCOMPARE(shape.width(), 30);
    QCOMPARE(shape.height(), 30);
    QCOMPARE(d.selectedAt(shape, 5, 5), 255);
    QCOMPARE(d.selectedAt(shape, 25, 5), 255);
    QCOMPARE(d.selectedAt(shape, 35, 5), 0);
    QCOMPARE(d.selectedAt(shape, 20, 20), 0);
    QCOMPARE(d.selectedAt(shape, 5, 35), 0);
    QCOMPARE(d.selectedAt(shape, 5, 25), 255);

    // Contracting by nothing, or by a negative value, leaves it; by its whole size, clears it.
    Selection same;
    same.select(5, 5, 20, 20, 255);
    same.contract(0);
    same.contract(-3);
    QCOMPARE(same.width(), 20);
    same.contract(20);
    QCOMPARE(same.width(), 0);
    QCOMPARE(d.selectedAt(same, 10, 10), 0);
}

void TestLibkisTraps::testSelectionResize()
{
    TrapDocument d(false);
    QVERIFY(d.valid());

    Selection box;
    box.select(10, 10, 40, 30, 255);
    // Smaller: clipped to the new box.
    box.resize(20, 10);
    QCOMPARE(box.x(), 10);
    QCOMPARE(box.y(), 10);
    QCOMPARE(box.width(), 20);
    QCOMPARE(box.height(), 10);
    QCOMPARE(d.selectedAt(box, 15, 15), 255);
    QCOMPARE(d.selectedAt(box, 35, 15), 0);
    QCOMPARE(d.selectedAt(box, 15, 25), 0);
    // Larger: the added area is selected.
    box.resize(50, 40);
    QCOMPARE(box.x(), 10);
    QCOMPARE(box.y(), 10);
    QCOMPARE(box.width(), 50);
    QCOMPARE(box.height(), 40);
    QCOMPARE(d.selectedAt(box, 55, 45), 255);
    QCOMPARE(d.selectedAt(box, 15, 15), 255);
    // Wider only, and taller only.
    Selection tall;
    tall.select(0, 0, 10, 10, 255);
    tall.resize(10, 25);
    QCOMPARE(tall.width(), 10);
    QCOMPARE(tall.height(), 25);

    // An empty selection resized becomes the rectangle at the origin.
    Selection empty;
    empty.resize(8, 6);
    QCOMPARE(empty.width(), 8);
    QCOMPARE(empty.height(), 6);
    // Negative sizes are refused.
    empty.resize(-1, 5);
    QCOMPARE(empty.width(), 8);
}

void TestLibkisTraps::testViewStateDoesNotLeakIntoStrokes()
{
    Painter::ensure();
    KoCanvasResourceProvider *resources = Painter::instance()->resources();
    TrapDocument d(false);
    QVERIFY(d.valid());

    // The artist turns mirroring, the alpha lock and the eraser blending on in the view.
    resources->setResource(KoCanvasResource::MirrorHorizontal, true);
    resources->setResource(KoCanvasResource::MirrorVertical, true);
    resources->setResource(KoCanvasResource::GlobalAlphaLock, true);
    resources->setResource(KoCanvasResource::CurrentEffectiveCompositeOp, QString("erase"));

    d.paint->paintLine(QPointF(10, 20), QPointF(40, 20), 1.0, 1.0);
    d.settle();
    // Painted where asked, in the view's colour, not erased, not locked to nothing, not mirrored.
    QVERIFY(nearColor(d.at(25, 20), QColor(Qt::blue), 8));
    QCOMPARE(d.at(imageWidth - 25, 20).alpha(), 0);
    QCOMPARE(d.at(25, imageHeight - 20).alpha(), 0);
    QCOMPARE(d.at(imageWidth - 25, imageHeight - 20).alpha(), 0);

    resources->setResource(KoCanvasResource::MirrorHorizontal, false);
    resources->setResource(KoCanvasResource::MirrorVertical, false);
    resources->setResource(KoCanvasResource::GlobalAlphaLock, false);
    resources->setResource(KoCanvasResource::CurrentEffectiveCompositeOp, QString("over"));
}

void TestLibkisTraps::testNoCallEndsOrHangsOnAnOpenStroke()
{
    Painter::ensure();
    WaitLimit limit(300);
    Filter invert;
    invert.setName("invert");

    using Call = std::function<void(TrapDocument &, Node *)>;
    const QList<QPair<QString, Call>> calls = {
        {"paintLine", [&](TrapDocument &d, Node *) { d.paint->paintLine(QPointF(5, 5), QPointF(50, 5), 1.0, 1.0); }},
        {"paintRectangle", [&](TrapDocument &d, Node *) { d.paint->paintRectangle(QRectF(5, 10, 20, 20)); }},
        {"paintEllipse", [&](TrapDocument &d, Node *) { d.paint->paintEllipse(QRectF(5, 10, 20, 20)); }},
        {"paintPolygon", [&](TrapDocument &d, Node *) { d.paint->paintPolygon(QList<QPointF>({QPointF(5, 5), QPointF(40, 5), QPointF(20, 30)})); }},
        {"setOpacity", [&](TrapDocument &d, Node *) { d.paint->setOpacity(10); }},
        {"setName", [&](TrapDocument &d, Node *) { d.paint->setName("x"); }},
        {"setVisible", [&](TrapDocument &d, Node *) { d.paint->setVisible(false); }},
        {"setBlendingMode", [&](TrapDocument &d, Node *) { d.paint->setBlendingMode("multiply"); }},
        {"setPixelData", [&](TrapDocument &d, Node *) { d.paint->setPixelData(QByteArray(4 * 4 * 4, char(1)), 0, 0, 4, 4); }},
        {"addChildNode", [&](TrapDocument &d, Node *child) { QScopedPointer<Node> root(d.doc->rootNode()); root->addChildNode(child, nullptr); }},
        {"remove", [&](TrapDocument &d, Node *) { d.otherNode->remove(); }},
        {"Filter.apply", [&](TrapDocument &d, Node *) { invert.apply(d.paint.data(), 0, 0, 10, 10); }},
        {"Filter.startFilter", [&](TrapDocument &d, Node *) { invert.startFilter(d.paint.data(), 0, 0, 10, 10); }},
        {"fill", [&](TrapDocument &d, Node *) { d.paint->fill(5, 5, QColor(Qt::green)); }},
        {"move", [&](TrapDocument &d, Node *) { d.paint->move(3, 3); }},
        {"setColorProfile", [&](TrapDocument &d, Node *) { d.doc->setColorProfile("sRGB-elle-V2-srgbtrc.icc"); }},
        {"crop", [&](TrapDocument &d, Node *) { d.doc->crop(0, 0, imageWidth - 1, imageHeight - 1); }},
        {"scaleImage", [&](TrapDocument &d, Node *) { d.doc->scaleImage(imageWidth, imageHeight, 72, 72, "Bicubic"); }},
        {"rotateImage", [&](TrapDocument &d, Node *) { d.doc->rotateImage(0.1); }},
        {"flatten", [&](TrapDocument &d, Node *) { d.doc->flatten(); }},
        {"refreshProjection", [&](TrapDocument &d, Node *) { d.doc->refreshProjection(); }},
        {"scaleNode", [&](TrapDocument &d, Node *) { d.paint->scaleNode(QPointF(0, 0), 50, 50, "Bicubic"); }},
        {"mergeDown", [&](TrapDocument &d, Node *) { delete d.paint->mergeDown(); }},
    };
    // One document for each call: a call that is held back is queued behind the artist's stroke and runs when it
    // ends, so the calls must not meet each other's results.
    for (const auto &call : calls) {
        TrapDocument d;
        QVERIFY(d.valid());
        QScopedPointer<Node> child(d.doc->createNode("child", "paintLayer"));
        QVERIFY(child);
        HeldStroke held(d.image);
        QVERIFY(held.id);
        QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
        QVERIFY(endRequests.isValid());

        QElapsedTimer timer;
        timer.start();
        call.second(d, child.data());
        // Returned within its bound (the wait limit is 300 ms; nothing may wait for the open stroke to end).
        QVERIFY2(timer.elapsed() < 5000, qPrintable(call.first + " took " + QString::number(timer.elapsed()) + " ms"));
        QVERIFY2(endRequests.count() == 0, qPrintable(call.first + " asked open strokes to end"));
        QVERIFY2(held.id, qPrintable(call.first));

        // The artist lifts the pen; whatever was held back runs or is cancelled, and the image settles.
        held.end();
        d.settle();
    }
}

namespace {
/// The artist's tool stroke on \p node, as the Gradient tool queues it (an applicator that reports its devices when
/// \p reports), or as it would without that (the way a stroke that does not report was queued before 2.9).
void artistToolStroke(KisImageSP image, KisNodeSP node, bool reports)
{
    KisProcessingApplicator applicator(image, node,
                                       reports ? KisProcessingApplicator::REPORTS_TOUCHED_DEVICES
                                               : KisProcessingApplicator::NONE,
                                       KisImageSignalVector(), kundo2_noi18n("artist tool"));
    KisPaintDeviceSP device = node->paintDevice();
    applicator.applyCommand(new KisCommandUtils::LambdaCommand([device]() mutable -> KUndo2Command * {
        KisTransaction transaction(device);
        device->fill(QRect(0, 0, 8, 8), KoColor(Qt::green, device->colorSpace()));
        return transaction.endAndTake();
    }));
    applicator.end();
}

/// The artist's fill, as the Fill tool queues it (a stroke of KisStrokeStrategyUndoCommandBased that reports its
/// devices).
void artistFillStroke(KisImageSP image, KisNodeSP node)
{
    KisStrokeStrategyUndoCommandBased *strategy =
        new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("artist fill"), false, image.data());
    strategy->setReportsTouchedDevices(true);
    KisStrokeId id = image->startStroke(strategy);
    KisPaintDeviceSP device = node->paintDevice();
    image->addJob(id, new KisStrokeStrategyUndoCommandBased::Data(
                          KUndo2CommandSP(new KisCommandUtils::LambdaCommand([device]() mutable -> KUndo2Command * {
                              KisTransaction transaction(device);
                              device->fill(QRect(0, 0, 8, 8), KoColor(Qt::green, device->colorSpace()));
                              return transaction.endAndTake();
                          })),
                          false, KisStrokeJobData::SEQUENTIAL, KisStrokeJobData::EXCLUSIVE));
    image->endStroke(id);
}
}

void TestLibkisTraps::testArtistToolStrokesOnOtherLayersDoNotSplitAMove()
{
    // The move paints on "paint"; the artist fills, gradients and encloses on "other": the move stays one step.
    for (int variant = 0; variant < 2; variant++) {
        TrapDocument d(false);
        QVERIFY(d.valid());
        QVERIFY(d.doc->beginAgentMove("move"));
        QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0xff)), 20, 20, 4, 4));
        d.settle();
        if (variant == 0) artistToolStroke(d.image, d.other, true);
        else artistFillStroke(d.image, d.other);
        d.settle();
        QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0x80)), 40, 20, 4, 4));
        QVERIFY(d.doc->endAgentMove());
        d.settle();
        const QStringList steps = d.steps();
        QVERIFY2(steps.count("Agent: move") == 1, qPrintable(steps.join(" | ")));
        QVERIFY2(steps.count() == 2 && steps.contains("Agent: move (cont.)") == false, qPrintable(steps.join(" | ")));
        // The artist's pixels are theirs: undoing the move does not touch them.
        d.undo();
        QCOMPARE(d.at(d.other, 2, 2).alpha(), 255);
        QCOMPARE(d.at(d.layer, 21, 21).alpha(), 0);
    }
}

void TestLibkisTraps::testNonReportingToolStrokeSplitsAMove()
{
    // A negative control: a stroke that does NOT report its devices (a tool this change did not touch) splits the
    // move as before, even on another layer.
    TrapDocument d(false);
    QVERIFY(d.valid());
    QVERIFY(d.doc->beginAgentMove("move"));
    QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0xff)), 20, 20, 4, 4));
    d.settle();
    artistToolStroke(d.image, d.other, false);
    d.settle();
    QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0x80)), 40, 20, 4, 4));
    QVERIFY(d.doc->endAgentMove());
    d.settle();
    const QStringList steps = d.steps();
    QVERIFY2(steps.count() == 3 && steps.at(0) == "Agent: move" && steps.at(1) == "artist tool"
                 && steps.at(2) == "Agent: move (cont.)",
             qPrintable(steps.join(" | ")));
}

void TestLibkisTraps::testPaintKeepsTheViewsOpacity()
{
    Painter::ensure();
    KoCanvasResourceProvider *resources = Painter::instance()->resources();
    TrapDocument d(false);
    QVERIFY(d.valid());

    // The plugin sets the stroke opacity through the view (View.setPaintingOpacity: the Opacity resource).
    resources->setResource(KoCanvasResource::Opacity, 1.0);
    d.paint->paintLine(QPointF(10, 20), QPointF(40, 20), 1.0, 1.0);
    resources->setResource(KoCanvasResource::Opacity, 0.5);
    d.paint->paintLine(QPointF(10, 60), QPointF(40, 60), 1.0, 1.0);
    d.settle();
    resources->setResource(KoCanvasResource::Opacity, 1.0);
    const int full = d.at(25, 20).alpha();
    const int half = d.at(25, 60).alpha();
    QVERIFY2(full >= 240, qPrintable(QString::number(full)));
    QVERIFY2(half >= 100 && half <= 160, qPrintable(QString::number(half)));
}

void TestLibkisTraps::testOrphanSetOpacityAddsNoStep()
{
    // The plugin creates a node, sets its opacity, then adds it: setting it must not touch the history (a junk step,
    // and the artist's redo stack purged).
    TrapDocument d(false);
    QVERIFY(d.valid());
    d.paint->setOpacity(100); // a step of the artist's, undone: redo is available
    d.undo();
    QVERIFY(d.kisdoc->undoStack()->canRedo());
    const int count = d.undoCount();

    QScopedPointer<Node> orphan(d.doc->createNode("orphan", "paintLayer"));
    QVERIFY(orphan);
    orphan->setOpacity(40);
    orphan->setName("renamed orphan");
    orphan->setVisible(false);
    d.settle();
    QCOMPARE(orphan->opacity(), 40);
    QCOMPARE(orphan->name(), QString("renamed orphan"));
    QVERIFY(!orphan->visible());
    QCOMPARE(d.undoCount(), count);
    QVERIFY(d.kisdoc->undoStack()->canRedo());
}

void TestLibkisTraps::testArtistStrokeDuringAScriptWaitStillEndsOtherStrokes()
{
    // While a script's call waits (handling events), an artist stroke that starts is an ordinary one: it asks the
    // open strokes to end. The suppression covers the script's own call, not the wait.
    TrapDocument d;
    QVERIFY(d.valid());
    WaitLimit limit(1500);
    HeldStroke held(d.image);
    QVERIFY(held.id);
    QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(endRequests.isValid());
    KisImageSP image = d.image;
    QTimer::singleShot(200, [image]() mutable {
        KisStrokeId late = image->startStroke(
            new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("late artist"), false, image.data()));
        image->endStroke(late);
    });
    d.doc->crop(0, 0, imageWidth - 1, imageHeight - 1); // waits the whole 1.5 s behind the held stroke
    QVERIFY2(endRequests.count() >= 1, qPrintable(QString::number(endRequests.count())));
    held.end();
    d.settle();
}

void TestLibkisTraps::testOverrideNestsAndEnds()
{
    TrapDocument d;
    QVERIFY(d.valid());
    QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(!KisProcessingApplicator::NoEndRequestsOverride::active());
    {
        KisProcessingApplicator::NoEndRequestsOverride outer;
        QVERIFY(KisProcessingApplicator::NoEndRequestsOverride::active());
        {
            KisProcessingApplicator::NoEndRequestsOverride inner;
            QVERIFY(KisProcessingApplicator::NoEndRequestsOverride::active());
        }
        QVERIFY(KisProcessingApplicator::NoEndRequestsOverride::active());
        KisStrokeId id = d.image->startStroke(new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("quiet"), false, d.image.data()));
        d.image->endStroke(id);
        QCOMPARE(endRequests.count(), 0);
        QCOMPARE(outer.strokes().size(), 1);
    }
    QVERIFY(!KisProcessingApplicator::NoEndRequestsOverride::active());
    // Outside it, a stroke asks again.
    KisStrokeId id = d.image->startStroke(new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("loud"), false, d.image.data()));
    d.image->endStroke(id);
    QVERIFY(endRequests.count() >= 1);
    d.settle();
}

void TestLibkisTraps::testToolStrokeWithNoScriptKeepsItsBehaviour()
{
    // The artist's own path: an ordinary tool stroke, no script active, behaves as in stock Krita.
    TrapDocument d(false);
    QVERIFY(d.valid());
    QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(endRequests.isValid());
    const QByteArray before = d.bytes(d.other);
    artistToolStroke(d.image, d.other, false);
    QVERIFY(endRequests.count() >= 1); // it asks open strokes to end, as ever
    d.settle();
    QCOMPARE(d.steps(), QStringList({"artist tool"}));
    QCOMPARE(d.at(d.other, 2, 2).alpha(), 255);
    d.undo();
    QVERIFY(d.bytes(d.other) == before);
    d.redo();
    QCOMPARE(d.at(d.other, 2, 2).alpha(), 255);
    QCOMPARE(d.steps(), QStringList({"artist tool"}));

    // The reporting variant (the Gradient tool's) behaves the same.
    artistToolStroke(d.image, d.layer, true);
    d.settle();
    QCOMPARE(d.steps(), QStringList({"artist tool", "artist tool"}));
}

void TestLibkisTraps::testHeldBackOperationsAreCancelled()
{
    // An image operation held back behind the artist's stroke is cancelled when the call gives up: it never runs
    // afterwards, and the document is as it was.
    Painter::ensure();
    WaitLimit limit(300);
    using Call = std::function<bool(TrapDocument &)>; // true when the call reported failure as it must
    const QList<QPair<QString, Call>> calls = {
        {"crop", [](TrapDocument &d) { d.doc->crop(0, 0, imageWidth - 10, imageHeight - 10); return true; }},
        {"resizeImage", [](TrapDocument &d) { d.doc->resizeImage(0, 0, imageWidth - 10, imageHeight - 10); return true; }},
        {"scaleImage", [](TrapDocument &d) { d.doc->scaleImage(60, 45, 72, 72, "Bicubic"); return true; }},
        {"rotateImage", [](TrapDocument &d) { d.doc->rotateImage(0.5); return true; }},
        {"flatten", [](TrapDocument &d) { d.doc->flatten(); return true; }},
        {"setColorSpace", [](TrapDocument &d) { return !d.doc->setColorSpace("RGBA", "U16", d.doc->colorProfile()); }},
        {"mergeDown", [](TrapDocument &d) { QScopedPointer<Node> merged(d.paint->mergeDown()); return !merged; }},
        {"scaleNode", [](TrapDocument &d) { d.paint->scaleNode(QPointF(0, 0), 30, 30, "Bicubic"); return true; }},
        {"cropNode", [](TrapDocument &d) { d.paint->cropNode(0, 0, 20, 20); return true; }},
        {"addFeature", [](TrapDocument &d) {
             QScopedPointer<Selection> mask(rectangle(10, 10, 20, 20));
             QScopedPointer<Feature> feature(d.doc->addFeature("held feature", "object", mask.data()));
             return !feature;
         }},
    };
    for (const auto &call : calls) {
        TrapDocument d;
        QVERIFY(d.valid());
        const QSize size = d.image->size();
        const QByteArray paintBefore = d.bytes(d.layer);
        const QByteArray otherBefore = d.bytes(d.other);
        const int childrenBefore = d.image->root()->childCount();
        const QString profileBefore = d.doc->colorModel() + d.doc->colorDepth();
        {
            HeldStroke held(d.image);
            QVERIFY(held.id);
            QVERIFY2(call.second(d), qPrintable(call.first + " did not report failure"));
            held.end();
            d.settle();
        }
        d.settle();
        QVERIFY2(d.image->size() == size, qPrintable(call.first + " changed the image size"));
        QVERIFY2(d.image->root()->childCount() == childrenBefore, qPrintable(call.first + " changed the layers"));
        QVERIFY2(d.bytes(d.layer) == paintBefore && d.bytes(d.other) == otherBefore, qPrintable(call.first + " changed pixels"));
        QVERIFY2(d.doc->colorModel() + d.doc->colorDepth() == profileBefore, qPrintable(call.first + " changed colours"));
        QVERIFY2(d.doc->features().isEmpty(), qPrintable(call.first + " added a feature"));
    }
}

void TestLibkisTraps::testLockedImageSettersAreImmediateAndUndoable()
{
    // Inside a Document.lock() block a script reads its changes back at once, and each is an undo step.
    TrapDocument d;
    QVERIFY(d.valid());
    Filter invert;
    invert.setName("invert");
    const QByteArray before = d.bytes(d.layer);
    d.doc->lock();
    d.paint->setOpacity(40);
    QCOMPARE(d.paint->opacity(), 40);
    d.paint->setName("locked name");
    QCOMPARE(d.paint->name(), QString("locked name"));
    d.paint->setVisible(false);
    QVERIFY(!d.paint->visible());
    QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0)), 50, 50, 4, 4));
    QCOMPARE(d.at(51, 51).alpha(), 0);
    QVERIFY(invert.apply(d.paint.data(), 0, 0, 10, 10));
    QVERIFY(nearColor(d.at(5, 5), QColor(0, 255, 255)));
    d.doc->unlock();
    d.settle();
    QCOMPARE(d.undoCount(), 5);
    for (int i = 0; i < 5; i++) d.undo();
    QCOMPARE(d.paint->opacity(), 255);
    QCOMPARE(d.paint->name(), QString("paint"));
    QVERIFY(d.paint->visible());
    QVERIFY(d.bytes(d.layer) == before);
}

void TestLibkisTraps::testSelectionContractOnAnInvertedSelection()
{
    // An inverted selection has no bounds: contract and resize leave it as it is, never hang or crash.
    TrapDocument d(false);
    QVERIFY(d.valid());
    Selection inverted;
    inverted.select(10, 10, 20, 20, 255);
    inverted.invert();
    QCOMPARE(d.selectedAt(inverted, 100, 80), 255);
    QCOMPARE(d.selectedAt(inverted, 15, 15), 0);
    inverted.contract(5);
    inverted.resize(10, 10);
    QCOMPARE(d.selectedAt(inverted, 100, 80), 255);
    QCOMPARE(d.selectedAt(inverted, 15, 15), 0);
}

void TestLibkisTraps::testArtistToolStrokesOnTheMovesLayerSplitIt()
{
    // On the layer the move changed, undo must stay in order: the move is split there, as before.
    for (int variant = 0; variant < 2; variant++) {
        TrapDocument d(false);
        QVERIFY(d.valid());
        QVERIFY(d.doc->beginAgentMove("move"));
        QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0xff)), 20, 20, 4, 4));
        d.settle();
        if (variant == 0) artistToolStroke(d.image, d.layer, true);
        else artistFillStroke(d.image, d.layer);
        d.settle();
        QVERIFY(d.paint->setPixelData(QByteArray(4 * 4 * 4, char(0x80)), 40, 20, 4, 4));
        QVERIFY(d.doc->endAgentMove());
        d.settle();
        const QStringList steps = d.steps();
        QVERIFY2(steps.count() == 3 && steps.at(1).startsWith("artist") && steps.at(2) == "Agent: move (cont.)",
                 qPrintable(steps.join(" | ")));
    }
}

KISTEST_TEMPORARY_HOME_MAIN(TestLibkisTraps)
