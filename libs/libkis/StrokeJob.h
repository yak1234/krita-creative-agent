/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_STROKEJOB_H
#define LIBKIS_STROKEJOB_H

#include <QObject>
#include <QRect>
#include <QSharedPointer>
#include <QString>
#include <QVariantMap>

#include "kritalibkis_export.h"
#include "libkis.h"

class StrokeJobShared;

/**
 * @brief A batch of brush strokes painting in the background, started by Node.paintStrokes().
 *
 * A job never blocks Krita's window: its strokes are queued in Krita's stroke system, one freehand stroke each, and
 * paint in Krita's worker threads while the window keeps responding. The job reports where it is:
 *
 * @code
 * job = layer.paintStrokes(strokes, {"preset": "b) Basic-5 Size", "name": "sky"})
 * while job.state() in ("queued", "running"):
 *     print(job.strokesDone(), "of", job.strokesTotal())   # or job.status() as one dict
 *     ...                                                   # answer the companion, do other work
 * job.wait(5000)                                            # waits for this job's strokes only
 * @endcode
 *
 * States:
 * <ul>
 * <li>"queued": the strokes are waiting behind other work in the image;</li>
 * <li>"running": at least one stroke has started;</li>
 * <li>"done": every stroke was painted;</li>
 * <li>"cancelled": the job ended with only some strokes painted (cancel(), or Krita cancelled them, for instance
 *     when the document closed). The strokes painted are always the first strokesDone() strokes, in order;</li>
 * <li>"failed": the job was refused and painted nothing (errorString() says why).</li>
 * </ul>
 *
 * The job belongs to the script. Dropping it does not stop its strokes: they paint to the end.
 */
class KRITALIBKIS_EXPORT StrokeJob : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(StrokeJob)

public:
    ~StrokeJob() override;

    /// For internal use: a job reporting \p shared (Node::paintStrokes() makes them).
    explicit StrokeJob(QSharedPointer<StrokeJobShared> shared, QObject *parent = nullptr);

public Q_SLOTS:

    /// "queued", "running", "done", "cancelled" or "failed". Any thread.
    QString state() const;

    /// The strokes painted so far.
    int strokesDone() const;

    /// The strokes in the job.
    int strokesTotal() const;

    /// strokesDone() / strokesTotal(), from 0 to 1 (1 for a job of no strokes).
    double progress() const;

    /**
     * The area the job's strokes have changed so far, in image pixels: the union of the areas the brush redrew on
     * the layer while the job's strokes ran. Empty before the first dab.
     */
    QRect changedRect() const;

    /// Why the job failed, or an empty string.
    QString errorString() const;

    /**
     * Why the job was cancelled, once it has been: "script" (cancel() was called, by a script or the plugin's Stop),
     * "undo" (the artist pressed Undo during the job), "document_closed" (the document was closing), or an empty
     * string while the job is not cancelled. The first reason stays. A cancel that came too late to stop anything
     * (every stroke had painted) leaves the job "done" and the reason empty.
     */
    QString cancelReason() const;

    /// The job's undo step name: the name given to paintStrokes(), or the open agent move's step.
    QString name() const;

    /// Milliseconds from paintStrokes() to the job's end, or to now while it runs.
    int elapsedMs() const;

    /**
     * Everything above in one map, for a bridge to send on: state, done, total, progress, rect ([x, y, w, h]), error,
     * cancelReason, name and ms.
     */
    QVariantMap status() const;

    /**
     * Blocks until this job's strokes have ended, or \p timeoutMs milliseconds pass. It waits for this job only,
     * never for the rest of the image's work as Document.waitForDone() does.
     *
     * Off the GUI thread (a script's own thread) a negative timeout waits without a limit. On the GUI thread a wait
     * always has a limit: the event loop does not run meanwhile, and some of Krita's strokes need it, so a negative
     * timeout there only polls (with a warning). On the GUI thread, poll state() or connect to finished instead.
     * @return true when the job has ended (done, cancelled or failed).
     */
    bool wait(int timeoutMs = -1);

    /**
     * Stops the job between strokes: strokes not started are dropped, and a stroke being painted is rolled back, so
     * the layer keeps exactly the first strokesDone() strokes. Returns at once; wait() for the end. Krita stops a job
     * the same way when the artist presses Undo during it (the undo is then carried out once the job has stopped)
     * and when its document closes; Esc and Krita's other stroke cancellations leave jobs alone.
     * @return true if the job was still painting.
     */
    bool cancel();

Q_SIGNALS:
    /// Emitted once in the job's thread when the job ends, with its final state.
    void finished(const QString &state);

    /// Emitted in the job's thread when more strokes have been painted: \p done out of \p total.
    void progressChanged(int done, int total);

private Q_SLOTS:
    void slotStrokesEnded();

private:
    void emitFinishedOnce();
    void reportProgress();

    QSharedPointer<StrokeJobShared> m_shared;
    bool m_finishedEmitted = false;
    int m_reportedDone = 0;
};

#endif // LIBKIS_STROKEJOB_H
