/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Times region refresh and the scaled projection read on a 6000x4500 document (openspec change krita-fork, tasks 2.1
// and 2.3). Not a unit test: build the AgentSpeedBenchmark target and run it; it prints one line per measurement.

#include <simpletest.h>
#include <testui.h>

#include <QElapsedTimer>
#include <QImage>
#include <QScopedPointer>

#include <algorithm>
#include <functional>
#include <sys/resource.h>

#include <Document.h>
#include <Node.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <KoCompositeOpRegistry.h>
#include <kis_fill_painter.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_layer_utils.h>

class AgentSpeedBenchmark : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void benchmark();
};

namespace {

/// Milliseconds of the fastest and median of \p runs calls.
QString timeIt(int runs, const std::function<void()> &f)
{
    QVector<double> ms;
    for (int i = 0; i < runs; ++i) {
        QElapsedTimer t;
        t.start();
        f();
        ms.append(t.nsecsElapsed() / 1e6);
    }
    std::sort(ms.begin(), ms.end());
    return QString("min %1 ms, median %2 ms (%3 runs)").arg(ms.first(), 0, 'f', 1).arg(ms[ms.size() / 2], 0, 'f', 1).arg(runs);
}

qint64 peakResidentBytes()
{
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    return qint64(usage.ru_maxrss); // bytes on macOS
}

void report(const QString &what, const QString &result)
{
    qInfo().noquote() << QString("%1: %2").arg(what, -58).arg(result);
}

/// A painting-like document: a gradient base with lines, translucent blocks at 70% opacity, a multiply layer.
KisImageSP makeImage(const QSize &size)
{
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP image = new KisImage(0, size.width(), size.height(), cs, "benchmark");
    const int w = size.width();
    const int h = size.height();

    KisPaintLayerSP base = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
    QByteArray row(w * 4, 0);
    for (int y = 0; y < h; ++y) {
        quint8 *p = reinterpret_cast<quint8 *>(row.data());
        for (int x = 0; x < w; ++x, p += 4) {
            p[0] = quint8(255 * y / h);
            p[1] = quint8((x ^ y) & 0xff);
            p[2] = quint8(255 * x / w);
            p[3] = 255;
        }
        base->paintDevice()->writeBytes(reinterpret_cast<const quint8 *>(row.constData()), 0, y, w, 1);
    }
    image->addNode(base);

    KisPaintLayerSP blocks = new KisPaintLayer(image, "blocks", quint8(0.7 * 255));
    {
        KisFillPainter gc(blocks->paintDevice());
        for (int i = 0; i < 40; ++i) {
            QColor c = QColor::fromHsv((i * 37) % 360, 200, 220, 160);
            gc.fillRect((i * 613) % (w - 900), (i * 401) % (h - 700), 900, 700, KoColor(c, cs));
        }
        gc.end();
    }
    image->addNode(blocks);

    KisPaintLayerSP multiply = new KisPaintLayer(image, "multiply", OPACITY_OPAQUE_U8);
    multiply->setCompositeOpId(COMPOSITE_MULT);
    {
        KisFillPainter gc(multiply->paintDevice());
        gc.fillRect(w / 4, h / 4, w / 2, h / 2, KoColor(QColor(200, 220, 255), cs));
        gc.end();
    }
    image->addNode(multiply);
    return image;
}

} // namespace

void AgentSpeedBenchmark::benchmark()
{
    const QSize big(6000, 4500);
    const int viewSide = 1568;
    const qreal viewScale = qreal(viewSide) / qMax(big.width(), big.height());
    const QSize viewSize(qRound(big.width() * viewScale), qRound(big.height() * viewScale));

    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    KisImageSP image = makeImage(big);
    kisdoc->setCurrentImage(image);
    QScopedPointer<Document> doc(new Document(kisdoc.data(), false));
    doc->refreshProjection();

    report("document", QString("%1x%2, 3 paint layers (normal, 70% opacity, multiply)").arg(big.width()).arg(big.height()));

    // Memory first, before any full-size read has raised the peak.
    {
        const qint64 before = peakResidentBytes();
        QImage view = doc->projection(QRect(QPoint(), big), viewScale);
        const qint64 afterScaled = peakResidentBytes();
        QImage full = doc->projection(0, 0, big.width(), big.height());
        const qint64 afterFull = peakResidentBytes();
        report("peak memory added by the scaled read", QString("%1 MB (output %2x%3 = %4 MB)")
               .arg((afterScaled - before) / 1e6, 0, 'f', 1).arg(view.width()).arg(view.height())
               .arg(view.sizeInBytes() / 1e6, 0, 'f', 1));
        report("peak memory added by the full read", QString("%1 MB (output %2 MB)")
               .arg((afterFull - afterScaled) / 1e6, 0, 'f', 1).arg(full.sizeInBytes() / 1e6, 0, 'f', 1));
    }

    report("refreshProjection() whole image", timeIt(3, [&]() { doc->refreshProjection(); }));
    const QRect region(2600, 1950, 800, 600);
    report("refreshProjection(QRect) 800x600", timeIt(10, [&]() { doc->refreshProjection(region); }));

    {
        QScopedPointer<Node> node(doc->nodeByName("blocks"));
        const QByteArray pixels = node->pixelData(region.x(), region.y(), region.width(), region.height());
        report("setPixelData 800x600 + waitForDone", timeIt(10, [&]() {
                   node->setPixelData(pixels, region.x(), region.y(), region.width(), region.height());
                   doc->waitForDone();
               }));
        report("setPixelData 800x600 + refreshProjection() (before)", timeIt(3, [&]() {
                   node->setPixelData(pixels, region.x(), region.y(), region.width(), region.height());
                   doc->refreshProjection();
               }));
    }

    {
        // The plugin's paint_grid and paint_pixels write row by row or pixel by pixel. Before setPixelData marked
        // its rect dirty it was a bare writeBytes, and the script refreshed the whole image once at the end.
        QScopedPointer<Node> node(doc->nodeByName("blocks"));
        KisPaintDeviceSP dev = KisLayerUtils::findNodeByName(image->root(), "blocks")->paintDevice();
        const QRect rows(2600, 1950, 800, 500);
        const QByteArray row = node->pixelData(rows.x(), rows.y(), rows.width(), 1);
        report("500 rows of 800x1: writeBytes + refreshProjection() (before)", timeIt(3, [&]() {
                   for (int i = 0; i < rows.height(); ++i) {
                       dev->writeBytes(reinterpret_cast<const quint8 *>(row.constData()), rows.x(), rows.y() + i, rows.width(), 1);
                   }
                   doc->refreshProjection();
               }));
        report("500 rows of 800x1: setPixelData each + waitForDone", timeIt(3, [&]() {
                   for (int i = 0; i < rows.height(); ++i) {
                       node->setPixelData(row, rows.x(), rows.y() + i, rows.width(), 1);
                   }
                   doc->waitForDone();
               }));
        report("500 rows of 800x1: setPixelData + refreshProjection(QRect)", timeIt(3, [&]() {
                   for (int i = 0; i < rows.height(); ++i) {
                       node->setPixelData(row, rows.x(), rows.y() + i, rows.width(), 1);
                   }
                   doc->refreshProjection(rows);
               }));
        const QByteArray pixel = node->pixelData(100, 100, 1, 1);
        report("500 single pixels: writeBytes + refreshProjection() (before)", timeIt(3, [&]() {
                   for (int i = 0; i < 500; ++i) {
                       dev->writeBytes(reinterpret_cast<const quint8 *>(pixel.constData()), (i * 997) % 6000, (i * 613) % 4500, 1, 1);
                   }
                   doc->refreshProjection();
               }));
        report("500 single pixels: setPixelData each + waitForDone", timeIt(3, [&]() {
                   for (int i = 0; i < 500; ++i) {
                       node->setPixelData(pixel, (i * 997) % 6000, (i * 613) % 4500, 1, 1);
                   }
                   doc->waitForDone();
               }));
    }

    report("projection() full read only", timeIt(3, [&]() {
               QImage full = doc->projection(0, 0, big.width(), big.height());
               Q_UNUSED(full);
           }));
    report("projection() full read + smooth scale to 1568", timeIt(3, [&]() {
               QImage full = doc->projection(0, 0, big.width(), big.height());
               QImage view = full.scaled(viewSize, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
               Q_UNUSED(view);
           }));
    report("projection(QRect, scale) to 1568", timeIt(5, [&]() {
               QImage view = doc->projection(QRect(QPoint(), big), viewScale);
               Q_UNUSED(view);
           }));
    report("projection(QRect, scale) 1600x1200 crop to 784", timeIt(5, [&]() {
               QImage view = doc->projection(QRect(2000, 1500, 1600, 1200), 0.49);
               Q_UNUSED(view);
           }));
    report("ref: createThumbnailUncached oversample 1", timeIt(3, [&]() {
               QImage view = image->projection()->createThumbnailUncached(viewSize.width(), viewSize.height(), QRect(QPoint(), big), 1);
               Q_UNUSED(view);
           }));
    report("ref: createThumbnailUncached oversample 2", timeIt(3, [&]() {
               QImage view = image->projection()->createThumbnailUncached(viewSize.width(), viewSize.height(), QRect(QPoint(), big), 2);
               Q_UNUSED(view);
           }));

    doc.reset();
    KisPart::instance()->removeDocument(kisdoc.data(), false);

    // The spec's comparison: reading a whole 1568x1176 painting.
    {
        QScopedPointer<KisDocument> smallDoc(KisPart::instance()->createDocument());
        smallDoc->setCurrentImage(makeImage(viewSize));
        QScopedPointer<Document> d(new Document(smallDoc.data(), false));
        d->refreshProjection();
        report("ref: projection() of a whole 1568x1176 painting", timeIt(5, [&]() {
                   QImage full = d->projection(0, 0, viewSize.width(), viewSize.height());
                   Q_UNUSED(full);
               }));
        report("ref: refreshProjection() of a whole 1568x1176 painting", timeIt(3, [&]() { d->refreshProjection(); }));
        d.reset();
        KisPart::instance()->removeDocument(smallDoc.data(), false);
    }
}

KISTEST_MAIN(AgentSpeedBenchmark)

#include "AgentSpeedBenchmark.moc"
