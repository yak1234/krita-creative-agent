/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Times Node.paintStrokes() on a 6000x4500 document (openspec change krita-fork, task 2.4): 256 seeded strokes as the
// plugin's stroke_compare paints them (agent_accel._probe_strokes: a cubic of 60-240 px, size 40, opacity 0.6, a random
// colour), with the three presets the native helper was measured with. Not a unit test: run it through
// agent/run-tests.sh AgentStrokeJobsBenchmark; it prints one line per measurement, and appends them to the file named by
// AGENT_BENCHMARK_OUT when set (the runner shows only test verdicts).

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QElapsedTimer>
#include <QFile>
#include <QScopedPointer>
#include <QTimer>

#include <algorithm>
#include <cmath>
#include <random>

#include <Document.h>
#include <Node.h>
#include <StrokeJob.h>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KoColorSpaceRegistry.h>
#include <KoResource.h>
#include <kis_image.h>
#include <kis_paint_layer.h>

class AgentStrokeJobsBenchmark : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void benchmark();
};

namespace {

void report(const QString &line)
{
    qDebug().noquote() << line;
    const QString path = qEnvironmentVariable("AGENT_BENCHMARK_OUT");
    QFile out(path);
    if (!path.isEmpty() && out.open(QIODevice::Append | QIODevice::Text)) out.write((line + "\n").toUtf8());
}

QString presetName(const QString &shown)
{
    for (const QString &name : {shown, QString(shown).replace(' ', '_')}) {
        KoResourceSP found = KisGlobalResourcesInterface::instance()->source(ResourceType::PaintOpPresets)
                                 .bestMatch(QString(), QString(), name);
        if (found && found->valid()) return name;
    }
    return QString();
}

QVariantList probeStrokes(int count, int width, int height, double size)
{
    std::mt19937 rng(7);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    auto uniform = [&] (double low, double high) { return low + (high - low) * unit(rng); };
    QVariantList strokes;
    for (int i = 0; i < count; i++) {
        const double x = uniform(0.2, 0.8) * width, y = uniform(0.2, 0.8) * height;
        const double angle = uniform(0, 2 * M_PI), length = uniform(60, 240);
        const QString color = QString("#%1%2%3").arg(int(uniform(0, 255.99)), 2, 16, QChar('0'))
                                  .arg(int(uniform(0, 255.99)), 2, 16, QChar('0')).arg(int(uniform(0, 255.99)), 2, 16, QChar('0'));
        strokes << QVariantMap{{"start", QVariantList{x, y}},
                               {"segments", QVariantList{QVariant(QVariantList{x + length * 0.3, y - 20, x + length * 0.7 * std::cos(angle), y + 20,
                                                                      x + length * std::cos(angle), y + length * std::sin(angle)})}},
                               {"size", size}, {"opacity", 0.6}, {"flow", 1.0}, {"color", color}};
    }
    return strokes;
}

struct Run {
    double callMs = 0;
    double totalMs = 0;
    qint64 longestGapMs = 0;
};

/// Paints \p strokes on a new layer of \p doc, as \p jobs jobs, and waits with the event loop running.
Run paint(Document *doc, KisImageSP image, const QVariantList &strokes, const QString &preset, int jobs)
{
    KisPaintLayerSP layer = new KisPaintLayer(image, "bench", OPACITY_OPAQUE_U8);
    image->addNode(layer);
    image->waitForDone();
    QScopedPointer<Node> node(doc->nodeByName("bench"));
    Run run;
    if (!node) return run;
    QList<StrokeJob *> started;
    QElapsedTimer clock;
    clock.start();
    const int per = (strokes.size() + jobs - 1) / jobs;
    for (int first = 0; first < strokes.size(); first += per) {
        started << node->paintStrokes(strokes.mid(first, per), {{"preset", preset}});
    }
    run.callMs = clock.nsecsElapsed() / 1e6;
    qint64 last = clock.elapsed();
    for (StrokeJob *job : started) {
        while (job && !job->wait(2)) {
            QCoreApplication::processEvents();
            const qint64 now = clock.elapsed();
            run.longestGapMs = qMax(run.longestGapMs, now - last);
            last = now;
        }
    }
    run.totalMs = clock.nsecsElapsed() / 1e6;
    for (StrokeJob *job : started) {
        if (!job || job->state() != "done") qWarning() << "job" << (job ? job->state() + " " + job->errorString() : QString("null"));
    }
    qDeleteAll(started);
    node.reset();
    image->removeNode(layer);
    image->waitForDone();
    return run;
}

} // namespace

void AgentStrokeJobsBenchmark::benchmark()
{
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    KisImageSP image = new KisImage(0, 6000, 4500, KoColorSpaceRegistry::instance()->rgb8(), "bench");
    image->addNode(new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8));
    kisdoc->setCurrentImage(image);
    KisPart::instance()->addDocument(kisdoc.data(), false);
    QScopedPointer<Document> doc(new Document(kisdoc.data(), false));
    image->waitForDone();
    const QVariantList strokes = probeStrokes(256, 6000, 4500, 40);

    for (const QString &shown : {QString("b) Basic-5 Size Opacity"), QString("f) Bristles-3 Large Smooth"), QString("b) Basic-6 Details")}) {
        const QString preset = presetName(shown);
        if (preset.isEmpty()) {
            report(shown + ": not in the resource database");
            continue;
        }
        for (int jobs : {1, 4, 256}) {
            QVector<double> totals;
            Run last;
            for (int i = 0; i < 3; i++) {
                last = paint(doc.data(), image, strokes, preset, jobs);
                totals << last.totalMs;
            }
            std::sort(totals.begin(), totals.end());
            report(QString("%1, 256 strokes as %2 job(s): median %3 ms (min %4), call %5 ms, longest event-loop gap %6 ms")
                                      .arg(shown).arg(jobs).arg(totals[1], 0, 'f', 0).arg(totals[0], 0, 'f', 0)
                                      .arg(last.callMs, 0, 'f', 1).arg(last.longestGapMs));
        }
    }
    // 1400 strokes, each its own random colour: the call queues the first window only (its snapshots), the rest is
    // queued window by window while painting.
    const QVariantList many = probeStrokes(1400, 6000, 4500, 40);
    for (const QString &shown : {QString("b) Basic-5 Size Opacity"), QString("b) Basic-6 Details")}) {
        const QString preset = presetName(shown);
        if (preset.isEmpty()) continue;
        QVector<double> totals;
        Run last;
        for (int i = 0; i < 3; i++) {
            last = paint(doc.data(), image, many, preset, 1);
            totals << last.totalMs;
        }
        std::sort(totals.begin(), totals.end());
        report(QString("%1, 1400 strokes in random colours as 1 job: median %2 ms (min %3), call %4 ms, longest event-loop gap %5 ms")
                   .arg(shown).arg(totals[1], 0, 'f', 0).arg(totals[0], 0, 'f', 0).arg(last.callMs, 0, 'f', 1).arg(last.longestGapMs));
    }
    doc.reset();
    KisPart::instance()->removeDocument(kisdoc.data(), false);
}

KISTEST_TEMPORARY_HOME_MAIN(AgentStrokeJobsBenchmark)
#include "AgentStrokeJobsBenchmark.moc"
