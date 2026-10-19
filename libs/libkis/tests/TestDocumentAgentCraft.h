/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_DOCUMENT_AGENT_CRAFT_H
#define TEST_DOCUMENT_AGENT_CRAFT_H

#include <QObject>

/**
 * Document::mergeGroups() (krita-fork 5.2): groups with masks and styles merge into one layer that renders the
 * same, in one undo step that restores them.
 */
class TestDocumentAgentCraft : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testMergeGroupsKeepsTheProjection();
    void testMergeOneGroupFlattensIt();
    void testMergeLeavesHiddenNodes();
    void testMergeRejectsBadInput();
    void testMergeRefusesLockedOrHiddenAncestors();
    void testMergeAndBakeInOneAgentMove();
};

#endif
