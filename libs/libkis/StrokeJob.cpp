/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "StrokeJob.h"
#include "StrokeJobShared.h"

#include <QCoreApplication>
#include <QDeadlineTimer>
#include <QDebug>
#include <QMutexLocker>
#include <QThread>
#include <QVariantList>

#include <KisRunnableStrokeJobUtils.h>
#include <KisRunnableStrokeJobsInterface.h>
#include <KoCanvasResourceProvider.h>
#include <kis_image.h>
#include <strokes/KisFreehandStrokeInfo.h>

#include "DocumentChanges.h"

// ---- StrokeJobShared -------------------------------------------------------------------------------------------------

StrokeJobShared::StrokeJobShared()
{
    m_clock.start();
}

StrokeJobShared::~StrokeJobShared()
{
    QObject::disconnect(dirtyConnection);
}

QSharedPointer<StrokeJobShared> StrokeJobShared::failed(const QString &error, const QString &name)
{
    QSharedPointer<StrokeJobShared> shared(new StrokeJobShared());
    shared->name = name;
    shared->m_failed = true;
    shared->m_error = error;
    shared->m_endMs = 0;
    return shared;
}

void StrokeJobShared::strokeStarted(int index)
{
    QMutexLocker locker(&m_mutex);
    m_started++;
    m_running = index;
}

void StrokeJobShared::notifyLocked()
{
    const bool allEnded = m_painted + m_dropped >= total;
    if (allEnded && m_endMs < 0) {
        m_endMs = m_clock.elapsed();
    }
    m_changed.wakeAll();
    // Posted while holding the lock: the job's and the feeder's destructors take it before they go, and Qt drops
    // the events of a deleted object.
    if (m_job) {
        QMetaObject::invokeMethod(m_job, "slotStrokesEnded", Qt::QueuedConnection);
    }
    if (m_feeder) {
        StrokeJobFeeder *feeder = m_feeder;
        QMetaObject::invokeMethod(feeder, [feeder] () { feeder->pump(); }, Qt::QueuedConnection);
    }
}

void StrokeJobShared::strokeEnded(int index, bool painted)
{
    bool allEnded = false;
    {
        QMutexLocker locker(&m_mutex);
        if (m_running == index) m_running = -1;
        if (painted) {
            m_painted++;
        } else {
            m_dropped++;
        }
        allEnded = m_painted + m_dropped >= total;
        notifyLocked();
    }
    if (allEnded) {
        QObject::disconnect(dirtyConnection); // outside the lock: a report may be calling nodeDirty() now
    }
}

void StrokeJobShared::dropUnqueued(int count)
{
    if (count <= 0) return;
    bool allEnded = false;
    {
        QMutexLocker locker(&m_mutex);
        m_dropped += count;
        allEnded = m_painted + m_dropped >= total;
        notifyLocked();
    }
    if (allEnded) {
        QObject::disconnect(dirtyConnection);
    }
}

void StrokeJobShared::nodeDirty(KisImage *dirtyImage, KisNode *dirtyNode, const QVector<QRect> &rects)
{
    // Strokes on an image run one at a time, so while one of the job's strokes runs (up to its pixels landing),
    // the redraws its layer asks for are the job's.
    if (dirtyNode != node || m_running.load() < 0 || dirtyImage != image.data()) return;
    QRect united;
    for (const QRect &rect : rects) united |= rect;
    if (united.isEmpty()) return;
    QMutexLocker locker(&m_mutex);
    m_rect |= united;
}

QString StrokeJobShared::state() const
{
    QMutexLocker locker(&m_mutex);
    if (m_failed) return QStringLiteral("failed");
    if (m_painted + m_dropped >= total) {
        return m_painted == total ? QStringLiteral("done") : QStringLiteral("cancelled");
    }
    return m_started > 0 ? QStringLiteral("running") : QStringLiteral("queued");
}

int StrokeJobShared::done() const
{
    QMutexLocker locker(&m_mutex);
    return m_painted;
}

int StrokeJobShared::endedCount() const
{
    QMutexLocker locker(&m_mutex);
    return m_painted + m_dropped;
}

bool StrokeJobShared::ended() const
{
    QMutexLocker locker(&m_mutex);
    return m_failed || m_painted + m_dropped >= total;
}

QRect StrokeJobShared::changedRect() const
{
    QMutexLocker locker(&m_mutex);
    return m_rect;
}

QString StrokeJobShared::error() const
{
    QMutexLocker locker(&m_mutex);
    return m_error;
}

int StrokeJobShared::elapsedMs() const
{
    QMutexLocker locker(&m_mutex);
    return int(m_endMs >= 0 ? m_endMs : m_clock.elapsed());
}

bool StrokeJobShared::wait(int timeoutMs)
{
    QDeadlineTimer deadline(timeoutMs < 0 ? QDeadlineTimer(QDeadlineTimer::Forever) : QDeadlineTimer(timeoutMs));
    QMutexLocker locker(&m_mutex);
    while (!m_failed && m_painted + m_dropped < total) {
        if (!m_changed.wait(&m_mutex, deadline)) {
            return m_failed || m_painted + m_dropped >= total;
        }
    }
    return true;
}

void StrokeJobShared::waitForChange(int timeoutMs)
{
    QMutexLocker locker(&m_mutex);
    if (m_failed || m_painted + m_dropped >= total) return;
    m_changed.wait(&m_mutex, QDeadlineTimer(qMax(0, timeoutMs)));
}

void StrokeJobShared::setJob(StrokeJob *job)
{
    QMutexLocker locker(&m_mutex);
    m_job = job;
}

void StrokeJobShared::setFeeder(StrokeJobFeeder *feeder)
{
    QMutexLocker locker(&m_mutex);
    m_feeder = feeder;
}

StrokeJobFeeder *StrokeJobShared::feeder() const
{
    QMutexLocker locker(&m_mutex);
    return m_feeder;
}

// ---- StrokeJobStrokeStrategy ---------------------------------------------------------------------------------------

StrokeJobStrokeStrategy::StrokeJobStrokeStrategy(KisResourcesSnapshotSP resources,
                                                 const KUndo2MagicString &name,
                                                 QSharedPointer<StrokeJobShared> shared,
                                                 int index)
    : FreehandStrokeStrategy(resources, new KisFreehandStrokeInfo(), name)
    , m_shared(shared)
    , m_index(index)
{
    // The artist comes first: a job stroke never asks open strokes (a transform, a selection, a stroke being drawn)
    // to end, and Krita's own cancellation (Esc, a click in the Undo History, a closing view) leaves it alone; the
    // job is stopped by its cancel flag instead (StrokeJob::cancel(), the artist's undo, the document closing).
    setRequestsOtherStrokesToEnd(false);
    setAsynchronouslyCancellable(false);
    // Points are in image pixels; the canvas's wrap-around mode never repeats them.
    setSupportsWrapAroundMode(false);
}

StrokeJobStrokeStrategy::~StrokeJobStrokeStrategy()
{
    // A stroke dropped before it started is deleted without a callback.
    report(false);
}

void StrokeJobStrokeStrategy::initStrokeCallback()
{
    if (m_shared->cancelRequested) {
        m_skipped = true; // cancelled while queued: no painters, no transaction, nothing to undo
        return;
    }
    if (KisImageSP image = m_shared->image.toStrongRef()) {
        if (DocumentChanges *changes = DocumentChanges::existingForImage(image.data())) {
            changes->beginAgentWork();
            m_agentWork = true;
        }
    }
    m_shared->strokeStarted(m_index);
    FreehandStrokeStrategy::initStrokeCallback();
}

void StrokeJobStrokeStrategy::finishStrokeCallback()
{
    if (m_skipped) {
        report(false);
        return;
    }
    // The report is queued first: jobs a callback adds go in front of the stroke's remaining jobs, so the merge
    // and undo jobs the base queues next run before it (KisStroke::addMutatedJobs).
    if (m_shared->cancelRequested) {
        // Cancelled while painting: what this stroke painted is rolled back (its transaction is reverted, as when
        // Krita cancels a stroke), so the layer keeps whole strokes only.
        reportAfterQueuedJobs(false);
        FreehandStrokeStrategy::cancelStrokeCallback();
        return;
    }
    reportAfterQueuedJobs(true);
    FreehandStrokeStrategy::finishStrokeCallback();
}

void StrokeJobStrokeStrategy::cancelStrokeCallback()
{
    // Krita cancels the stroke itself only when its queue is torn down.
    if (!m_skipped) {
        FreehandStrokeStrategy::cancelStrokeCallback();
    }
    report(false);
}

void StrokeJobStrokeStrategy::doStrokeCallback(KisStrokeJobData *data)
{
    if (m_skipped) {
        return; // never started: nothing to paint or update
    }
    if (m_shared->cancelRequested && dynamic_cast<FreehandStrokeStrategy::Data *>(data)) {
        return; // a dab job after cancel(): paint nothing more
    }
    FreehandStrokeStrategy::doStrokeCallback(data);
}

KisStrokeStrategy *StrokeJobStrokeStrategy::createLodClone(int levelOfDetail)
{
    Q_UNUSED(levelOfDetail);
    return nullptr;
}

void StrokeJobStrokeStrategy::reportAfterQueuedJobs(bool painted)
{
    // A Wash-mode brush's finish only queues the merge of its temporary layer (and the undo command after it): the
    // stroke has landed once those jobs have run, so the report is a barrier after them, never cancelled. Called
    // before the base callback queues them (see finishStrokeCallback()).
    QVector<KisRunnableStrokeJobData *> jobs;
    KritaUtils::addJobBarrier(jobs, [this, painted] () { report(painted); });
    Q_FOREACH (KisRunnableStrokeJobData *job, jobs) {
        job->setCancellable(false);
    }
    runnableJobsInterface()->addRunnableJobs(jobs);
}

void StrokeJobStrokeStrategy::report(bool painted)
{
    if (m_reported.exchange(true)) return;
    if (m_agentWork) {
        m_agentWork = false;
        if (KisImageSP image = m_shared->image.toStrongRef()) {
            if (DocumentChanges *changes = DocumentChanges::existingForImage(image.data())) {
                changes->endAgentWork();
            }
        }
    }
    m_shared->strokeEnded(m_index, painted);
}

// ---- StrokeJob -----------------------------------------------------------------------------------------------------

namespace {
bool onGuiThread()
{
    return QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread();
}
} // namespace

StrokeJob::StrokeJob(QSharedPointer<StrokeJobShared> shared, QObject *parent)
    : QObject(parent)
    , m_shared(shared)
{
    m_shared->setJob(this);
    if (m_shared->ended()) {
        // A failed or empty job tells its end from the event loop, as any other job does.
        QMetaObject::invokeMethod(this, "slotStrokesEnded", Qt::QueuedConnection);
    }
}

StrokeJob::~StrokeJob()
{
    m_shared->setJob(nullptr);
}

QString StrokeJob::state() const
{
    return m_shared->state();
}

int StrokeJob::strokesDone() const
{
    return m_shared->done();
}

int StrokeJob::strokesTotal() const
{
    return m_shared->total;
}

double StrokeJob::progress() const
{
    return m_shared->total > 0 ? double(m_shared->done()) / m_shared->total : 1.0;
}

QRect StrokeJob::changedRect() const
{
    return m_shared->changedRect();
}

QString StrokeJob::errorString() const
{
    return m_shared->error();
}

QString StrokeJob::name() const
{
    return m_shared->name;
}

int StrokeJob::elapsedMs() const
{
    return m_shared->elapsedMs();
}

QVariantMap StrokeJob::status() const
{
    const QRect rect = changedRect();
    return QVariantMap{
        {QStringLiteral("state"), state()},
        {QStringLiteral("done"), strokesDone()},
        {QStringLiteral("total"), strokesTotal()},
        {QStringLiteral("progress"), progress()},
        {QStringLiteral("rect"), QVariantList{rect.x(), rect.y(), rect.width(), rect.height()}},
        {QStringLiteral("error"), errorString()},
        {QStringLiteral("name"), name()},
        {QStringLiteral("ms"), elapsedMs()},
    };
}

bool StrokeJob::wait(int timeoutMs)
{
    if (!onGuiThread()) {
        return m_shared->wait(timeoutMs); // the GUI thread queues the job's windows meanwhile
    }
    // On the GUI thread a wait never runs without a limit: some strokes need the GUI thread to finish
    // (KisGuiContextCommand, the autosave's clone), and so does the job's own next window, which this loop queues.
    if (timeoutMs < 0) {
        qWarning() << "StrokeJob.wait() without a timeout on the GUI thread only polls: pass a timeout, poll state(),"
                      " or connect to finished";
        timeoutMs = 0;
    }
    QDeadlineTimer deadline(timeoutMs);
    Q_FOREVER {
        if (StrokeJobFeeder *feeder = m_shared->feeder()) feeder->pump();
        if (m_shared->ended()) {
            emitFinishedOnce();
            return true;
        }
        const qint64 left = deadline.remainingTime();
        if (left <= 0) return false;
        m_shared->waitForChange(int(qMin<qint64>(left, 10)));
    }
}

bool StrokeJob::cancel()
{
    if (m_shared->ended()) return false;
    // Not KisImage::cancelStroke(): the queued strokes are already ended, and cancelling an ended stroke would count
    // it out of the queue's open strokes a second time. Each stroke reads the flag instead, and the feeder drops the
    // strokes not queued yet.
    m_shared->cancelRequested = true;
    if (onGuiThread()) {
        if (StrokeJobFeeder *feeder = m_shared->feeder()) feeder->pump();
    } else {
        QSharedPointer<StrokeJobShared> shared = m_shared;
        QMetaObject::invokeMethod(QCoreApplication::instance(), [shared] () {
            if (StrokeJobFeeder *feeder = shared->feeder()) feeder->pump();
        }, Qt::QueuedConnection);
    }
    return true;
}

void StrokeJob::slotStrokesEnded()
{
    reportProgress();
    if (m_shared->ended()) {
        emitFinishedOnce();
    }
}

void StrokeJob::reportProgress()
{
    const int done = m_shared->done();
    if (done == m_reportedDone) return;
    m_reportedDone = done;
    Q_EMIT progressChanged(done, m_shared->total);
}

void StrokeJob::emitFinishedOnce()
{
    if (m_finishedEmitted) return;
    reportProgress();
    m_finishedEmitted = true;
    Q_EMIT finished(m_shared->state());
}
