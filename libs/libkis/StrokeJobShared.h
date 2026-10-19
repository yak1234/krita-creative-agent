/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_STROKEJOBSHARED_H
#define LIBKIS_STROKEJOBSHARED_H

// Internal to libkis: the state a StrokeJob shares with its strokes, the feeder that queues them in windows, and
// their stroke strategy (Node::paintStrokes, NodeStrokeJobs.cpp; StrokeJob.cpp).

#include <QColor>
#include <QElapsedTimer>
#include <QHash>
#include <QMetaObject>
#include <QMutex>
#include <QObject>
#include <QPointF>
#include <QPointer>
#include <QRect>
#include <QSharedPointer>
#include <QString>
#include <QVector>
#include <QWaitCondition>

#include <atomic>

#include <brushengine/kis_paint_information.h>
#include <kis_types.h>
#include <kundo2magicstring.h>
#include <strokes/freehand_stroke.h>

class KisDocument;
class KoCanvasResourceProvider;
class ScriptStepHold;
class StrokeJob;
class StrokeJobFeeder;

/**
 * What a job's strokes report, from Krita's worker threads, and what the job reads, from any thread. Every stroke of
 * the job holds it, so it outlives a job the script has dropped.
 */
class StrokeJobShared
{
public:
    StrokeJobShared();
    ~StrokeJobShared();

    /// A job that failed before painting anything.
    static QSharedPointer<StrokeJobShared> failed(const QString &error, const QString &name);

    // ---- set once by Node::paintStrokes(), in the GUI thread, before the first stroke is queued ----
    QString name;
    int total = 0;
    KisImageWSP image;
    KisNode *node = nullptr;                 ///< compared only, never dereferenced from the reports
    QSharedPointer<KoCanvasResourceProvider> resources; ///< the job's own brush resources, kept for its strokes
    QMetaObject::Connection dirtyConnection;

    /// Set by StrokeJob::cancel(), or by Krita (the artist's undo, the document closing): strokes not yet painted
    /// paint nothing, and the one painting rolls back.
    std::atomic<bool> cancelRequested {false};

    // ---- reported by the strokes (any thread) ----
    void strokeStarted(int index);
    void strokeEnded(int index, bool painted);
    void nodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects);

    /// The feeder drops \p count strokes it will never queue (the job was cancelled first).
    void dropUnqueued(int count);

    // ---- read by the job (any thread) ----
    QString state() const;
    int done() const;
    int endedCount() const;                   ///< strokes painted or dropped
    bool ended() const;
    QRect changedRect() const;
    QString error() const;
    int elapsedMs() const;
    /// Waits until the job ends or \p timeoutMs passes (negative: no limit). Not for the GUI thread (StrokeJob::wait).
    bool wait(int timeoutMs);
    /// Waits at most \p timeoutMs for the next stroke to end, or the job to end.
    void waitForChange(int timeoutMs);

    /// Sets the job to tell about ended strokes (null: none). Holding the lock, so a job being deleted is never told.
    void setJob(StrokeJob *job);
    /// The same for the feeder.
    void setFeeder(StrokeJobFeeder *feeder);
    /// The feeder, while it runs. GUI thread (it is deleted there).
    StrokeJobFeeder *feeder() const;

private:
    void notifyLocked();

    mutable QMutex m_mutex;
    QWaitCondition m_changed;
    int m_started = 0;
    int m_painted = 0;
    int m_dropped = 0;
    bool m_failed = false;
    QString m_error;
    QRect m_rect;
    QElapsedTimer m_clock;
    qint64 m_endMs = -1;
    StrokeJob *m_job = nullptr;
    StrokeJobFeeder *m_feeder = nullptr;
    std::atomic<int> m_running {-1};          ///< the index of the stroke painting now, or -1
};

/// One stroke as given, read into Krita's input samples.
struct StrokeJobInput {
    QVector<KisPaintInformation> points;   ///< the start, then each segment's or line's end
    QVector<QPointF> controls;             ///< cubic segments: two control points per segment
    bool cubic = false;
    QColor color;
    qreal size = -1;
    qreal opacity = -1;
    qreal flow = -1;
};

/**
 * Queues a job's strokes from the GUI thread, at most kWindow at a time: when half of those have painted, it tops
 * them up again. An artist's stroke started meanwhile therefore waits behind at most kWindow job strokes instead of
 * the whole job. Deletes itself when the job has ended, releasing the job's hold on its undo step.
 */
class StrokeJobFeeder : public QObject
{
public:
    /// Strokes queued at a time. 32 of the plugin's usual strokes (40 px, 60-240 px long) paint in about 40 ms on
    /// a 6000x4500 canvas, so an artist's stroke waits at most about that long behind a job; topping up at half
    /// keeps the queue from running dry while the GUI thread queues more.
    static const int kWindow = 32;

    StrokeJobFeeder(QSharedPointer<StrokeJobShared> shared, KisImageSP image, KisNodeSP node, KisDocument *document);
    ~StrokeJobFeeder() override;

    // Set by Node::paintStrokes() before start().
    QVector<StrokeJobInput> inputs;
    KisPaintOpPresetSP basePreset;
    QString compositeOp;
    KisSelectionSP clip;
    QSharedPointer<ScriptStepHold> hold;
    KUndo2MagicString strokeName;

    void start();
    /// Queues the next window if the last one has ended, drops what is left after a cancel, and ends the feeding
    /// once every stroke has ended. GUI thread.
    void pump();
    bool finished() const { return m_finished; }
    KisImageWSP image() const { return m_image; }
    QSharedPointer<StrokeJobShared> shared() const { return m_shared; }

private:
    void queueWindow(int count);
    void finish();
    KisResourcesSnapshotSP snapshotFor(const StrokeJobInput &input);

    QSharedPointer<StrokeJobShared> m_shared;
    KisImageWSP m_image;
    KisNodeSP m_node;
    QPointer<KisDocument> m_document;
    int m_next = 0;
    bool m_finished = false;
    QHash<QString, KisPaintOpPresetSP> m_presets;
    QHash<QString, KisResourcesSnapshotSP> m_snapshots;
};

/**
 * One stroke of a job: Krita's freehand stroke, reporting its start and end to the job. It never makes a
 * level-of-detail copy, never asks the artist's strokes to end, is never cancelled by Krita's own cancellation
 * (Esc, the Undo History docker), and reports its end only after its pixels have landed: Wash-mode brushes merge
 * their temporary layer after finishStrokeCallback(), in jobs of their own.
 */
class StrokeJobStrokeStrategy : public FreehandStrokeStrategy
{
public:
    StrokeJobStrokeStrategy(KisResourcesSnapshotSP resources,
                            const KUndo2MagicString &name,
                            QSharedPointer<StrokeJobShared> shared,
                            int index);
    ~StrokeJobStrokeStrategy() override;

    void initStrokeCallback() override;
    void finishStrokeCallback() override;
    void cancelStrokeCallback() override;
    void doStrokeCallback(KisStrokeJobData *data) override;
    KisStrokeStrategy *createLodClone(int levelOfDetail) override;

private:
    void reportAfterQueuedJobs(bool painted);
    void report(bool painted);

    QSharedPointer<StrokeJobShared> m_shared;
    int m_index;
    std::atomic<bool> m_reported {false};
    bool m_agentWork = false;
    bool m_skipped = false; ///< cancelled before it began: it never set up its painters
};

#endif // LIBKIS_STROKEJOBSHARED_H
