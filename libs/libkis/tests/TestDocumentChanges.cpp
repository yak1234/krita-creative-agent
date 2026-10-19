/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentChanges.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QCryptographicHash>
#include <QElapsedTimer>
#include <QScopedPointer>

#include <limits>
#include <thread>
#include <vector>

#include "ChangeEventRecorder.h"

#include <Document.h>
#include <DocumentChanges.h>
#include <Notifier.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_fill_painter.h>
#include <KisImageChangeReports.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>

namespace {

/// A document with a red layer under an empty one (so the image composites into a projection of its own), added to
/// KisPart with a notification, its first composite done and reported.
struct ChangesDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;

    explicit ChangesDocument(const QSize &size = QSize(200, 150))
        : kisdoc(KisPart::instance()->createDocument())
    {
        image = new KisImage(0, size.width(), size.height(), KoColorSpaceRegistry::instance()->rgb8(), "test");
        layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(image->bounds(), KoColor(Qt::red, layer->colorSpace()));
        image->addNode(layer);
        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data());
        doc.reset(new Document(kisdoc.data(), false));
        image->refreshGraphAsync();
        settle();
    }

    ~ChangesDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    /// Writes blue into \p rect of the layer and asks for it to be redrawn, as a script's setPixelData does.
    void paint(const QRect &rect)
    {
        layer->paintDevice()->fill(rect, KoColor(Qt::blue, layer->colorSpace()));
        layer->setDirty(rect);
    }

    /// Waits for the image, then lets queued reports reach the GUI thread.
    void settle()
    {
        image->waitForDone();
        for (int i = 0; i < 5; i++) {
            QCoreApplication::sendPostedEvents();
            QCoreApplication::processEvents();
        }
    }
};

QString rectText(const QRect &rect)
{
    return QString("%1,%2 %3x%4").arg(rect.x()).arg(rect.y()).arg(rect.width()).arg(rect.height());
}

} // namespace

void TestDocumentChanges::testRevisionStartsPositiveAndStaysWithoutChanges()
{
    ChangesDocument d;
    const qint64 first = d.doc->revision();
    QVERIFY2(first >= 1, qPrintable(QString::number(first)));
    d.settle();
    QCOMPARE(d.doc->revision(), first);
    QVERIFY(d.doc->changedRect(first).isEmpty());
}

void TestDocumentChanges::testRevisionIncreasesOnPixelChange()
{
    ChangesDocument d;
    const qint64 before = d.doc->revision();
    d.paint(QRect(10, 20, 30, 40));
    d.doc->waitForDone(); // the revision counts the change once the image is done, without the event loop
    const qint64 after = d.doc->revision();
    QVERIFY2(after > before, qPrintable(QString("%1 -> %2").arg(before).arg(after)));
    d.settle();
    QCOMPARE(d.doc->revision(), after);
}

void TestDocumentChanges::testChangedRectIsExactlyTheChangedArea()
{
    ChangesDocument d;
    const qint64 before = d.doc->revision();
    const QRect area(10, 20, 30, 40);
    d.paint(area);
    d.settle();
    QCOMPARE(rectText(d.doc->changedRect(before)), rectText(area));
    QVERIFY(d.doc->changedRect(d.doc->revision()).isEmpty());
}

void TestDocumentChanges::testChangedRectUnitesAreasSinceRevision()
{
    ChangesDocument d;
    const qint64 start = d.doc->revision();
    const QRect first(0, 0, 10, 10);
    const QRect second(100, 100, 20, 10);
    d.paint(first);
    d.settle();
    const qint64 middle = d.doc->revision();
    d.paint(second);
    d.settle();
    QCOMPARE(rectText(d.doc->changedRect(start)), rectText(first | second));
    QCOMPARE(rectText(d.doc->changedRect(middle)), rectText(second));
}

void TestDocumentChanges::testChangedRectIsWholeImageWhenHistoryIsGone()
{
    ChangesDocument d;
    const QRect whole = d.image->bounds();
    QCOMPARE(rectText(d.doc->changedRect(0)), rectText(whole));
    QCOMPARE(rectText(d.doc->changedRect(-5)), rectText(whole));

    const qint64 start = d.doc->revision();
    // More reports than the history keeps: each 1 px paint in a new column is one report.
    for (int i = 0; i <= DocumentChanges::kHistoryLimit; i++) {
        d.paint(QRect((i % 66) * 3, (i / 66) * 2, 1, 1)); // apart, so they are not merged
        d.image->waitForDone();
    }
    d.settle();
    QCOMPARE(rectText(d.doc->changedRect(start)), rectText(whole));
    // Recent history is still exact.
    const qint64 recent = d.doc->revision();
    d.paint(QRect(5, 140, 2, 2));
    d.settle();
    QCOMPARE(rectText(d.doc->changedRect(recent)), rectText(QRect(5, 140, 2, 2)));
}

void TestDocumentChanges::testLongStrokeKeepsItsHistory()
{
    // A stroke reports many small touching areas; more of them than the history holds must still give its area,
    // not the whole image.
    ChangesDocument d;
    const qint64 start = d.doc->revision();
    const int dabs = DocumentChanges::kHistoryLimit + 1000;
    for (int i = 0; i < dabs; i++) {
        d.paint(QRect(i % 200, i / 200, 1, 1));
        d.image->waitForDone();
    }
    d.settle();
    QCOMPARE(rectText(d.doc->changedRect(start)), rectText(QRect(0, 0, 200, (dabs + 199) / 200)));
}

void TestDocumentChanges::testResizeChangesWholeImage()
{
    ChangesDocument d;
    const qint64 before = d.doc->revision();
    d.doc->resizeImage(0, 0, 300, 100);
    d.settle();
    QVERIFY(d.doc->revision() > before);
    QCOMPARE(rectText(d.doc->changedRect(before)), rectText(QRect(0, 0, 300, 100)));
}

void TestDocumentChanges::testWrappersShareTheReport()
{
    ChangesDocument d;
    Document other(d.kisdoc.data(), false);
    const qint64 before = d.doc->revision();
    QCOMPARE(other.revision(), before);
    d.paint(QRect(1, 2, 3, 4));
    d.settle();
    QCOMPARE(other.revision(), d.doc->revision());
    QCOMPARE(rectText(other.changedRect(before)), rectText(QRect(1, 2, 3, 4)));

    other.setAgentActive(true);
    QVERIFY(d.doc->agentActive());
    QCOMPARE(d.doc->changeSource(), QString("agent"));
    other.setAgentActive(false);
    QVERIFY(!d.doc->agentActive());
    QCOMPARE(d.doc->changeSource(), QString("artist"));
}

void TestDocumentChanges::testSourceIsAgentWhileActive()
{
    ChangesDocument d;
    Notifier notifier;
    ChangeEventRecorder recorder(&notifier, d.doc.data());
    QList<QVariantList> &changed = recorder.events("imageChanged");
    d.settle();
    recorder.clear();

    QCOMPARE(d.doc->changeSource(), QString("artist"));
    d.doc->setAgentActive(true);
    QVERIFY(d.doc->agentActive());
    d.paint(QRect(0, 0, 8, 8));
    d.settle();
    d.doc->setAgentActive(false);
    QCOMPARE(changed.count(), 1);
    QVERIFY(changed.at(0).at(0).toBool()); // this document
    QCOMPARE(rectText(changed.at(0).at(1).toRect()), rectText(QRect(0, 0, 8, 8)));
    QCOMPARE(changed.at(0).at(2).toString(), QString("agent"));

    recorder.clear();
    d.paint(QRect(50, 50, 4, 4));
    d.settle();
    QCOMPARE(changed.count(), 1);
    QCOMPARE(rectText(changed.at(0).at(1).toRect()), rectText(QRect(50, 50, 4, 4)));
    QCOMPARE(changed.at(0).at(2).toString(), QString("artist"));
}

void TestDocumentChanges::testAgentWorkNests()
{
    ChangesDocument d;
    DocumentChanges *changes = DocumentChanges::forImage(d.image);
    QVERIFY(changes);
    QCOMPARE(DocumentChanges::forImage(d.image), changes);
    QCOMPARE(DocumentChanges::existingForImage(d.image.data()), changes);

    changes->beginAgentWork();
    changes->beginAgentWork();
    QCOMPARE(changes->agentWorkDepth(), 2);
    changes->endAgentWork();
    QCOMPARE(d.doc->changeSource(), QString("agent"));
    QVERIFY(d.doc->agentActive());
    changes->endAgentWork();
    QCOMPARE(d.doc->changeSource(), QString("artist"));
    // An unmatched end is ignored and never makes the depth negative.
    changes->endAgentWork();
    QCOMPARE(changes->agentWorkDepth(), 0);

    // The switch and the work count are independent: either one makes the source "agent".
    changes->beginAgentWork();
    d.doc->setAgentActive(true);
    changes->endAgentWork();
    QCOMPARE(d.doc->changeSource(), QString("agent"));
    d.doc->setAgentActive(false);
    QCOMPARE(d.doc->changeSource(), QString("artist"));
}

void TestDocumentChanges::testSourceIsTakenWhenTheChangeIsRequested()
{
    // The agent paints, then switches off before Krita recomposites: the change is still the agent's.
    ChangesDocument d;
    Notifier notifier;
    ChangeEventRecorder recorder(&notifier, d.doc.data());
    d.settle();
    recorder.clear();

    d.image->barrierLock(); // holds the recomposite back
    d.doc->setAgentActive(true);
    d.paint(QRect(20, 20, 6, 6));
    d.doc->setAgentActive(false);
    d.image->unlock();
    d.settle();

    QCOMPARE(recorder.events("imageChanged").count(), 1);
    QCOMPARE(rectText(recorder.events("imageChanged").at(0).at(1).toRect()), rectText(QRect(20, 20, 6, 6)));
    QCOMPARE(recorder.events("imageChanged").at(0).at(2).toString(), QString("agent"));
    QCOMPARE(recorder.events("nodePixelsChanged").count(), 1);
    QCOMPARE(recorder.events("nodePixelsChanged").at(0).at(3).toString(), QString("agent"));
}

void TestDocumentChanges::testArtistRequestStaysArtistWhenAgentStartsLater()
{
    // The artist paints; the agent switches on before Krita recomposites: the change stays the artist's.
    ChangesDocument d;
    Notifier notifier;
    ChangeEventRecorder recorder(&notifier, d.doc.data());
    d.settle();
    recorder.clear();

    d.image->barrierLock();
    d.paint(QRect(60, 30, 5, 5));
    d.doc->setAgentActive(true);
    d.image->unlock();
    d.settle();
    d.doc->setAgentActive(false);

    QCOMPARE(recorder.events("imageChanged").count(), 1);
    QCOMPARE(recorder.events("imageChanged").at(0).at(2).toString(), QString("artist"));
    QCOMPARE(recorder.events("nodePixelsChanged").count(), 1);
    QCOMPARE(recorder.events("nodePixelsChanged").at(0).at(3).toString(), QString("artist"));
}

void TestDocumentChanges::testNodePixelsCarryTheSource()
{
    ChangesDocument d;
    Notifier notifier;
    ChangeEventRecorder recorder(&notifier, d.doc.data());
    QList<QVariantList> &pixels = recorder.events("nodePixelsChanged");
    d.settle();
    recorder.clear();

    d.doc->setAgentActive(true);
    d.paint(QRect(3, 4, 5, 6));
    d.settle();
    d.doc->setAgentActive(false);
    d.paint(QRect(30, 40, 5, 6));
    d.settle();

    QCOMPARE(pixels.count(), 2);
    QCOMPARE(rectText(pixels.at(0).at(2).toRect()), rectText(QRect(3, 4, 5, 6)));
    QCOMPARE(pixels.at(0).at(3).toString(), QString("agent"));
    QCOMPARE(rectText(pixels.at(1).at(2).toRect()), rectText(QRect(30, 40, 5, 6)));
    QCOMPARE(pixels.at(1).at(3).toString(), QString("artist"));
}

void TestDocumentChanges::testLevelOfDetailReportsAreInImagePixels()
{
    // During an instant-preview pass the image asks for redraws at a reduced resolution: level of detail 2 is a
    // quarter of the size. Reports must come out in image pixels, as the image's own updates do.
    ChangesDocument d;
    Notifier notifier;
    ChangeEventRecorder recorder(&notifier, d.doc.data());
    QList<QVariantList> &pixels = recorder.events("nodePixelsChanged");
    d.settle();
    recorder.clear();

    KisImageChangeReports::instance()->reportNodeDirty(d.image.data(), d.layer.data(), {QRect(10, 5, 4, 3)}, 2);
    d.settle();
    QCOMPARE(pixels.count(), 1);
    QCOMPARE(rectText(pixels.at(0).at(2).toRect()), rectText(QRect(40, 20, 16, 12)));
}

void TestDocumentChanges::benchmarkRevisionAgainstHash()
{
    if (qgetenv("KRITA_AGENT_BENCHMARK") != "1") {
        QSKIP("set KRITA_AGENT_BENCHMARK=1 to compare revision() with hashing a 6000x4500 projection");
    }
    ChangesDocument d(QSize(6000, 4500));
    const QRect bounds = d.image->bounds();

    QElapsedTimer timer;
    timer.start();
    QByteArray pixels(int(bounds.width()) * bounds.height() * 4, Qt::Uninitialized);
    d.image->projection()->readBytes(reinterpret_cast<quint8 *>(pixels.data()), bounds);
    const qint64 readMs = timer.elapsed();
    timer.restart();
    const QByteArray digest = QCryptographicHash::hash(pixels, QCryptographicHash::Sha256);
    const qint64 hashMs = timer.elapsed();
    QVERIFY(!digest.isEmpty());

    const int calls = 1000000;
    qint64 sum = 0;
    timer.restart();
    for (int i = 0; i < calls; i++) {
        sum += d.doc->revision();
    }
    const qint64 revisionNs = timer.nsecsElapsed();
    QVERIFY(sum > 0);

    timer.restart();
    const QRect changed = d.doc->changedRect(d.doc->revision() - 1);
    const qint64 changedRectNs = timer.nsecsElapsed();
    Q_UNUSED(changed);

    qInfo("6000x4500 projection (%.0f MB): read %lld ms + SHA-256 %lld ms = %lld ms; revision() %.1f ns per call "
          "(%d calls); changedRect() %lld ns",
          pixels.size() / 1e6, readMs, hashMs, readMs + hashMs, double(revisionNs) / calls, calls, changedRectNs);
}

void TestDocumentChanges::benchmarkDirtyRequests()
{
    // Run alone (./TestDocumentChanges benchmarkDirtyRequests) so that "no listener" really has none.
    if (qgetenv("KRITA_AGENT_BENCHMARK") != "1") {
        QSKIP("set KRITA_AGENT_BENCHMARK=1 and run this function alone to time 2000 dab redraw requests");
    }
    ChangesDocument d(QSize(3000, 2000));
    QVector<QRect> dabs;
    for (int i = 0; i < 2000; i++) {
        dabs << QRect(100 + i, 500 + (i % 300), 24, 24);
    }
    auto stroke = [&d, &dabs] () {
        QElapsedTimer timer;
        qint64 best = std::numeric_limits<qint64>::max();
        for (int round = 0; round < 5; round++) {
            d.settle();
            timer.start();
            for (const QRect &dab : dabs) {
                d.layer->setDirty(dab);
            }
            best = qMin(best, timer.nsecsElapsed());
            d.settle();
        }
        return best / 1000;
    };
    // The report alone, as requestProjectionUpdate() makes it: from 4 threads at once, 20000 dabs each.
    auto reports = [&d, &dabs] () {
        QElapsedTimer timer;
        timer.start();
        std::vector<std::thread> threads;
        for (int t = 0; t < 4; t++) {
            threads.emplace_back([&d, &dabs] () {
                for (int i = 0; i < 20000; i++) {
                    KisImageChangeReports::instance()->reportNodeDirty(d.image.data(), d.layer.data(),
                                                                       {dabs[i % dabs.size()]}, 0);
                }
            });
        }
        for (std::thread &thread : threads) thread.join();
        const qint64 ns = timer.nsecsElapsed();
        d.settle();
        return double(ns) / 80000;
    };

    const qint64 none = stroke();
    const double noneReport = reports();
    ChangesDocument other;
    QVERIFY(other.doc->revision() > 0); // a report on another image only
    const qint64 otherImage = stroke();
    const double otherReport = reports();
    QVERIFY(d.doc->revision() > 0); // a report on this image
    const qint64 thisImage = stroke();
    const double thisReport = reports();
    Notifier notifier; // and a Notifier queueing the events
    const qint64 withNotifier = stroke();
    const double notifierReport = reports();
    qInfo("2000 dab redraw requests (best of 5, request calls only): no listener %lld us; report on another image "
          "%lld us; report on this image %lld us; with a Notifier %lld us",
          none, otherImage, thisImage, withNotifier);
    qInfo("one report from 4 threads at once (wall time per report): no listener %.0f ns; report on another image "
          "%.0f ns; report on this image %.0f ns; with a Notifier %.0f ns",
          noneReport, otherReport, thisReport, notifierReport);
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentChanges)
