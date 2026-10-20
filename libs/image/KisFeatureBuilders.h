/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KIS_FEATURE_BUILDERS_H
#define KIS_FEATURE_BUILDERS_H

#include <functional>

#include <QPointF>
#include <QPolygonF>
#include <QRect>
#include <QVector>

#include <KoColor.h>

#include "kis_default_bounds_base.h"
#include "kis_types.h"
#include "kritaimage_export.h"

/**
 * Builders of feature masks (krita-fork 6.3): the selection tools' logic as functions, for scripts and the agent,
 * without a view or a tool. Each builds a new 8-bit mask (a KisPixelSelection: 255 inside, 0 outside, in between at
 * soft edges) from a reference device (the composited image or a layer) and changes nothing else: no device, no
 * selection, no undo history. Krita's own workers do the work:
 *
 * - contiguous(): the contiguous selection tool's flood (KisFillPainter::createFloodSelection, KisScanlineFill);
 * - similarColors(): the similar colour selection tool's test (KisFillPainter::createSimilarColorsSelection);
 * - grow, shrink, feather and anti-alias: the selection filters the fill painter applies (refine());
 * - snapOutline(): the magnetic selection tool's edge tracing (KisMagneticWorker) between rough points;
 * - segment(): the colorize mask's lazy brush (KisColorizeStrokeStrategy and its KisWatershedWorker) from hints.
 *
 * Coordinates are image pixels; masks are cut to \p bounds (the image's bounds, which start at 0, 0).
 */
namespace KisFeatureBuilders
{

/// Asked now and then while a builder works; true makes it stop and give back what it has (the caller discards it).
/// A script's time limit. A single flood fill or filter pass is not interrupted, only the steps between them.
typedef std::function<bool()> StopFn;

/// Grow (or shrink, when negative), feather and anti-alias, as the selection tools apply them after their search.
struct KRITAIMAGE_EXPORT Refinement {
    int grow = 0;                        ///< pixels; negative shrinks
    bool stopGrowingAtDarkestPixel = false;
    int feather = 0;                     ///< pixels; replaces anti-aliasing when set
    bool antiAlias = false;
};

/// How a colour search compares, as the contiguous and similar colour tools' options.
struct KRITAIMAGE_EXPORT ColorSearch {
    int threshold = 8;                   ///< 0-255: Krita's colour difference a pixel may have (0 the same colour only)
    int opacitySpread = 100;             ///< 0-100: 100 a hard edge; less makes the less similar pixels partly selected
    int closeGap = 0;                    ///< contiguous only: gaps up to this many pixels in the edges are closed
    Refinement refinement;
};

/// Applies \p refinement to \p mask in place. \p reference is the device the mask was built from (grow until
/// darkest pixel reads it).
KRITAIMAGE_EXPORT void refine(KisPixelSelectionSP mask, const Refinement &refinement, KisPaintDeviceSP reference);

/**
 * The contiguous selection from every seed, together: each seed's pixels joined to it whose colour is within the
 * threshold of the seed's own. With \p within, the search stays inside it (the tool's "selection as boundary"); a
 * seed outside it adds nothing. Seeds outside \p bounds add nothing.
 */
KRITAIMAGE_EXPORT KisPixelSelectionSP contiguous(KisPaintDeviceSP reference,
                                                 const QVector<QPoint> &seeds,
                                                 const QRect &bounds,
                                                 const ColorSearch &search,
                                                 KisPixelSelectionSP within = KisPixelSelectionSP(),
                                                 const StopFn &stop = StopFn());

/// Every pixel in \p bounds (and in \p within, when given) whose colour is within the threshold of any of \p colors,
/// joined or not. Each colour is searched in patches on the thread pool, as the similar colour tool does.
KRITAIMAGE_EXPORT KisPixelSelectionSP similarColors(KisPaintDeviceSP reference,
                                                    const QVector<KoColor> &colors,
                                                    const QRect &bounds,
                                                    const ColorSearch &search,
                                                    KisPixelSelectionSP within = KisPixelSelectionSP(),
                                                    const StopFn &stop = StopFn());

/// How rough points are snapped, as the magnetic selection tool's options.
struct KRITAIMAGE_EXPORT OutlineSnap {
    int searchRadius = 30;               ///< how far (pixels) the traced edge may stray from the line between points
    qreal filterRadius = 3.0;            ///< the edge filter's radius: larger follows broader, softer edges
    int anchorRadius = 10;               ///< each point first moves to the strongest edge this close (0 keeps it)
    int stretchMs = 2000;                ///< a stretch still searching after this long is drawn straight
};

/**
 * The closed outline through \p points, each stretch between two points traced along the strongest edges of
 * \p reference by the magnetic tool's worker. A stretch whose two points both lie on the same side of \p bounds
 * (within one pixel) runs straight along that side: the canvas edge is where a sky or ground region ends. Empty for
 * fewer than three points.
 */
KRITAIMAGE_EXPORT QPolygonF snapOutline(KisPaintDeviceSP reference,
                                        const QVector<QPointF> &points,
                                        const QRect &bounds,
                                        const OutlineSnap &snap,
                                        const StopFn &stop = StopFn());

/// The inside of \p polygon as a mask cut to \p bounds, filled as the polygonal selection tool fills it.
KRITAIMAGE_EXPORT KisPixelSelectionSP polygonMask(const QPolygonF &polygon, const QRect &bounds, bool antiAlias,
                                                 KisDefaultBoundsBaseSP defaultBounds = KisDefaultBoundsBaseSP());

/// The colorize mask's filtering of the reference before the lazy brush runs.
struct KRITAIMAGE_EXPORT Segmentation {
    bool edgeDetection = true;           ///< on for paintings; off for clean line art
    qreal edgeSize = 4.0;                ///< pixels: the width of the edges it looks for
    qreal fuzzyRadius = 0.0;             ///< pixels: closes gaps in line art
    qreal cleanUp = 0.0;                 ///< 0-1: how hard small stray regions are merged away
};

/**
 * Splits \p rect of \p reference into one region per hint, as the colorize mask does with its key strokes: each
 * pixel joins the hint it reaches first across the weakest edges. Later hints win where hints overlap. Runs as a
 * stroke of \p image (never undoable, never asking other strokes to end, never at a lower level of detail) and waits
 * for it, while \p stop is asked about every few milliseconds (the events of the GUI thread are not pumped here: \p stop
 * does that); when it says stop the stroke is cancelled. \p reference should be a snapshot of the image (a copy that
 * shares its tiles), not the live projection. Returns one mask per hint, in order; nothing when the stroke was
 * cancelled or stopped.
 */
KRITAIMAGE_EXPORT QVector<KisPixelSelectionSP> segment(KisImageSP image,
                                                       KisPaintDeviceSP reference,
                                                       const QVector<KisPixelSelectionSP> &hints,
                                                       const QRect &rect,
                                                       const Segmentation &segmentation,
                                                       const StopFn &stop = StopFn());

/**
 * \p mask with its edge settled by the painting within \p band pixels of it: farther inside it stays selected,
 * farther outside it stays unselected, and the band between is split between the two by segment(). For a rough
 * outline (snapOutline(), or a polygon) that should follow the painting's edges exactly. A mask thinner than twice
 * \p band, or filling the image, has no core on one side to hold: it comes back as it is, with a warning. Nothing
 * when the stroke was cancelled or stopped.
 */
KRITAIMAGE_EXPORT KisPixelSelectionSP settleEdge(KisImageSP image,
                                                 KisPaintDeviceSP reference,
                                                 KisPixelSelectionSP mask,
                                                 int band,
                                                 const Segmentation &segmentation,
                                                 const StopFn &stop = StopFn());
}

#endif // KIS_FEATURE_BUILDERS_H
