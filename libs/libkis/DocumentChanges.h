/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_DOCUMENTCHANGES_H
#define LIBKIS_DOCUMENTCHANGES_H

#include <QAtomicInteger>
#include <QMutex>
#include <QObject>
#include <QRect>
#include <QString>
#include <QVector>

#include <deque>

#include <kis_types.h>

#include "kritalibkis_export.h"

/**
 * The change report of one image: a revision counter, the areas changed since a revision, and who changed them.
 *
 * One DocumentChanges lives as a child of each KisImage that scripts asked about (forImage() creates it on first use
 * and the image deletes it), so every libkis Document wrapper of a document shares it.
 *
 * **Revision.** revision() increases each time Krita reports a recomposited area of the image
 * (KisImage::sigImageUpdated, the signal that redraws the canvas), and when the image's size or colour space changes.
 * It is updated in the thread that reports the update, so after Document.waitForDone() it already counts every
 * finished change. Revisions come from one counter shared by all images. Use revisions of the same document: a revision
 * of another document or of a replaced image says nothing about this one, and changedRect() then gives the whole
 * image if the revision is older than this report's history, or the changes since that moment otherwise.
 *
 * **Changed areas.** changedRect(since) unites the areas reported after revision \p since, clipped to the image. When
 * that history is gone (older than the last kHistoryLimit entries, or from before this report began) it returns the
 * whole image, so a caller never misses a change. Touching reports (a stroke's) share one entry when their union stays
 * compact, so the history lasts; a query from between them gets their union.
 *
 * **Node pixels.** Each node's redraw requests (KisImageChangeReports, reported before update filters) are passed on
 * as nodePixelsChanged.
 *
 * **Source.** Each change is marked "agent" or "artist" when it is requested, that is when a node asks for an area to
 * be redrawn (KisImageChangeReports, in the thread that changed the pixels): "agent" while an agent move or job is
 * open, "artist" otherwise. A recomposited area takes the mark of the requests it covers (both, split, if it covers
 * both kinds); an area no request explains (a refresh, a resize) takes the mark of the moment. Two independent
 * switches open agent work:
 *  - setAgentActive(bool), a plain on/off switch (Document.setAgentActive in Python);
 *  - beginAgentWork() / endAgentWork(), a nesting count for C++ callers such as agent moves (Document's
 *    beginAgentMove / endAgentMove) and async stroke jobs: each begin needs one end, and the source is "agent" while
 *    any is open.
 * The source is "agent" while either is on. Limits: a request is marked by the switch at the moment its pixels are
 * written, so an agent stroke still executing after the switch closed is marked "artist", and an artist stroke
 * written while it is open is marked "agent". Close agent work after its strokes have landed (waitForDone, or the
 * job's end).
 *
 * The Python switch does not nest: it belongs to the one script driving the agent, and a count would let an
 * unbalanced script mark every later change as the agent's. Code that needs nesting uses agent work.
 *
 * **Signals** imageChangedAsync(rect, agent) and nodePixelsChangedAsync(node, rect, agent) are emitted in the thread
 * that reported the change, once per report and uncoalesced: connect with Qt::DirectConnection and pass them on (as
 * NotifierExtras does, which merges and orders them for Notifier).
 */
class KRITALIBKIS_EXPORT DocumentChanges : public QObject
{
    Q_OBJECT
public:
    static const QString AgentSource;  ///< "agent"
    static const QString ArtistSource; ///< "artist"

    /// The number of changed areas kept for changedRect(); older ones collapse into "the whole image".
    static const int kHistoryLimit = 4096;

    /**
     * The change report of \p image, created on first use (call it in the GUI thread). Null for a null image.
     */
    static DocumentChanges *forImage(KisImageSP image);

    /// The change report of \p image if one was created, else null. Any thread.
    static DocumentChanges *existingForImage(KisImage *image);

    ~DocumentChanges() override;

    qint64 revision() const;
    QRect changedRect(qint64 sinceRevision) const;

    void setAgentActive(bool active);
    bool agentActive() const;

    void beginAgentWork();
    void endAgentWork();
    int agentWorkDepth() const;

    /// "agent" while setAgentActive(true) or an agent work is open, else "artist".
    QString currentSource() const;

Q_SIGNALS:
    /// The image was recomposited in \p rect (image pixels), by the agent if \p agent, else the artist. Any thread.
    void imageChangedAsync(const QRect &rect, bool agent);

    /// \p node asked for \p rect to be redrawn (its pixels or what it shows changed); \p agent as above. Any thread.
    void nodePixelsChangedAsync(KisNodeSP node, const QRect &rect, bool agent);

    /// The registry's: forImage() created a report, so listeners can start following the image's document.
    void created(KisImage *image);

    /// The registry's: the report of \p image (being deleted) is gone; a document may have a new image. Any thread.
    void released(KisImage *image);

public:
    /// The object that emits created() and released(); never deleted.
    static DocumentChanges *registry();

private Q_SLOTS:
    void slotImageUpdated(const QRect &rect);
    void slotWholeImageChanged();
    void slotNodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects); // the registry's, any thread

private:
    explicit DocumentChanges(KisImage *image);
    DocumentChanges();

    void record(const QRect &rect);
    void recordNode(KisNode *node, const QRect &rect);
    bool isAgent() const;

    KisImage *m_image {nullptr};
    QAtomicInteger<qint64> m_revision {0};
    QAtomicInteger<int> m_agentSwitch {0};
    QAtomicInteger<int> m_agentDepth {0};

    mutable QMutex m_mutex;
    qint64 m_floor {0};                          ///< changedRect(since) knows the history for since >= m_floor
    std::deque<std::pair<qint64, QRect>> m_history;
    QVector<QRect> m_agentRequested;  ///< areas the agent asked to redraw, not recomposited yet
    QVector<QRect> m_artistRequested; ///< the same for the artist
};

#endif // LIBKIS_DOCUMENTCHANGES_H
