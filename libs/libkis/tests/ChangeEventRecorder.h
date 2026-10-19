/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef CHANGEEVENTRECORDER_H
#define CHANGEEVENTRECORDER_H

#include <QList>
#include <QMap>
#include <QObject>
#include <QRect>
#include <QStringList>
#include <QVariant>

#include <Document.h>
#include <Node.h>
#include <Notifier.h>

/**
 * Records Notifier's change events as they arrive. The Document and Node objects of an event live only during the
 * signal, so each event is recorded as values: [document is the reference (bool), then each argument, a node as its
 * name ("" for none)]. Each event's name and node also go into order(), as "signal:node" or "signal".
 */
class ChangeEventRecorder : public QObject
{
public:
    ChangeEventRecorder(Notifier *notifier, Document *reference)
        : m_reference(reference)
    {
        connect(notifier, &Notifier::imageChanged, this, [this] (Document *d, const QRect &rect, const QString &source) {
            add("imageChanged", d, {rect, source});
        });
        connect(notifier, &Notifier::nodeAdded, this, [this] (Document *d, Node *node) {
            add("nodeAdded", d, {name(node)});
        });
        connect(notifier, &Notifier::nodeRemoved, this, [this] (Document *d, Node *node) {
            add("nodeRemoved", d, {name(node)});
        });
        connect(notifier, &Notifier::nodeChanged, this, [this] (Document *d, Node *node) {
            add("nodeChanged", d, {name(node)});
        });
        connect(notifier, &Notifier::nodePixelsChanged, this,
                [this] (Document *d, Node *node, const QRect &rect, const QString &source) {
            add("nodePixelsChanged", d, {name(node), rect, source});
        });
        connect(notifier, &Notifier::selectionChanged, this, [this] (Document *d) {
            add("selectionChanged", d, {});
        });
        connect(notifier, &Notifier::undoIndexChanged, this, [this] (Document *d, int index) {
            add("undoIndexChanged", d, {index});
        });
        connect(notifier, &Notifier::documentModified, this, [this] (Document *d, bool modified) {
            add("documentModified", d, {modified});
        });
    }

    static QStringList names()
    {
        return {"imageChanged", "nodeAdded", "nodeRemoved", "nodeChanged", "nodePixelsChanged", "selectionChanged",
                "undoIndexChanged", "documentModified"};
    }

    QList<QVariantList> &events(const QString &name)
    {
        return m_events[name];
    }

    QStringList &order()
    {
        return m_order;
    }

    /// Empties the records; references from events() stay valid.
    void clear()
    {
        for (QList<QVariantList> &events : m_events) {
            events.clear();
        }
        m_order.clear();
    }

private:
    static QString name(Node *node)
    {
        return node ? node->name() : QString();
    }

    void add(const QString &signal, Document *document, const QVariantList &arguments)
    {
        QVariantList event {bool(document && m_reference && *document == *m_reference)};
        event << arguments;
        m_events[signal] << event;
        const bool hasNode = signal.startsWith("node");
        m_order << (hasNode ? signal + ":" + arguments.value(0).toString() : signal);
    }

    Document *m_reference;
    QMap<QString, QList<QVariantList>> m_events;
    QStringList m_order;
};

#endif // CHANGEEVENTRECORDER_H
