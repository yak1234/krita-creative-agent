/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestStrokeJobs.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>

#include <QAtomicInt>
#include <QElapsedTimer>
#include <QImage>
#include <QPointer>
#include <QScopedPointer>
#include <QSemaphore>
#include <QSignalSpy>
#include <QTimer>

#include <Document.h>
#include <Node.h>
#include <Selection.h>
#include <StrokeJob.h>
#include <DocumentChanges.h>

#include <QThread>
#include <atomic>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KoColorSpaceRegistry.h>
#include <brushengine/kis_paintop_preset.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_group_layer.h>
#include <kis_simple_stroke_strategy.h>
#include <kundo2stack.h>

namespace {

/**
 * A document registered with KisPart, as Krita's own are (so it has an undo history for scripts), with one empty paint
 * layer "paint", and its libkis wrappers. No main window or view exists in this test: every job paints without one.
 */
struct JobDocument {
    QPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;
    QScopedPointer<Node> paint;

    explicit JobDocument(int width = 200, int height = 100)
    {
        kisdoc = KisPart::instance()->createDocument();
        image = new KisImage(0, width, height, KoColorSpaceRegistry::instance()->rgb8(), "jobs");
        layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        image->addNode(layer);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc, false);
        doc.reset(new Document(kisdoc, false));
        paint.reset(doc->nodeByName("paint"));
        image->waitForDone();
        kisdoc->undoStack()->clear();
    }

    ~JobDocument()
    {
        paint.reset();
        doc.reset();
        if (image) image->waitForDone();
        QCoreApplication::processEvents();
        if (kisdoc) {
            KisPart::instance()->removeDocument(kisdoc, false);
            delete kisdoc;
        }
    }

    /// The layer's alpha, one byte per pixel, as an 8-bit image of the whole canvas.
    QImage alpha() const
    {
        const QImage rgba = layer->paintDevice()->convertToQImage(nullptr, 0, 0, image->width(), image->height());
        QImage out(rgba.size(), QImage::Format_Grayscale8);
        for (int y = 0; y < rgba.height(); y++) {
            const QRgb *in = reinterpret_cast<const QRgb *>(rgba.constScanLine(y));
            uchar *line = out.scanLine(y);
            for (int x = 0; x < rgba.width(); x++) line[x] = uchar(qAlpha(in[x]));
        }
        return out;
    }
};

/// Painted pixels (alpha above \p threshold) in column \p x of \p alpha.
int columnCount(const QImage &alpha, int x, int threshold = 32)
{
    int count = 0;
    for (int y = 0; y < alpha.height(); y++) count += alpha.constScanLine(y)[x] > threshold ? 1 : 0;
    return count;
}

/// Painted pixels in \p rect of \p alpha.
int areaCount(const QImage &alpha, const QRect &rect, int threshold = 32)
{
    int count = 0;
    const QRect clipped = rect & alpha.rect();
    for (int y = clipped.top(); y <= clipped.bottom(); y++) {
        for (int x = clipped.left(); x <= clipped.right(); x++) count += alpha.constScanLine(y)[x] > threshold ? 1 : 0;
    }
    return count;
}

/**
 * The name of one of Krita's own presets as the resource database holds it (the bundle's files use underscores
 * where Krita shows spaces), or an empty string.
 */
QString presetName(const QString &shown)
{
    for (const QString &name : {shown, QString(shown).replace(' ', '_')}) {
        KoResourceSP found = KisGlobalResourcesInterface::instance()->source(ResourceType::PaintOpPresets)
                                 .bestMatch(QString(), QString(), name);
        if (found && found->valid()) return name;
    }
    return QString();
}

/// A preset of Krita's that paints round, plain dabs whose size follows pressure.
QString pressurePreset()
{
    return presetName("b) Basic-5 Size");
}

/// A stroke along \p points ([x, y, pressure...] each), in \p color with \p size.
QVariantMap line(const QList<QVariantList> &points, double size = 20, const QString &color = "#000000")
{
    QVariantList list;
    for (const QVariantList &point : points) list << QVariant(point);
    return QVariantMap{{"points", list}, {"size", size}, {"color", color}};
}

/// \p count short horizontal strokes, one per row band, inside \p area.
QVariantList rows(int count, const QRect &area, double size = 4)
{
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        const double y = area.top() + (i % qMax(1, area.height())) + 0.5;
        strokes << line({{area.left() + 2, y}, {area.right() - 2, y}}, size);
    }
    return strokes;
}

/// Waits for \p job without blocking the event loop, for at most \p ms.
bool settle(StrokeJob *job, int ms = 20000)
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

struct GateState {
    QSemaphore open;
    QAtomicInt entered;
};

/// A stroke that holds Krita's stroke queue (an exclusive job) until released: work that keeps Krita busy.
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
        m_state->open.tryAcquire(1, 30000); // never hangs the test run
    }

private:
    QSharedPointer<GateState> m_state; // shared: a failed check never leaves the stroke on a destroyed semaphore
};

/// Holds \p image's stroke queue from here until release() or the end of the scope, whichever comes first.
class Gate
{
public:
    explicit Gate(KisImageSP image)
        : m_state(new GateState())
    {
        KisStrokeId gate = image->startStroke(new GateStroke(m_state));
        image->endStroke(gate);
    }
    ~Gate()
    {
        release();
    }
    void release()
    {
        if (m_released) return;
        m_released = true;
        m_state->open.release();
    }
    bool released() const
    {
        return m_released;
    }
    int entered() const
    {
        return m_state->entered.loadAcquire();
    }

private:
    QSharedPointer<GateState> m_state;
    bool m_released = false;
};

/// The artist's stroke: records how many strokes \p job had painted when it ran.
class ArtistStroke : public KisSimpleStrokeStrategy
{
public:
    ArtistStroke(StrokeJob *job, QSharedPointer<QAtomicInt> doneWhenRun)
        : KisSimpleStrokeStrategy(QLatin1String("test-artist"))
        , m_job(job)
        , m_doneWhenRun(doneWhenRun)
    {
        enableJob(JOB_INIT, true, KisStrokeJobData::SEQUENTIAL, KisStrokeJobData::EXCLUSIVE);
    }

    void initStrokeCallback() override
    {
        m_doneWhenRun->storeRelease(m_job->strokesDone());
    }

private:
    StrokeJob *m_job;
    QSharedPointer<QAtomicInt> m_doneWhenRun;
};

} // namespace

void TestStrokeJobs::testPaintsWithoutAView()
{
    const QString preset = pressurePreset();
    QVERIFY2(!preset.isEmpty(), "Krita's preset b) Basic-5 Size is in the resource database");
    JobDocument d;
    QVERIFY(d.paint);
    QVERIFY(!KisPart::instance()->currentMainwindow());

    QScopedPointer<StrokeJob> job(d.paint->paintStrokes({line({{20, 50}, {180, 50}})}, {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY2(job->state() != "failed", qPrintable(job->errorString()));
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("done"));
    QCOMPARE(job->strokesDone(), 1);
    QCOMPARE(job->strokesTotal(), 1);
    QCOMPARE(job->progress(), 1.0);
    QVERIFY(columnCount(d.alpha(), 100) > 10);
}

void TestStrokeJobs::testRefusesCleanly()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QVERIFY(d.paint);
    const QVariantList one = {line({{20, 50}, {180, 50}})};

    auto refused = [] (StrokeJob *raw, const QString &why) {
        QScopedPointer<StrokeJob> job(raw);
        if (!job) return QString("no job");
        if (job->state() != "failed") return QString("state %1").arg(job->state());
        if (!job->errorString().contains(why)) return QString("error \"%1\"").arg(job->errorString());
        if (!job->wait(0)) return QString("a failed job has not ended");
        return QString();
    };

    // No preset and no view to take one from.
    QCOMPARE(refused(d.paint->paintStrokes(one), "no active view"), QString());
    QCOMPARE(refused(d.paint->paintStrokes(one, {{"preset", "no such preset 2.4"}}), "no brush preset"), QString());
    QCOMPARE(refused(d.paint->paintStrokes(one, {{"preset", preset}, {"compositeOp", "no-such-op"}}), "blending mode"),
             QString());
    QCOMPARE(refused(d.paint->paintStrokes({QVariantMap{{"color", "#ff0000"}}}, {{"preset", preset}}), "stroke 0"),
             QString());
    QCOMPARE(refused(d.paint->paintStrokes({line({{1, 2}}), QVariantMap{{"points", QVariantList{QVariant(QVariantList{1})}}}},
                                           {{"preset", preset}}),
                     "stroke 1"),
             QString());
    QCOMPARE(refused(d.paint->paintStrokes({QVariantMap{{"points", QVariantList{QVariant(QVariantList{1, 2})}}, {"color", "not a colour"}}},
                                           {{"preset", preset}}),
                     "colour"),
             QString());

    // A group has no pixels of its own; a locked layer is not painted.
    d.image->addNode(new KisGroupLayer(d.image, "group", OPACITY_OPAQUE_U8));
    d.image->waitForDone();
    QScopedPointer<Node> group(d.doc->nodeByName("group"));
    QVERIFY(group);
    QCOMPARE(refused(group->paintStrokes(one, {{"preset", preset}}), "no pixels"), QString());
    d.layer->setUserLocked(true);
    QCOMPARE(refused(d.paint->paintStrokes(one, {{"preset", preset}}), "locked"), QString());
    d.layer->setUserLocked(false);

    // Nothing was painted or added to the history.
    d.image->waitForDone();
    QCOMPARE(d.layer->paintDevice()->exactBounds(), QRect());
    QCOMPARE(d.kisdoc->undoStack()->count(), 0);

    // An empty job is done at once.
    QScopedPointer<StrokeJob> empty(d.paint->paintStrokes({}, {{"preset", preset}}));
    QVERIFY(empty);
    QCOMPARE(empty->state(), QString("done"));
    QCOMPARE(empty->strokesTotal(), 0);
}

void TestStrokeJobs::testPressureTapers()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QVERIFY(d.paint);
    // Pressure 0.1 at both ends and 1 in the middle, with a 40 px brush.
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(
        {line({{20, 50, 0.1}, {100, 50, 1.0}, {180, 50, 0.1}}, 40)}, {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("done"));
    const QImage alpha = d.alpha();
    const int start = columnCount(alpha, 24), middle = columnCount(alpha, 100), end = columnCount(alpha, 176);
    QVERIFY2(middle >= 30, qPrintable(QString("middle %1 px").arg(middle)));
    QVERIFY2(start > 0 && start * 3 < middle, qPrintable(QString("start %1 px, middle %2 px").arg(start).arg(middle)));
    QVERIFY2(end > 0 && end * 3 < middle, qPrintable(QString("end %1 px, middle %2 px").arg(end).arg(middle)));

    // Without pressure the same stroke keeps one width.
    JobDocument flat;
    QScopedPointer<StrokeJob> even(flat.paint->paintStrokes({line({{20, 50}, {100, 50}, {180, 50}}, 40)}, {{"preset", preset}}));
    QVERIFY(settle(even.data()));
    const QImage flatAlpha = flat.alpha();
    QVERIFY(qAbs(columnCount(flatAlpha, 24) - columnCount(flatAlpha, 100)) <= 2);
}

namespace {

/// The painted pixels of one horizontal stroke with \p preset, at pen input \p pen for every point ([pressure,
/// xTilt, yTilt, rotation, speed, timeMs]), on a fresh layer.
int footprint(const QString &preset, const QVariantList &pen, double size, QString *error)
{
    JobDocument d(300, 160);
    QList<QVariantList> points;
    for (int i = 0; i <= 10; i++) points << (QVariantList{40 + 22 * i, 80} + pen);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes({line(points, size)}, {{"preset", preset}}));
    if (!job || !settle(job.data()) || job->state() != "done") {
        *error = job ? job->state() + ": " + job->errorString() : QString("no job");
        return -1;
    }
    return areaCount(d.alpha(), QRect(60, 0, 180, 160));
}

} // namespace

void TestStrokeJobs::testTiltWidensATiltPreset()
{
    // The helper's probe (task 0.5): tilt widens c) Pencil-5 Tilted from 2 to 9 px over 0 to 60 degrees.
    const QString preset = presetName("c) Pencil-5 Tilted");
    QVERIFY2(!preset.isEmpty(), "Krita's preset c) Pencil-5 Tilted is in the resource database");
    QString error;
    const int upright = footprint(preset, {1.0, 0.0, 0.0}, 10, &error);
    QVERIFY2(upright > 0, qPrintable(error));
    const int tilted = footprint(preset, {1.0, 60.0, 0.0}, 10, &error);
    QVERIFY2(tilted > 0, qPrintable(error));
    QVERIFY2(tilted > upright * 1.5, qPrintable(QString("upright %1 px, tilted %2 px").arg(upright).arg(tilted)));
}

void TestStrokeJobs::testSpeedThinsASpeedPreset()
{
    // The helper's probe (task 0.5): speed thins d) Ink-1 Precision from 48 to 28 px.
    const QString preset = presetName("d) Ink-1 Precision");
    QVERIFY2(!preset.isEmpty(), "Krita's preset d) Ink-1 Precision is in the resource database");
    QString error;
    const int slow = footprint(preset, {1.0, 0.0, 0.0, 0.0, 0.0}, 40, &error);
    QVERIFY2(slow > 0, qPrintable(error));
    const int fast = footprint(preset, {1.0, 0.0, 0.0, 0.0, 1.0}, 40, &error);
    QVERIFY2(fast > 0, qPrintable(error));
    QVERIFY2(fast * 1.2 < slow, qPrintable(QString("slow %1 px, fast %2 px").arg(slow).arg(fast)));
}

void TestStrokeJobs::testCubicSegmentsAndPerPointLists()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    // The plugin's paint_pass form: a start, cubic segments, and pressure as a per-point list.
    JobDocument d;
    const QVariantMap curve{{"start", QVariantList{20, 50}},
                            {"segments", QVariantList{QVariant(QVariantList{60, 10, 140, 90, 180, 50})}},
                            {"pressure", QVariantList{0.1, 1.0}},
                            {"size", 30}, {"color", "#ff0000"}, {"opacity", 1.0}};
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes({curve}, {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY2(job->state() != "failed", qPrintable(job->errorString()));
    QVERIFY(settle(job.data()));
    const QImage alpha = d.alpha();
    QVERIFY(columnCount(alpha, 24) < columnCount(alpha, 170));
    // The curve bends: above the straight line near its first quarter (t = 0.25: x 56, y 39), below it near its
    // third (t = 0.75: x 144, y 61).
    QVERIFY(areaCount(alpha, QRect(50, 28, 12, 14)) > 0);
    QCOMPARE(areaCount(alpha, QRect(50, 52, 12, 20)), 0);
    QVERIFY(areaCount(alpha, QRect(138, 62, 12, 8)) > 0);
    QCOMPARE(areaCount(alpha, QRect(138, 15, 12, 15)), 0);
    const QImage rgba = d.layer->paintDevice()->convertToQImage(nullptr, 0, 0, 200, 100);
    QVERIFY(qRed(rgba.pixel(176, 50)) > 200 && qGreen(rgba.pixel(176, 50)) < 60);

    // A list shorter than the points is refused.
    QVariantMap shortList = curve;
    shortList["pressure"] = QVariantList{0.5};
    QScopedPointer<StrokeJob> refused(d.paint->paintStrokes({shortList}, {{"preset", preset}}));
    QCOMPARE(refused->state(), QString("failed"));
    QVERIFY(refused->errorString().contains("pressure"));
}

void TestStrokeJobs::testChangedRectAndSignals()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes({line({{50, 40}, {120, 40}}, 10), line({{60, 70}, {80, 70}}, 10)},
                                                        {{"preset", preset}, {"name", "rect"}}));
    QVERIFY(job);
    QSignalSpy finished(job.data(), &StrokeJob::finished);
    QSignalSpy progress(job.data(), &StrokeJob::progressChanged);
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("done"));
    QTRY_COMPARE(finished.count(), 1);
    QCOMPARE(finished.first().first().toString(), QString("done"));
    QVERIFY(progress.count() >= 1);
    QCOMPARE(progress.last().at(0).toInt(), 2);

    const QRect painted = d.layer->paintDevice()->exactBounds();
    QVERIFY(!painted.isEmpty());
    const QRect changed = job->changedRect();
    QVERIFY2(changed.contains(painted), qPrintable(QString("changed %1,%2 %3x%4").arg(changed.x()).arg(changed.y())
                                                       .arg(changed.width()).arg(changed.height())));
    QVERIFY(QRect(30, 20, 110, 70).contains(changed));

    const QVariantMap status = job->status();
    QCOMPARE(status.value("state").toString(), QString("done"));
    QCOMPARE(status.value("done").toInt(), 2);
    QCOMPARE(status.value("total").toInt(), 2);
    QCOMPARE(status.value("name").toString(), QString("rect"));
    QCOMPARE(status.value("rect").toList().size(), 4);

    // A later wait() does not emit finished again.
    QVERIFY(job->wait(0));
    QCoreApplication::processEvents();
    QCOMPARE(finished.count(), 1);
}

void TestStrokeJobs::testSelectionClipsOrNone()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    // The document's own selection never clips a job: none given paints everywhere.
    QScopedPointer<Selection> global(new Selection());
    global->select(0, 0, 10, 10, 255);
    d.doc->setSelection(global.data());
    d.image->waitForDone();
    QScopedPointer<StrokeJob> everywhere(d.paint->paintStrokes({line({{20, 30}, {180, 30}}, 10)}, {{"preset", preset}}));
    QVERIFY(settle(everywhere.data()));
    QVERIFY(columnCount(d.alpha(), 150) > 0);

    // A selection given clips the strokes to it.
    QScopedPointer<Selection> left(new Selection());
    left->select(0, 0, 100, 100, 255);
    QScopedPointer<StrokeJob> clipped(
        d.paint->paintStrokes({line({{20, 70}, {180, 70}}, 10)}, {{"preset", preset}}, left.data()));
    QVERIFY(settle(clipped.data()));
    const QImage alpha = d.alpha();
    QVERIFY(areaCount(alpha, QRect(20, 60, 70, 20)) > 0);
    QCOMPARE(areaCount(alpha, QRect(102, 60, 98, 20)), 0);
}

void TestStrokeJobs::testWaitIsPerJob()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(rows(20, QRect(10, 10, 180, 40)), {{"preset", preset}}));
    QVERIFY(job);
    // Unrelated work queued after the job, which holds Krita until released: Document.waitForDone() would wait
    // for it, and so time out here.
    Gate gate(d.image);
    QElapsedTimer clock;
    clock.start();
    const bool waited = job->wait(15000);
    const qint64 waitedMs = clock.elapsed();
    const bool gateStillHolds = !gate.released(); // released only below
    gate.release();
    QVERIFY(waited);
    QVERIFY2(waitedMs < 10000, qPrintable(QString("wait() took %1 ms").arg(waitedMs)));
    QVERIFY(gateStillHolds);
    QCOMPARE(job->state(), QString("done"));
    QCOMPARE(job->strokesDone(), 20);
    d.image->waitForDone();
    QCOMPARE(gate.entered(), 1);
}

void TestStrokeJobs::testCancelLeavesAPrefix()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    const int count = 30;
    JobDocument d(20 * count + 20, 300);
    // One slow stroke per 20 px column, zigzagging down it: stroke i paints column i only.
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        QVariantList points;
        const double x = 10 + 20 * i + 10;
        for (int k = 0; k < 400; k++) points << QVariant(QVariantList{x + ((k % 2) ? 4 : -4), 10 + (k % 40) * 7});
        strokes << QVariantMap{{"points", points}, {"size", 8}};
    }
    Gate gate(d.image); // the job waits behind other work, then runs
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}, {"name", "columns"}}));
    QVERIFY(job);
    QCOMPARE(job->state(), QString("queued"));
    gate.release();
    QElapsedTimer clock;
    clock.start();
    while (job->strokesDone() < 3 && clock.elapsed() < 20000) QCoreApplication::processEvents();
    QVERIFY(job->cancel());
    QVERIFY(settle(job.data()));
    const int done = job->strokesDone();
    QVERIFY2(done >= 3 && done < count, qPrintable(QString("%1 strokes painted").arg(done)));
    QCOMPARE(job->state(), QString("cancelled"));
    QVERIFY(!job->cancel());

    d.image->waitForDone();
    const QImage alpha = d.alpha();
    for (int i = 0; i < count; i++) {
        const int painted = areaCount(alpha, QRect(10 + 20 * i + 2, 0, 16, 300));
        if (i < done) {
            QVERIFY2(painted > 100, qPrintable(QString("column %1 of the %2 painted is empty").arg(i).arg(done)));
        } else {
            QVERIFY2(painted == 0, qPrintable(QString("column %1 after the %2 painted has %3 px").arg(i).arg(done).arg(painted)));
        }
    }
    // The shorter pass is still one undo step, and undoing it clears it.
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("columns"));
    d.kisdoc->undoStack()->undo();
    d.image->waitForDone();
    QCOMPARE(d.layer->paintDevice()->exactBounds(), QRect());
}

void TestStrokeJobs::testJobIsOneNamedUndoStep()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(rows(50, QRect(10, 10, 180, 50)), {{"preset", preset}, {"name", "clouds"}}));
    QVERIFY(job);
    QCOMPARE(job->name(), QString("clouds"));
    QVERIFY(settle(job.data()));
    d.image->waitForDone();
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("clouds"));
    d.kisdoc->undoStack()->undo();
    d.image->waitForDone();
    QCOMPARE(d.layer->paintDevice()->exactBounds(), QRect());
}

void TestStrokeJobs::testAgentMoveOf1400StrokesIsOneStep()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d(400, 300);
    // An artist step before the move stays in the history.
    QScopedPointer<StrokeJob> before(d.paint->paintStrokes({line({{5, 290}, {395, 290}}, 4)}, {{"preset", preset}, {"name", "earlier"}}));
    QVERIFY(settle(before.data()));
    d.image->waitForDone();
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);

    QVERIFY(d.doc->beginAgentMove("sky"));
    QList<StrokeJob *> jobs;
    int total = 0;
    for (int pass = 0; pass < 6; pass++) {
        const int strokes = pass < 5 ? 234 : 1400 - 5 * 234;
        jobs << d.paint->paintStrokes(rows(strokes, QRect(10, 10 + 45 * pass, 380, 40), 2), {{"preset", preset}});
        QVERIFY(jobs.last());
        QCOMPARE(jobs.last()->name(), QString("Agent: sky"));
        total += strokes;
    }
    QCOMPARE(total, 1400);
    QVERIFY(d.doc->endAgentMove());
    for (StrokeJob *job : jobs) {
        QVERIFY(settle(job, 60000));
        QCOMPARE(job->state(), QString("done"));
    }
    qDeleteAll(jobs);
    d.image->waitForDone();
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 2);
    QCOMPARE(d.kisdoc->undoStack()->text(1), QString("Agent: sky"));
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("earlier"));

    // One undo removes all six passes and leaves the earlier step.
    d.kisdoc->undoStack()->undo();
    d.image->waitForDone();
    QCOMPARE(areaCount(d.alpha(), QRect(0, 0, 400, 280)), 0);
    QVERIFY(areaCount(d.alpha(), QRect(0, 280, 400, 20)) > 0);
}

void TestStrokeJobs::testNothingLostWhenBusy()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d(400, 200);
    Gate gate(d.image); // Krita busy with other work
    QList<StrokeJob *> jobs;
    for (int i = 0; i < 5; i++) {
        jobs << d.paint->paintStrokes(rows(40, QRect(10 + 76 * i, 20, 70, 160), 3), {{"preset", preset}, {"name", QString("pass %1").arg(i)}});
        QVERIFY(jobs.last());
        QCOMPARE(jobs.last()->state(), QString("queued"));
        QCOMPARE(jobs.last()->wait(0), false);
    }
    gate.release();
    for (StrokeJob *job : jobs) {
        QVERIFY(settle(job));
        QCOMPARE(job->state(), QString("done"));
        QCOMPARE(job->strokesDone(), 40);
    }
    // A job started while the others run is not lost either.
    QScopedPointer<StrokeJob> late(d.paint->paintStrokes(rows(10, QRect(10, 185, 380, 10), 3), {{"preset", preset}}));
    QVERIFY(settle(late.data()));
    QCOMPARE(late->strokesDone(), 10);
    d.image->waitForDone();
    const QImage alpha = d.alpha();
    for (int i = 0; i < 5; i++) {
        QVERIFY2(areaCount(alpha, QRect(10 + 76 * i, 20, 70, 160)) > 40 * 30,
                 qPrintable(QString("pass %1 is missing pixels").arg(i)));
    }
    qDeleteAll(jobs);
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 6);
}

void TestStrokeJobs::testWindowRespondsWhileAJobPaints()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d(1600, 1200);
    QVariantList strokes;
    for (int i = 0; i < 60; i++) {
        QVariantList points;
        for (int k = 0; k < 20; k++) points << QVariant(QVariantList{40 + (k % 2) * 1500, 20 + i * 18 + k * 0.2});
        strokes << QVariantMap{{"points", points}, {"size", 60}};
    }
    QElapsedTimer call;
    call.start();
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    const qint64 callMs = call.elapsed();
    QVERIFY(job);
    QVERIFY2(callMs < 1000, qPrintable(QString("paintStrokes took %1 ms to return").arg(callMs)));

    // The event loop runs while the job paints: a 10 ms timer keeps firing until the job's finished signal.
    int ticks = 0, ticksWhileRunning = 0;
    qint64 longestGap = 0, last = 0;
    QElapsedTimer clock;
    clock.start();
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, [&] () {
        const qint64 now = clock.elapsed();
        longestGap = qMax(longestGap, now - last);
        last = now;
        ticks++;
        if (job->state() == "running") ticksWhileRunning++;
    });
    QEventLoop loop;
    QObject::connect(job.data(), &StrokeJob::finished, &loop, &QEventLoop::quit);
    QTimer::singleShot(120000, &loop, &QEventLoop::quit);
    timer.start(10);
    loop.exec();
    timer.stop();
    QCOMPARE(job->state(), QString("done"));
    QVERIFY2(ticksWhileRunning >= 10, qPrintable(QString("%1 ticks while painting, of %2 in %3 ms")
                                                    .arg(ticksWhileRunning).arg(ticks).arg(clock.elapsed())));
    qDebug() << "job of" << job->strokesTotal() << "strokes:" << job->elapsedMs() << "ms; call" << callMs << "ms;"
             << ticks << "timer ticks, longest gap" << longestGap << "ms";
}

void TestStrokeJobs::testWashBrushLandsBeforeTheJobEnds()
{
    // A Wash-mode preset paints on a temporary layer merged after the stroke's finish: the job ends after that.
    const QString preset = presetName("b) Basic-5 Size Opacity");
    QVERIFY2(!preset.isEmpty(), "Krita's preset b) Basic-5 Size Opacity is in the resource database");
    JobDocument d(3000, 2000); // large strokes: the merge of the temporary layer takes a while
    DocumentChanges *changes = DocumentChanges::forImage(d.image);
    QVERIFY(changes);
    std::atomic<int> artistReports {0}, agentReports {0};
    KisNode *layer = d.layer.data();
    QMetaObject::Connection connection = QObject::connect(changes, &DocumentChanges::nodePixelsChangedAsync,
        [&] (KisNodeSP node, const QRect &, bool agent) {
            if (node.data() != layer) return;
            (agent ? agentReports : artistReports)++;
        });
    QVariantList strokes;
    for (int i = 0; i < 6; i++) strokes << line({{100, 150 + 300 * i}, {2900, 150 + 300 * i}}, 250);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY2(job->state() != "failed", qPrintable(job->errorString()));
    QVERIFY(job->wait(30000));
    // Read at once, with no event loop turn: the last stroke's pixels are there.
    const QImage alpha = d.alpha();
    const int lastRow = areaCount(alpha, QRect(100, 1600, 2800, 100));
    const QRect changed = job->changedRect();
    const QRect painted = d.layer->paintDevice()->exactBounds();
    QObject::disconnect(connection);
    QVERIFY2(lastRow > 100000, qPrintable(QString("the last stroke has %1 px when the job ends (%2, %3 of %4, painted %5,%6 %7x%8)")
                                              .arg(lastRow).arg(job->state()).arg(job->strokesDone()).arg(job->strokesTotal())
                                              .arg(painted.x()).arg(painted.y()).arg(painted.width()).arg(painted.height())));
    QVERIFY2(changed.contains(painted), "changedRect covers the merged pixels");
    QVERIFY(agentReports.load() > 0);
    QVERIFY2(artistReports.load() == 0, qPrintable(QString("%1 reports marked the artist's").arg(artistReports.load())));
    QCOMPARE(job->state(), QString("done"));

    // The moment a waiting thread wakes, the last stroke's pixels are on the layer (read at once, one pixel each).
    int missing = 0;
    QStringList alphas;
    for (int i = 0; i < 5; i++) {
        const QPoint centre(1500, 120 + 350 * i);
        QScopedPointer<StrokeJob> one(d.paint->paintStrokes({line({{200, centre.y()}, {2800, centre.y()}}, 120)},
                                                            {{"preset", preset}, {"color", "#ff0000"}}));
        QVERIFY(one);
        std::atomic<int> alphaAtEnd {-1};
        KisPaintDeviceSP device = d.layer->paintDevice();
        QScopedPointer<QThread> waiter(QThread::create([&] () {
            if (!one->wait(30000)) return;
            QColor colour;
            device->pixel(centre.x(), centre.y(), &colour);
            alphaAtEnd = colour.alpha();
        }));
        waiter->start();
        QElapsedTimer clock;
        clock.start();
        while (!waiter->isFinished() && clock.elapsed() < 30000) QCoreApplication::processEvents();
        QVERIFY(waiter->wait(1000));
        if (alphaAtEnd.load() < 200) missing++;
        d.image->waitForDone();
        QColor later;
        device->pixel(centre.x(), centre.y(), &later);
        alphas << QString("%1 %2 later %3").arg(alphaAtEnd.load()).arg(one->state()).arg(later.alpha());
    }
    QVERIFY2(missing == 0, qPrintable(QString("%1 of 5 jobs ended before their pixels (alpha %2)").arg(missing).arg(alphas.join(", "))));
}

void TestStrokeJobs::testKritasCancellationLeavesJobsAlone()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    Gate gate(d.image);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(rows(20, QRect(10, 10, 180, 40)), {{"preset", preset}}));
    QVERIFY(job);
    // Esc in a tool, a click in the Undo History docker, a view closing.
    d.image->requestStrokeCancellation();
    gate.release();
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("done"));
    QCOMPARE(job->strokesDone(), 20);
}

void TestStrokeJobs::testClosingTheDocumentStopsAJob()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    const int count = 200;
    QScopedPointer<JobDocument> d(new JobDocument(20 * 30 + 20, 300));
    KisNodeSP layer = d->layer;
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        QVariantList points;
        const double x = 20 + 20 * (i % 30);
        for (int k = 0; k < 400; k++) points << QVariant(QVariantList{x + ((k % 2) ? 4 : -4), 10 + (k % 40) * 7});
        strokes << QVariantMap{{"points", points}, {"size", 8}};
    }
    QScopedPointer<StrokeJob> job(d->paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(job);
    QElapsedTimer clock;
    clock.start();
    while (job->strokesDone() < 2 && clock.elapsed() < 20000) QCoreApplication::processEvents();
    QVERIFY(job->strokesDone() >= 2);
    // Close the document as Krita does, without waiting for the job first.
    clock.restart();
    d->paint.reset();
    d->doc.reset();
    KisPart::instance()->removeDocument(d->kisdoc, false);
    delete d->kisdoc;
    d->image = nullptr;
    const qint64 closeMs = clock.elapsed();
    QVERIFY(settle(job.data(), 5000));
    QCOMPARE(job->state(), QString("cancelled"));
    const int done = job->strokesDone();
    QVERIFY2(done < count, qPrintable(QString("%1 strokes painted").arg(done)));
    QVERIFY2(closeMs < 3000, qPrintable(QString("closing took %1 ms").arg(closeMs)));
    qDebug() << "closing mid-job:" << closeMs << "ms," << done << "of" << count << "strokes kept";
    d.reset();
}

void TestStrokeJobs::testGuiThreadWaitIsBounded()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    Gate gate(d.image);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(rows(10, QRect(10, 10, 180, 40)), {{"preset", preset}}));
    QVERIFY(job);
    // On the GUI thread a wait without a limit only polls: it can never hang the window.
    QElapsedTimer clock;
    clock.start();
    const bool ended = job->wait(-1);
    const qint64 ms = clock.elapsed();
    QVERIFY(!ended);
    QVERIFY2(ms < 1000, qPrintable(QString("wait(-1) on the GUI thread took %1 ms").arg(ms)));
    // Off the GUI thread it waits for the end.
    std::atomic<int> result {-1};
    QScopedPointer<QThread> waiter(QThread::create([&] () { result = job->wait(-1) ? 1 : 0; }));
    waiter->start();
    gate.release();
    clock.restart();
    while (!waiter->isFinished() && clock.elapsed() < 20000) QCoreApplication::processEvents();
    QVERIFY(waiter->wait(1000));
    QCOMPARE(result.load(), 1);
    QCOMPARE(job->state(), QString("done"));
}

void TestStrokeJobs::testJobsNeverAskArtistStrokesToEnd()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    QSignalSpy endRequests(d.image.data(), &KisImage::sigStrokeEndRequested);
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(rows(40, QRect(10, 10, 180, 40)), {{"preset", preset}}));
    QVERIFY(job);
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("done"));
    QCOMPARE(endRequests.count(), 0); // (KisImage::waitForDone() asks too, so the count is read before any)
}

void TestStrokeJobs::testRefusesFarPointsAndOversizedJobs()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    auto refused = [&] (const QVariantList &strokes, const QString &why) {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
        if (!job) return QString("no job");
        if (job->state() != "failed") return QString("state %1").arg(job->state());
        if (!job->errorString().contains(why)) return QString("error \"%1\"").arg(job->errorString());
        return QString();
    };
    QCOMPARE(refused({line({{20, 50}, {1e7, 50}}, 10)}, "outside"), QString());
    QCOMPARE(refused({line({{20, 50}, {180, 50}}, 10), line({{-1e7, -1e7}}, 10)}, "stroke 1"), QString());
    QCOMPARE(refused({QVariantMap{{"start", QVariantList{20, 50}},
                                  {"segments", QVariantList{QVariant(QVariantList{1e7, 0, 60, 60, 100, 50})}},
                                  {"size", 10}}},
                     "control point"),
             QString());
    // One brush size past the edge is allowed, as creative_validation allows it.
    QScopedPointer<StrokeJob> edge(d.paint->paintStrokes({line({{-9, 50}, {209, 50}}, 10)}, {{"preset", preset}}));
    QVERIFY2(edge->state() != "failed", qPrintable(edge->errorString()));
    QVERIFY(settle(edge.data()));
    // Too many strokes, or points in a stroke.
    QVariantList many;
    for (int i = 0; i < 10001; i++) many << line({{20, 50}}, 4);
    QCOMPARE(refused(many, "strokes"), QString());
    QVariantList points;
    for (int i = 0; i < 10001; i++) points << QVariant(QVariantList{20 + i % 100, 50});
    QCOMPARE(refused({QVariantMap{{"points", points}}}, "points"), QString());
    // A per-point list longer than the points is refused too.
    QCOMPARE(refused({QVariantMap{{"points", QVariantList{QVariant(QVariantList{20, 50}), QVariant(QVariantList{60, 50})}},
                                  {"pressure", QVariantList{0.5, 0.5, 0.5}}}},
                     "pressure"),
             QString());
    d.image->waitForDone();
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1); // only the edge job
}

void TestStrokeJobs::testArtistStrokeRunsBeforeTheJobEnds()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    const int count = 200;
    JobDocument d(20 * 30 + 20, 300);
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        QVariantList points;
        const double x = 20 + 20 * (i % 30);
        for (int k = 0; k < 100; k++) points << QVariant(QVariantList{x + ((k % 2) ? 4 : -4), 10 + (k % 40) * 7});
        strokes << QVariantMap{{"points", points}, {"size", 8}};
    }
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}}));
    QVERIFY(job);
    QElapsedTimer clock;
    clock.start();
    while (job->strokesDone() < 1 && clock.elapsed() < 20000) QCoreApplication::processEvents();
    QVERIFY(job->strokesDone() >= 1);
    // The artist starts a stroke while the job paints.
    QSharedPointer<QAtomicInt> doneWhenRun(new QAtomicInt(-1));
    KisStrokeId artist = d.image->startStroke(new ArtistStroke(job.data(), doneWhenRun));
    d.image->endStroke(artist);
    QVERIFY(settle(job.data(), 60000));
    QCOMPARE(job->state(), QString("done"));
    d.image->waitForDone();
    const int doneThen = doneWhenRun->loadAcquire();
    QVERIFY2(doneThen >= 0 && doneThen <= 2 * 32,
             qPrintable(QString("the artist's stroke ran after %1 of %2 job strokes").arg(doneThen).arg(count)));
}

void TestStrokeJobs::testArtistUndoStopsTheJobThenUndoes()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    const int count = 150;
    JobDocument d(20 * 30 + 20, 300);
    QScopedPointer<StrokeJob> earlier(d.paint->paintStrokes({line({{5, 295}, {600, 295}}, 4)}, {{"preset", preset}, {"name", "earlier"}}));
    QVERIFY(settle(earlier.data()));
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        QVariantList points;
        const double x = 20 + 20 * (i % 30);
        for (int k = 0; k < 200; k++) points << QVariant(QVariantList{x + ((k % 2) ? 4 : -4), 10 + (k % 38) * 7});
        strokes << QVariantMap{{"points", points}, {"size", 8}};
    }
    QScopedPointer<StrokeJob> job(d.paint->paintStrokes(strokes, {{"preset", preset}, {"name", "long"}}));
    QVERIFY(job);
    QElapsedTimer clock;
    clock.start();
    while (job->strokesDone() < 3 && clock.elapsed() < 20000) QCoreApplication::processEvents();
    QVERIFY(job->strokesDone() >= 3);
    // The artist presses Ctrl+Z.
    d.kisdoc->undoStack()->undo();
    QVERIFY(settle(job.data()));
    QCOMPARE(job->state(), QString("cancelled"));
    QVERIFY(job->strokesDone() < count);
    // Then the undo is carried out: the job's step is undone, the earlier step stays.
    QTRY_COMPARE_WITH_TIMEOUT(d.kisdoc->undoStack()->index(), 1, 10000);
    QCOMPARE(d.kisdoc->undoStack()->count(), 2);
    QCOMPARE(d.kisdoc->undoStack()->text(1), QString("long"));
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("earlier"));
    d.image->waitForDone();
    QCOMPARE(areaCount(d.alpha(), QRect(0, 0, 620, 285)), 0);
    QVERIFY(areaCount(d.alpha(), QRect(0, 285, 620, 15)) > 0);
}

void TestStrokeJobs::testEraseOpacityAndFlow()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    // compositeOp "erase" erases.
    QScopedPointer<StrokeJob> paint(d.paint->paintStrokes({line({{20, 30}, {180, 30}}, 16)}, {{"preset", preset}}));
    QVERIFY(settle(paint.data()));
    QScopedPointer<StrokeJob> erase(d.paint->paintStrokes({line({{80, 30}, {120, 30}}, 30)}, {{"preset", preset}, {"compositeOp", "erase"}}));
    QVERIFY2(erase->state() != "failed", qPrintable(erase->errorString()));
    QVERIFY(settle(erase.data()));
    QImage alpha = d.alpha();
    QCOMPARE(columnCount(alpha, 100), 0);
    QVERIFY(columnCount(alpha, 40) > 8);
    // One dab each: opacity and flow scale it; at 1 and 1 it is opaque.
    QScopedPointer<StrokeJob> dabs(d.paint->paintStrokes(
        {QVariantMap{{"points", QVariantList{QVariant(QVariantList{40, 75})}}, {"size", 20}, {"opacity", 1.0}, {"flow", 1.0}},
         QVariantMap{{"points", QVariantList{QVariant(QVariantList{100, 75})}}, {"size", 20}, {"opacity", 0.3}, {"flow", 1.0}},
         QVariantMap{{"points", QVariantList{QVariant(QVariantList{160, 75})}}, {"size", 20}, {"opacity", 1.0}, {"flow", 0.3}}},
        {{"preset", preset}}));
    QVERIFY(settle(dabs.data()));
    alpha = d.alpha();
    const int full = alpha.constScanLine(75)[40], lowOpacity = alpha.constScanLine(75)[100], lowFlow = alpha.constScanLine(75)[160];
    QVERIFY2(full > 240, qPrintable(QString("full %1").arg(full)));
    QVERIFY2(lowOpacity > 50 && lowOpacity < 110, qPrintable(QString("opacity 0.3: %1").arg(lowOpacity)));
    QVERIFY2(lowFlow > 50 && lowFlow < 110, qPrintable(QString("flow 0.3: %1").arg(lowFlow)));
}

void TestStrokeJobs::testOffGuiThreadRefusedAndALoneStartDabs()
{
    const QString preset = pressurePreset();
    QVERIFY(!preset.isEmpty());
    JobDocument d;
    // paintStrokes() is for the GUI thread.
    QString state, error;
    QScopedPointer<QThread> other(QThread::create([&] () {
        QScopedPointer<StrokeJob> job(d.paint->paintStrokes({line({{20, 50}, {180, 50}})}, {{"preset", preset}}));
        state = job ? job->state() : QString("no job");
        error = job ? job->errorString() : QString();
    }));
    other->start();
    QVERIFY(other->wait(10000));
    QCOMPARE(state, QString("failed"));
    QVERIFY(error.contains("GUI thread"));
    // A stroke of a start and no segments paints one dab.
    QScopedPointer<StrokeJob> dab(d.paint->paintStrokes({QVariantMap{{"start", QVariantList{100, 50}}, {"size", 20}}},
                                                        {{"preset", preset}}));
    QVERIFY2(dab->state() != "failed", qPrintable(dab->errorString()));
    QVERIFY(settle(dab.data()));
    const QRect bounds = d.layer->paintDevice()->exactBounds();
    QVERIFY(!bounds.isEmpty() && bounds.width() <= 24 && bounds.contains(QPoint(100, 50)));
}

KISTEST_TEMPORARY_HOME_MAIN(TestStrokeJobs)
