/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisAgentHooks.h"

#include <atomic>

namespace
{
std::atomic<KisAgentHooks::BeforeAddCommand> s_beforeAddCommand {nullptr};
std::atomic<KisAgentHooks::DocumentEvent> s_beforeHistoryMove {nullptr};
std::atomic<KisAgentHooks::DocumentEvent> s_beforeSave {nullptr};
std::atomic<KisAgentHooks::DocumentEvent> s_beforeBeginMacro {nullptr};
std::atomic<KisAgentHooks::DocumentEvent> s_afterEndMacro {nullptr};
}

void KisAgentHooks::setBeforeAddCommand(BeforeAddCommand hook)
{
    s_beforeAddCommand = hook;
}

void KisAgentHooks::setBeforeHistoryMove(DocumentEvent hook)
{
    s_beforeHistoryMove = hook;
}

void KisAgentHooks::setBeforeSave(DocumentEvent hook)
{
    s_beforeSave = hook;
}

void KisAgentHooks::beforeAddCommand(KisDocument *document, const KUndo2Command *command)
{
    if (BeforeAddCommand hook = s_beforeAddCommand) {
        hook(document, command);
    }
}

void KisAgentHooks::beforeHistoryMove(KisDocument *document)
{
    if (DocumentEvent hook = s_beforeHistoryMove) {
        hook(document);
    }
}

void KisAgentHooks::beforeSave(KisDocument *document)
{
    if (DocumentEvent hook = s_beforeSave) {
        hook(document);
    }
}

void KisAgentHooks::setBeforeBeginMacro(DocumentEvent hook)
{
    s_beforeBeginMacro = hook;
}

void KisAgentHooks::setAfterEndMacro(DocumentEvent hook)
{
    s_afterEndMacro = hook;
}

void KisAgentHooks::beforeBeginMacro(KisDocument *document)
{
    if (DocumentEvent hook = s_beforeBeginMacro) {
        hook(document);
    }
}

void KisAgentHooks::afterEndMacro(KisDocument *document)
{
    if (DocumentEvent hook = s_afterEndMacro) {
        hook(document);
    }
}
