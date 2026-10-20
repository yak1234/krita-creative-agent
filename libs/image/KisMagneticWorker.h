/*
 *  SPDX-FileCopyrightText: 2019 Kuntal Majumder <hellozee@disroot.org>
 *
 *  SPDX-License-Identifier: LGPL-2.1-only
 */

#ifndef KISMAGNETICWORKER_H
#define KISMAGNETICWORKER_H

#include <functional>

#include <kis_paint_device.h>
#include <kis_random_accessor_ng.h>
#include <kritaimage_export.h>

class KisMagneticLazyTiles {
private:
    QVector<QRect> m_tiles;
    QVector<qreal> m_radiusRecord;
    KisPaintDeviceSP m_dev;
    QSize m_tileSize;
    int m_tilesPerRow;
    int m_tilesPerColumn {0};

public:
    KisMagneticLazyTiles(KisPaintDeviceSP dev);
    void filter(qreal radius, QRect &rect);
    inline KisPaintDeviceSP device(){ return m_dev; }
    inline QVector<QRect> tiles(){ return m_tiles; }
};

/**
 * Krita Agent (krita-fork 6.3): limits for one computeEdge() call, for scripts. The magnetic tool passes none.
 */
struct KisMagneticSearchLimits {
    /// Only search within `bounds` pixels of the straight line between the points, not the whole grown rectangle.
    bool corridor = false;
    /// Asked every few thousand vertices; true gives up (computeEdge() then answers as when it finds no path).
    std::function<bool()> shouldStop;
};

class KRITAIMAGE_EXPORT KisMagneticWorker {
public:
    KisMagneticWorker(const KisPaintDeviceSP &dev);

    QVector<QPointF> computeEdge(int bounds, QPoint start, QPoint end, qreal radius,
                                 const KisMagneticSearchLimits &limits = KisMagneticSearchLimits());
    void saveTheImage(vQPointF points);
    qreal intensity(QPoint pt);

private:
    KisMagneticLazyTiles m_lazyTileFilter;
    KisRandomAccessorSP m_intensityAccessor;
};

#endif // ifndef KISMAGNETICWORKER_H
