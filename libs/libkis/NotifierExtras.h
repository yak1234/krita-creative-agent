/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_NOTIFIEREXTRAS_H
#define LIBKIS_NOTIFIEREXTRAS_H

#include <QHash>
#include <QList>
#include <QMetaObject>
#include <QMutex>
#include <QObject>
#include <QPointer>
#include <QRect>
#include <QSet>
#include <QString>
#include <QVector>

#include <kis_types.h>

class Notifier;
class KisDocument;
class KisImage;
class KisMainWindow;
class KoCanvasController;

/**
 * The wiring behind Notifier's change events (krita-fork 2.2 and 2.8): it follows every open document and every main
 * window, and emits Notifier's imageChanged, nodeAdded, nodeRemoved, nodeChanged, nodePixelsChanged,
 * selectionChanged, undoIndexChanged, documentModified, activeNodeChanged, toolChanged and brushPresetChanged.
 *
 * A child of its Notifier (Notifier's constructor creates it).
 *
 * **Order.** Every change, from any thread, goes into one queue in the order it was reported and reaches the GUI
 * thread in one hop, so the events arrive in the order the changes happened. Repeated image, pixel, property and
 * selection reports are merged into the earlier event with the same document, node and source, unless a structural
 * event (node added or removed, undo step, modified flag, active node, tool, preset) came between them.
 *
 * **Objects.** Each emission gets its own Document and Node objects, deleted when the signal returns: a receiver may
 * use them during the call. Keeping one is safe in Python (PyQt then raises RuntimeError on use), but useless: compare
 * nodes with == or by uniqueId(), and documents with ==, and look them up again when needed.
 */
class NotifierExtras : public QObject
{
    Q_OBJECT
public:
    explicit NotifierExtras(Notifier *notifier);
    ~NotifierExtras() override;

    /// Follows any open document not followed yet, and its current image. Called on every hint that one appeared.
    void followDocuments();

private Q_SLOTS:
    void slotFollowDocuments();
    void slotFollowMainWindows();
    void slotToolChanged(KoCanvasController *canvas);
    void flush();

private:
    struct Followed {
        QPointer<KisDocument> kisdoc;
        QPointer<KisImage> image;
        QList<QMetaObject::Connection> imageConnections;
    };

    struct Event {
        enum Kind {
            ImageChanged,
            NodePixelsChanged,
            NodeChanged,
            SelectionChanged,
            NodeAdded,
            NodeRemoved,
            UndoIndexChanged,
            DocumentModified,
            ActiveNodeChanged,
            ToolChanged,
            BrushPresetChanged,
        };
        Kind kind;
        QPointer<KisDocument> document;
        bool hasDocument {true}; ///< false for tool and preset events with no document
        KisNodeSP node;
        QRect rect;
        QString text; ///< tool id or preset name
        int number {0}; ///< undo index, modified flag, or 1 for the agent's image and pixel changes
    };

    void follow(KisDocument *document);
    void followImage(Followed *followed, KisImageSP image);
    void followMainWindow(KisMainWindow *window);
    void forget(KisDocument *document);

    /// Any thread.
    void enqueue(Event event);
    void emitEvent(const Event &event);

    Notifier *m_notifier;
    QHash<KisDocument *, Followed *> m_followed;
    QSet<KisMainWindow *> m_windows;
    bool m_following {false};

    QMutex m_queueMutex;
    QVector<Event> m_queue;
    bool m_flushScheduled {false};
};

#endif // LIBKIS_NOTIFIEREXTRAS_H
