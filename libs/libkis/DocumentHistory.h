/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_DOCUMENTHISTORY_H
#define LIBKIS_DOCUMENTHISTORY_H

#include <QObject>
#include <QPointer>
#include <QScopedPointer>
#include <QSharedPointer>
#include <QString>
#include <QTimer>
#include <QVector>

#include <atomic>

#include <kis_types.h>
#include <kis_stroke_job_strategy.h>
#include <kundo2magicstring.h>
#include <processing/KisToolFunctions.h>

#include "kritalibkis_export.h"

class KisDocument;
class KisPostExecutionUndoAdapter;
class KisStrokeUndoFacade;
class KUndo2Command;
class KUndo2Stack;
class ScriptStep;
class DocumentHistory;

/**
 * A stroke job's hold on the undo step its strokes go to (DocumentHistory::holdStep()). While held, the step does not
 * land, so strokes queued later (a job feeds its strokes in windows) still join it. GUI thread only.
 */
class KRITALIBKIS_EXPORT ScriptStepHold
{
public:
    ~ScriptStepHold();
    /// The post-execution undo adapter the job's strokes send their commands to, or null once released.
    KisPostExecutionUndoAdapter *adapter() const;
    /// The step's text in the Undo History ("Agent: <move>", or the job's own name).
    QString stepName() const;
    /// Counts as script work on the step (its idle timeout).
    void touch();
    /// Lets the step go: a job's own step closes (it lands after the strokes queued so far), and a move or macro
    /// closed while held lands now that nothing holds it. Further calls do nothing.
    void release();

private:
    friend class DocumentHistory;
    ScriptStepHold() = default;
    QSharedPointer<ScriptStep> m_step;
    QPointer<DocumentHistory> m_history;
};

/**
 * The history a script writes into one document: named macros, and agent moves, each of which becomes one named
 * undo step ("Agent: <name>") however many strokes, layers, pixel writes and filters it holds, while the artist's
 * own work keeps its own steps.
 *
 * How it works. An open macro or move is a ScriptStep: an undo store of its own, with its own post-execution undo
 * adapter. The script's work sends its commands there instead of to the document's stack: strokes through the
 * stroke's resources (PaintingResources::createHelper), filters through theirs, new layers through a command stroke
 * on that adapter, pixel writes as queued strokes (queuePixelWrite). Everything else, the artist's work included, goes to the
 * document's stack as usual, so undo stays available. Ending the step queues a small stroke after the script's
 * strokes; when it runs, everything collected is pushed as one step (nothing for an empty step). No call waits for
 * the image or asks the artist's strokes to end.
 *
 * Steps per device stay in order. Krita undoes a paint device's changes strictly newest first. A command the artist
 * adds to the history while a step has collected work is checked: if it may change a device the step has changed
 * (or what it changes cannot be read), the step's work so far is pushed first, and the rest of it continues as
 * "Agent: <name> (cont.)". Artist work on other layers leaves the move whole.
 *
 * A step left open closes by itself, with a warning: when the document is saved (so the saved state is a step in
 * the history), when the history moves (undo, redo, a step chosen in the Undo History docker), and after
 * agentMoveIdleTimeout() without script work.
 *
 * There is one DocumentHistory per KisDocument, a child of it, created on first use by of(). Its methods are for
 * the GUI thread, except isAgentMoveOpen() and the hook called when commands are added (any thread).
 */
class KRITALIBKIS_EXPORT DocumentHistory : public QObject
{
    Q_OBJECT
public:
    ~DocumentHistory() override;

    /// The history of \p document, created on first use; null for a null document.
    static DocumentHistory *of(KisDocument *document);

    /// The history of \p document if one was created, else null.
    static DocumentHistory *find(KisDocument *document);

    /// The history of the document whose current image is \p image, if one was created, else null.
    static DocumentHistory *forImage(KisImageSP image);

    /// Whether an agent move is open on \p image. Any thread.
    static bool isAgentMoveOpen(KisImage *image);

    /**
     * The name of a scripted stroke on \p image: \p name when given, else the step name of the agent move open on
     * the image ("Agent: <move>"), else upstream's "Scripted Brush Stroke".
     */
    static KUndo2MagicString scriptedStrokeName(KisImageSP image, const QString &name = QString());

    /// The step name of an agent move called \p name: "Agent: <name>". The Undo History docker shows it as is.
    static KUndo2MagicString agentMoveText(const QString &name);

    /**
     * The undo adapter a script's work on \p image sends its commands to: the open macro's or move's, or null when
     * none is open (the image's own then). \p device is what the work will change, if known: the step orders its
     * work against the artist's on it before the commands arrive. Each call counts as script activity.
     */
    static KisPostExecutionUndoAdapter *scriptUndoAdapter(KisImageSP image, KisPaintDeviceSP device = nullptr);

    /**
     * Runs \p command in a stroke on \p image, as KisProcessingApplicator::runSingleCommandStroke() does, with its
     * undo going to the open macro or move if there is one, and returns at once. The stroke never asks the artist's
     * open strokes to end. Its completion says when it has run (ScriptWaits waits for it). \p pixelsOnly: the command
     * changes only paint devices' pixels, through transactions, and the step reports which devices (KisTouchedDevices).
     */
    static KisToolFunctions::CompletionSP runCommandStroke(KisImageSP image,
                                                           KUndo2Command *command,
                                                           KisStrokeJobData::Sequentiality sequentiality = KisStrokeJobData::SEQUENTIAL,
                                                           KisStrokeJobData::Exclusivity exclusivity = KisStrokeJobData::NORMAL,
                                                           bool pixelsOnly = false);

    /**
     * runCommandStroke(), then waits for that stroke only (ScriptWaits::waitForStroke()): true once it has run;
     * false, with the stroke cancelled and a warning naming \p call, when it was held back past the wait limit.
     */
    static bool runCommandStrokeAndWait(KisImageSP image,
                                        KUndo2Command *command,
                                        const char *call,
                                        KisStrokeJobData::Sequentiality sequentiality = KisStrokeJobData::SEQUENTIAL,
                                        KisStrokeJobData::Exclusivity exclusivity = KisStrokeJobData::NORMAL,
                                        bool pixelsOnly = false);

    /**
     * Runs \p command at once on this thread, for an image that is locked (Document.lock(): no stroke runs until it
     * is unlocked), and records its undo step: in the open macro or move, else the image's history. The command is
     * run as the first redo of a stroke would. True always.
     */
    static bool runCommandDirect(KisImageSP image, KUndo2Command *command);

    /**
     * For the simple property and pixel calls (opacity, name, visibility, pixel data): as runCommandStrokeAndWait(),
     * but on a locked image the command is run at once and recorded (runCommandDirect()), so a script inside a
     * lock block reads the new value back at once.
     */
    static bool runPropertyCommand(KisImageSP image, KUndo2Command *command, const char *call, bool pixelsOnly = false);

    /**
     * The stroke undo facade of the open macro or move on \p image, or null when none is open. Upstream operations
     * that build their own KisProcessingApplicator (merges, flattening) send their step there when run under a
     * KisProcessingApplicator::UndoFacadeOverride of it. \p device and activity as for scriptUndoAdapter().
     */
    static KisStrokeUndoFacade *scriptUndoFacade(KisImageSP image, KisPaintDeviceSP device = nullptr);

    /// Inside an open macro or move on \p image: runs \p command as a stroke of it (taking it) and returns true.
    /// Otherwise returns false and leaves \p command to the caller.
    static bool runCommandStrokeInStep(KisImageSP image, KUndo2Command *command);

    /**
     * Krita Agent, krita-fork 6.5: \p image if the script writes now are the agent's and some feature is protected
     * (an agent move or job is open, or Document.setAgentActive(true) is on, and protection is not suspended), else
     * null. The script pixel writes that are not tool functions or stroke jobs (Node.setPixelData(), Filter.apply(),
     * Filter.startFilter(), Selection.cut() and paste()) keep out of the protected features exactly when this is not
     * null. Any thread.
     */
    static KisImageSP protectionFor(KisImageSP image);

    /// How long an open macro or move may go without script work before it closes itself: 120 s unless set.
    static void setAgentMoveIdleTimeout(int milliseconds);
    static int agentMoveIdleTimeout();

    /// Opens a macro named \p name; one opened inside an open macro or move joins it. Refused without an image.
    bool beginMacro(const QString &name);

    /// Closes the innermost macro. Refused when none is open, or when the innermost open step is an agent move.
    bool endMacro();

    /// Opens an agent move named \p name. Refused without an image, or when a move or macro is already open.
    bool beginAgentMove(const QString &name);

    /// Closes the open agent move; its step lands once the strokes queued in it have finished. Refused when no move
    /// is open, or a macro opened inside it is still open.
    bool endAgentMove();

    bool agentMoveOpen() const;

    /// The open agent move's name as given to beginAgentMove(), or an empty string.
    QString agentMoveName() const;

    /// The open agent move's number (see Document::agentMoveId()), or 0.
    int agentMoveId() const;

    /// Whether a macro or move is open.
    bool stepOpen() const;

    /// The steps still kept (open, landing, or possibly still sent commands by queued strokes). For tests.
    int trackedStepCount() const;

    /// Whether the history can move to \p index now: nothing open, and 0 <= index <= the stack's count.
    bool canSetIndex(int index) const;

    /**
     * Inside an open macro or move on \p image: queues a write of \p data (in \p node's paint device's pixel
     * format) into \p rect as a stroke of the step, after the script's earlier strokes, undoable with it, and
     * returns true. Outside them it does nothing and returns false (the caller writes at once, as upstream).
     */
    static bool queuePixelWrite(KisImageSP image, KisNodeSP node, const QByteArray &data, const QRect &rect);

    /**
     * Writes \p data into \p rect of \p node's paint device as an undo step: part of the open macro or move (queued,
     * as queuePixelWrite()), else a step of its own, "Set Pixel Data", waited for (its own stroke only). False when
     * the node has no paint device, or the step was held back past the wait limit and cancelled.
     */
    static bool writePixelData(KisImageSP image, KisNodeSP node, const QByteArray &data, const QRect &rect);

    /**
     * A hold on the step a stroke job on \p image joins: the open macro or agent move, or else a new step of the
     * job's own named \p name, which other script work never joins. Null when the image belongs to no document with a
     * history. \p device as for scriptUndoAdapter(). GUI thread.
     */
    static QSharedPointer<ScriptStepHold> holdStep(KisImageSP image, const QString &name, KisPaintDeviceSP device);

Q_SIGNALS:
    /**
     * Emitted after an agent move opens (\p open true) and after it has closed (\p open false: its work has landed),
     * with the move's name, in the GUI thread. Each opening is followed by one closing.
     */
    void agentMoveChanged(bool open, const QString &name);

private Q_SLOTS:
    void slotCheckIdle();

private:
    explicit DocumentHistory(KisDocument *document);

    bool begin(const QString &name, bool agent);
    ScriptStep *activeStep();
    void resume();
    void close(QSharedPointer<ScriptStep> step);
    void queueLanding(QSharedPointer<ScriptStep> step);
    void autoClose(const char *reason, bool landNow);
    bool dropStepOfReplacedImage();
    void stepLanded(QSharedPointer<ScriptStep> step);
    void pruneSteps();
    void agentMoveHook(bool open, const QString &name, KisImageWSP image);

    static void beforeAddCommand(KisDocument *document, const KUndo2Command *command);
    static void beforeHistoryMove(KisDocument *document);
    static void beforeSave(KisDocument *document);
    static void beforeBeginMacro(KisDocument *document);
    static void afterEndMacro(KisDocument *document);

    friend class ScriptStep;
    friend class ScriptStepHold;

    KisDocument *m_document;
    QSharedPointer<ScriptStep> m_current;       ///< the open step, if any

    /// A step that closed by itself (save, history move, idle) while its script still had it open: the script's
    /// next work reopens it as "<name> (cont.)", and the script's end ends it.
    struct Resting {
        QString name;
        bool agent = false;
        int nestedMacros = 0;
        KisImageWSP image;
    };
    QScopedPointer<Resting> m_resting;
    int m_currentId = 0; ///< the number of the open (or resting) step
    int m_nestedMacros = 0;                     ///< macros opened inside the open step
    QVector<QSharedPointer<ScriptStep>> m_steps; ///< every step made, kept while strokes may hold their adapters
    std::atomic<KisImage *> m_agentImage {nullptr}; ///< the image of the open agent move, for isAgentMoveOpen()
    QTimer m_idleTimer;
    /// Macros open on the document's stack (GUI legacy macros): no step lands while one is open.
    QSharedPointer<std::atomic<int>> m_openStackMacros {new std::atomic<int>(0)};
};

#endif // LIBKIS_DOCUMENTHISTORY_H
