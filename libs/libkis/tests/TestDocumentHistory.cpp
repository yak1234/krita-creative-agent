/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentHistory.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>
#include <testutil.h>

#include <QElapsedTimer>
#include <QPointer>
#include <QScopedPointer>
#include <QSignalSpy>
#include <QTemporaryDir>

#include <Document.h>
#include <DocumentHistory.h>
#include <InfoObject.h>
#include <Selection.h>
#include <Node.h>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KoCanvasResourceProvider.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <brushengine/kis_paintop_preset.h>
#include <kis_canvas_resource_provider.h>
#include <kis_image.h>
#include <kis_paint_layer.h>
#include <kis_paintop_settings.h>
#include <kundo2stack.h>
#include <kis_command_utils.h>
#include <kis_figure_painting_tool_helper.h>
#include <commands/kis_image_layer_add_command.h>
#include <DocumentChanges.h>

namespace {

const int imageWidth = 120;
const int imageHeight = 90;

/**
 * The brush libkis paints with comes from the active view: one main window (never shown) with one view, on a
 * document of its own, for the whole test run. Its brush is a 4 px round brush in blue. Main windows load Krita's
 * dockers, some of which outlive a deleted window, so the window is made once and deleted in cleanupTestCase().
 */
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
        if (!instance()) {
            instance() = new Painter();
        }
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
        KoCanvasResourceProvider *resources = view->viewManager()->canvasResourceProvider()->resourceManager();
        resources->setResource(KoCanvasResource::CurrentPaintOpPreset, QVariant::fromValue(preset));
        resources->setForegroundColor(KoColor(Qt::blue, image->colorSpace()));
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

/**
 * A document registered with KisPart, as Krita's own are, with one paint layer, "paint", filled with nothing, and an
 * empty history. libkis paints on it with the Painter's brush.
 */
struct PaintingDocument {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;
    QScopedPointer<Node> paint;

    PaintingDocument()
    {
        Painter::ensure();
        kisdoc = KisPart::instance()->createDocument();
        image = new KisImage(0, imageWidth, imageHeight, KoColorSpaceRegistry::instance()->rgb8(), "history");
        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);

        doc.reset(new Document(kisdoc, false));
        paint.reset(doc->nodeByName("paint"));
        image->waitForDone();
        kisdoc->undoStack()->clear();
    }

    ~PaintingDocument()
    {
        paint.reset();
        doc.reset();
        image = nullptr;
        layer = nullptr;
        if (kisdoc) {
            KisPart::instance()->removeDocument(kisdoc, false);
            delete kisdoc;
        }
    }

    /// Waits until everything queued has landed, closing moves included (their steps arrive from the strokes queue).
    void settle()
    {
        for (int i = 0; i < 3; i++) {
            doc->waitForDone();
            QCoreApplication::processEvents();
        }
    }

    /// A paint layer added without undo, for the artist.
    KisNodeSP addLayer(const QString &name)
    {
        KisNodeSP node = new KisPaintLayer(image, name, OPACITY_OPAQUE_U8);
        image->addNode(node);
        image->waitForDone();
        return node;
    }

    KUndo2Stack *stack() const
    {
        return kisdoc->undoStack();
    }

    /// A short horizontal line at row \p y, as libkis paints it: one stroke, one undo step outside a move.
    void line(int y, const QString &name = QString())
    {
        paint->paintLine(QPointF(10, y), QPointF(100, y), 1.0, 1.0, "ForegroundColor", name);
    }
};

/// Everything a script can see of the image: the layers' names in order, their pixels, and the projection.
struct ImageState {
    QStringList layers;
    QList<QByteArray> pixels;
    QImage projection;

    static ImageState of(PaintingDocument &p)
    {
        p.settle();
        p.doc->refreshProjection();
        ImageState state;
        QScopedPointer<Node> root(p.doc->rootNode());
        Q_FOREACH (Node *child, root->childNodes()) {
            state.layers << child->name();
            state.pixels << child->pixelData(0, 0, imageWidth, imageHeight);
            delete child;
        }
        state.projection = p.doc->projection(0, 0, imageWidth, imageHeight);
        return state;
    }

    bool operator==(const ImageState &rhs) const
    {
        return layers == rhs.layers && pixels == rhs.pixels && projection == rhs.projection;
    }
};

/// \p w x \p h opaque pixels of one colour, in the layer's BGRA byte order.
QByteArray pixels(int w, int h, QColor color)
{
    QByteArray data;
    for (int i = 0; i < w * h; i++) {
        data.append(char(color.blue()));
        data.append(char(color.green()));
        data.append(char(color.red()));
        data.append(char(255));
    }
    return data;
}

/// The commands one history step holds: a script step's commands, or none for a single command.
QList<const KUndo2Command *> commandsOf(const KUndo2Command *step)
{
    QList<const KUndo2Command *> list;
    if (const KisCommandUtils::CompositeCommand *composite = dynamic_cast<const KisCommandUtils::CompositeCommand *>(step)) {
        Q_FOREACH (const KUndo2Command *command, composite->commands()) {
            list << command;
        }
    }
    return list;
}

/**
 * The artist's brush: a stroke on \p node with the view's brush, its commands going to the document's history as a
 * tool's do. It is open until the object is destroyed, like a pen held down.
 */
struct ArtistStroke {
    QScopedPointer<KisFigurePaintingToolHelper> helper;

    ArtistStroke(PaintingDocument &p, KisNodeSP node, const QString &name)
    {
        KoCanvasResourceProvider *resources =
            Painter::instance()->view->viewManager()->canvasResourceProvider()->resourceManager();
        helper.reset(new KisFigurePaintingToolHelper(kundo2_noi18n(name), p.image, node, resources,
                                                     KisToolShapeUtils::StrokeStyleForeground,
                                                     KisToolShapeUtils::FillStyleNone));
    }

    void line(int y)
    {
        KisPaintInformation a(QPointF(10, y));
        KisPaintInformation b(QPointF(100, y));
        helper->paintLine(a, b);
    }

    void end()
    {
        helper.reset();
    }
};

} // namespace

void TestDocumentHistory::cleanupTestCase()
{
    delete Painter::instance();
    Painter::instance() = nullptr;
}

void TestDocumentHistory::testUndoQueries()
{
    PaintingDocument p;
    QCOMPARE(p.doc->undoCount(), 0);
    QCOMPARE(p.doc->undoIndex(), 0);
    QCOMPARE(p.doc->cleanIndex(), 0);

    p.line(10, "first");
    p.line(20, "second");
    p.settle();

    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoIndex(), 2);
    QCOMPARE(p.doc->undoText(0), QString("first"));
    QCOMPARE(p.doc->undoText(1), QString("second"));
    QCOMPARE(p.doc->undoText(2), QString());
    QCOMPARE(p.doc->undoText(-1), QString());

    QCOMPARE(p.doc->cleanIndex(), 0);
    p.stack()->setClean();
    QCOMPARE(p.doc->cleanIndex(), 2);
}

void TestDocumentHistory::testSetUndoIndex()
{
    PaintingDocument p;
    const ImageState empty = ImageState::of(p);

    p.line(10);
    const ImageState one = ImageState::of(p);
    p.line(20);
    const ImageState two = ImageState::of(p);
    QVERIFY(!(one == empty));
    QVERIFY(!(two == one));

    QVERIFY(p.doc->setUndoIndex(1));
    QCOMPARE(p.doc->undoIndex(), 1);
    QVERIFY(ImageState::of(p) == one);

    QVERIFY(p.doc->setUndoIndex(0));
    QVERIFY(ImageState::of(p) == empty);

    QVERIFY(p.doc->setUndoIndex(2));
    QVERIFY(ImageState::of(p) == two);

    QVERIFY(!p.doc->setUndoIndex(3));
    QVERIFY(!p.doc->setUndoIndex(-1));
    QCOMPARE(p.doc->undoIndex(), 2);
    QCOMPARE(p.doc->undoCount(), 2);
}

void TestDocumentHistory::testNamedStrokes()
{
    PaintingDocument p;

    p.line(10);
    p.settle();
    QCOMPARE(p.doc->undoText(0), QString("Scripted Brush Stroke"));

    p.line(20, "horizon");
    p.paint->paintPolylineStroke({StrokePoint(QPointF(5, 30)), StrokePoint(QPointF(60, 40))}, "ForegroundColor",
                                 "polyline");
    p.paint->paintRectangle(QRectF(10, 50, 20, 10), "ForegroundColor", "None", "rectangle");
    p.paint->paintPolygon({QPointF(40, 50), QPointF(60, 50), QPointF(50, 60)}, "ForegroundColor", "None", "polygon");
    p.paint->paintEllipse(QRectF(70, 50, 20, 10), "ForegroundColor", "None", "ellipse");
    QPainterPath path;
    path.moveTo(5, 80);
    path.lineTo(100, 85);
    p.paint->paintPath(path, "ForegroundColor", "None", "path");
    p.settle();
    QCOMPARE(p.doc->undoCount(), 7);
    QCOMPARE(p.doc->undoText(1), QString("horizon"));
    QCOMPARE(p.doc->undoText(2), QString("polyline"));
    QCOMPARE(p.doc->undoText(3), QString("rectangle"));
    QCOMPARE(p.doc->undoText(4), QString("polygon"));
    QCOMPARE(p.doc->undoText(5), QString("ellipse"));
    QCOMPARE(p.doc->undoText(6), QString("path"));

    // In an agent move, unnamed strokes take the move's name; a name argument still wins.
    QVERIFY(p.doc->beginAgentMove("sky"));
    p.line(15);
    p.line(25, "cloud");
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 8);
    const QList<const KUndo2Command *> move = commandsOf(p.stack()->command(7));
    QCOMPARE(move.size(), 2);
    QCOMPARE(move[0]->text().toString(), QString("Agent: sky"));
    QCOMPARE(move[1]->text().toString(), QString("cloud"));
}

void TestDocumentHistory::testUndoMacro()
{
    PaintingDocument p;
    const ImageState empty = ImageState::of(p);

    QVERIFY(p.doc->beginUndoMacro("three lines"));
    p.line(10);
    p.line(20);
    p.line(30);
    QVERIFY(p.doc->endUndoMacro());
    p.settle();

    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoIndex(), 1);
    QCOMPARE(p.doc->undoText(0), QString("three lines"));
    QCOMPARE(commandsOf(p.stack()->command(0)).size(), 3);

    // A macro opened inside another joins it: one step, named after the outer one.
    QVERIFY(p.doc->beginUndoMacro("outer"));
    p.line(40);
    QVERIFY(p.doc->beginUndoMacro("inner"));
    p.line(50);
    QVERIFY(p.doc->endUndoMacro());
    QVERIFY(p.doc->endUndoMacro());
    QVERIFY(!p.doc->endUndoMacro());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(1), QString("outer"));
    QCOMPARE(commandsOf(p.stack()->command(1)).size(), 2);

    QVERIFY(p.doc->setUndoIndex(0));
    QVERIFY(ImageState::of(p) == empty);
}

void TestDocumentHistory::testAgentMoveIsOneStep()
{
    PaintingDocument p;

    p.line(5, "artist");
    const ImageState before = ImageState::of(p);

    QVERIFY(p.doc->beginAgentMove("paint sky"));
    QVERIFY(p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveName(), QString("paint sky"));
    for (int i = 0; i < 40; i++) {
        p.line(10 + i);
    }
    QScopedPointer<Node> added(p.doc->createNode("sky", "paintlayer"));
    QScopedPointer<Node> root(p.doc->rootNode());
    QVERIFY(root->addChildNode(added.data(), nullptr));
    added->paintLine(QPointF(0, 0), QPointF(100, 80), 1.0, 1.0, "ForegroundColor");
    QVERIFY(p.paint->setPixelData(pixels(8, 6, Qt::red), 100, 70, 8, 6));
    QVERIFY(added->setPixelData(pixels(5, 5, Qt::green), 2, 2, 5, 5));
    QVERIFY(p.doc->endAgentMove());
    QVERIFY(!p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveName(), QString());
    const ImageState after = ImageState::of(p);
    QVERIFY(!(after == before));
    QCOMPARE(after.layers, QStringList({"paint", "sky"}));

    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoIndex(), 2);
    QCOMPARE(p.doc->undoText(0), QString("artist"));
    QCOMPARE(p.doc->undoText(1), QString("Agent: paint sky"));

    QVERIFY(p.doc->setUndoIndex(1));
    QVERIFY(ImageState::of(p) == before);

    QVERIFY(p.doc->setUndoIndex(2));
    QVERIFY(ImageState::of(p) == after);
}

void TestDocumentHistory::testStrokesOutsideMoveStaySeparate()
{
    PaintingDocument p;
    p.line(10, "a");
    p.line(20, "b");
    QVERIFY(p.doc->beginAgentMove("move"));
    p.line(30);
    p.line(40);
    QVERIFY(p.doc->endAgentMove());
    p.line(50, "c");
    p.line(60, "d");
    p.settle();

    QCOMPARE(p.doc->undoCount(), 5);
    QCOMPARE(p.doc->undoText(0), QString("a"));
    QCOMPARE(p.doc->undoText(1), QString("b"));
    QCOMPARE(p.doc->undoText(2), QString("Agent: move"));
    QCOMPARE(p.doc->undoText(3), QString("c"));
    QCOMPARE(p.doc->undoText(4), QString("d"));
    QCOMPARE(commandsOf(p.stack()->command(2)).size(), 2);
}

void TestDocumentHistory::testPixelWriteOutsideMoveKeepsUpstreamBehaviour()
{
    PaintingDocument p;
    QVERIFY(p.paint->setPixelData(pixels(4, 4, Qt::red), 0, 0, 4, 4));
    p.settle();
    QCOMPARE(p.doc->undoCount(), 0);
}

void TestDocumentHistory::testRefusals()
{
    PaintingDocument p;

    QVERIFY(!p.doc->endAgentMove());
    QVERIFY(!p.doc->endUndoMacro());

    QVERIFY(p.doc->beginAgentMove("one"));
    p.line(10);
    QVERIFY(!p.doc->beginAgentMove("two"));
    QVERIFY(p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveName(), QString("one"));
    QVERIFY(!p.doc->setUndoIndex(0));
    QVERIFY(p.doc->beginUndoMacro("inner"));
    QVERIFY(!p.doc->endAgentMove());
    QVERIFY(p.doc->endUndoMacro());
    QVERIFY(!p.doc->endUndoMacro());
    QVERIFY(p.doc->endAgentMove());
    QVERIFY(!p.doc->endAgentMove());

    QVERIFY(p.doc->beginUndoMacro("outer"));
    p.line(20);
    QVERIFY(!p.doc->beginAgentMove("nested"));
    QVERIFY(p.doc->endUndoMacro());

    QVERIFY(p.doc->beginAgentMove("shared"));
    p.line(30);
    Document other(p.kisdoc, false);
    QVERIFY(other.agentMoveOpen());
    QVERIFY(!other.beginAgentMove("other"));
    QVERIFY(other.endAgentMove());
    QVERIFY(!p.doc->agentMoveOpen());
    p.settle();

    QCOMPARE(p.doc->undoCount(), 3);
    QCOMPARE(p.doc->undoText(0), QString("Agent: one"));
    QCOMPARE(p.doc->undoText(1), QString("outer"));
    QCOMPARE(p.doc->undoText(2), QString("Agent: shared"));
}

void TestDocumentHistory::testCloseMidMove()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("interrupted"));
    p.line(10);
    p.line(20);

    QPointer<KisDocument> closed = p.kisdoc;
    QVERIFY(p.doc->close());
    QVERIFY(!p.doc->endAgentMove());
    QVERIFY(!p.doc->agentMoveOpen());
    QVERIFY(!p.doc->beginAgentMove("after close"));
    QVERIFY(!p.doc->setUndoIndex(0));
    QCOMPARE(p.doc->undoCount(), 0);
    QCOMPARE(p.doc->undoIndex(), 0);
    QCOMPARE(p.doc->undoText(0), QString());

    QTest::qWait(50);
    QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    QVERIFY(!closed);
    // The strokes queued in the move finish on the image after the document is gone, without a crash.
    p.image->waitForDone();
    QCoreApplication::processEvents();
}

void TestDocumentHistory::testBigMoveKeepsUndoLimit()
{
    PaintingDocument p;
    p.stack()->setUndoLimit(200);

    p.line(5, "artist");
    const ImageState before = ImageState::of(p);

    QElapsedTimer timer;
    timer.start();
    QVERIFY(p.doc->beginAgentMove("1400 strokes"));
    for (int i = 0; i < 1400; i++) {
        const int y = 10 + (i % 70);
        const int x = (i / 70) * 5;
        p.paint->paintLine(QPointF(x, y), QPointF(x + 4, y), 1.0, 1.0, "ForegroundColor");
    }
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    const qint64 painted = timer.restart();

    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(0), QString("artist"));
    QCOMPARE(p.doc->undoText(1), QString("Agent: 1400 strokes"));
    QCOMPARE(commandsOf(p.stack()->command(1)).size(), 1400);

    QVERIFY(p.doc->setUndoIndex(1));
    QVERIFY(ImageState::of(p) == before);
    const qint64 undone = timer.elapsed();
    QCOMPARE(p.doc->undoText(0), QString("artist"));
    qWarning() << "1400-stroke move: painted and landed in" << painted << "ms, undone in" << undone << "ms";
}

void TestDocumentHistory::testAgentMoveChangedSignal()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginUndoMacro("plain"));
    QVERIFY(p.doc->endUndoMacro());

    DocumentHistory *history = DocumentHistory::of(p.kisdoc);
    QVERIFY(history);
    QSignalSpy spy(history, SIGNAL(agentMoveChanged(bool, QString)));
    QVERIFY(p.doc->beginAgentMove("signal"));
    QCOMPARE(spy.count(), 1);
    QCOMPARE(spy.at(0).at(0).toBool(), true);
    QCOMPARE(spy.at(0).at(1).toString(), QString("signal"));
    QVERIFY(DocumentHistory::isAgentMoveOpen(p.image.data()));

    QVERIFY(!p.doc->beginAgentMove("refused"));
    QCOMPARE(spy.count(), 1);

    p.line(10);
    QVERIFY(p.doc->endAgentMove());
    QVERIFY(!DocumentHistory::isAgentMoveOpen(p.image.data()));
    // The move closes for the change sources once its work has landed.
    p.settle();
    QCOMPARE(spy.count(), 2);
    QCOMPARE(spy.at(1).at(0).toBool(), false);
    QCOMPARE(spy.at(1).at(1).toString(), QString("signal"));

    // The document's image is replaced under an open move: the move is gone, its end is refused, it closes once.
    QVERIFY(p.doc->beginAgentMove("replaced"));
    QCOMPARE(spy.count(), 3);
    p.line(10);
    p.settle();
    KisImageSP replacement = new KisImage(0, imageWidth, imageHeight, p.image->colorSpace(), "replacement");
    replacement->addNode(new KisPaintLayer(replacement, "paint", OPACITY_OPAQUE_U8));
    p.kisdoc->setCurrentImage(replacement);
    QVERIFY(!p.doc->agentMoveOpen());
    QVERIFY(!p.doc->endAgentMove());
    p.settle();
    QCOMPARE(spy.count(), 4);
    QCOMPARE(spy.at(3).at(0).toBool(), false);
    QVERIFY(p.doc->beginAgentMove("next"));
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(spy.count(), 6);
}

void TestDocumentHistory::testArtistStrokesStaySeparate()
{
    PaintingDocument p;
    KisNodeSP artistLayer = p.addLayer("artist");
    QSignalSpy endRequests(p.image.data(), SIGNAL(sigStrokeEndRequested()));

    // A stroke the artist is drawing when the move begins is not ended by it.
    ArtistStroke first(p, artistLayer, "artist one");
    first.line(10);
    endRequests.clear();
    QVERIFY(p.doc->beginAgentMove("move"));
    QCOMPARE(endRequests.count(), 0);
    first.line(20);
    first.end();

    p.line(30);
    p.line(40);

    // Nor one being drawn when it ends.
    ArtistStroke second(p, artistLayer, "artist two");
    second.line(50);
    endRequests.clear();
    QVERIFY(p.doc->endAgentMove());
    QCOMPARE(endRequests.count(), 0);
    second.line(60);
    second.end();
    p.settle();

    QCOMPARE(p.doc->undoCount(), 3);
    QCOMPARE(p.doc->undoText(0), QString("artist one"));
    QCOMPARE(p.doc->undoText(1), QString("artist two"));
    QCOMPARE(p.doc->undoText(2), QString("Agent: move"));
    QCOMPARE(commandsOf(p.stack()->command(2)).size(), 2);
}

void TestDocumentHistory::testUndoDuringMoveClosesIt()
{
    PaintingDocument p;
    KisNodeSP artistLayer = p.addLayer("artist");
    ArtistStroke stroke(p, artistLayer, "artist");
    stroke.line(10);
    stroke.end();
    const ImageState beforeMove = ImageState::of(p);

    QVERIFY(p.doc->beginAgentMove("move"));
    p.line(20);
    p.settle();
    // Undo stays available during a move (the stack has no open macro).
    QVERIFY(p.stack()->canUndo());

    // The artist presses Undo: the move's work so far becomes a step, and that newest step is undone.
    p.stack()->undo();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(1), QString("Agent: move"));
    QCOMPARE(p.doc->undoIndex(), 1);
    QVERIFY(ImageState::of(p) == beforeMove);

    // The artist's own stroke undoes next.
    p.stack()->undo();
    p.settle();
    QCOMPARE(p.doc->undoIndex(), 0);
}

void TestDocumentHistory::testLateAgentStrokeLandsInMove()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("late"));
    for (int i = 0; i < 30; i++) {
        p.line(10 + i);
    }
    // Ended at once, with the strokes still queued: they land in the move's step.
    QVERIFY(p.doc->endAgentMove());
    p.line(60, "after");
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(0), QString("Agent: late"));
    QCOMPARE(commandsOf(p.stack()->command(0)).size(), 30);
    QCOMPARE(p.doc->undoText(1), QString("after"));
}

void TestDocumentHistory::testDeviceSplit()
{
    PaintingDocument p;
    KisNodeSP artistLayer = p.addLayer("artist");
    const ImageState empty = ImageState::of(p);

    QVERIFY(p.doc->beginAgentMove("split"));
    p.line(10);
    p.settle();

    // The artist paints another layer: the move's work so far stays in the move.
    ArtistStroke other(p, artistLayer, "artist elsewhere");
    other.line(20);
    other.end();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("artist elsewhere"));

    // The artist paints the layer the move has painted: the move's work so far becomes a step first, so each
    // layer's steps stay in the order they were painted.
    ArtistStroke same(p, p.layer, "artist on the agent's layer");
    same.line(30);
    same.end();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 3);
    QCOMPARE(p.doc->undoText(1), QString("Agent: split"));
    QCOMPARE(p.doc->undoText(2), QString("artist on the agent's layer"));

    // The rest of the move continues as its own step.
    p.line(40);
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 4);
    QCOMPARE(p.doc->undoText(3), QString("Agent: split (cont.)"));

    QVERIFY(p.doc->setUndoIndex(0));
    QVERIFY(ImageState::of(p) == empty);
}

void TestDocumentHistory::testLegacyCommandInMove()
{
    PaintingDocument p;
    const ImageState empty = ImageState::of(p);

    QVERIFY(p.doc->beginAgentMove("legacy"));
    p.line(10);
    p.settle();

    // A command the GUI adds directly (a new layer through the legacy undo adapter) is the artist's own step; what
    // it changes is not known, so the move's work so far becomes a step first.
    KisNodeSP layer = new KisPaintLayer(p.image, "gui layer", OPACITY_OPAQUE_U8);
    p.image->undoAdapter()->addCommand(new KisImageLayerAddCommand(p.image, layer, p.image->root(), nullptr));
    p.line(20);
    QVERIFY(p.doc->endAgentMove());
    p.settle();

    QCOMPARE(p.doc->undoCount(), 3);
    QCOMPARE(p.doc->undoText(0), QString("Agent: legacy"));
    QCOMPARE(p.doc->undoText(2), QString("Agent: legacy (cont.)"));

    QVERIFY(p.doc->setUndoIndex(0));
    QVERIFY(ImageState::of(p) == empty);
}

void TestDocumentHistory::testSaveDuringMove()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("saved"));
    p.line(10);
    p.settle();

    QTemporaryDir dir;
    // As Document.saveAs() does, without warning dialogs (a failed save would wait on one).
    QVERIFY(p.kisdoc->saveAs(dir.filePath("saved.kra"), "application/x-krita", false));
    p.kisdoc->waitForSavingToComplete();
    // Saving lands the move's work, so the saved state is a step in the history and the history is clean there.
    p.settle();
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("Agent: saved"));
    QCOMPARE(p.doc->cleanIndex(), 1);
    QVERIFY(p.stack()->isClean());
    QVERIFY(!p.kisdoc->isModified());
}

void TestDocumentHistory::testEmptyMove()
{
    PaintingDocument p;
    QVERIFY(!p.kisdoc->isModified());
    QVERIFY(p.doc->beginAgentMove("nothing"));
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 0);
    QVERIFY(!p.kisdoc->isModified());
}

void TestDocumentHistory::testIdleMoveCloses()
{
    PaintingDocument p;
    const int timeout = DocumentHistory::agentMoveIdleTimeout();
    DocumentHistory::setAgentMoveIdleTimeout(300);
    QVERIFY(p.doc->beginAgentMove("forgotten"));
    p.line(10);
    p.settle();
    const int id = p.doc->agentMoveId();
    QVERIFY(id > 0);
    QTest::qWait(1200);
    p.settle();
    // Its work so far is a step, and the document is no longer agent-active; the move stays the script's, resting.
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("Agent: forgotten"));
    QVERIFY(!p.doc->agentActive());
    QVERIFY(p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveId(), id);
    // The script ends it: nothing more lands.
    QVERIFY(p.doc->endAgentMove());
    QVERIFY(!p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveId(), 0);
    p.settle();
    QCOMPARE(p.doc->undoCount(), 1);
    DocumentHistory::setAgentMoveIdleTimeout(timeout);
}

void TestDocumentHistory::testMoveIsAgentWork()
{
    PaintingDocument p;
    DocumentChanges *changes = DocumentChanges::forImage(p.image);
    QVERIFY(!p.doc->agentActive());

    QList<bool> sources;
    QMutex mutex;
    QObject::connect(changes, &DocumentChanges::imageChangedAsync, changes,
                     [&](const QRect &, bool agent) {
                         QMutexLocker locker(&mutex);
                         sources << agent;
                     },
                     Qt::DirectConnection);

    QVERIFY(p.doc->beginAgentMove("work"));
    QVERIFY(p.doc->agentActive());
    QCOMPARE(p.doc->changeSource(), QString("agent"));
    p.line(10);
    p.settle();
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QVERIFY(!p.doc->agentActive());
    {
        QMutexLocker locker(&mutex);
        QVERIFY(!sources.isEmpty());
        QVERIFY(!sources.contains(false));
        sources.clear();
    }

    p.line(20, "artist");
    p.settle();
    QMutexLocker locker(&mutex);
    QVERIFY(!sources.isEmpty());
    QVERIFY(!sources.contains(true));
}

void TestDocumentHistory::testHistoryMoveWhileBusyKeepsMove()
{
    PaintingDocument p;
    p.line(5, "artist");
    p.settle();

    QVERIFY(p.doc->beginAgentMove("busy"));
    for (int i = 0; i < 300; i++) {
        p.line(10 + i % 70);
    }
    // The artist presses Undo while the move's strokes are still running: Krita drops an undo on a busy image, so
    // the move stays open and nothing of it lands early (no step is pushed from the GUI thread meanwhile).
    QVERIFY(!p.image->isIdle());
    p.stack()->undo();
    QVERIFY(p.doc->agentMoveOpen());
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoIndex(), 2);
    QCOMPARE(p.doc->undoText(1), QString("Agent: busy"));
    QCOMPARE(commandsOf(p.stack()->command(1)).size(), 300);
}

void TestDocumentHistory::testImageReplacedWhileStrokesQueued()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("replaced"));
    for (int i = 0; i < 50; i++) {
        p.line(10 + i);
    }
    // The document's image is replaced while the move's strokes are still queued on the old one: the move is gone,
    // and none of its strokes reach the new image's history, now or when they finish.
    KisImageSP old = p.image;
    KisImageSP replacement = new KisImage(0, imageWidth, imageHeight, old->colorSpace(), "replacement");
    replacement->addNode(new KisPaintLayer(replacement, "paint", OPACITY_OPAQUE_U8));
    p.kisdoc->setCurrentImage(replacement);
    QVERIFY(!p.doc->endAgentMove());
    old->waitForDone();
    QCoreApplication::processEvents();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 0);
}

void TestDocumentHistory::testLegacyMacroStaysApart()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("macro"));
    p.line(10);
    p.settle();
    const ImageState agentFirst = ImageState::of(p);

    // The GUI opens a real undo macro (as KisNodeCommandsAdapter and KisSelectionManager do) while the move holds
    // collected work: the move's work goes in before the macro opens, never inside it.
    p.image->undoAdapter()->beginMacro(kundo2_noi18n("artist macro"));
    KisNodeSP layer = new KisPaintLayer(p.image, "macro layer", OPACITY_OPAQUE_U8);
    p.image->undoAdapter()->addCommand(new KisImageLayerAddCommand(p.image, layer, p.image->root(), nullptr));
    p.image->undoAdapter()->endMacro();
    p.line(20);
    QVERIFY(p.doc->endAgentMove());
    p.settle();

    QCOMPARE(p.doc->undoCount(), 3);
    QCOMPARE(p.doc->undoText(0), QString("Agent: macro"));
    QCOMPARE(p.doc->undoText(1), QString("artist macro"));
    QCOMPARE(p.doc->undoText(2), QString("Agent: macro (cont.)"));
    QCOMPARE(p.stack()->command(1)->childCount(), 1);

    // One undo each: the artist's macro undoes alone, leaving the move's first step applied.
    QVERIFY(p.doc->setUndoIndex(1));
    QVERIFY(ImageState::of(p) == agentFirst);
}

void TestDocumentHistory::testPixelWriteAfterStrokeOnSameLayer()
{
    PaintingDocument p;
    p.line(5, "artist");
    const ImageState before = ImageState::of(p);

    // A stroke and then a pixel write on the same layer, the write issued while the stroke may still be running:
    // the write goes after the stroke, and one undo of the move restores the layer exactly.
    QVERIFY(p.doc->beginAgentMove("stroke then pixels"));
    for (int i = 0; i < 20; i++) {
        p.paint->paintLine(QPointF(0, 20 + i), QPointF(110, 20 + i), 1.0, 1.0, "ForegroundColor");
    }
    QVERIFY(p.paint->setPixelData(pixels(40, 20, Qt::red), 30, 25, 40, 20));
    p.paint->paintLine(QPointF(0, 30), QPointF(110, 40), 1.0, 1.0, "ForegroundColor");
    QVERIFY(p.doc->endAgentMove());
    const ImageState after = ImageState::of(p);
    QVERIFY(!(after == before));
    QCOMPARE(p.doc->undoCount(), 2);
    // In script order: the strokes, then the red write over them (a red pixel inside it, clear of the last line).
    QCOMPARE(p.paint->pixelData(60, 26, 1, 1), pixels(1, 1, Qt::red));

    QVERIFY(p.doc->setUndoIndex(1));
    QVERIFY(ImageState::of(p) == before);
    QVERIFY(p.doc->setUndoIndex(2));
    QVERIFY(ImageState::of(p) == after);
}

void TestDocumentHistory::testExportKeepsMove()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("exported"));
    p.line(10);
    p.settle();

    // An export (File > Export; libkis exportImage takes another path that never closes a move) is not a save: the
    // move stays open and whole.
    QTemporaryDir dir;
    QVERIFY(p.kisdoc->exportDocument(dir.filePath("export.kra"), "application/x-krita", false, false));
    p.kisdoc->waitForSavingToComplete();
    QVERIFY(p.doc->agentMoveOpen());
    p.line(20);
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("Agent: exported"));
    QCOMPARE(commandsOf(p.stack()->command(0)).size(), 2);
}

void TestDocumentHistory::testQueuedWorkIsNotIdle()
{
    PaintingDocument p;
    const int timeout = DocumentHistory::agentMoveIdleTimeout();
    DocumentHistory::setAgentMoveIdleTimeout(100);
    QVERIFY(p.doc->beginAgentMove("long"));
    // One long stroke, which sends nothing to the move until it ends.
    QList<StrokePoint> points;
    for (int i = 0; i < 4000; i++) {
        points << StrokePoint(QPointF(5 + (i % 2) * 100, 5 + (i % 80)));
    }
    p.paint->paintPolylineStroke(points, "ForegroundColor");
    // It runs for longer than the idle timeout: queued and running work counts as activity.
    QElapsedTimer busy;
    busy.start();
    while (!p.image->isIdle()) {
        QTest::qWait(10);
    }
    const qint64 busyMs = busy.elapsed();
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    DocumentHistory::setAgentMoveIdleTimeout(timeout);
    if (busyMs < 200) {
        QSKIP("the strokes finished within twice the timeout; the case needs a longer queue on this machine");
    }
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("Agent: long"));
    QCOMPARE(commandsOf(p.stack()->command(0)).size(), 1);
    qWarning() << "the long stroke ran" << busyMs << "ms";
}

void TestDocumentHistory::testScriptContinuesAfterSave()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("saved"));
    const int id = p.doc->agentMoveId();
    p.line(10);
    p.settle();

    QTemporaryDir dir;
    QVERIFY(p.kisdoc->saveAs(dir.filePath("saved.kra"), "application/x-krita", false));
    p.kisdoc->waitForSavingToComplete();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 1);

    // The script goes on painting after the save closed its move: the work joins the move again, as its
    // continuation, not as loose steps, and the script's own end closes it.
    QVERIFY(p.doc->agentMoveOpen());
    QCOMPARE(p.doc->agentMoveId(), id);
    p.line(20);
    p.line(30);
    QVERIFY(p.doc->agentActive());
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(0), QString("Agent: saved"));
    QCOMPARE(p.doc->undoText(1), QString("Agent: saved (cont.)"));
    QCOMPARE(commandsOf(p.stack()->command(1)).size(), 2);

    // A new move after an auto-close is a new move.
    QVERIFY(p.doc->beginAgentMove("next"));
    QVERIFY(p.doc->agentMoveId() != id);
    QVERIFY(p.doc->endAgentMove());
}

void TestDocumentHistory::testSetUndoIndexWithPenDown()
{
    PaintingDocument p;
    KisNodeSP artistLayer = p.addLayer("artist");
    p.line(10, "first");
    p.settle();

    // The artist holds the pen down: setUndoIndex does not freeze the window waiting for it; it gives up soon.
    ArtistStroke held(p, artistLayer, "held");
    held.line(20);
    QElapsedTimer timer;
    timer.start();
    QVERIFY(!p.doc->setUndoIndex(0));
    QVERIFY2(timer.elapsed() < 5000, qPrintable(QString::number(timer.elapsed())));
    QCOMPARE(p.doc->undoIndex(), 1);
    held.end();
    p.settle();
    QVERIFY(p.doc->setUndoIndex(1));
}

void TestDocumentHistory::testLandedStepsArePruned()
{
    PaintingDocument p;
    DocumentHistory *history = DocumentHistory::of(p.kisdoc);
    for (int i = 0; i < 20; i++) {
        QVERIFY(p.doc->beginAgentMove(QString("move %1").arg(i)));
        p.line(10 + i);
        QVERIFY(p.doc->endAgentMove());
        p.settle();
    }
    QCOMPARE(p.doc->undoCount(), 20);
    // Landed steps are let go once nothing can still send them commands: the hook walks only live ones.
    QVERIFY(p.doc->beginAgentMove("live"));
    QVERIFY2(history->trackedStepCount() <= 2, qPrintable(QString::number(history->trackedStepCount())));
    QVERIFY(p.doc->endAgentMove());
}

void TestDocumentHistory::testSelectionJoinsMove()
{
    PaintingDocument p;
    QVERIFY(p.doc->beginAgentMove("select"));
    p.line(10);
    Selection selection;
    selection.select(0, 0, 20, 20, 255);
    p.doc->setSelection(&selection);
    p.line(20);
    QVERIFY(p.doc->endAgentMove());
    p.settle();
    // Setting the global selection is part of the move, not a step of its own between its strokes.
    QCOMPARE(p.doc->undoCount(), 1);
    QCOMPARE(p.doc->undoText(0), QString("Agent: select"));
    QVERIFY(p.image->globalSelection());
    QVERIFY(p.doc->setUndoIndex(0));
    p.settle();
    QVERIFY(!p.image->globalSelection());
}

void TestDocumentHistory::testAgentStrokesWaitBehindHeldPen()
{
    PaintingDocument p;
    KisNodeSP artistLayer = p.addLayer("artist");

    // What happens today when the agent paints while the artist holds the pen down (startStroke's behaviour,
    // left to task 2.9): each agent stroke asks open strokes to end (Krita's tools decide whether to: freehand
    // keeps going; transform, move, crop, line and selection tools commit, and animation playback stops), and the
    // agent's strokes wait in the queue behind the artist's until the pen lifts. The history stays in order.
    ArtistStroke held(p, artistLayer, "held");
    held.line(10);
    QSignalSpy endRequests(p.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(p.doc->beginAgentMove("behind"));
    p.line(20);
    p.line(30);
    QVERIFY(p.doc->endAgentMove());
    QCOMPARE(endRequests.count(), 2);
    QTest::qWait(200);
    QCOMPARE(p.doc->undoCount(), 0); // nothing ran past the held stroke
    held.line(40);
    held.end();
    p.settle();
    QCOMPARE(p.doc->undoCount(), 2);
    QCOMPARE(p.doc->undoText(0), QString("held"));
    QCOMPARE(p.doc->undoText(1), QString("Agent: behind"));
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentHistory)
