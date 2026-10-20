/*
 *  SPDX-FileCopyrightText: 2019 Kuntal Majumder <hellozee@disroot.org>
 *
 *  SPDX-License-Identifier: LGPL-2.1-only
 */

#include "KisMagneticWorker.h"

#include <kis_gaussian_kernel.h>
#include <lazybrush/kis_lazy_fill_tools.h>
#include <kis_algebra_2d.h>
#include <kis_painter.h>

#include <QtCore>
#include <QPolygon>
#include <QPainter>
#include <QPainterPath>

#include <vector>

#include <boost/graph/astar_search.hpp>
#include <boost/property_map/property_map.hpp>
#include <krita_utils.h>

#include "KisMagneticGraph.h"

namespace {

struct GoalFound { };
struct GaveUp { };

// Krita Agent (krita-fork 6.3): the search's per-vertex data in flat arrays over the graph's rectangle, where there were
// std::maps keyed by vertex (a tree walk and an allocation per vertex: 40 s for a 20-point outline of a 6000x4500
// painting).

/// Vertex to its number in the rectangle, row by row.
struct CellIndex {
    typedef VertexDescriptor key_type;
    typedef std::size_t value_type;
    typedef std::size_t reference;
    typedef boost::readable_property_map_tag category;

    QRect rect;

    std::size_t at(const VertexDescriptor &v) const
    {
        return std::size_t(v.y - rect.top()) * std::size_t(rect.width()) + std::size_t(v.x - rect.left());
    }
};

inline std::size_t get(const CellIndex &map, const VertexDescriptor &v)
{
    return map.at(v);
}

template <typename T>
using FlatMap = boost::iterator_property_map<typename std::vector<T>::iterator, CellIndex, T, T &>;

/// The predecessor of each vertex, as a cell number (-1: none yet; read as the vertex itself, as before).
struct PredecessorMap {
    typedef VertexDescriptor key_type;
    typedef VertexDescriptor value_type;
    typedef VertexDescriptor reference;
    typedef boost::read_write_property_map_tag category;

    CellIndex index;
    std::vector<qint32> *cells = nullptr;
};

inline VertexDescriptor get(const PredecessorMap &map, const VertexDescriptor &v)
{
    const qint32 cell = (*map.cells)[map.index.at(v)];
    if (cell < 0) return v;
    const int width = map.index.rect.width();
    return VertexDescriptor(map.index.rect.left() + cell % width, map.index.rect.top() + cell / width);
}

inline void put(PredecessorMap &map, const VertexDescriptor &key, const VertexDescriptor &value)
{
    (*map.cells)[map.index.at(key)] = qint32(map.index.at(value));
}

double EuclideanDistance(VertexDescriptor p1, VertexDescriptor p2)
{
    return std::sqrt(std::pow(p1.y - p2.y, 2) + std::pow(p1.x - p2.x, 2));
}

/// The cost of an edge: its length plus how weak the edge in the painting is there.
struct WeightMap {
    typedef std::pair<VertexDescriptor, VertexDescriptor> key_type;
    typedef double value_type;
    typedef double reference;
    typedef boost::readable_property_map_tag category;

    KisMagneticGraph *graph = nullptr;
};

inline double get(const WeightMap &map, const WeightMap::key_type &k)
{
    const double edge_gradient = (map.graph->getIntensity(k.first) + map.graph->getIntensity(k.second)) / 2.0;
    return EuclideanDistance(k.first, k.second) + 255.0 - edge_gradient;
}

class AStarHeuristic : public boost::astar_heuristic<KisMagneticGraph, double>
{
private:
    VertexDescriptor m_goal;

public:
    explicit AStarHeuristic(VertexDescriptor goal) :
        m_goal(goal)
    { }

    double operator () (VertexDescriptor v)
    {
        return EuclideanDistance(v, m_goal);
    }
};

class AStarGoalVisitor : public boost::default_astar_visitor
{
public:
    AStarGoalVisitor(VertexDescriptor goal, const std::function<bool()> *shouldStop, qint64 *examined)
        : m_goal(goal), m_shouldStop(shouldStop), m_examined(examined)
    { }

    void examine_vertex(VertexDescriptor u, KisMagneticGraph const &g)
    {
        Q_UNUSED(g);
        if (u == m_goal) {
            throw GoalFound();
        }
        // Asked every few thousand vertices, not each: a clock read costs more than the vertex.
        if ((++*m_examined & 0xfff) == 0 && m_shouldStop && *m_shouldStop && (*m_shouldStop)()) {
            throw GaveUp();
        }
    }

private:
    VertexDescriptor m_goal;
    const std::function<bool()> *m_shouldStop;
    qint64 *m_examined;
};

/// A search rectangle larger than this (in vertices) is not searched: 32 bytes of search data each.
const qint64 MAX_SEARCH_CELLS = 4000000;

} // namespace

KisMagneticLazyTiles::KisMagneticLazyTiles(KisPaintDeviceSP dev)
{
    m_dev = KisPainter::convertToAlphaAsGray(dev);
    QSize s = dev->defaultBounds()->bounds().size();
    m_tileSize    = KritaUtils::optimalPatchSize();
    m_tilesPerRow = (int) std::ceil((double) s.width() / (double) m_tileSize.width());
    int tilesPerColumn = (int) std::ceil((double) s.height() / (double) m_tileSize.height());
    m_dev->setDefaultBounds(dev->defaultBounds());

    for (int i = 0; i < tilesPerColumn; i++) {
        for (int j = 0; j < m_tilesPerRow; j++) {
            int width  = std::min(s.width() - j * m_tileSize.width(), m_tileSize.width());
            int height = std::min(s.height() - i * m_tileSize.height(), m_tileSize.height());
            QRect temp(j *m_tileSize.width(), i *m_tileSize.height(), width, height);
            m_tiles.push_back(temp);
        }
    }
    m_tilesPerColumn = tilesPerColumn;
    m_radiusRecord = QVector<qreal>(m_tiles.size(), -1);
}

void KisMagneticLazyTiles::filter(qreal radius, QRect &rect)
{
    auto divide = [](QPoint p, QSize s){
                      return QPoint(p.x() / s.width(), p.y() / s.height());
                  };

    // Krita Agent: only the tiles that exist (a rectangle grown past the image's top or left edge gave negative tile
    // numbers, one past its right edge the next row's tiles).
    const QRect inside = rect & m_dev->defaultBounds()->bounds();
    if (inside.isEmpty()) return;
    QPoint firstTile = divide(inside.topLeft(), m_tileSize);
    QPoint lastTile  = divide(inside.bottomRight(), m_tileSize);
    lastTile.setX(qMin(lastTile.x(), m_tilesPerRow - 1));
    lastTile.setY(qMin(lastTile.y(), m_tilesPerColumn - 1));
    for (int i = firstTile.y(); i <= lastTile.y(); i++) {
        for (int j = firstTile.x(); j <= lastTile.x(); j++) {
            int currentTile = i * m_tilesPerRow + j;
            if (currentTile < m_tiles.size()
                    && currentTile < m_radiusRecord.size()
                    && radius != m_radiusRecord[currentTile]) {
                QRect bounds = m_tiles[currentTile];
                KisGaussianKernel::applyTightLoG(m_dev, bounds, radius, -1.0, QBitArray(), nullptr);
                KisLazyFillTools::normalizeAlpha8Device(m_dev, bounds);
                m_radiusRecord[currentTile] = radius;
            }
        }
    }
}

KisMagneticWorker::KisMagneticWorker(const KisPaintDeviceSP &dev) :
    m_lazyTileFilter(dev)
{ }

QVector<QPointF> KisMagneticWorker::computeEdge(int bounds, QPoint begin, QPoint end, qreal radius,
                                                const KisMagneticSearchLimits &limits)
{
    QVector<QPointF> result;
    result.push_back(QPointF(begin));                          // what a search that finds nothing answers

    // Krita Agent: the search rectangle is cut to the image (it was grown past it, and the filter's tiles with it).
    const QRect imageBounds = m_lazyTileFilter.device()->defaultBounds()->bounds();
    QRect rect;
    KisAlgebra2D::accumulateBounds(QVector<QPoint> { begin, end }, &rect);
    rect = kisGrowRect(rect, bounds) & imageBounds;
    if (!rect.contains(begin) || !rect.contains(end)) return result;
    const qint64 cells = qint64(rect.width()) * rect.height();
    if (cells > MAX_SEARCH_CELLS) return result;

    m_lazyTileFilter.filter(radius, rect);

    VertexDescriptor goal(end);
    VertexDescriptor start(begin);

    KisMagneticGraph graph(m_lazyTileFilter.device(), rect);
    if (limits.corridor) graph.setCorridor(begin, end, bounds);

    // How many maps does it require?
    // Take a look here, if it doesn't make sense, https://www.boost.org/doc/libs/1_70_0/libs/graph/doc/astar_search.html
    const CellIndex index{rect};
    std::vector<double> distances(cells, std::numeric_limits<double>::max());
    std::vector<qint32> predecessors(cells, -1);
    std::vector<double> ranks(cells, 0.0);
    std::vector<boost::default_color_type> colors(cells, boost::white_color);
    std::vector<double> heapIndices(cells, 0.0);

    PredecessorMap pmap;
    pmap.index = index;
    pmap.cells = &predecessors;
    FlatMap<double> dmap(distances.begin(), index);
    put(dmap, start, 0.0);
    WeightMap wmap;
    wmap.graph = &graph;
    AStarHeuristic heuristic(goal);
    qint64 examined = 0;

    try {
        boost::astar_search_no_init(
            graph, start, heuristic,
            boost::visitor(AStarGoalVisitor(goal, &limits.shouldStop, &examined))
            .distance_map(dmap)
            .predecessor_map(boost::ref(pmap))
            .weight_map(wmap)
            .vertex_index_map(FlatMap<double>(heapIndices.begin(), index))
            .rank_map(FlatMap<double>(ranks.begin(), index))
            .color_map(FlatMap<boost::default_color_type>(colors.begin(), index))
            .distance_combine(std::plus<double>())
            .distance_compare(std::less<double>())
            );
    } catch (GoalFound const &) {
        result.clear();
        for (VertexDescriptor u = goal; u != start; u = get(pmap, u)) {
            result.push_front(QPointF(u.x, u.y));
        }
        result.push_front(QPoint(start.x, start.y));
    } catch (GaveUp const &) {
        // The caller's limit: answer as when no path is found.
    }

    return result;
} // KisMagneticWorker::computeEdge

qreal KisMagneticWorker::intensity(QPoint pt)
{
    if (!m_intensityAccessor) {
        m_intensityAccessor = m_lazyTileFilter.device()->createRandomAccessorNG();
    }
    m_intensityAccessor->moveTo(pt.x(), pt.y());
    return *m_intensityAccessor->rawData();
}

void KisMagneticWorker::saveTheImage(vQPointF points)
{
    QImage img = m_lazyTileFilter.device()->convertToQImage(nullptr, m_lazyTileFilter.device()->exactBounds());

    const QPointF offset = m_lazyTileFilter.device()->exactBounds().topLeft();
    for (QPointF &pt : points) {
        pt -= offset;
    }

    img.convertTo(QImage::Format_ARGB32);
    QPainter gc(&img);

    QPainterPath path;

    for (int i = 0; i < points.size(); i++) {
        if (i == 0) {
            path.moveTo(points[i]);
        } else {
            path.lineTo(points[i]);
        }
    }

    gc.setPen(Qt::blue);
    gc.drawPath(path);

    gc.setPen(Qt::green);
    gc.drawEllipse(points[0], 3, 3);
    gc.setPen(Qt::red);
    gc.drawEllipse(points[points.count() - 1], 2, 2);

    for (QRect &r : m_lazyTileFilter.tiles() ) {
        gc.drawRect(r);
    }

    img.save("result.png");
} // KisMagneticWorker::saveTheImage
