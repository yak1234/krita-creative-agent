/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISAGENTHOOKS_H
#define KISAGENTHOOKS_H

#include "kritaui_export.h"

class KisDocument;
class KUndo2Command;

/**
 * Krita Agent: the points where a document's history tells a scripting layer (libkis's DocumentHistory) what is
 * about to happen, so a script's undo steps can stay apart from the artist's. Each hook is one plain function
 * pointer, set once by the layer that uses it (null: nothing happens, as upstream).
 */
class KRITAUI_EXPORT KisAgentHooks
{
public:
    /// Called with every command about to be added to \p document's undo stack through its undo store, in the
    /// thread that adds it (stroke threads included).
    using BeforeAddCommand = void (*)(KisDocument *document, const KUndo2Command *command);

    /// Called in the GUI thread before \p document's history moves (undo, redo, a step chosen in the Undo History
    /// docker) or before it is saved.
    using DocumentEvent = void (*)(KisDocument *document);

    /// True while an agent move, an asynchronous stroke job or the script's agent switch (Document.setAgentActive) is
    /// open on any document (libkis's DocumentChanges::agentActive()). The plugin's own flows (paint passes, brush
    /// selection) are not covered by it unless they run inside a move. Used by the brush preset session storage, which must not save the agent's
    /// brush changes as the artist's tweaks. GUI thread.
    using AgentWorkProbe = bool (*)();

    static void setBeforeAddCommand(BeforeAddCommand hook);
    static void setAgentWorkProbe(AgentWorkProbe probe);
    /// Before a macro opens on \p document's undo stack through its undo store (everything added until it ends
    /// becomes its child), and after it ends. GUI thread.
    static void setBeforeBeginMacro(DocumentEvent hook);
    static void setAfterEndMacro(DocumentEvent hook);
    static void setBeforeHistoryMove(DocumentEvent hook);
    static void setBeforeSave(DocumentEvent hook);

    /// False without a probe (nothing is the agent's).
    static bool agentWorkOpen();
    static void beforeAddCommand(KisDocument *document, const KUndo2Command *command);
    static void beforeBeginMacro(KisDocument *document);
    static void afterEndMacro(KisDocument *document);
    static void beforeHistoryMove(KisDocument *document);
    static void beforeSave(KisDocument *document);
};

#endif // KISAGENTHOOKS_H
