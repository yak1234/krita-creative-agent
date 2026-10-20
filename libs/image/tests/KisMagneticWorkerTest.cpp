/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisMagneticWorkerTest.h"

#include <cmath>

#include <QElapsedTimer>
#include <QTest>

#include <KoColor.h>
#include <KoColorSpaceRegistry.h>

#include <KisMagneticWorker.h>
#include <kis_default_bounds.h>
#include <kis_image.h>
#include <kis_paint_device.h>

#include <KisTemporaryHomeTest.h>

namespace {

int s_boundsDestroyed = 0;

/// Default bounds that count their destruction: a device (or a copy of it) that is still alive keeps them.
class CountingBounds : public KisDefaultBounds
{
public:
    using KisDefaultBounds::KisDefaultBounds;
    ~CountingBounds() override { s_boundsDestroyed++; }
};

/// A white image with a black horizontal line (3 px thick) at y = lineY from x = fromX to the right edge.
KisPaintDeviceSP lineImage(KisImageSP *keep, const QSize &size, int lineY, int fromX = 0, bool counting = false)
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    *keep = new KisImage(nullptr, size.width(), size.height(), cs, "test");
    KisPaintDeviceSP device = new KisPaintDevice(cs);
    if (counting) {
        device->setDefaultBounds(new CountingBounds(*keep));
    } else {
        device->setDefaultBounds(new KisDefaultBounds(*keep));
    }
    device->fill(QRect(QPoint(0, 0), size), KoColor(Qt::white, cs));
    device->fill(QRect(fromX, lineY - 1, size.width() - fromX, 3), KoColor(Qt::black, cs));
    return device;
}

} // namespace

void KisMagneticWorkerTest::testNothingIsLeaked()
{
    // computeEdge() builds a graph on the worker's filtered copy of the image each call; the copy (and what it holds,
    // such as its default bounds) must be released when the worker is.
    s_boundsDestroyed = 0;
    {
        KisImageSP image;
        KisPaintDeviceSP device = lineImage(&image, QSize(200, 100), 50, 0, true);
        KisMagneticWorker worker(device);
        for (int i = 0; i < 3; i++) {
            const QVector<QPointF> path = worker.computeEdge(20, QPoint(10, 50), QPoint(190, 50), 3.0);
            QVERIFY(path.size() > 2);
        }
        device = nullptr;
        image = nullptr;
    }
    QCOMPARE(s_boundsDestroyed, 1);
}

void KisMagneticWorkerTest::testPathFollowsAnEdge()
{
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(300, 120), 70);
    KisMagneticWorker worker(device);
    // The points are 6 px off the line, either side: the path ends at them and runs along the line between.
    const QVector<QPointF> path = worker.computeEdge(30, QPoint(20, 64), QPoint(280, 76), 3.0);
    QVERIFY(path.size() > 250);
    QCOMPARE(path.first().toPoint(), QPoint(20, 64));
    QCOMPARE(path.last().toPoint(), QPoint(280, 76));
    int onLine = 0;
    for (const QPointF &point : path) {
        if (point.x() > 50 && point.x() < 250 && qAbs(point.y() - 70) <= 2) onLine++;
    }
    QVERIFY2(onLine > 190, qPrintable(QString("%1 of the 200 middle columns on the line").arg(onLine)));
}

void KisMagneticWorkerTest::testCorridorKeepsThePathNearTheLine()
{
    // The points lie on a diagonal; a strong edge runs along y = 250 from x = 100 to the right, far from the diagonal
    // but inside the search rectangle. Following it pays more than the way between the points, so the open search
    // detours down to it; the corridor of 40 px around the diagonal does not allow that.
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(400, 300), 250, 100);
    KisMagneticWorker worker(device);
    const QPointF from(20, 20), to(380, 280);
    const QPointF along = to - from;
    const qreal length = std::sqrt(along.x() * along.x() + along.y() * along.y());
    auto farthest = [&](const QVector<QPointF> &path) {
        qreal far = 0;
        for (const QPointF &point : path) {
            const QPointF d = point - from;
            far = qMax(far, qAbs(d.x() * along.y() - d.y() * along.x()) / length);
        }
        return far;
    };
    const QVector<QPointF> open = worker.computeEdge(40, QPoint(20, 20), QPoint(380, 280), 3.0);
    QVERIFY(open.size() > 300);
    QCOMPARE(open.last().toPoint(), QPoint(380, 280));
    QVERIFY2(farthest(open) > 45, qPrintable(QString("the open search strays %1 px").arg(farthest(open))));

    KisMagneticSearchLimits limits;
    limits.corridor = true;
    const QVector<QPointF> corridor = worker.computeEdge(40, QPoint(20, 20), QPoint(380, 280), 3.0, limits);
    QVERIFY(corridor.size() > 300);
    QCOMPARE(corridor.last().toPoint(), QPoint(380, 280));
    QVERIFY2(farthest(corridor) <= 41, qPrintable(QString("the corridor search strays %1 px").arg(farthest(corridor))));
}

void KisMagneticWorkerTest::testGivingUpAnswersWithTheStartOnly()
{
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(400, 300), 150);
    KisMagneticWorker worker(device);
    KisMagneticSearchLimits limits;
    int asked = 0;
    limits.shouldStop = [&asked]() { return ++asked > 1; };
    QElapsedTimer timer;
    timer.start();
    const QVector<QPointF> path = worker.computeEdge(100, QPoint(20, 30), QPoint(380, 280), 3.0, limits);
    QCOMPARE(path.size(), 1);
    QCOMPARE(path.first().toPoint(), QPoint(20, 30));
    QVERIFY(asked >= 2);
    QVERIFY2(timer.elapsed() < 3000, qPrintable(QString("%1 ms").arg(timer.elapsed())));
}

void KisMagneticWorkerTest::testSearchRadiusBeyondTheImageIsSafe()
{
    // A search radius larger than the distance to the image's top and left edges: the rectangle is cut to the image,
    // and the tiles of the filter are only those that exist.
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(300, 200), 5);
    KisMagneticWorker worker(device);
    const QVector<QPointF> path = worker.computeEdge(600, QPoint(0, 0), QPoint(120, 5), 3.0);
    QVERIFY(path.size() >= 1);
    QCOMPARE(path.first().toPoint(), QPoint(0, 0));
    for (const QPointF &point : path) {
        QVERIFY(point.x() >= 0 && point.x() < 300 && point.y() >= 0 && point.y() < 200);
    }
    // Near the bottom right, where the tile index would wrap into the next row.
    const QVector<QPointF> corner = worker.computeEdge(600, QPoint(299, 150), QPoint(299, 199), 3.0);
    QVERIFY(corner.size() >= 1);
    QCOMPARE(corner.first().toPoint(), QPoint(299, 150));
}

void KisMagneticWorkerTest::testSearchRadiusBeyondALargeImageIsSafe()
{
    // The same on an image of many tiles: the tile numbers of a rectangle grown past its top and left edges reach far
    // before the tile list, and past its right and bottom edges the next row's (or the list's end).
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(2600, 1800), 900);
    KisMagneticWorker worker(device);
    const QVector<QPointF> top = worker.computeEdge(600, QPoint(0, 0), QPoint(40, 30), 3.0);
    QVERIFY(top.size() >= 1);
    const QVector<QPointF> bottom = worker.computeEdge(600, QPoint(2559, 1769), QPoint(2599, 1799), 3.0);
    QVERIFY(bottom.size() >= 1);
    for (const QPointF &point : top + bottom) {
        QVERIFY(point.x() >= 0 && point.x() < 2600 && point.y() >= 0 && point.y() < 1800);
    }
}

void KisMagneticWorkerTest::testIntensityAfterAnEdge()
{
    // The magnetic tool asks for the edge strength of points after tracing: strong on the line, weak off it.
    KisImageSP image;
    KisPaintDeviceSP device = lineImage(&image, QSize(300, 120), 70);
    KisMagneticWorker worker(device);
    worker.computeEdge(30, QPoint(20, 70), QPoint(280, 70), 3.0);
    QVERIFY(worker.intensity(QPoint(150, 70)) > worker.intensity(QPoint(150, 95)) + 100);
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisMagneticWorkerTest)
