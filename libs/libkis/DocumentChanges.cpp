/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "DocumentChanges.h"

#include <QMutexLocker>
#include <QReadWriteLock>

#include <KisDocument.h>
#include <KisImageChangeReports.h>
#include <kis_image.h>
#include <kis_node.h>

#include "Document.h"

const QString DocumentChanges::AgentSource = QStringLiteral("agent");
const QString DocumentChanges::ArtistSource = QStringLiteral("artist");

namespace {

/// The one counter all images take their revisions from, so revisions are ordered in time across documents.
QAtomicInteger<qint64> s_lastRevision {0};

/// Whether \p rect continues \p last closely enough to share its history entry: they touch or overlap, and their
/// union is at most twice their areas together.
bool mergesWith(const QRect &last, const QRect &rect)
{
    if (!last.adjusted(-1, -1, 1, 1).intersects(rect)) return false;
    const QRect united = last | rect;
    const qint64 area = qint64(united.width()) * united.height();
    const qint64 parts = qint64(last.width()) * last.height() + qint64(rect.width()) * rect.height();
    return area <= 2 * parts;
}

/// Adds a requested area: merged into a touching one while compact (a stroke's dabs), and never more than
/// kRequestedLimit areas (the oldest two merge), so a request costs a short scan.
const int kRequestedLimit = 32;

void addRequested(QVector<QRect> &requested, const QRect &rect)
{
    for (QRect &earlier : requested) {
        if (earlier.contains(rect)) return;
        if (mergesWith(earlier, rect)) {
            earlier |= rect;
            return;
        }
    }
    if (requested.size() >= kRequestedLimit) {
        requested[1] |= requested[0];
        requested.removeFirst();
    }
    requested.append(rect);
}

/// Removes what \p update recomposited from the requested areas; returns the bounding rect of the requested parts
/// it covered (empty if none).
QRect takeRequested(QVector<QRect> &requested, const QRect &update)
{
    QRect covered;
    for (int i = requested.size() - 1; i >= 0; i--) {
        QRect &area = requested[i];
        if (!area.intersects(update)) continue;
        covered |= area & update;
        if (update.contains(area)) {
            requested.removeAt(i);
        } else if (update.left() <= area.left() && update.right() >= area.right()) {
            // Covered across its width (updates come in patches): keep the rows above or below.
            if (update.top() <= area.top()) area.setTop(update.bottom() + 1);
            else if (update.bottom() >= area.bottom()) area.setBottom(update.top() - 1);
        } else if (update.top() <= area.top() && update.bottom() >= area.bottom()) {
            if (update.left() <= area.left()) area.setLeft(update.right() + 1);
            else if (update.right() >= area.right()) area.setRight(update.left() - 1);
        }
    }
    return covered;
}

qint64 nextRevision()
{
    return s_lastRevision.fetchAndAddOrdered(1) + 1;
}

/// The reports by image. The registry's mutex also keeps a report alive while a worker thread records into it.
/// Written in the GUI thread when a report is created or deleted, read on every node redraw request (any thread):
/// readers share the lock, and with no report at all they skip it.
QReadWriteLock s_reportsLock;
QHash<KisImage *, DocumentChanges *> s_reports;
QAtomicInteger<int> s_reportCount {0};

} // namespace

DocumentChanges *DocumentChanges::registry()
{
    static DocumentChanges *s_registry = [] () {
        DocumentChanges *registry = new DocumentChanges();
        // Every node's redraw request, from any thread: recorded straight into the image's report.
        QObject::connect(KisImageChangeReports::instance(), &KisImageChangeReports::sigNodeDirty, registry,
                         &DocumentChanges::slotNodeDirty, Qt::DirectConnection);
        return registry;
    }();
    return s_registry;
}

DocumentChanges *DocumentChanges::existingForImage(KisImage *image)
{
    QReadLocker locker(&s_reportsLock);
    return s_reports.value(image, nullptr);
}

DocumentChanges *DocumentChanges::forImage(KisImageSP image)
{
    if (!image) return nullptr;
    DocumentChanges *registryObject = registry();
    if (DocumentChanges *existing = existingForImage(image.data())) {
        return existing;
    }
    DocumentChanges *changes = new DocumentChanges(image.data());
    {
        QWriteLocker locker(&s_reportsLock);
        s_reports.insert(image.data(), changes);
        s_reportCount.storeRelease(s_reports.size());
    }
    Q_EMIT registryObject->created(image.data());
    return changes;
}

DocumentChanges::DocumentChanges()
    : QObject(nullptr)
{
}

DocumentChanges::DocumentChanges(KisImage *image)
    : QObject(image)
    , m_image(image)
{
    m_floor = nextRevision();
    m_revision.storeRelease(m_floor);

    // Emitted in the thread that finished the update: count it at once, so the revision is current after
    // waitForDone() without waiting for the event loop.
    connect(image, &KisImage::sigImageUpdated, this, &DocumentChanges::slotImageUpdated, Qt::DirectConnection);
    connect(image, &KisImage::sigSizeChanged, this, &DocumentChanges::slotWholeImageChanged, Qt::DirectConnection);
    connect(image, &KisImage::sigColorSpaceChanged, this, &DocumentChanges::slotWholeImageChanged,
            Qt::DirectConnection);
    connect(image, &KisImage::sigProfileChanged, this, &DocumentChanges::slotWholeImageChanged, Qt::DirectConnection);
}

DocumentChanges::~DocumentChanges()
{
    if (!m_image) return;
    {
        QWriteLocker locker(&s_reportsLock);
        s_reports.remove(m_image);
        s_reportCount.storeRelease(s_reports.size());
    }
    Q_EMIT registry()->released(m_image);
}

qint64 DocumentChanges::revision() const
{
    return m_revision.loadAcquire();
}

QRect DocumentChanges::changedRect(qint64 sinceRevision) const
{
    const QRect bounds = m_image ? m_image->bounds() : QRect();
    QMutexLocker locker(&m_mutex);
    if (sinceRevision >= m_revision.loadAcquire()) {
        return QRect();
    }
    if (sinceRevision < m_floor) {
        return bounds;
    }
    QRect united;
    for (auto it = m_history.rbegin(); it != m_history.rend() && it->first > sinceRevision; ++it) {
        united |= it->second;
    }
    return united & bounds;
}

void DocumentChanges::setAgentActive(bool active)
{
    m_agentSwitch.storeRelease(active ? 1 : 0);
}

bool DocumentChanges::agentActive() const
{
    return isAgent();
}

void DocumentChanges::beginAgentWork()
{
    m_agentDepth.ref();
}

void DocumentChanges::endAgentWork()
{
    // Never below zero: an unmatched end is ignored.
    int depth = m_agentDepth.loadAcquire();
    while (depth > 0 && !m_agentDepth.testAndSetOrdered(depth, depth - 1)) {
        depth = m_agentDepth.loadAcquire();
    }
}

int DocumentChanges::agentWorkDepth() const
{
    return m_agentDepth.loadAcquire();
}

QString DocumentChanges::currentSource() const
{
    return isAgent() ? AgentSource : ArtistSource;
}

bool DocumentChanges::isAgent() const
{
    return m_agentSwitch.loadAcquire() || m_agentDepth.loadAcquire() > 0;
}

void DocumentChanges::slotImageUpdated(const QRect &rect)
{
    record(rect);
}

void DocumentChanges::slotWholeImageChanged()
{
    // A new size or colour space changes every pixel; the image's bounds are already the new ones.
    record(m_image->bounds());
}

void DocumentChanges::slotNodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects)
{
    if (!s_reportCount.loadAcquire()) return;
    QRect united;
    for (const QRect &rect : rects) {
        united |= rect;
    }
    if (united.isEmpty()) return;

    // The read lock keeps the report alive while it records: only its destructor takes the write lock.
    QReadLocker locker(&s_reportsLock);
    DocumentChanges *changes = s_reports.value(image, nullptr);
    if (changes) {
        changes->recordNode(node, united);
    }
}

void DocumentChanges::record(const QRect &rect)
{
    if (rect.isEmpty()) return;
    QRect agentRect;
    QRect artistRect;
    {
        QMutexLocker locker(&m_mutex);
        const qint64 revision = nextRevision();
        if (!m_history.empty() && mergesWith(m_history.back().second, rect)) {
            // A stroke reports many small touching areas: one entry for them keeps the history long. A query from
            // between the merged reports gets their union, a little more than changed, never less.
            m_history.back() = {revision, m_history.back().second | rect};
        } else {
            m_history.emplace_back(revision, rect);
        }
        while (m_history.size() > size_t(kHistoryLimit)) {
            // Whatever asks for changes since before the dropped entry gets the whole image.
            m_floor = m_history.front().first;
            m_history.pop_front();
        }
        m_revision.storeRelease(revision);

        // Who changed it was decided when the change was requested (recordNode), not now: a stroke may be
        // recomposited after the agent's switch changed.
        const QRect byAgent = takeRequested(m_agentRequested, rect);
        const QRect byArtist = takeRequested(m_artistRequested, rect);
        if (!byAgent.isEmpty() && !byArtist.isEmpty()) {
            agentRect = byAgent;
            artistRect = byArtist;
        } else if (!byAgent.isEmpty()) {
            agentRect = rect;
        } else if (!byArtist.isEmpty()) {
            artistRect = rect;
        } else {
            // No request seen for this area (a refresh, a resize, a change made before this report began).
            (isAgent() ? agentRect : artistRect) = rect;
        }
    }
    if (!agentRect.isEmpty()) Q_EMIT imageChangedAsync(agentRect, true);
    if (!artistRect.isEmpty()) Q_EMIT imageChangedAsync(artistRect, false);
}

void DocumentChanges::recordNode(KisNode *node, const QRect &rect)
{
    const bool agent = isAgent();
    {
        QMutexLocker locker(&m_mutex);
        addRequested(agent ? m_agentRequested : m_artistRequested, rect);
    }
    Q_EMIT nodePixelsChangedAsync(KisNodeSP(node), rect, agent);
}

// Document's change reports (declared in Document.h).

namespace {
DocumentChanges *changesOf(const QPointer<KisDocument> &document)
{
    if (!document) return nullptr;
    return DocumentChanges::forImage(document->image());
}
} // namespace

qint64 Document::revision() const
{
    DocumentChanges *changes = changesOf(document());
    return changes ? changes->revision() : 0;
}

QRect Document::changedRect(qint64 sinceRevision) const
{
    DocumentChanges *changes = changesOf(document());
    return changes ? changes->changedRect(sinceRevision) : QRect();
}

void Document::setAgentActive(bool active)
{
    if (DocumentChanges *changes = changesOf(document())) {
        changes->setAgentActive(active);
    }
}

bool Document::agentActive() const
{
    DocumentChanges *changes = changesOf(document());
    return changes && changes->agentActive();
}

QString Document::changeSource() const
{
    DocumentChanges *changes = changesOf(document());
    return changes ? changes->currentSource() : DocumentChanges::ArtistSource;
}
