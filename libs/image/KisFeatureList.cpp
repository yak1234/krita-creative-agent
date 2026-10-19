/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureList.h"

#include <QHash>
#include <QMutex>
#include <QMutexLocker>
#include <QSet>

#include <algorithm>
#include <mutex>
#include <iterator>
#include <utility>
#include <vector>

#include <boost/geometry.hpp>
#include <boost/geometry/geometries/box.hpp>
#include <boost/geometry/geometries/point.hpp>
#include <boost/geometry/index/rtree.hpp>

#include "kis_pixel_selection.h"

namespace bg = boost::geometry;
namespace bgi = boost::geometry::index;

namespace {

typedef bg::model::point<int, 2, bg::cs::cartesian> IndexPoint;
typedef bg::model::box<IndexPoint> IndexBox;
// The feature's address identifies it in the index; the list keeps the feature alive while it is indexed.
typedef std::pair<IndexBox, KisFeature *> IndexValue;
typedef bgi::rtree<IndexValue, bgi::quadratic<16>> FeatureIndex;

/// Boost's boxes are closed: a QRect's last pixel is its right() and bottom().
IndexBox toBox(const QRect &rect)
{
    return IndexBox(IndexPoint(rect.left(), rect.top()), IndexPoint(rect.right(), rect.bottom()));
}

} // namespace

struct KisFeatureList::Private {
    mutable QMutex mutex;
    /// The features' link to this list (see KisFeatureOwnerGuard).
    QSharedPointer<KisFeatureOwnerGuard> guard {new KisFeatureOwnerGuard()};
    KisDefaultBoundsBaseSP defaultBounds;
    int sourceVersion {1};
    bool mayHaveFeatures {false};
    QList<KisFeatureSP> features;
    FeatureIndex index;
    /// The box each indexed feature has in the index, to remove it exactly.
    QHash<KisFeature *, IndexBox> indexed;

    void unindex(KisFeature *feature)
    {
        auto it = indexed.find(feature);
        if (it == indexed.end()) return;
        index.remove(IndexValue(it.value(), feature));
        indexed.erase(it);
    }

    void reindex(KisFeature *feature)
    {
        unindex(feature);
        const QRect bounds = feature->bounds();
        if (bounds.isEmpty()) return;
        const IndexBox box = toBox(bounds);
        index.insert(IndexValue(box, feature));
        indexed.insert(feature, box);
    }

    /// The features among \p hits, in list order.
    QList<KisFeatureSP> inListOrder(const std::vector<IndexValue> &hits) const
    {
        QList<KisFeatureSP> result;
        if (hits.empty()) return result;
        QSet<KisFeature *> found;
        for (const IndexValue &hit : hits) {
            found.insert(hit.second);
        }
        Q_FOREACH (KisFeatureSP feature, features) {
            if (found.contains(feature.data())) {
                result << feature;
            }
        }
        return result;
    }
};

KisFeatureList::KisFeatureList(KisDefaultBoundsBaseSP defaultBounds, QObject *parent)
    : QObject(parent)
    , m_d(new Private)
{
    m_d->defaultBounds = defaultBounds;
    m_d->guard->list = this;
}

KisFeatureList::~KisFeatureList()
{
    {
        // Waits for a notification in progress in another thread; none starts after this.
        std::lock_guard<QRecursiveMutex> l(m_d->guard->mutex);
        m_d->guard->list = nullptr;
    }
    QMutexLocker l(&m_d->mutex);
    Q_FOREACH (KisFeatureSP feature, m_d->features) {
        feature->setOwner(QSharedPointer<KisFeatureOwnerGuard>());
    }
}

void KisFeatureList::copyFrom(const KisFeatureList &rhs)
{
    if (&rhs == this) return;
    const QList<KisFeatureSP> source = rhs.features();
    QList<KisFeatureSP> copies;
    Q_FOREACH (KisFeatureSP feature, source) {
        copies << KisFeatureSP(new KisFeature(*feature));
    }

    clear();
    Q_FOREACH (KisFeatureSP copy, copies) {
        insertFeature(copy);
    }
    setSourceVersion(rhs.sourceVersion());
    if (rhs.mayHaveFeatures()) {
        setMayHaveFeatures();
    }
}

int KisFeatureList::sourceVersion() const
{
    QMutexLocker l(&m_d->mutex);
    return m_d->sourceVersion;
}

void KisFeatureList::setSourceVersion(int version)
{
    QMutexLocker l(&m_d->mutex);
    m_d->sourceVersion = version;
}

bool KisFeatureList::mayHaveFeatures() const
{
    QMutexLocker l(&m_d->mutex);
    return m_d->mayHaveFeatures;
}

void KisFeatureList::setMayHaveFeatures()
{
    QMutexLocker l(&m_d->mutex);
    m_d->mayHaveFeatures = true;
}

KisDefaultBoundsBaseSP KisFeatureList::defaultBounds() const
{
    QMutexLocker l(&m_d->mutex);
    return m_d->defaultBounds;
}

QList<KisFeatureSP> KisFeatureList::features() const
{
    QMutexLocker l(&m_d->mutex);
    return m_d->features;
}

int KisFeatureList::count() const
{
    QMutexLocker l(&m_d->mutex);
    return m_d->features.size();
}

bool KisFeatureList::isEmpty() const
{
    return count() == 0;
}

KisFeatureSP KisFeatureList::feature(const QUuid &id) const
{
    QMutexLocker l(&m_d->mutex);
    Q_FOREACH (KisFeatureSP feature, m_d->features) {
        if (feature->id() == id) return feature;
    }
    return KisFeatureSP();
}

KisFeatureSP KisFeatureList::featureByName(const QString &name) const
{
    QMutexLocker l(&m_d->mutex);
    Q_FOREACH (KisFeatureSP feature, m_d->features) {
        if (feature->name() == name) return feature;
    }
    return KisFeatureSP();
}

int KisFeatureList::indexOf(const QUuid &id) const
{
    QMutexLocker l(&m_d->mutex);
    for (int i = 0; i < m_d->features.size(); i++) {
        if (m_d->features[i]->id() == id) return i;
    }
    return -1;
}

bool KisFeatureList::insertFeature(KisFeatureSP feature, int index)
{
    if (!feature) return false;
    {
        QMutexLocker l(&m_d->mutex);
        Q_FOREACH (KisFeatureSP existing, m_d->features) {
            if (existing == feature || existing->id() == feature->id()) return false;
        }
        if (m_d->defaultBounds) {
            feature->mask()->setDefaultBounds(m_d->defaultBounds);
        }
        if (index < 0 || index > m_d->features.size()) {
            index = m_d->features.size();
        }
        m_d->features.insert(index, feature);
        m_d->mayHaveFeatures = true;
        m_d->reindex(feature.data());
        feature->setOwner(m_d->guard);
    }
    Q_EMIT sigFeatureAdded(feature->id());
    return true;
}

KisFeatureSP KisFeatureList::removeFeature(const QUuid &id)
{
    KisFeatureSP removed;
    {
        QMutexLocker l(&m_d->mutex);
        for (int i = 0; i < m_d->features.size(); i++) {
            if (m_d->features[i]->id() == id) {
                removed = m_d->features.takeAt(i);
                break;
            }
        }
        if (!removed) return removed;
        m_d->unindex(removed.data());
        removed->setOwner(QSharedPointer<KisFeatureOwnerGuard>());
    }
    Q_EMIT sigFeatureRemoved(id);
    return removed;
}

void KisFeatureList::clear()
{
    QList<KisFeatureSP> removed;
    {
        QMutexLocker l(&m_d->mutex);
        removed = m_d->features;
        m_d->features.clear();
        m_d->index.clear();
        m_d->indexed.clear();
        Q_FOREACH (KisFeatureSP feature, removed) {
            feature->setOwner(QSharedPointer<KisFeatureOwnerGuard>());
        }
    }
    Q_FOREACH (KisFeatureSP feature, removed) {
        Q_EMIT sigFeatureRemoved(feature->id());
    }
}

QList<KisFeatureSP> KisFeatureList::featuresWithBoundsIntersecting(const QRect &rect) const
{
    if (rect.isEmpty()) return QList<KisFeatureSP>();
    QMutexLocker l(&m_d->mutex);
    std::vector<IndexValue> hits;
    m_d->index.query(bgi::intersects(toBox(rect)), std::back_inserter(hits));
    return m_d->inListOrder(hits);
}

QList<KisFeatureSP> KisFeatureList::featuresWithBoundsContaining(const QPoint &point) const
{
    return featuresWithBoundsIntersecting(QRect(point, QSize(1, 1)));
}

void KisFeatureList::featureChanged(KisFeature *feature, bool boundsChanged)
{
    {
        QMutexLocker l(&m_d->mutex);
        // A feature removed between its change and this call is no longer ours.
        if (!m_d->indexed.contains(feature)) {
            bool listed = false;
            Q_FOREACH (KisFeatureSP f, m_d->features) {
                if (f.data() == feature) {
                    listed = true;
                    break;
                }
            }
            if (!listed) return;
        }
        if (boundsChanged) {
            m_d->reindex(feature);
        }
    }
    Q_EMIT sigFeatureChanged(feature->id());
}
