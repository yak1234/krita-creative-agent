/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "NotifierExtras.h"

#include <QMutexLocker>
#include <QScopedPointer>

#include <utility>

#include <KisDocument.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KoToolManager.h>
#include <kis_canvas_controller.h>
#include <kis_canvas_resource_provider.h>
#include <kis_image.h>
#include <kis_node.h>
#include <kis_node_manager.h>
#include <kis_paintop_preset.h>
#include <kis_undo_adapter.h>
#include <kundo2stack.h>

#include "Document.h"
#include "DocumentChanges.h"
#include "Node.h"
#include "Notifier.h"

namespace {

/// Events that may merge with an earlier one of the same kind and key; any other kind ends the search.
bool isMergeable(int kind)
{
    return kind <= 3; // ImageChanged, NodePixelsChanged, NodeChanged, SelectionChanged
}

const QString &sourceName(int agent)
{
    return agent ? DocumentChanges::AgentSource : DocumentChanges::ArtistSource;
}

} // namespace

NotifierExtras::NotifierExtras(Notifier *notifier)
    : QObject(notifier)
    , m_notifier(notifier)
{
    KisPart *part = KisPart::instance();
    connect(part, &KisPart::sigDocumentAdded, this, &NotifierExtras::slotFollowDocuments);
    connect(part, &KisPart::sigDocumentRemoved, this, &NotifierExtras::slotFollowDocuments);
    connect(part, &KisPart::sigViewAdded, this, &NotifierExtras::slotFollowDocuments);
    connect(part, &KisPart::sigMainWindowCreated, this, &NotifierExtras::slotFollowMainWindows);
    // A document's image got a change report (a script asked, or Krita.createDocument() made it), or one went away
    // (the document may have a new image).
    connect(DocumentChanges::registry(), &DocumentChanges::created, this, &NotifierExtras::slotFollowDocuments);
    connect(DocumentChanges::registry(), &DocumentChanges::released, this, &NotifierExtras::slotFollowDocuments,
            Qt::QueuedConnection);
    connect(KoToolManager::instance(), &KoToolManager::changedTool, this, &NotifierExtras::slotToolChanged);

    followDocuments();
    slotFollowMainWindows();
}

NotifierExtras::~NotifierExtras()
{
    qDeleteAll(m_followed);
}

void NotifierExtras::slotFollowDocuments()
{
    followDocuments();
}

void NotifierExtras::followDocuments()
{
    // Following an image creates its change report, which calls this again: the outer call finishes the work.
    if (m_following) return;
    m_following = true;
    const QList<QPointer<KisDocument>> documents = KisPart::instance()->documents();
    QSet<KisDocument *> open;
    for (const QPointer<KisDocument> &document : documents) {
        if (!document) continue;
        open.insert(document.data());
        Followed *followed = m_followed.value(document.data(), nullptr);
        if (!followed) {
            follow(document.data());
        } else if (followed->image != document->image().data()) {
            followImage(followed, document->image());
        }
    }
    const QList<KisDocument *> followedDocuments = m_followed.keys();
    for (KisDocument *document : followedDocuments) {
        if (!open.contains(document)) forget(document);
    }
    m_following = false;
}

void NotifierExtras::follow(KisDocument *document)
{
    Followed *followed = new Followed;
    followed->kisdoc = document;
    m_followed.insert(document, followed);

    QPointer<KisDocument> guarded(document);
    connect(document, &QObject::destroyed, this, [this, document] () { forget(document); });
    connect(document, &KisDocument::sigLoadingFinished, this, &NotifierExtras::slotFollowDocuments);
    connect(document, &KisDocument::modified, this, [this, guarded] (bool modified) {
        Event event {Event::DocumentModified, guarded};
        event.number = modified ? 1 : 0;
        enqueue(event);
    });
    if (KUndo2Stack *stack = document->undoStack()) {
        connect(stack, &KUndo2Stack::indexChanged, this, [this, guarded] (int index) {
            Event event {Event::UndoIndexChanged, guarded};
            event.number = index;
            enqueue(event);
        });
    }
    followImage(followed, document->image());
}

void NotifierExtras::followImage(Followed *followed, KisImageSP image)
{
    for (const QMetaObject::Connection &connection : std::as_const(followed->imageConnections)) {
        disconnect(connection);
    }
    followed->imageConnections.clear();
    followed->image = image.data();
    if (!image) return;

    QPointer<KisDocument> document = followed->kisdoc;
    QList<QMetaObject::Connection> &connections = followed->imageConnections;

    // All of these may come from a worker thread: they only queue the event, with a strong reference to the node.
    connections << connect(image.data(), &KisImage::sigNodeAddedAsync, this,
                           [this, document] (KisNodeSP node, KisNodeAdditionFlags) {
        Event event {Event::NodeAdded, document};
        event.node = node;
        enqueue(event);
    }, Qt::DirectConnection);
    connections << connect(image.data(), &KisImage::sigRemoveNodeAsync, this, [this, document] (KisNodeSP node) {
        Event event {Event::NodeRemoved, document};
        event.node = node;
        enqueue(event);
    }, Qt::DirectConnection);
    connections << connect(image.data(), &KisImage::sigNodeChanged, this, [this, document] (KisNodeSP node) {
        Event event {Event::NodeChanged, document};
        event.node = node;
        enqueue(event);
    }, Qt::DirectConnection);
    connections << connect(image->undoAdapter(), &KisUndoAdapter::selectionChanged, this, [this, document] () {
        enqueue(Event {Event::SelectionChanged, document});
    }, Qt::DirectConnection);

    DocumentChanges *changes = DocumentChanges::forImage(image);
    connections << connect(changes, &DocumentChanges::imageChangedAsync, this,
                           [this, document] (const QRect &rect, bool agent) {
        Event event {Event::ImageChanged, document};
        event.rect = rect;
        event.number = agent;
        enqueue(event);
    }, Qt::DirectConnection);
    connections << connect(changes, &DocumentChanges::nodePixelsChangedAsync, this,
                           [this, document] (KisNodeSP node, const QRect &rect, bool agent) {
        Event event {Event::NodePixelsChanged, document};
        event.node = node;
        event.rect = rect;
        event.number = agent;
        enqueue(event);
    }, Qt::DirectConnection);
}

void NotifierExtras::forget(KisDocument *document)
{
    Followed *followed = m_followed.take(document);
    if (!followed) return;
    for (const QMetaObject::Connection &connection : std::as_const(followed->imageConnections)) {
        disconnect(connection);
    }
    if (followed->kisdoc) {
        followed->kisdoc->disconnect(this);
        if (KUndo2Stack *stack = followed->kisdoc->undoStack()) stack->disconnect(this);
    }
    delete followed;
}

void NotifierExtras::enqueue(Event event)
{
    QMutexLocker locker(&m_queueMutex);
    if (isMergeable(event.kind)) {
        for (int i = m_queue.size() - 1; i >= 0 && isMergeable(m_queue[i].kind); i--) {
            Event &earlier = m_queue[i];
            if (earlier.kind == event.kind && earlier.node == event.node && earlier.number == event.number
                && earlier.document == event.document) {
                earlier.rect |= event.rect;
                return;
            }
        }
    }
    m_queue.append(std::move(event));
    if (!m_flushScheduled) {
        m_flushScheduled = true;
        QMetaObject::invokeMethod(this, &NotifierExtras::flush, Qt::QueuedConnection);
    }
}

void NotifierExtras::flush()
{
    QVector<Event> events;
    {
        QMutexLocker locker(&m_queueMutex);
        m_flushScheduled = false;
        std::swap(events, m_queue);
    }
    // A document's image may have been replaced (revert, reload) without a signal of its own.
    followDocuments();
    for (const Event &event : std::as_const(events)) {
        emitEvent(event);
    }
}

void NotifierExtras::emitEvent(const Event &event)
{
    QScopedPointer<Document> document;
    KisImageSP image;
    if (event.hasDocument) {
        // A document closed or removed while its events were queued: they are dropped.
        if (!event.document || !m_followed.contains(event.document.data())) return;
        document.reset(new Document(event.document.data(), false));
        image = event.document->image();
    }
    QScopedPointer<Node> node(event.node ? Node::createNode(image, event.node) : nullptr);

    switch (event.kind) {
    case Event::ImageChanged:
        Q_EMIT m_notifier->imageChanged(document.data(), event.rect, sourceName(event.number));
        break;
    case Event::NodePixelsChanged:
        Q_EMIT m_notifier->nodePixelsChanged(document.data(), node.data(), event.rect, sourceName(event.number));
        break;
    case Event::NodeChanged:
        Q_EMIT m_notifier->nodeChanged(document.data(), node.data());
        break;
    case Event::SelectionChanged:
        Q_EMIT m_notifier->selectionChanged(document.data());
        break;
    case Event::NodeAdded:
        Q_EMIT m_notifier->nodeAdded(document.data(), node.data());
        break;
    case Event::NodeRemoved:
        Q_EMIT m_notifier->nodeRemoved(document.data(), node.data());
        break;
    case Event::UndoIndexChanged:
        Q_EMIT m_notifier->undoIndexChanged(document.data(), event.number);
        break;
    case Event::DocumentModified:
        Q_EMIT m_notifier->documentModified(document.data(), event.number != 0);
        break;
    case Event::ActiveNodeChanged:
        Q_EMIT m_notifier->activeNodeChanged(document.data(), node.data());
        break;
    case Event::ToolChanged:
        Q_EMIT m_notifier->toolChanged(document.data(), event.text);
        break;
    case Event::BrushPresetChanged:
        Q_EMIT m_notifier->brushPresetChanged(document.data(), event.text);
        break;
    }
}

void NotifierExtras::slotFollowMainWindows()
{
    followDocuments();
    for (const QPointer<KisMainWindow> &window : KisPart::instance()->mainWindows()) {
        if (window && !m_windows.contains(window.data())) followMainWindow(window.data());
    }
}

void NotifierExtras::followMainWindow(KisMainWindow *window)
{
    KisViewManager *viewManager = window->viewManager();
    if (!viewManager) return; // not fully created: sigMainWindowCreated comes back
    m_windows.insert(window);
    connect(window, &QObject::destroyed, this, [this, window] () { m_windows.remove(window); });

    QPointer<KisViewManager> manager(viewManager);
    if (KisNodeManager *nodeManager = viewManager->nodeManager()) {
        connect(nodeManager, &KisNodeManager::sigNodeActivated, this, [this, manager] (KisNodeSP node) {
            if (!manager || !manager->document()) return;
            Event event {Event::ActiveNodeChanged, QPointer<KisDocument>(manager->document())};
            event.node = node;
            enqueue(event);
        });
    }
    if (KisCanvasResourceProvider *provider = viewManager->canvasResourceProvider()) {
        connect(provider, &KisCanvasResourceProvider::sigPaintOpPresetChanged, this,
                [this, manager] (const KisPaintOpPresetSP preset) {
            Event event {Event::BrushPresetChanged, QPointer<KisDocument>(manager ? manager->document() : nullptr)};
            event.hasDocument = !event.document.isNull();
            event.text = preset ? preset->name() : QString();
            enqueue(event);
        });
    }
}

void NotifierExtras::slotToolChanged(KoCanvasController *canvas)
{
    KisDocument *document = nullptr;
    if (canvas) {
        for (const QPointer<KisView> &view : KisPart::instance()->views()) {
            if (view && static_cast<KoCanvasController *>(view->canvasController()) == canvas) {
                document = view->document();
                break;
            }
        }
    }
    followDocuments();
    Event event {Event::ToolChanged, QPointer<KisDocument>(document)};
    event.hasDocument = document != nullptr;
    event.text = KoToolManager::instance()->activeToolId();
    enqueue(event);
}
