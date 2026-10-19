/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "DocumentHistory.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QHash>
#include <QPointer>
#include <QRecursiveMutex>
#include <QSet>
#include <QThread>

#include <functional>
#include <typeinfo>

#include <KisAgentHooks.h>
#include <KisDocument.h>
#include <commands_new/kis_saved_commands.h>
#include <kis_command_utils.h>
#include <kis_image.h>
#include <kis_image_interfaces.h>
#include <kis_paint_device.h>
#include <kis_post_execution_undo_adapter.h>
#include <kis_processing_applicator.h>
#include <kis_simple_stroke_strategy.h>
#include <kis_stroke_strategy_undo_command_based.h>
#include <kis_transaction.h>
#include <kis_transaction_data.h>
#include <kis_undo_store.h>
#include <kundo2stack.h>

#include "Document.h"
#include "DocumentChanges.h"

namespace
{
/// Every DocumentHistory alive, by document, and the steps they hold: read from stroke threads by the hook.
QRecursiveMutex &registryMutex()
{
    static QRecursiveMutex mutex;
    return mutex;
}

QHash<KisDocument *, DocumentHistory *> &registry()
{
    static QHash<KisDocument *, DocumentHistory *> histories;
    return histories;
}

std::atomic<int> s_idleTimeout {120000};

qint64 monotonicMs()
{
    static QElapsedTimer clock = [] {
        QElapsedTimer timer;
        timer.start();
        return timer;
    }();
    return clock.elapsed();
}

/**
 * The paint devices \p command changes, as far as they can be read: transactions name their device; containers
 * (plain commands with children, composites, saved commands) are looked into. \p unknown is set when some part of it
 * cannot be read (a saved macro's commands are private, and other commands may change devices in ways not shown).
 */
void collectDevices(const KUndo2Command *command, QSet<const KisPaintDevice *> &devices, bool &unknown)
{
    if (!command) {
        return;
    }
    KisSavedCommand::unwrap(command, [&](const KUndo2Command *inner) {
        if (const KisTransactionData *transaction = dynamic_cast<const KisTransactionData *>(inner)) {
            devices.insert(transaction->device().data());
        } else if (dynamic_cast<const KisSavedCommandBase *>(inner)) {
            unknown = true;
            return;
        } else if (const KisCommandUtils::CompositeCommand *composite =
                       dynamic_cast<const KisCommandUtils::CompositeCommand *>(inner)) {
            Q_FOREACH (const KUndo2Command *part, composite->commands()) {
                collectDevices(part, devices, unknown);
            }
        } else if (inner->childCount() == 0 && typeid(*inner) != typeid(KUndo2Command)) {
            unknown = true;
        }
        for (int i = 0; i < inner->childCount(); i++) {
            collectDevices(inner->child(i), devices, unknown);
        }
    });
}

/// A stroke with nothing to do but call \p done when the strokes queued before it have finished (or it is cancelled).
class StepEndStrokeStrategy : public KisSimpleStrokeStrategy
{
public:
    explicit StepEndStrokeStrategy(std::function<void()> done)
        : KisSimpleStrokeStrategy(QLatin1String("krita-agent-step-end"), kundo2_noi18n("Agent step end"))
        , m_done(std::move(done))
    {
        enableJob(JOB_FINISH, true);
        enableJob(JOB_CANCEL, true);
        // It never touches the artist's strokes or the redo history.
        setRequestsOtherStrokesToEnd(false);
        setClearsRedoOnStart(false);
    }

    void finishStrokeCallback() override
    {
        run();
    }

    void cancelStrokeCallback() override
    {
        run();
    }

private:
    void run()
    {
        if (!m_ran.exchange(true)) {
            m_done();
        }
    }

    std::function<void()> m_done;
    std::atomic<bool> m_ran {false};
};
} // namespace

/**
 * One open macro or agent move: the undo store its work's commands are sent to (through m_adapter, from any
 * thread), holding them until they are pushed to the document's stack as one step.
 */
class ScriptStep : public KisUndoStore, public KisStrokeUndoFacade
{
    int m_flushes; ///< steps pushed so far; the later ones, and all of a continued step's, are "(cont.)"

public:
    enum State { Open, Closing, Landed };

    ScriptStep(KisDocument *document,
               KisImageSP image,
               const QString &name,
               bool agent,
               QSharedPointer<std::atomic<int>> openStackMacros,
               bool continued = false)
        : m_flushes(continued ? 1 : 0)
        , m_document(document)
        , m_image(image)
        , m_name(name)
        , m_agent(agent)
        , m_openStackMacros(openStackMacros)
        , m_adapter(this, image.data())
    {
        touch();
    }

    // KisUndoStore: the post-execution adapter's commands arrive here.
    const KUndo2Command *presentCommand() override
    {
        return nullptr;
    }
    void undoLastCommand() override
    {
    }
    void addCommand(KUndo2Command *command) override
    {
        if (!command) {
            return;
        }
        QMutexLocker locker(&m_mutex);
        if (!m_document) {
            delete command;
            return;
        }
        if (m_state == Landed) {
            // Late script work (queued before its step was dropped or landed): a step of its own, unless the
            // document's image was replaced since (it belongs to an image whose history is gone).
            if (onCurrentImage()) {
                m_document->undoStack()->push(command);
            } else {
                delete command;
            }
            return;
        }
        bool unknown = false;
        collectDevices(command, m_devices, unknown);
        m_pending << command;
        touch();
    }
    void beginMacro(const KUndo2MagicString &) override
    {
    }
    void endMacro() override
    {
    }
    void purgeRedoState() override
    {
    }

    // KisStrokeUndoFacade: command strokes run for the step send their macro to it.
    KisPostExecutionUndoAdapter *postExecutionUndoAdapter() const override
    {
        return const_cast<KisPostExecutionUndoAdapter *>(&m_adapter);
    }
    const KUndo2Command *lastExecutedCommand() const override
    {
        return nullptr;
    }

    KisPostExecutionUndoAdapter *adapter()
    {
        return &m_adapter;
    }

    void touch()
    {
        m_lastActivity = monotonicMs();
    }

    qint64 idleMs() const
    {
        return monotonicMs() - m_lastActivity;
    }

    void noteDevice(KisPaintDeviceSP device)
    {
        if (device) {
            QMutexLocker locker(&m_mutex);
            m_devices.insert(device.data());
        }
    }

    /// The artist is adding \p command: if it may change what the step has changed, the step's work goes first.
    void checkArtistCommand(const KUndo2Command *command)
    {
        QMutexLocker locker(&m_mutex);
        if (m_state == Landed || m_pending.isEmpty()) {
            return;
        }
        QSet<const KisPaintDevice *> devices;
        bool unknown = false;
        collectDevices(command, devices, unknown);
        if (unknown || devices.intersects(m_devices)) {
            flush();
        }
    }

    /// Pushes the work collected so far as one step. False when there was nothing to push, or a macro is open on
    /// the document's stack (the step would become its child): the work then waits for the macro to end.
    bool flush()
    {
        QMutexLocker locker(&m_mutex);
        if (m_pending.isEmpty() || !m_document || *m_openStackMacros > 0) {
            return false;
        }
        KisImageSP image = m_image;
        if (!image || m_document->image().data() != image.data()) {
            discardLocked();
            return false;
        }
        KisCommandUtils::CompositeCommand *step = new KisCommandUtils::CompositeCommand();
        step->setText(m_flushes == 0 ? stepText() : continuedText());
        Q_FOREACH (KUndo2Command *command, m_pending) {
            step->addCommand(command);
        }
        m_pending.clear();
        m_devices.clear();
        m_flushes++;
        m_document->undoStack()->push(step);
        return true;
    }

    /// Pushes what is left; from now on, commands still arriving are steps of their own. False, landing nothing,
    /// while a macro is open on the document's stack: the step lands when the macro ends.
    bool land()
    {
        QMutexLocker locker(&m_mutex);
        if (*m_openStackMacros > 0 && m_document) {
            m_landingDeferred = true;
            return false;
        }
        flush();
        m_state = Landed;
        return true;
    }

    /// Whether the step's landing waits for a macro to end; clears the mark.
    bool takeDeferredLanding()
    {
        QMutexLocker locker(&m_mutex);
        const bool deferred = m_landingDeferred;
        m_landingDeferred = false;
        return deferred;
    }

    /// Drops what was collected (the document's image was replaced, or the document is going away).
    void discard()
    {
        QMutexLocker locker(&m_mutex);
        discardLocked();
        m_state = Landed;
    }

    void detach()
    {
        QMutexLocker locker(&m_mutex);
        discardLocked();
        m_state = Landed;
        m_document = nullptr;
    }

    void setClosing()
    {
        QMutexLocker locker(&m_mutex);
        if (m_state == Open) {
            m_state = Closing;
        }
    }

    bool landed() const
    {
        QMutexLocker locker(&m_mutex);
        return m_state == Landed;
    }

    KisImageSP image() const
    {
        return m_image;
    }

    bool onCurrentImage() const
    {
        KisImageSP image = m_image;
        return m_document && image && m_document->image().data() == image.data();
    }

    KisDocument *m_document;
    KisImageWSP m_image;
    const QString m_name;
    const bool m_agent;

private:
    KUndo2MagicString stepText() const
    {
        return m_agent ? DocumentHistory::agentMoveText(m_name) : kundo2_noi18n(m_name);
    }

    KUndo2MagicString continuedText() const
    {
        return m_agent ? kundo2_i18nc("Undo History step: the rest of an AI agent's move after the artist's work on "
                                      "the same layer; %1 is the move's name",
                                      "Agent: %1 (cont.)",
                                      m_name)
                       : kundo2_i18nc("Undo History step: the rest of a script's step; %1 is its name",
                                      "%1 (cont.)",
                                      m_name);
    }

    void discardLocked()
    {
        qDeleteAll(m_pending);
        m_pending.clear();
        m_devices.clear();
    }

    QSharedPointer<std::atomic<int>> m_openStackMacros;
    bool m_landingDeferred = false;
    mutable QRecursiveMutex m_mutex;
    KisPostExecutionUndoAdapter m_adapter;
    QList<KUndo2Command *> m_pending;
    QSet<const KisPaintDevice *> m_devices;
    State m_state = Open;
    std::atomic<qint64> m_lastActivity {0};
};

/*
 * DocumentHistory
 */

DocumentHistory::DocumentHistory(KisDocument *document)
    : QObject(document)
    , m_document(document)
{
    static const bool hooksInstalled = [] {
        KisAgentHooks::setBeforeAddCommand(&DocumentHistory::beforeAddCommand);
        KisAgentHooks::setBeforeHistoryMove(&DocumentHistory::beforeHistoryMove);
        KisAgentHooks::setBeforeSave(&DocumentHistory::beforeSave);
        KisAgentHooks::setBeforeBeginMacro(&DocumentHistory::beforeBeginMacro);
        KisAgentHooks::setAfterEndMacro(&DocumentHistory::afterEndMacro);
        return true;
    }();
    Q_UNUSED(hooksInstalled);

    setObjectName(QStringLiteral("DocumentHistory"));
    connect(&m_idleTimer, SIGNAL(timeout()), this, SLOT(slotCheckIdle()));
    QMutexLocker locker(&registryMutex());
    registry().insert(document, this);
}

DocumentHistory::~DocumentHistory()
{
    QMutexLocker locker(&registryMutex());
    registry().remove(m_document);
    m_agentImage = nullptr;
    Q_FOREACH (QSharedPointer<ScriptStep> step, m_steps) {
        step->detach();
    }
    m_steps.clear();
    m_current.reset();
}

DocumentHistory *DocumentHistory::of(KisDocument *document)
{
    if (!document) {
        return nullptr;
    }
    DocumentHistory *history = find(document);
    return history ? history : new DocumentHistory(document);
}

DocumentHistory *DocumentHistory::find(KisDocument *document)
{
    QMutexLocker locker(&registryMutex());
    return registry().value(document, nullptr);
}

DocumentHistory *DocumentHistory::forImage(KisImageSP image)
{
    if (!image) {
        return nullptr;
    }
    QMutexLocker locker(&registryMutex());
    Q_FOREACH (DocumentHistory *history, registry()) {
        if (history->m_document->image().data() == image.data()) {
            return history;
        }
    }
    return nullptr;
}

bool DocumentHistory::isAgentMoveOpen(KisImage *image)
{
    if (!image) {
        return false;
    }
    QMutexLocker locker(&registryMutex());
    Q_FOREACH (DocumentHistory *history, registry()) {
        if (history->m_agentImage == image) {
            return true;
        }
    }
    return false;
}

KUndo2MagicString DocumentHistory::scriptedStrokeName(KisImageSP image, const QString &name)
{
    if (!name.isEmpty()) {
        return kundo2_noi18n(name);
    }
    DocumentHistory *history = forImage(image);
    if (history && history->agentMoveOpen()) {
        return agentMoveText(history->agentMoveName());
    }
    return kundo2_i18n("Scripted Brush Stroke");
}

KUndo2MagicString DocumentHistory::agentMoveText(const QString &name)
{
    return kundo2_i18nc("Undo History step of everything an AI agent did in one move; %1 is the move's name",
                        "Agent: %1",
                        name);
}

KisPostExecutionUndoAdapter *DocumentHistory::scriptUndoAdapter(KisImageSP image, KisPaintDeviceSP device)
{
    DocumentHistory *history = forImage(image);
    ScriptStep *step = history ? history->activeStep() : nullptr;
    if (!step) {
        return nullptr;
    }
    step->noteDevice(device);
    step->touch();
    return step->adapter();
}

bool DocumentHistory::runCommandStrokeInStep(KisImageSP image, KUndo2Command *command)
{
    DocumentHistory *history = forImage(image);
    if (!history || !history->activeStep()) {
        return false;
    }
    runCommandStroke(image, command);
    return true;
}

void DocumentHistory::runCommandStroke(KisImageSP image, KUndo2Command *command)
{
    DocumentHistory *history = forImage(image);
    ScriptStep *step = history ? history->activeStep() : nullptr;
    if (!step) {
        KisProcessingApplicator::runSingleCommandStroke(image, command);
        return;
    }
    step->touch();
    KisStrokeStrategyUndoCommandBased *strategy = new KisStrokeStrategyUndoCommandBased(command->text(), false, step);
    KisStrokeId id = image->startStroke(strategy);
    image->addJob(id, new KisStrokeStrategyUndoCommandBased::Data(KUndo2CommandSP(command), false));
    image->endStroke(id);
}

void DocumentHistory::setAgentMoveIdleTimeout(int milliseconds)
{
    s_idleTimeout = qMax(1, milliseconds);
}

int DocumentHistory::agentMoveIdleTimeout()
{
    return s_idleTimeout;
}

bool DocumentHistory::beginMacro(const QString &name)
{
    return begin(name, false);
}

bool DocumentHistory::beginAgentMove(const QString &name)
{
    return begin(name, true);
}

bool DocumentHistory::begin(const QString &name, bool agent)
{
    const char *what = agent ? "beginAgentMove" : "beginUndoMacro";
    KisImageSP image = m_document ? KisImageSP(m_document->image()) : KisImageSP();
    if (!image) {
        qWarning() << what << "refused: the document has no image";
        return false;
    }
    dropStepOfReplacedImage();
    if (m_resting) {
        if (agent) {
            // A new move: the one that closed by itself is over.
            m_resting.reset();
        } else {
            resume(); // a macro joins the resting step, which continues
        }
    }
    if (m_current) {
        if (agent) {
            qWarning() << what << "refused:" << (m_current->m_agent ? "an agent move" : "a macro")
                       << m_current->m_name << "is already open (agent moves are always top-level steps)";
            return false;
        }
        m_nestedMacros++;
        m_current->touch();
        return true;
    }

    pruneSteps();
    QSharedPointer<ScriptStep> step(new ScriptStep(m_document, image, name, agent, m_openStackMacros));
    {
        QMutexLocker locker(&registryMutex());
        m_steps << step;
    }
    m_current = step;
    m_nestedMacros = 0;
    static int s_lastId = 0;
    m_currentId = ++s_lastId;
    if (agent) {
        m_agentImage = image.data();
        agentMoveHook(true, name, image);
    }
    m_idleTimer.start(qBound(20, s_idleTimeout / 4, 1000));
    return true;
}

bool DocumentHistory::endMacro()
{
    if (dropStepOfReplacedImage()) {
        qWarning() << "endUndoMacro refused: the document's image was replaced, and the open step with it";
        return false;
    }
    if (!m_current && m_resting) {
        if (m_resting->nestedMacros > 0) {
            m_resting->nestedMacros--;
            return true;
        }
        if (!m_resting->agent) {
            m_resting.reset(); // the macro closed by itself earlier; nothing more to land
            m_currentId = 0;
            return true;
        }
        qWarning() << "endUndoMacro refused: the open step is the agent move" << m_resting->name
                   << "(end it with endAgentMove)";
        return false;
    }
    if (!m_current) {
        qWarning() << "endUndoMacro refused: no macro is open";
        return false;
    }
    if (m_nestedMacros > 0) {
        m_nestedMacros--;
        return true;
    }
    if (m_current->m_agent) {
        qWarning() << "endUndoMacro refused: the open step is the agent move" << m_current->m_name
                   << "(end it with endAgentMove)";
        return false;
    }
    close(m_current);
    return true;
}

bool DocumentHistory::endAgentMove()
{
    if (dropStepOfReplacedImage()) {
        qWarning() << "endAgentMove refused: the document's image was replaced, and the open move with it";
        return false;
    }
    if (!m_current && m_resting && m_resting->agent) {
        if (m_resting->nestedMacros > 0) {
            qWarning() << "endAgentMove refused: a macro opened inside the move" << m_resting->name
                       << "is still open (end it with endUndoMacro first)";
            return false;
        }
        m_resting.reset(); // the move closed by itself earlier; nothing more to land
        m_currentId = 0;
        return true;
    }
    if (!m_current || !m_current->m_agent) {
        qWarning() << "endAgentMove refused: no agent move is open";
        return false;
    }
    if (m_nestedMacros > 0) {
        qWarning() << "endAgentMove refused: a macro opened inside the move" << m_current->m_name
                   << "is still open (end it with endUndoMacro first)";
        return false;
    }
    close(m_current);
    return true;
}

bool DocumentHistory::agentMoveOpen() const
{
    if (m_current) {
        return m_current->m_agent && m_current->onCurrentImage();
    }
    return m_resting && m_resting->agent && m_document
        && KisImageSP(m_resting->image).data() == m_document->image().data();
}

QString DocumentHistory::agentMoveName() const
{
    if (!agentMoveOpen()) {
        return QString();
    }
    return m_current ? m_current->m_name : m_resting->name;
}

int DocumentHistory::agentMoveId() const
{
    return agentMoveOpen() ? m_currentId : 0;
}

ScriptStep *DocumentHistory::activeStep()
{
    dropStepOfReplacedImage();
    if (!m_current && m_resting) {
        resume();
    }
    return m_current && m_current->onCurrentImage() ? m_current.data() : nullptr;
}

void DocumentHistory::resume()
{
    QScopedPointer<Resting> resting(m_resting.take());
    KisImageSP image = resting->image;
    if (!image || !m_document || m_document->image().data() != image.data()) {
        m_currentId = 0;
        return;
    }
    QSharedPointer<ScriptStep> step(
        new ScriptStep(m_document, image, resting->name, resting->agent, m_openStackMacros, true));
    {
        QMutexLocker locker(&registryMutex());
        m_steps << step;
    }
    m_current = step;
    m_nestedMacros = resting->nestedMacros;
    if (resting->agent) {
        m_agentImage = image.data();
        agentMoveHook(true, resting->name, image);
    }
    m_idleTimer.start(qBound(20, s_idleTimeout / 4, 1000));
}

int DocumentHistory::trackedStepCount() const
{
    QMutexLocker locker(&registryMutex());
    return m_steps.size();
}

bool DocumentHistory::stepOpen() const
{
    return m_current && m_current->onCurrentImage();
}

bool DocumentHistory::canSetIndex(int index) const
{
    return m_document && !stepOpen() && index >= 0 && index <= m_document->undoStack()->count();
}

void DocumentHistory::close(QSharedPointer<ScriptStep> step)
{
    if (m_current == step) {
        m_current.reset();
        m_nestedMacros = 0;
        m_idleTimer.stop();
    }
    if (step->m_agent) {
        m_agentImage = nullptr;
    }
    step->setClosing();

    queueLanding(step);
}

void DocumentHistory::queueLanding(QSharedPointer<ScriptStep> step)
{
    KisImageSP image = step->image();
    if (!image) {
        if (step->land()) {
            stepLanded(step);
        }
        return;
    }

    // The step lands when the strokes queued before this point have finished: a stroke of no work, queued after
    // them, pushes what was collected. It neither waits nor asks other strokes to end.
    QPointer<DocumentHistory> self(this);
    KisStrokeId id = image->startStroke(new StepEndStrokeStrategy([step, self]() {
        if (!step->land()) {
            return; // a macro is open on the stack: the step lands when it ends (afterEndMacro)
        }
        QMetaObject::invokeMethod(
            QCoreApplication::instance(),
            [step, self]() {
                if (self) {
                    self->stepLanded(step);
                }
            },
            Qt::QueuedConnection);
    }));
    image->endStroke(id);
}

void DocumentHistory::autoClose(const char *reason, bool landNow)
{
    dropStepOfReplacedImage();
    if (!m_current) {
        return;
    }
    qWarning().noquote() << QStringLiteral("Krita Agent: the %1 \"%2\" was left open and closes by itself: %3")
                                .arg(m_current->m_agent ? QStringLiteral("agent move") : QStringLiteral("macro"),
                                     m_current->m_name,
                                     QString::fromLatin1(reason));
    QSharedPointer<ScriptStep> step = m_current;
    Resting *resting = new Resting;
    resting->name = step->m_name;
    resting->agent = step->m_agent;
    resting->nestedMacros = m_nestedMacros;
    resting->image = step->m_image;
    // With landNow the caller has checked that the image is idle: no stroke is running, so the step can be pushed
    // from this thread. Otherwise it lands through a queued stroke, after the work queued before it.
    if (landNow) {
        m_current.reset();
        m_nestedMacros = 0;
        m_idleTimer.stop();
        if (step->m_agent) {
            m_agentImage = nullptr;
        }
        step->setClosing();
        if (step->land()) {
            stepLanded(step);
        }
    } else {
        close(step);
    }
    // The script's later work reopens it as "<name> (cont.)"; its end ends it.
    m_resting.reset(resting);
}

bool DocumentHistory::dropStepOfReplacedImage()
{
    if (m_resting && (!m_document || KisImageSP(m_resting->image).data() != m_document->image().data())) {
        const bool agent = m_resting->agent;
        m_resting.reset();
        m_currentId = 0;
        if (!m_current) {
            return agent;
        }
    }
    if (!m_current || m_current->onCurrentImage()) {
        return false;
    }
    QSharedPointer<ScriptStep> step = m_current;
    m_current.reset();
    m_nestedMacros = 0;
    m_idleTimer.stop();
    if (step->m_agent) {
        m_agentImage = nullptr;
    }
    step->discard();
    stepLanded(step);
    return true;
}

void DocumentHistory::stepLanded(QSharedPointer<ScriptStep> step)
{
    if (step->m_agent) {
        agentMoveHook(false, step->m_name, step->m_image);
    }
    pruneSteps();
}

void DocumentHistory::pruneSteps()
{
    // A landed step can be let go once its image has no queued work: the strokes that hold its undo adapter are
    // all done then (a step's adapter is handed only to work started while it was open).
    QMutexLocker locker(&registryMutex());
    for (auto it = m_steps.begin(); it != m_steps.end();) {
        QSharedPointer<ScriptStep> step = *it;
        KisImageSP image = step->image();
        if (step != m_current && step->landed() && (!image || image->isIdle(true))) {
            it = m_steps.erase(it);
        } else {
            ++it;
        }
    }
}

void DocumentHistory::slotCheckIdle()
{
    if (!m_current) {
        m_idleTimer.stop();
        return;
    }
    // Work queued or running on the image counts as activity: a long stroke sends nothing until it ends.
    KisImageSP image = m_current->image();
    if (image && !image->isIdle()) {
        m_current->touch();
        return;
    }
    if (m_current->idleMs() > s_idleTimeout) {
        autoClose(QStringLiteral("no script work for %1 ms").arg(int(s_idleTimeout)).toLatin1().constData(), false);
    }
}

void DocumentHistory::agentMoveHook(bool open, const QString &name, KisImageWSP image)
{
    // Krita Agent coordination point with the change reports (DocumentChanges, tasks 2.2/2.8): every agent move
    // opens and closes here, once each, with the image it began on. While it is open the image's changes are the
    // agent's (agent work nests with other agent work and with the Python switch).
    KisImageSP strongImage = image;
    if (strongImage) {
        if (DocumentChanges *changes = DocumentChanges::forImage(strongImage)) {
            if (open) {
                changes->beginAgentWork();
            } else {
                changes->endAgentWork();
            }
        }
    }
    Q_EMIT agentMoveChanged(open, name);
}

void DocumentHistory::beforeAddCommand(KisDocument *document, const KUndo2Command *command)
{
    // Any thread: the artist's command (or the GUI's) is about to join the document's history.
    QMutexLocker locker(&registryMutex());
    DocumentHistory *history = registry().value(document, nullptr);
    if (!history) {
        return;
    }
    Q_FOREACH (QSharedPointer<ScriptStep> step, history->m_steps) {
        if (!step->landed()) {
            step->checkArtistCommand(command);
        }
    }
}

void DocumentHistory::beforeBeginMacro(KisDocument *document)
{
    // GUI thread, before a macro opens on the stack (the legacy undo adapter holds the image's barrier lock then,
    // so no stroke is running): the work collected so far goes in first, as for a command of unknown kind.
    QMutexLocker locker(&registryMutex());
    DocumentHistory *history = registry().value(document, nullptr);
    if (!history) {
        return;
    }
    Q_FOREACH (QSharedPointer<ScriptStep> step, history->m_steps) {
        if (!step->landed()) {
            step->flush();
        }
    }
    (*history->m_openStackMacros)++;
}

void DocumentHistory::afterEndMacro(KisDocument *document)
{
    DocumentHistory *history = find(document);
    if (!history || *history->m_openStackMacros == 0) {
        return;
    }
    if (--(*history->m_openStackMacros) > 0) {
        return;
    }
    // Steps that were to land during the macro land now, after it.
    Q_FOREACH (QSharedPointer<ScriptStep> step, history->m_steps) {
        if (step->takeDeferredLanding()) {
            history->queueLanding(step);
        }
    }
}

void DocumentHistory::beforeHistoryMove(KisDocument *document)
{
    DocumentHistory *history = find(document);
    if (!history) {
        return;
    }
    // Krita's undo stack moves only when it gets the image's barrier lock without waiting (UndoStack::undoImpl and
    // friends in KisDocument.cpp); on a busy image the move is dropped. Then the step stays open and nothing lands.
    KisImageSP image = document->image();
    if (!image || !image->isIdle()) {
        return;
    }
    history->autoClose("the history moved (undo, redo or a step chosen in the Undo History)", true);
}

void DocumentHistory::beforeSave(KisDocument *document)
{
    DocumentHistory *history = find(document);
    if (!history) {
        return;
    }
    // On an idle image the step lands now, before the save copies the image, so the saved state is that step and
    // the history is clean there. On a busy one it lands through a queued stroke, which the save's lock waits for;
    // Krita then counts it as a change made while saving, and the document stays marked modified.
    KisImageSP image = document->image();
    history->autoClose("the document was saved", image && image->isIdle());
}

namespace
{
/// Writes pixels into a device when first run, keeping the transaction to undo and redo it.
class PixelWriteCommand : public KUndo2Command
{
public:
    PixelWriteCommand(KisNodeSP node, const QByteArray &data, const QRect &rect)
        : KUndo2Command(kundo2_i18n("Set Pixel Data"))
        , m_node(node)
        , m_data(data)
        , m_rect(rect)
    {
    }

    void redo() override
    {
        if (!m_transaction) {
            KisPaintDeviceSP device = m_node->paintDevice();
            if (!device) {
                return;
            }
            KisTransaction transaction(device);
            device->writeBytes(reinterpret_cast<const quint8 *>(m_data.constData()),
                               m_rect.x(), m_rect.y(), m_rect.width(), m_rect.height());
            m_transaction.reset(transaction.endAndTake());
            m_transaction->redo(); // a transaction's first redo only marks it done: the write is already in
            m_data.clear();
            m_node->setDirty(m_rect);
        } else {
            m_transaction->redo();
        }
    }

    void undo() override
    {
        if (m_transaction) {
            m_transaction->undo();
        }
    }

private:
    KisNodeSP m_node;
    QByteArray m_data;
    QRect m_rect;
    QScopedPointer<KUndo2Command> m_transaction;
};
} // namespace

bool DocumentHistory::queuePixelWrite(KisImageSP image, KisNodeSP node, const QByteArray &data, const QRect &rect)
{
    if (!node || !node->paintDevice() || !scriptUndoAdapter(image, node->paintDevice())) {
        return false;
    }
    runCommandStroke(image, new PixelWriteCommand(node, data, rect));
    return true;
}

/*
 * Document's history methods (declared in Document.h).
 */

namespace
{
/// Waits until \p image has no queued work, without asking any stroke to end: false if it stays busy for 3 s, or
/// when called again from inside the wait. Input events are handled meanwhile, so an artist holding the pen
/// down can lift it (a stroke the artist keeps open would otherwise never end).
bool waitUntilIdle(KisImageSP image)
{
    static bool waiting = false;
    if (waiting) {
        return false;
    }
    waiting = true;
    QElapsedTimer timer;
    timer.start();
    bool idle = false;
    while (!(idle = image->tryBarrierLock(true)) && timer.elapsed() < 3000) {
        QCoreApplication::processEvents(QEventLoop::AllEvents);
        QThread::msleep(1);
    }
    if (idle) {
        image->unlock();
    }
    waiting = false;
    return idle;
}
} // namespace

int Document::undoCount() const
{
    QPointer<KisDocument> doc = document();
    return doc ? doc->undoStack()->count() : 0;
}

QString Document::undoText(int index) const
{
    QPointer<KisDocument> doc = document();
    return doc ? doc->undoStack()->text(index) : QString();
}

int Document::undoIndex() const
{
    QPointer<KisDocument> doc = document();
    return doc ? doc->undoStack()->index() : 0;
}

bool Document::setUndoIndex(int index)
{
    QPointer<KisDocument> doc = document();
    if (!doc || !doc->image()) {
        qWarning() << "setUndoIndex refused: the document is closed or has no image";
        return false;
    }
    DocumentHistory *history = DocumentHistory::find(doc);
    if (history && history->stepOpen()) {
        qWarning() << "setUndoIndex refused: a macro or agent move is open";
        return false;
    }
    if (index < 0 || index > doc->undoStack()->count()) {
        qWarning() << "setUndoIndex refused: index" << index << "is outside 0 to" << doc->undoStack()->count();
        return false;
    }
    // Krita's undo cancels running strokes and gives up while the image is busy: let the queued work finish.
    if (!waitUntilIdle(doc->image())) {
        qWarning() << "setUndoIndex refused: the image stayed busy for 3 s (a stroke still open, or long work)";
        return false;
    }
    doc->undoStack()->setIndex(index);
    return doc->undoStack()->index() == index;
}

int Document::cleanIndex() const
{
    QPointer<KisDocument> doc = document();
    return doc ? doc->undoStack()->cleanIndex() : -1;
}

bool Document::beginUndoMacro(const QString &name)
{
    DocumentHistory *history = DocumentHistory::of(document());
    if (!history) {
        qWarning() << "beginUndoMacro refused: the document is closed";
        return false;
    }
    return history->beginMacro(name);
}

bool Document::endUndoMacro()
{
    DocumentHistory *history = DocumentHistory::find(document());
    if (!history) {
        qWarning() << "endUndoMacro refused: no macro is open";
        return false;
    }
    return history->endMacro();
}

bool Document::beginAgentMove(const QString &name)
{
    DocumentHistory *history = DocumentHistory::of(document());
    if (!history) {
        qWarning() << "beginAgentMove refused: the document is closed";
        return false;
    }
    return history->beginAgentMove(name);
}

bool Document::endAgentMove()
{
    DocumentHistory *history = DocumentHistory::find(document());
    if (!history) {
        qWarning() << "endAgentMove refused: no agent move is open";
        return false;
    }
    return history->endAgentMove();
}

bool Document::agentMoveOpen() const
{
    DocumentHistory *history = DocumentHistory::find(document());
    return history && history->agentMoveOpen();
}

QString Document::agentMoveName() const
{
    DocumentHistory *history = DocumentHistory::find(document());
    return history ? history->agentMoveName() : QString();
}

int Document::agentMoveId() const
{
    DocumentHistory *history = DocumentHistory::find(document());
    return history ? history->agentMoveId() : 0;
}
