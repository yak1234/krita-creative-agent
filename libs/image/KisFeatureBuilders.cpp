/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureBuilders.h"

#include <QAtomicInt>
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QRunnable>
#include <QThread>
#include <QThreadPool>
#include <QBitArray>
#include <QSharedPointer>
#include <QtMath>

#include <KoColorSpaceRegistry.h>

#include "KisMagneticWorker.h"
#include "kis_debug.h"
#include "KisRunnableStrokeJobDataBase.h"
#include "KisSelectionTags.h"
#include "kis_default_bounds.h"
#include "kis_fill_painter.h"
#include "kis_gaussian_kernel.h"
#include "kis_image.h"
#include "kis_paint_device.h"
#include "kis_painter.h"
#include "kis_pixel_selection.h"
#include "kis_selection_filters.h"
#include "lazybrush/kis_colorize_stroke_strategy.h"
#include "lazybrush/kis_lazy_fill_tools.h"

namespace KisFeatureBuilders
{

namespace
{

KisPixelSelectionSP newMask(KisPaintDeviceSP reference)
{
    return new KisPixelSelection(new KisSelectionDefaultBounds(reference));
}

quint8 selectedness(KisPixelSelectionSP mask, const QPoint &point)
{
    quint8 value = MIN_SELECTED;
    mask->readBytes(&value, point.x(), point.y(), 1, 1);
    return value;
}

/// The colorize mask's lazy brush, run as Krita runs it for the mask, but never at a lower level of detail: a
/// builder answers once, at full resolution.
class BuilderColorizeStrategy : public KisColorizeStrokeStrategy
{
public:
    using KisColorizeStrokeStrategy::KisColorizeStrokeStrategy;

    KisStrokeStrategy *createLodClone(int levelOfDetail) override
    {
        Q_UNUSED(levelOfDetail);
        return nullptr;
    }
};

bool stopped(const StopFn &stop)
{
    return stop && stop();
}

/**
 * Runs the jobs the fill painter makes for a stroke, without a stroke: concurrent jobs on the thread pool, the others
 * (barriers, sequential) alone in order, as the stroke would. \p stop is asked while waiting; once it says stop, jobs
 * that have not begun are dropped. All the jobs are deleted. Returns false when stopped.
 */
bool runJobs(const QVector<KisStrokeJobData *> &jobs, const StopFn &stop)
{
    QAtomicInt running(0);
    bool ok = true;
    auto wait = [&]() {
        while (running.loadAcquire() > 0) {
            if (stopped(stop)) ok = false;
            QThread::msleep(1);
        }
    };
    for (KisStrokeJobData *job : jobs) {
        KisRunnableStrokeJobDataBase *runnable = dynamic_cast<KisRunnableStrokeJobDataBase *>(job);
        if (ok && stopped(stop)) ok = false;
        if (!ok || !runnable) {
            delete job;
            continue;
        }
        if (job->isBarrier() || job->isSequential()) {
            wait();
            if (ok) runnable->run();
            delete job;
        } else {
            running.ref();
            QThreadPool::globalInstance()->start(QRunnable::create([runnable, &running]() {
                runnable->run();
                delete runnable;
                running.deref();
            }));
        }
    }
    wait();
    return ok;
}

/// Which side of \p bounds \p point lies on, within one pixel: 1 left, 2 top, 4 right, 8 bottom (a corner has two).
int borderSides(const QPointF &point, const QRect &bounds)
{
    int sides = 0;
    if (point.x() <= bounds.left() + 1) sides |= 1;
    if (point.y() <= bounds.top() + 1) sides |= 2;
    if (point.x() >= bounds.right()) sides |= 4;
    if (point.y() >= bounds.bottom()) sides |= 8;
    return sides;
}

/// \p point moved onto the sides of \p bounds it lies on: exactly on the canvas edge, so the edge pixels are inside.
QPointF onBorder(const QPointF &point, const QRect &bounds, int sides)
{
    QPointF result = point;
    if (sides & 1) result.setX(bounds.left());
    if (sides & 2) result.setY(bounds.top());
    if (sides & 4) result.setX(bounds.right() + 1);
    if (sides & 8) result.setY(bounds.bottom() + 1);
    return result;
}

QPoint pixelOf(const QPointF &point, const QRect &bounds)
{
    return QPoint(qBound(bounds.left(), qFloor(point.x()), bounds.right()),
                  qBound(bounds.top(), qFloor(point.y()), bounds.bottom()));
}

/**
 * The pixel within \p radius of \p point where the magnetic tool's edge filter answers most strongly (the nearest
 * such pixel): the same filter KisMagneticWorker traces on (the image as grey, Krita's tight Laplacian of Gaussian),
 * run on a crop around the point.
 */
QPoint strongestEdgeNear(KisPaintDeviceSP reference, const QPoint &point, int radius, qreal filterRadius,
                         const QRect &bounds)
{
    const int margin = qCeil(3 * filterRadius) + 2;
    const QRect area = QRect(point - QPoint(radius + margin, radius + margin),
                             QSize(2 * (radius + margin) + 1, 2 * (radius + margin) + 1)) & bounds;
    if (area.isEmpty()) return point;

    KisPaintDeviceSP crop = new KisPaintDevice(reference->colorSpace());
    KisPainter::copyAreaOptimized(area.topLeft(), reference, crop, area);
    KisPaintDeviceSP gray = KisPainter::convertToAlphaAsGray(crop);
    KisGaussianKernel::applyTightLoG(gray, area, filterRadius, -1.0, QBitArray(), nullptr);

    QVector<quint8> values(area.width() * area.height());
    gray->readBytes(values.data(), area);
    QPoint best = point;
    int bestValue = -1;
    qint64 bestDistance = 0;
    for (int y = qMax(area.top(), point.y() - radius); y <= qMin(area.bottom(), point.y() + radius); y++) {
        for (int x = qMax(area.left(), point.x() - radius); x <= qMin(area.right(), point.x() + radius); x++) {
            const qint64 distance = qint64(x - point.x()) * (x - point.x()) + qint64(y - point.y()) * (y - point.y());
            if (distance > qint64(radius) * radius) continue;
            const int value = values[(y - area.top()) * area.width() + (x - area.left())];
            if (value > bestValue || (value == bestValue && distance < bestDistance)) {
                best = QPoint(x, y);
                bestValue = value;
                bestDistance = distance;
            }
        }
    }
    return best;
}

} // namespace

void refine(KisPixelSelectionSP mask, const Refinement &refinement, KisPaintDeviceSP reference)
{
    if (!mask) return;
    // The order and the filters are KisFillPainter's (createFloodSelection, createSimilarColorsSelectionJobs).
    const int grow = refinement.grow;
    if (grow > 0 && !mask->selectedRect().isEmpty()) {
        const QRect rect = mask->selectedRect().adjusted(-grow, -grow, grow, grow);
        if (refinement.stopGrowingAtDarkestPixel && reference) {
            KisGrowUntilDarkestPixelSelectionFilter filter(grow, reference);
            filter.process(mask, rect);
        } else {
            KisGrowSelectionFilter filter(grow, grow);
            filter.process(mask, rect);
        }
    } else if (grow < 0 && !mask->selectedRect().isEmpty()) {
        KisShrinkSelectionFilter filter(-grow, -grow, false);
        filter.process(mask, mask->selectedRect());
    }
    if (refinement.feather > 0 && !mask->selectedRect().isEmpty()) {
        const int feather = refinement.feather;
        KisFeatherSelectionFilter filter(feather);
        filter.process(mask, mask->selectedRect().adjusted(-feather, -feather, feather, feather));
    } else if (refinement.antiAlias && !mask->selectedRect().isEmpty()) {
        KisAntiAliasSelectionFilter filter;
        filter.process(mask, mask->selectedRect());
    }
    mask->invalidateOutlineCache();
}

KisPixelSelectionSP contiguous(KisPaintDeviceSP reference,
                               const QVector<QPoint> &seeds,
                               const QRect &bounds,
                               const ColorSearch &search,
                               KisPixelSelectionSP within,
                               const StopFn &stop)
{
    KisPixelSelectionSP result = newMask(reference);
    if (!reference || bounds.isEmpty()) return result;

    for (const QPoint &seed : seeds) {
        if (stopped(stop)) return result;
        if (!bounds.contains(seed)) continue;
        if (within && selectedness(within, seed) == MIN_SELECTED) continue;
        if (selectedness(result, seed) == MAX_SELECTED) continue;    // an earlier seed's region holds it already

        // The contiguous selection tool's flood, without its refinement (applied once, to all seeds together).
        KisFillPainter painter;
        painter.setWidth(bounds.right() + 1);
        painter.setHeight(bounds.bottom() + 1);
        painter.setRegionFillingMode(KisFillPainter::RegionFillingMode_FloodFill);
        painter.setFillThreshold(search.threshold);
        painter.setOpacitySpread(search.opacitySpread);
        painter.setCloseGap(search.closeGap);
        painter.setUseCompositing(true);
        painter.setSizemod(0);
        painter.setFeather(0);
        painter.setAntiAlias(false);
        painter.setUseSelectionAsBoundary(bool(within));

        KisPixelSelectionSP region = newMask(reference);
        painter.createFloodSelection(region, seed.x(), seed.y(), reference, within);
        result->applySelection(region, SELECTION_ADD);
    }

    refine(result, search.refinement, reference);
    result->crop(bounds);
    return result;
}

KisPixelSelectionSP similarColors(KisPaintDeviceSP reference,
                                  const QVector<KoColor> &colors,
                                  const QRect &bounds,
                                  const ColorSearch &search,
                                  KisPixelSelectionSP within,
                                  const StopFn &stop)
{
    KisPixelSelectionSP result = newMask(reference);
    if (!reference || bounds.isEmpty()) return result;

    for (const KoColor &color : colors) {
        if (stopped(stop)) return result;
        // The tool's own jobs: the area in patches, searched at once on the thread pool. The refinement is left out
        // of them (the painter's defaults) and applied once to the union below.
        KisFillPainter painter;
        painter.setFillThreshold(search.threshold);
        painter.setOpacitySpread(search.opacitySpread);
        painter.setSizemod(0);
        painter.setFeather(0);
        painter.setAntiAlias(false);
        KisPixelSelectionSP region = newMask(reference);
        const QVector<KisStrokeJobData *> jobs =
            painter.createSimilarColorsSelectionJobs(region, QSharedPointer<KoColor>(new KoColor(color)), reference, bounds, within);
        if (!runJobs(jobs, stop)) return result;
        result->applySelection(region, SELECTION_ADD);
    }

    refine(result, search.refinement, reference);
    result->crop(bounds);
    return result;
}

QPolygonF snapOutline(KisPaintDeviceSP reference,
                      const QVector<QPointF> &points,
                      const QRect &bounds,
                      const OutlineSnap &snap,
                      const StopFn &stop)
{
    if (!reference || points.size() < 3 || bounds.isEmpty()) return QPolygonF();

    // Each point: the outline's corner there, and the pixel the edge tracing starts or ends at. A point on the canvas
    // edge stays on it; another moves to the strongest edge near it first, so the outline never makes a detour out
    // to where it was put roughly and back.
    const int count = points.size();
    QVector<int> sides(count);
    QVector<QPoint> anchors(count);
    QVector<QPointF> corners(count);
    for (int i = 0; i < count; i++) {
        sides[i] = borderSides(points[i], bounds);
        anchors[i] = pixelOf(points[i], bounds);
        if (stopped(stop)) return QPolygonF();
        if (!sides[i] && snap.anchorRadius > 0) {
            anchors[i] = strongestEdgeNear(reference, anchors[i], snap.anchorRadius, snap.filterRadius, bounds);
        }
        // Traced pixels are edge pixels: the outline runs through their centres.
        corners[i] = sides[i] ? onBorder(points[i], bounds, sides[i]) : QPointF(anchors[i]) + QPointF(0.5, 0.5);
    }

    KisMagneticWorker worker(reference);
    QPolygonF outline;
    for (int i = 0; i < count; i++) {
        const int next = (i + 1) % count;
        outline << corners[i];
        if (sides[i] & sides[next]) continue;              // both on one side of the canvas: straight along it
        if (anchors[i] == anchors[next]) continue;

        // Each stretch within the radius of its line, and for at most stretchMs: a stretch that does not find its way
        // by then (noise has no edge to follow) is drawn straight.
        if (stopped(stop)) return QPolygonF();
        QElapsedTimer stretchTimer;
        stretchTimer.start();
        KisMagneticSearchLimits limits;
        limits.corridor = true;
        limits.shouldStop = [&stop, &stretchTimer, &snap]() { return stretchTimer.elapsed() > snap.stretchMs || stopped(stop); };
        const QVector<QPointF> path = worker.computeEdge(snap.searchRadius, anchors[i], anchors[next], snap.filterRadius, limits);
        // The path runs from the first anchor to the second, both included; without the second the search failed,
        // and the stretch stays straight.
        if (path.size() < 2 || path.last().toPoint() != anchors[next]) continue;
        for (int j = 1; j < path.size() - 1; j++) {
            outline << path[j] + QPointF(0.5, 0.5);
        }
    }
    return outline;
}

KisPixelSelectionSP polygonMask(const QPolygonF &polygon, const QRect &bounds, bool antiAlias,
                                KisDefaultBoundsBaseSP defaultBounds)
{
    KisPixelSelectionSP mask = new KisPixelSelection(defaultBounds);
    if (polygon.size() < 3 || bounds.isEmpty()) return mask;

    // As the polygonal selection tool fills its polygon.
    KisPainter painter(mask);
    painter.setPaintColor(KoColor(Qt::black, mask->colorSpace()));
    painter.setAntiAliasPolygonFill(antiAlias);
    painter.setFillStyle(KisPainter::FillStyleForegroundColor);
    painter.setStrokeStyle(KisPainter::StrokeStyleNone);
    painter.paintPolygon(polygon);
    painter.end();

    mask->crop(bounds);
    mask->invalidateOutlineCache();
    return mask;
}

QVector<KisPixelSelectionSP> segment(KisImageSP image,
                                     KisPaintDeviceSP reference,
                                     const QVector<KisPixelSelectionSP> &hints,
                                     const QRect &rect,
                                     const Segmentation &segmentation,
                                     const StopFn &stop)
{
    if (!image || !reference || hints.isEmpty() || rect.isEmpty() || hints.size() > 0xffff) {
        return QVector<KisPixelSelectionSP>();
    }

    // Each hint is a key stroke of its own colour: the label's number, R the low byte and G the high one.
    const KoColorSpace *rgb = KoColorSpaceRegistry::instance()->rgb8();
    KisPaintDeviceSP labels = new KisPaintDevice(rgb);
    labels->setDefaultBounds(reference->defaultBounds());
    KisPaintDeviceSP filtered = new KisPaintDevice(KoColorSpaceRegistry::instance()->alpha8());
    filtered->setDefaultBounds(reference->defaultBounds());

    // The progress node is the image's root: it has no progress proxy (those belong to the nodes added under it), so
    // the stroke shows no progress bar.
    BuilderColorizeStrategy *strategy =
        new BuilderColorizeStrategy(reference, labels, filtered, false, rect, image->root(), false);
    strategy->setFilteringOptions(KisLazyFillTools::FilteringOptions(segmentation.edgeDetection,
                                                                     segmentation.edgeSize,
                                                                     segmentation.fuzzyRadius,
                                                                     qBound(0.0, segmentation.cleanUp, 1.0)));
    for (int i = 0; i < hints.size(); i++) {
        const int label = i + 1;
        // A snapshot of each hint: the caller may change its own meanwhile.
        strategy->addKeyStroke(new KisPixelSelection(*hints[i]), KoColor(QColor(label & 0xff, label >> 8, 0), rgb));
    }

    QSharedPointer<QAtomicInt> finished(new QAtomicInt(0));
    QSharedPointer<QAtomicInt> cancelled(new QAtomicInt(0));
    QObject::connect(strategy, &KisColorizeStrokeStrategy::sigFinished, [finished]() { finished->storeRelease(1); });
    QObject::connect(strategy, &KisColorizeStrokeStrategy::sigCancelled, [cancelled]() { cancelled->storeRelease(1); });

    // Never image->waitForDone(): it asks the artist's open stroke to end, and waits for it. The stroke is polled
    // instead, and cancelled when \p stop says so.
    // The stroke stays open until its work is done (its jobs run from its start), so cancelling it is the plain
    // cancelStroke() of an open stroke, and ending it is a formality.
    KisStrokeId id = image->startStroke(strategy);
    while (!finished->loadAcquire() && !cancelled->loadAcquire()) {
        if (stopped(stop)) {
            image->cancelStroke(id);
            return QVector<KisPixelSelectionSP>();
        }
        QThread::msleep(2);
    }
    if (cancelled->loadAcquire()) return QVector<KisPixelSelectionSP>();
    image->endStroke(id);

    // One mask per label, read in strips of rows.
    QVector<KisPixelSelectionSP> masks;
    for (int i = 0; i < hints.size(); i++) masks << newMask(reference);
    const int strip = 64;
    QVector<quint8> pixels(rect.width() * strip * 4);
    QVector<QByteArray> rows(hints.size());
    for (int top = rect.top(); top <= rect.bottom(); top += strip) {
        const QRect band(rect.left(), top, rect.width(), qMin(strip, rect.bottom() + 1 - top));
        const int size = band.width() * band.height();
        labels->readBytes(pixels.data(), band);
        for (QByteArray &row : rows) row.fill('\0', size);
        for (int p = 0; p < size; p++) {
            const quint8 *pixel = pixels.constData() + 4 * p;   // B, G, R, A
            if (pixel[3] != OPACITY_OPAQUE_U8) continue;
            const int label = pixel[2] | (pixel[1] << 8);
            if (label >= 1 && label <= rows.size()) rows[label - 1][p] = char(MAX_SELECTED);
        }
        for (int i = 0; i < masks.size(); i++) {
            masks[i]->writeBytes(reinterpret_cast<const quint8 *>(rows[i].constData()), band);
        }
    }
    for (KisPixelSelectionSP mask : masks) mask->invalidateOutlineCache();
    return masks;
}

KisPixelSelectionSP settleEdge(KisImageSP image,
                               KisPaintDeviceSP reference,
                               KisPixelSelectionSP mask,
                               int band,
                               const Segmentation &segmentation,
                               const StopFn &stop)
{
    if (!image || !reference || !mask) return KisPixelSelectionSP();
    const QRect bounds = image->bounds();
    KisPixelSelectionSP result = newMask(reference);
    result->applySelection(mask, SELECTION_REPLACE);
    result->crop(bounds);
    if (band <= 0 || result->selectedExactRect().isEmpty()) return result;

    // Farther than the band inside: the mask's own. The canvas edge does not count as an edge of the mask.
    KisPixelSelectionSP inside = newMask(reference);
    inside->applySelection(result, SELECTION_REPLACE);
    KisShrinkSelectionFilter shrink(band, band, true);
    shrink.process(inside, inside->selectedRect());

    // Farther than the band outside: not the mask's.
    KisPixelSelectionSP grown = newMask(reference);
    grown->applySelection(result, SELECTION_REPLACE);
    KisGrowSelectionFilter grow(band, band);
    grow.process(grown, grown->selectedRect().adjusted(-band, -band, band, band));
    KisPixelSelectionSP outside = newMask(reference);
    outside->select(bounds);
    outside->applySelection(grown, SELECTION_SUBTRACT);

    // Without a core on one side (a mask thinner than twice the band, or one that fills the image) the lazy brush has
    // nothing to hold that side with, and would give it all away.
    if (inside->selectedExactRect().isEmpty() || outside->selectedExactRect().isEmpty()) {
        warnImage << "settleEdge: the mask has no core farther than" << band << "px from its edge on both sides; left as it is";
        return result;
    }

    // The lazy brush splits the band between them, in the band's bounds (and a little more, so it sees both sides).
    const QRect area = grown->selectedExactRect().adjusted(-2, -2, 2, 2) & bounds;
    const QVector<KisPixelSelectionSP> regions = segment(image, reference, {inside, outside}, area, segmentation, stop);
    if (regions.size() != 2) return KisPixelSelectionSP();

    KisPixelSelectionSP settled = newMask(reference);
    settled->applySelection(inside, SELECTION_REPLACE);
    settled->applySelection(regions[0], SELECTION_ADD);
    settled->crop(bounds);
    settled->invalidateOutlineCache();
    return settled;
}

} // namespace KisFeatureBuilders
