/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTNOTIFIERCHANGES_H
#define TESTNOTIFIERCHANGES_H

#include <QObject>

/// Notifier's change events beyond the image (krita-fork 2.8), those that need no window.
class TestNotifierChanges : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testNodeAdded();
    void testNodeRemoved();
    void testNodePropertiesChanged();
    void testNodePixelsChanged();
    void testSelectionChanged();
    void testUndoIndexChanged();
    void testDocumentModified();
    void testFollowsDocumentAddedWithoutNotification();
    void testFollowsKritaCreateDocument();
    void testInactiveNotifierIsSilent();
    void testWindowSignalsDeclared();
    void testReplacedImageIsReleased();
    void testRemovedGroupChildrenAreReleased();
    void testEventsArriveInOrder();
    void testPixelEventsInOrder();
    void testChangesFromAnotherThread();
    void testDocumentClosedWithEventsQueued();
};

#endif // TESTNOTIFIERCHANGES_H
