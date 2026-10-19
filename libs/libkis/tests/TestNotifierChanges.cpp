/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestNotifierChanges.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QMap>
#include <QStringList>

#include <thread>
#include <QMetaMethod>
#include <QScopedPointer>
#include <QSharedPointer>
#include <QSignalSpy>

#include "ChangeEventRecorder.h"

#include <Document.h>
#include <Krita.h>
#include <Node.h>
#include <Notifier.h>
#include <Selection.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kundo2stack.h>

namespace {

/// A document with a red layer under an empty one, and a Notifier with a spy on each change event.
struct Watched {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;
    QScopedPointer<Notifier> notifier;
    QScopedPointer<ChangeEventRecorder> recorder;

    explicit Watched(bool notify = true)
        : kisdoc(KisPart::instance()->createDocument())
    {
        image = new KisImage(0, 200, 150, KoColorSpaceRegistry::instance()->rgb8(), "test");
        layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(image->bounds(), KoColor(Qt::red, layer->colorSpace()));
        image->addNode(layer);
        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        notifier.reset(new Notifier());
        KisPart::instance()->addDocument(kisdoc.data(), notify);
        doc.reset(new Document(kisdoc.data(), false));
        recorder.reset(new ChangeEventRecorder(notifier.data(), doc.data()));
        image->refreshGraphAsync();
        settle();
        clear();
    }

    ~Watched()
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

    void clear()
    {
        recorder->clear();
    }

    QList<QVariantList> &spy(const QString &name)
    {
        return recorder->events(name);
    }

    /// Checks that each named signal fired exactly once, and that each of \p silent did not fire.
    bool firedOnce(const QStringList &once, const QStringList &silent, QString *failure)
    {
        QStringList problems;
        for (const QString &name : once) {
            if (spy(name).count() != 1) problems << QString("%1 fired %2 times, not once").arg(name).arg(spy(name).count());
        }
        for (const QString &name : silent) {
            if (spy(name).count() != 0) problems << QString("%1 fired %2 times, not at all").arg(name).arg(spy(name).count());
        }
        *failure = problems.join("; ");
        return problems.isEmpty();
    }

    bool isThisDocument(const QList<QVariant> &arguments)
    {
        return arguments.at(0).toBool();
    }

    QString nodeName(const QList<QVariant> &arguments, int index = 1)
    {
        return arguments.at(index).toString();
    }
};

} // namespace

void TestNotifierChanges::testNodeAdded()
{
    Watched w;
    w.image->addNode(new KisPaintLayer(w.image, "added", OPACITY_OPAQUE_U8));
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodeAdded"}, {"nodeRemoved", "nodeChanged", "selectionChanged", "undoIndexChanged"},
                         &failure),
             qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("nodeAdded").at(0)));
    QCOMPARE(w.nodeName(w.spy("nodeAdded").at(0)), QString("added"));
}

void TestNotifierChanges::testNodeRemoved()
{
    Watched w;
    KisNodeSP added = new KisPaintLayer(w.image, "doomed", OPACITY_OPAQUE_U8);
    w.image->addNode(added);
    w.settle();
    w.clear();
    w.image->removeNode(added);
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodeRemoved"}, {"nodeAdded", "nodeChanged", "selectionChanged", "undoIndexChanged"},
                         &failure),
             qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("nodeRemoved").at(0)));
    QCOMPARE(w.nodeName(w.spy("nodeRemoved").at(0)), QString("doomed"));
}

void TestNotifierChanges::testNodePropertiesChanged()
{
    Watched w;
    w.layer->setName("renamed");
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodeChanged"},
                         {"nodeAdded", "nodeRemoved", "nodePixelsChanged", "selectionChanged", "undoIndexChanged"},
                         &failure),
             qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("nodeChanged").at(0)));
    QCOMPARE(w.nodeName(w.spy("nodeChanged").at(0)), QString("renamed"));
}

void TestNotifierChanges::testNodePixelsChanged()
{
    Watched w;
    const QRect area(10, 20, 30, 40);
    w.layer->paintDevice()->fill(area, KoColor(Qt::blue, w.layer->colorSpace()));
    w.layer->setDirty(area);
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodePixelsChanged", "imageChanged"},
                         {"nodeAdded", "nodeRemoved", "nodeChanged", "selectionChanged", "undoIndexChanged"}, &failure),
             qPrintable(failure));
    const QList<QVariant> pixels = w.spy("nodePixelsChanged").at(0);
    QVERIFY(w.isThisDocument(pixels));
    QCOMPARE(w.nodeName(pixels), QString("layer"));
    QCOMPARE(pixels.at(2).toRect(), area);
    QCOMPARE(pixels.at(3).toString(), QString("artist"));
    QCOMPARE(w.spy("imageChanged").at(0).at(1).toRect(), area);
}

void TestNotifierChanges::testSelectionChanged()
{
    Watched w;
    Selection selection;
    selection.select(10, 10, 50, 40, 255);
    w.doc->setSelection(&selection);
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"selectionChanged"}, {"nodeRemoved"}, &failure), qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("selectionChanged").at(0)));
    // The global selection lives in a selection mask, which may be added and changed; the layers are not touched.
    for (const QList<QVariant> &changed : w.spy("nodeChanged")) {
        QVERIFY2(w.nodeName(changed) != "layer" && w.nodeName(changed) != "empty", qPrintable(w.nodeName(changed)));
    }

    w.clear();
    w.doc->setSelection(nullptr);
    w.settle();
    QVERIFY2(w.firedOnce({"selectionChanged"}, {}, &failure), qPrintable(failure));
}

void TestNotifierChanges::testUndoIndexChanged()
{
    Watched w;
    KUndo2Stack *stack = w.kisdoc->undoStack();
    const int start = stack->index();

    Selection selection;
    selection.select(0, 0, 20, 20, 255);
    w.doc->setSelection(&selection);
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"undoIndexChanged"}, {}, &failure), qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("undoIndexChanged").at(0)));
    QCOMPARE(w.spy("undoIndexChanged").at(0).at(1).toInt(), start + 1);

    w.clear();
    stack->undo();
    w.settle();
    QVERIFY2(w.firedOnce({"undoIndexChanged"}, {}, &failure), qPrintable(failure));
    QCOMPARE(w.spy("undoIndexChanged").at(0).at(1).toInt(), start);

    w.clear();
    stack->redo();
    w.settle();
    QVERIFY2(w.firedOnce({"undoIndexChanged"}, {}, &failure), qPrintable(failure));
    QCOMPARE(w.spy("undoIndexChanged").at(0).at(1).toInt(), start + 1);
}

void TestNotifierChanges::testDocumentModified()
{
    Watched w;
    QVERIFY(!w.kisdoc->isModified());

    Selection selection;
    selection.select(0, 0, 20, 20, 255);
    w.doc->setSelection(&selection);
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"documentModified"}, {}, &failure), qPrintable(failure));
    QVERIFY(w.isThisDocument(w.spy("documentModified").at(0)));
    QCOMPARE(w.spy("documentModified").at(0).at(1).toBool(), true);

    // Already modified: a second change does not report it again.
    w.clear();
    w.doc->setSelection(nullptr);
    w.settle();
    QVERIFY2(w.firedOnce({}, {"documentModified"}, &failure), qPrintable(failure));

    w.kisdoc->setModified(false);
    w.settle();
    QVERIFY2(w.firedOnce({"documentModified"}, {}, &failure), qPrintable(failure));
    QCOMPARE(w.spy("documentModified").at(0).at(1).toBool(), false);
}

void TestNotifierChanges::testFollowsDocumentAddedWithoutNotification()
{
    // Krita.createDocument() adds its document without a notification; asking for its revision starts the events.
    Watched w(false);
    QVERIFY(w.doc->revision() > 0);
    w.image->addNode(new KisPaintLayer(w.image, "late", OPACITY_OPAQUE_U8));
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodeAdded"}, {}, &failure), qPrintable(failure));
    QCOMPARE(w.nodeName(w.spy("nodeAdded").at(0)), QString("late"));
}

void TestNotifierChanges::testFollowsKritaCreateDocument()
{
    // A script's new document reports from the start, with no call to revision() first.
    Notifier notifier;
    QScopedPointer<Document> doc(Krita::instance()->createDocument(64, 48, "made", "RGBA", "U8", "", 72.0));
    QVERIFY(doc);
    ChangeEventRecorder recorder(&notifier, doc.data());
    Node *layer = doc->createNode("scripted", "paintlayer");
    QVERIFY(layer);
    QVERIFY(doc->rootNode()->addChildNode(layer, nullptr));
    delete layer;
    doc->waitForDone();
    for (int i = 0; i < 5; i++) {
        QCoreApplication::sendPostedEvents();
        QCoreApplication::processEvents();
    }
    QCOMPARE(recorder.order().filter("nodeAdded").join(" "), QString("nodeAdded:scripted"));
    QVERIFY(recorder.events("nodeAdded").at(0).at(0).toBool());
    doc->close();
}

void TestNotifierChanges::testInactiveNotifierIsSilent()
{
    Watched w;
    w.notifier->setActive(false);
    w.image->addNode(new KisPaintLayer(w.image, "quiet", OPACITY_OPAQUE_U8));
    w.layer->setName("quiet too");
    w.layer->setDirty(QRect(0, 0, 5, 5));
    w.settle();
    for (const QString &name : ChangeEventRecorder::names()) {
        QVERIFY2(w.spy(name).isEmpty(), qPrintable(name));
    }
}

void TestNotifierChanges::testWindowSignalsDeclared()
{
    // activeNodeChanged, toolChanged and brushPresetChanged need a main window with a view: checked live, not here.
    const QMetaObject *meta = &Notifier::staticMetaObject;
    for (const char *signature : {"activeNodeChanged(Document*,Node*)", "toolChanged(Document*,QString)",
                                  "brushPresetChanged(Document*,QString)"}) {
        const int index = meta->indexOfSignal(signature);
        QVERIFY2(index >= 0, signature);
        QCOMPARE(meta->method(index).methodType(), QMetaMethod::Signal);
    }
}

void TestNotifierChanges::testReplacedImageIsReleased()
{
    // Events hand out Document and Node objects; nothing of them may keep an image alive after a revert or reload.
    Watched w;
    w.image->addNode(new KisPaintLayer(w.image, "added", OPACITY_OPAQUE_U8));
    w.layer->setName("renamed");
    w.layer->setDirty(QRect(0, 0, 4, 4));
    w.settle();
    QVERIFY(w.spy("nodeAdded").count() == 1 && w.spy("nodeChanged").count() == 1);

    KisImageWSP old = w.image;
    KisImageSP replacement = new KisImage(0, 50, 40, KoColorSpaceRegistry::instance()->rgb8(), "replacement");
    replacement->addNode(new KisPaintLayer(replacement, "new", OPACITY_OPAQUE_U8));
    w.kisdoc->setCurrentImage(replacement);
    w.image = replacement;
    w.layer.clear();
    w.settle();
    QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    QVERIFY2(!old.isValid(), "the replaced image is still alive");

    // And the new image reports.
    w.clear();
    replacement->addNode(new KisPaintLayer(replacement, "after", OPACITY_OPAQUE_U8));
    w.settle();
    QCOMPARE(w.spy("nodeAdded").count(), 1);
    QCOMPARE(w.nodeName(w.spy("nodeAdded").at(0)), QString("after"));
}

void TestNotifierChanges::testRemovedGroupChildrenAreReleased()
{
    Watched w;
    KisNodeSP group = new KisGroupLayer(w.image, "group", OPACITY_OPAQUE_U8);
    KisNodeSP child = new KisPaintLayer(w.image, "child", OPACITY_OPAQUE_U8);
    w.image->addNode(group);
    w.image->addNode(child, group);
    w.settle();
    child->setName("child renamed");
    child->setDirty(QRect(0, 0, 3, 3));
    w.settle();
    QCOMPARE(w.spy("nodeChanged").count(), 1);

    KisNodeWSP groupAlive = group;
    KisNodeWSP childAlive = child;
    w.image->removeNode(group);
    group.clear();
    child.clear();
    w.settle();
    QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    QVERIFY2(!groupAlive.isValid(), "the removed group is still alive");
    QVERIFY2(!childAlive.isValid(), "the removed group's child is still alive");
}

void TestNotifierChanges::testEventsArriveInOrder()
{
    Watched w;
    QStringList *log = &w.recorder->order();

    // A node added from this thread, then an undo step: the node's event must come first.
    w.image->addNode(new KisPaintLayer(w.image, "first", OPACITY_OPAQUE_U8));
    Selection selection;
    selection.select(0, 0, 10, 10, 255);
    w.doc->setSelection(&selection);
    w.settle();
    QVERIFY2(log->indexOf("nodeAdded:first") >= 0, qPrintable(log->join(" ")));
    QVERIFY2(log->indexOf("nodeAdded:first") < log->indexOf("undoIndexChanged"), qPrintable(log->join(" ")));

    // A rename, then the removal: the rename is reported before the removal.
    log->clear();
    w.layer->setName("going");
    w.image->removeNode(w.layer);
    w.settle();
    QVERIFY2(log->indexOf("nodeChanged:going") >= 0, qPrintable(log->join(" ")));
    QVERIFY2(log->indexOf("nodeChanged:going") < log->indexOf("nodeRemoved:going"), qPrintable(log->join(" ")));
}

void TestNotifierChanges::testPixelEventsInOrder()
{
    Watched w;
    KisNodeSP layers[8];
    for (int i = 0; i < 8; i++) {
        layers[i] = new KisPaintLayer(w.image, QString("p%1").arg(i), OPACITY_OPAQUE_U8);
        w.image->addNode(layers[i]);
    }
    w.settle();
    QStringList *log = &w.recorder->order();
    for (int round = 0; round < 3; round++) {
        log->clear();
        for (int i = 0; i < 8; i++) layers[i]->setDirty(QRect(i, i, 2, 2));
        w.settle();
        QStringList expected;
        for (int i = 0; i < 8; i++) expected << QString("nodePixelsChanged:p%1").arg(i);
        QCOMPARE(log->filter("nodePixelsChanged").join(" "), expected.join(" "));
    }
}

void TestNotifierChanges::testChangesFromAnotherThread()
{
    Watched w;
    KisNodeSP layer = w.layer;
    std::thread worker([layer] () mutable {
        for (int i = 0; i < 50; i++) layer->setDirty(QRect(i, 0, 1, 1));
    });
    worker.join();
    w.settle();
    QString failure;
    QVERIFY2(w.firedOnce({"nodePixelsChanged", "imageChanged"}, {"nodeAdded", "nodeRemoved", "nodeChanged"}, &failure),
             qPrintable(failure));
    QCOMPARE(w.spy("nodePixelsChanged").at(0).at(2).toRect(), QRect(0, 0, 50, 1));
}

void TestNotifierChanges::testDocumentClosedWithEventsQueued()
{
    QScopedPointer<Watched> w(new Watched);
    Notifier *notifier = w->notifier.take();
    QSignalSpy added(notifier, SIGNAL(nodeAdded(Document*,Node*)));
    QSignalSpy pixels(notifier, SIGNAL(nodePixelsChanged(Document*,Node*,QRect,QString)));
    w->image->addNode(new KisPaintLayer(w->image, "late", OPACITY_OPAQUE_U8));
    w->layer->setDirty(QRect(0, 0, 4, 4));
    w->image->waitForDone();
    w.reset(); // the document closes before its events reach the GUI thread
    for (int i = 0; i < 5; i++) {
        QCoreApplication::sendPostedEvents();
        QCoreApplication::processEvents();
    }
    QCOMPARE(added.count(), 0);
    QCOMPARE(pixels.count(), 0);
    delete notifier;
}

KISTEST_TEMPORARY_HOME_MAIN(TestNotifierChanges)
