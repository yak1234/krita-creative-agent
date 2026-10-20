/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "ScriptWaits.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QThread>

#include <kis_debug.h>
#include <kis_image.h>
#include <kis_layer_utils.h>
#include <kis_processing_applicator.h>
#include <kis_simple_stroke_strategy.h>

namespace ScriptWaits
{

namespace
{
/// Waits nested on the GUI thread (a script run from an event handled during a wait): only the outermost handles
/// events.
thread_local int s_depth = 0;

bool onGuiThread()
{
    return QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread();
}

/// Waits until \p done says so or \p limit ms have passed, handling events on the GUI thread (outermost wait only).
template<typename Done, typename Block>
bool waitUntil(int limit, Done done, Block block)
{
    QElapsedTimer timer;
    timer.start();
    const bool handleEvents = onGuiThread() && s_depth == 0;
    s_depth++;
    while (!done() && timer.elapsed() < limit) {
        const int left = int(qMax<qint64>(0, limit - timer.elapsed()));
        if (handleEvents) {
            block(qMin(left, 5));
            QCoreApplication::processEvents(QEventLoop::AllEvents | QEventLoop::ExcludeSocketNotifiers);
        } else {
            block(left);
        }
    }
    s_depth--;
    return done();
}

/// A stroke that does nothing: its end, after everything queued before it, completes \p completion.
class MarkerStrokeStrategy : public KisSimpleStrokeStrategy
{
public:
    explicit MarkerStrokeStrategy(KisToolFunctions::CompletionSP completion)
        : KisSimpleStrokeStrategy(QLatin1String("krita-agent-script-wait"), kundo2_noi18n("Script wait"))
        , m_completion(completion)
    {
        // It waits for the jobs running before it (the operation's last ones and their redraws).
        enableJob(JOB_FINISH, true, KisStrokeJobData::BARRIER, KisStrokeJobData::EXCLUSIVE);
        enableJob(JOB_CANCEL, true);
        setRequestsOtherStrokesToEnd(false);
        setClearsRedoOnStart(false);
        setAsynchronouslyCancellable(false);
    }

    void finishStrokeCallback() override
    {
        m_completion->end(true);
    }

    void cancelStrokeCallback() override
    {
        m_completion->end(false);
    }

private:
    KisToolFunctions::CompletionSP m_completion;
};
} // namespace

bool wait(KisToolFunctions::CompletionSP completion)
{
    if (!completion) return false;
    return waitUntil(
        KisToolFunctions::waitLimit(),
        [&]() { return completion->finished(); },
        [&](int ms) { completion->wait(ms); });
}

bool waitForStroke(KisToolFunctions::CompletionSP completion, const char *call)
{
    if (wait(completion)) return true;
    completion->cancel();
    warnScript << call << "refused, not done within" << KisToolFunctions::waitLimit() / 1000.0
               << "s (another stroke, such as one the artist is drawing, held it back, or it was cancelled);"
               << "cancelled, nothing changed";
    return false;
}

bool waitForQueuedWork(KisImageSP image, const char *call, const QList<KisStrokeId> &started)
{
    if (!image) return false;
    if (image->locked()) return true; // a locked image runs nothing until unlocked; nothing to wait for
    KisLayerUtils::forceAllDelayedNodesUpdate(image->root()); // timed updates (filter masks) start now
    KisToolFunctions::CompletionSP marker(new KisToolFunctions::Completion());
    const KisStrokeId id = image->startStroke(new MarkerStrokeStrategy(marker));
    marker->setStroke(image, id);
    image->endStroke(id);
    if (!wait(marker)) {
        // Held back (behind a stroke the artist is drawing): the operation never runs, so later strokes of the script
        // cannot land in a changed image minutes from now.
        Q_FOREACH (const KisStrokeId &stroke, started) {
            image->cancelStroke(stroke);
        }
        marker->cancel();
        warnScript << call << "refused, not done within" << KisToolFunctions::waitLimit() / 1000.0
                   << "s (another stroke, such as one the artist is drawing, held it back); cancelled, nothing changed";
        return false;
    }
    // Everything the operation asked for (its redraws, run by the update scheduler outside the strokes) too: until
    // the image is idle. With redraws queued that takes as long as they do (up to the wait limit); with only strokes
    // in the way (the artist drawing again) it gives up after 2 s.
    QElapsedTimer idleTimer;
    idleTimer.start();
    const bool idle = waitUntil(
        KisToolFunctions::waitLimit(),
        [&]() {
            if (image->tryBarrierLock(true)) {
                image->unlock();
                return true;
            }
            // only strokes hold it: stop looking after 2 s
            return !image->hasUpdatesRunning() && idleTimer.elapsed() >= 2000;
        },
        [](int ms) { QThread::msleep(qMax(1, qMin(ms, 2))); });
    if (!idle) {
        warnScript << call << ": the image did not become idle within the wait limit; its redraws may still be running";
    }
    return true;
}

bool run(KisImageSP image, const char *call, const std::function<void()> &operation)
{
    if (!image) return false;
    QList<KisStrokeId> started;
    {
        KisProcessingApplicator::NoEndRequestsOverride noEndRequests;
        operation();
        started = noEndRequests.strokes();
    }
    return waitForQueuedWork(image, call, started);
}

} // namespace ScriptWaits
