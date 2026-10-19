/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentScaledProjection.h"

#include <simpletest.h>
#include <testui.h>

#include <QColor>
#include <QImage>
#include <QScopedPointer>

#include <atomic>
#include <thread>
#include <vector>

#include <Document.h>
#include <KisAgentScaledRead.h>
#include <Krita.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorProfile.h>
#include <KoColorSpaceRegistry.h>
#include <kis_fill_painter.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_image_config.h>
#include <kis_simple_stroke_strategy.h>

#include <QElapsedTimer>

namespace {

/**
 * A document with detail at every scale: a two-axis gradient, coloured blocks, a 50% transparent band on a second
 * layer at half opacity, and one-pixel lines.
 */
struct PatternDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    QScopedPointer<Document> doc;

    explicit PatternDocument(const QSize &size)
        : kisdoc(KisPart::instance()->createDocument())
    {
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(0, size.width(), size.height(), cs, "test");

        KisPaintLayerSP base = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
        {
            const int w = size.width();
            const int h = size.height();
            QByteArray row(w * 4, 0);
            for (int y = 0; y < h; ++y) {
                quint8 *p = reinterpret_cast<quint8 *>(row.data());
                for (int x = 0; x < w; ++x, p += 4) {
                    p[0] = quint8(255 * y / qMax(1, h - 1));               // B
                    p[1] = quint8(128);                                    // G
                    p[2] = quint8(255 * x / qMax(1, w - 1));               // R
                    p[3] = 255;                                            // A
                    if (x % 37 == 0 || y % 41 == 0) {                      // one-pixel lines
                        p[0] = p[1] = p[2] = 0;
                    }
                }
                base->paintDevice()->writeBytes(reinterpret_cast<const quint8 *>(row.constData()), 0, y, w, 1);
            }
            KisFillPainter gc(base->paintDevice());
            gc.fillRect(w / 8, h / 8, w / 4, h / 4, KoColor(Qt::yellow, cs));
            gc.fillRect(w / 2, h / 2, w / 3, h / 5, KoColor(Qt::darkCyan, cs));
            gc.end();
        }
        image->addNode(base);

        KisPaintLayerSP top = new KisPaintLayer(image, "top", OPACITY_OPAQUE_U8 / 2);
        {
            QColor translucentMagenta(Qt::magenta);
            translucentMagenta.setAlpha(128);
            KisFillPainter gc(top->paintDevice());
            gc.fillRect(0, size.height() / 3, size.width(), size.height() / 6, KoColor(translucentMagenta, cs));
            gc.end();
        }
        image->addNode(top);

        kisdoc->setCurrentImage(image);
        doc.reset(new Document(kisdoc.data(), false));
        doc->refreshProjection();
    }

    ~PatternDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }
};

/// Largest and mean per-channel difference between two images of the same size (non-premultiplied ARGB).
void compare(const QImage &a, const QImage &b, int *maxDiff, double *meanDiff)
{
    const QImage x = a.convertToFormat(QImage::Format_ARGB32);
    const QImage y = b.convertToFormat(QImage::Format_ARGB32);
    qint64 sum = 0;
    int largest = 0;
    for (int row = 0; row < x.height(); ++row) {
        const QRgb *p = reinterpret_cast<const QRgb *>(x.constScanLine(row));
        const QRgb *q = reinterpret_cast<const QRgb *>(y.constScanLine(row));
        for (int col = 0; col < x.width(); ++col) {
            const int d[4] = {qAbs(qRed(p[col]) - qRed(q[col])), qAbs(qGreen(p[col]) - qGreen(q[col])),
                              qAbs(qBlue(p[col]) - qBlue(q[col])), qAbs(qAlpha(p[col]) - qAlpha(q[col]))};
            for (int c = 0; c < 4; ++c) {
                largest = qMax(largest, d[c]);
                sum += d[c];
            }
        }
    }
    *maxDiff = largest;
    *meanDiff = double(sum) / qMax(1, 4 * x.width() * x.height());
}

} // namespace

void TestDocumentScaledProjection::testSize_data()
{
    QTest::addColumn<QRect>("rect");
    QTest::addColumn<qreal>("scale");
    QTest::addColumn<QSize>("expected");

    QTest::newRow("whole image, quarter") << QRect(0, 0, 600, 400) << 0.25 << QSize(150, 100);
    QTest::newRow("sub-rect, half") << QRect(100, 50, 300, 200) << 0.5 << QSize(150, 100);
    QTest::newRow("long side to 157") << QRect(0, 0, 600, 400) << 157.0 / 600 << QSize(157, 105);
    QTest::newRow("tiny scale keeps one pixel") << QRect(0, 0, 600, 400) << 0.0001 << QSize(1, 1);
    QTest::newRow("rect past the image edge") << QRect(500, 300, 200, 200) << 0.5 << QSize(100, 100);
}

void TestDocumentScaledProjection::testSize()
{
    QFETCH(QRect, rect);
    QFETCH(qreal, scale);
    QFETCH(QSize, expected);

    PatternDocument d(QSize(600, 400));
    const QImage view = d.doc->projection(rect, scale);
    QCOMPARE(view.size(), expected);
}

void TestDocumentScaledProjection::testMatchesSmoothDownscaleOfFullRead_data()
{
    QTest::addColumn<QRect>("rect");
    QTest::addColumn<qreal>("scale");
    QTest::addColumn<int>("maxTolerance");
    QTest::addColumn<double>("meanTolerance");

    // Both are area averages: they differ only by rounding, also where an output pixel's edges fall inside
    // source pixels (fractional ratios) and across the one-pixel lines.
    QTest::newRow("whole image, quarter") << QRect(0, 0, 600, 400) << 0.25 << 2 << 0.5;
    QTest::newRow("sub-rect, half") << QRect(120, 80, 300, 200) << 0.5 << 2 << 0.5;
    QTest::newRow("long side to 157") << QRect(0, 0, 600, 400) << 157.0 / 600 << 2 << 0.5;
    QTest::newRow("sub-rect to 0.37") << QRect(33, 21, 400, 300) << 0.37 << 2 << 0.5;
}

void TestDocumentScaledProjection::testMatchesSmoothDownscaleOfFullRead()
{
    QFETCH(QRect, rect);
    QFETCH(qreal, scale);
    QFETCH(int, maxTolerance);
    QFETCH(double, meanTolerance);

    PatternDocument d(QSize(600, 400));
    const QImage view = d.doc->projection(rect, scale);
    QVERIFY(!view.isNull());

    const QImage full = d.doc->projection(rect.x(), rect.y(), rect.width(), rect.height());
    const QImage reference = full.scaled(view.size(), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);

    int maxDiff = 0;
    double meanDiff = 0;
    compare(view, reference, &maxDiff, &meanDiff);
    qDebug() << "max" << maxDiff << "mean" << meanDiff;
    QVERIFY2(maxDiff <= maxTolerance, qPrintable(QString("largest channel difference %1").arg(maxDiff)));
    QVERIFY2(meanDiff <= meanTolerance, qPrintable(QString("mean channel difference %1").arg(meanDiff)));
}

void TestDocumentScaledProjection::testTransparencyIsKept()
{
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
    KisImageSP image = new KisImage(0, 400, 200, cs, "test");
    KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
    KisFillPainter gc(layer->paintDevice());
    gc.fillRect(0, 0, 200, 200, KoColor(Qt::green, cs)); // the right half stays transparent
    gc.end();
    image->addNode(layer);
    kisdoc->setCurrentImage(image);
    {
        Document doc(kisdoc.data(), false);
        doc.refreshProjection();

        const QImage view = doc.projection(QRect(0, 0, 400, 200), 0.25);
        QCOMPARE(view.size(), QSize(100, 50));
        QCOMPARE(view.pixelColor(10, 10), QColor(Qt::green));
        QCOMPARE(view.pixelColor(90, 40).alpha(), 0);
        // Output column 49 covers source columns 196-199, all green: fully opaque.
        const QColor edge = view.pixelColor(49, 10);
        QCOMPARE(edge.alpha(), 255);
        // A pixel straddling the edge (columns 196-203, half green, half transparent) is green at half alpha, not
        // darkened by the transparent half.
        const QImage straddle = doc.projection(QRect(196, 0, 8, 8), 0.125);
        QCOMPARE(straddle.size(), QSize(1, 1));
        QVERIFY2(qAbs(straddle.pixelColor(0, 0).alpha() - 128) <= 1, qPrintable(QString::number(straddle.pixelColor(0, 0).alpha())));
        QCOMPARE(straddle.pixelColor(0, 0).green(), 255);
        QCOMPARE(straddle.pixelColor(0, 0).red(), 0);
    }
    KisPart::instance()->removeDocument(kisdoc.data(), false);
}

void TestDocumentScaledProjection::testSixteenBitDocument()
{
    // Converted to 8-bit sRGB as projection(x, y, w, h) converts, then averaged.
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb16();
    KisImageSP image = new KisImage(0, 300, 200, cs, "test");
    KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
    KisFillPainter gc(layer->paintDevice());
    gc.fillRect(0, 0, 300, 200, KoColor(QColor(40, 90, 200), cs));
    gc.fillRect(50, 30, 101, 77, KoColor(QColor(250, 200, 10), cs));
    gc.end();
    image->addNode(layer);
    kisdoc->setCurrentImage(image);
    {
        Document doc(kisdoc.data(), false);
        doc.refreshProjection();
        const QRect rect(0, 0, 300, 200);
        const QImage view = doc.projection(rect, 0.3);
        QCOMPARE(view.size(), QSize(90, 60));
        const QImage reference = doc.projection(0, 0, 300, 200).scaled(view.size(), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
        int maxDiff = 0;
        double meanDiff = 0;
        compare(view, reference, &maxDiff, &meanDiff);
        QVERIFY2(maxDiff <= 2, qPrintable(QString("largest channel difference %1").arg(maxDiff)));
        QVERIFY2(meanDiff <= 0.5, qPrintable(QString("mean channel difference %1").arg(meanDiff)));
    }
    KisPart::instance()->removeDocument(kisdoc.data(), false);
}

void TestDocumentScaledProjection::testScaleOneIsTheFullRead()
{
    PatternDocument d(QSize(300, 200));
    const QRect rect(10, 20, 120, 90);
    const QImage view = d.doc->projection(rect, 1.0);
    const QImage full = d.doc->projection(rect.x(), rect.y(), rect.width(), rect.height());
    QCOMPARE(view.size(), rect.size());
    QCOMPARE(view.convertToFormat(QImage::Format_ARGB32), full.convertToFormat(QImage::Format_ARGB32));

    // No upscaling: a scale above one reads at full size.
    QCOMPARE(d.doc->projection(rect, 2.0).size(), rect.size());
}

void TestDocumentScaledProjection::testInvalidArguments()
{
    PatternDocument d(QSize(300, 200));
    QVERIFY(d.doc->projection(QRect(), 0.5).isNull());
    QVERIFY(d.doc->projection(QRect(0, 0, 100, 100), 0).isNull());
    QVERIFY(d.doc->projection(QRect(0, 0, 100, 100), -1).isNull());
}

void TestDocumentScaledProjection::testConversionDuringRead()
{
    // Colour-space conversions (8 to 16 bit and back: the pixel size doubles) run while another thread reads
    // views. The read must never see a device change under it: no crash, and each view is the 8-bit image or
    // the 16-bit one.
    PatternDocument d(QSize(1200, 900));
    const QRect rect(0, 0, 1200, 900);
    const qreal scale = 0.5;
    const KoColorSpace *rgb8 = KoColorSpaceRegistry::instance()->rgb8();
    const KoColorSpace *rgb16 = KoColorSpaceRegistry::instance()->rgb16();
    auto convert = [&](const KoColorSpace *cs) {
        d.image->convertImageColorSpace(cs, KoColorConversionTransformation::internalRenderingIntent(),
                                        KoColorConversionTransformation::internalConversionFlags());
        d.image->waitForDone();
    };
    // The two states a view may show: the 8-bit image, and the 16-bit one (which composites with other rounding).
    const QImage reference = d.doc->projection(rect, scale);
    QCOMPARE(reference.size(), QSize(600, 450));
    convert(rgb16);
    const QImage reference16 = d.doc->projection(rect, scale);
    convert(rgb8);
    {
        int maxDiff = 0;
        double meanDiff = 0;
        compare(d.doc->projection(rect, scale), reference, &maxDiff, &meanDiff);
        QVERIFY2(maxDiff <= 2, qPrintable(QString("8 bit again differs by %1").arg(maxDiff)));
        compare(reference16, reference, &maxDiff, &meanDiff);
        qDebug() << "8 and 16 bit views differ by up to" << maxDiff << "mean" << meanDiff;
    }

    std::atomic<bool> done(false);
    std::vector<QImage> views;
    std::thread reader([&]() {
        while (!done.load()) {
            views.push_back(d.doc->projection(rect, scale));
        }
    });

    for (int i = 0; i < 6; ++i) {
        convert(i % 2 ? rgb8 : rgb16);
        // The reader takes the lock only between jobs, never forcing them to end: leave it room.
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }
    done = true;
    reader.join();

    QVERIFY2(views.size() >= 3, qPrintable(QString("only %1 views read").arg(views.size())));
    int worst = 0;
    for (const QImage &view : views) {
        QCOMPARE(view.size(), reference.size());
        int maxDiff = 0;
        int maxDiff16 = 0;
        double meanDiff = 0;
        compare(view, reference, &maxDiff, &meanDiff);
        compare(view, reference16, &maxDiff16, &meanDiff);
        worst = qMax(worst, qMin(maxDiff, maxDiff16));
    }
    qDebug() << views.size() << "views read during 6 conversions, largest difference" << worst;
    QVERIFY2(worst <= 2, qPrintable(QString("a view differs by %1").arg(worst)));
}

void TestDocumentScaledProjection::testOpenStrokeIsNotEnded()
{
    // The read waits for the image's queued work without asking anyone to end a stroke: with a stroke open (the
    // artist holding the pen) it returns a null image after its timeout, or a view once the stroke ends, and the
    // image never emits sigStrokeEndRequested.
    PatternDocument d(QSize(400, 300));
    std::atomic<int> endRequests(0);
    QObject::connect(d.image.data(), &KisImage::sigStrokeEndRequested, d.image.data(),
                     [&]() { ++endRequests; }, Qt::DirectConnection);

    const KisStrokeId stroke = d.image->startStroke(new KisSimpleStrokeStrategy(QLatin1String("held-pen")));
    const int requestsBeforeRead = endRequests.load(); // starting a stroke asks other strokes to end: not ours
    // A watchdog ends the stroke after 2 s, so a read that waits for the stroke's end cannot hang the test.
    std::thread watchdog([&]() {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        d.image->endStroke(stroke);
    });

    const int previousTimeout = KisAgentScaledRead::readLockTimeoutMs();
    KisAgentScaledRead::setReadLockTimeoutMs(300);
    QElapsedTimer timer;
    timer.start();
    const QImage view = d.doc->projection(QRect(0, 0, 400, 300), 0.5);
    const qint64 waited = timer.elapsed();
    const int requestsDuringRead = endRequests.load() - requestsBeforeRead;
    KisAgentScaledRead::setReadLockTimeoutMs(previousTimeout);
    watchdog.join();
    d.image->waitForDone(); // (waitForDone() itself asks for a stroke end: counted apart)

    qDebug() << "read returned after" << waited << "ms, null:" << view.isNull();
    QCOMPARE(requestsDuringRead, 0);
    QVERIFY2(view.isNull() ? waited < 2000 : waited >= 1900, "neither a timeout nor a wait for the stroke's end");

    // With the stroke over, the read works again, still without asking for a stroke end.
    const int before = endRequests.load();
    QVERIFY(!d.doc->projection(QRect(0, 0, 400, 300), 0.5).isNull());
    QCOMPARE(endRequests.load(), before);
}

void TestDocumentScaledProjection::testThreadedEqualsSingleThread()
{
    // Output rows are split into stripes read in parallel, a source row on a stripe's edge shared by two stripes.
    // With Krita's thread limit at 1 the read is one stripe: the pixels must be the same bit for bit.
    PatternDocument d(QSize(1500, 1100));
    const QRect rect(7, 3, 1490, 1093);
    const qreal scale = 0.37;
    const QImage threaded = d.doc->projection(rect, scale);

    KisImageConfig config(false);
    const int limit = config.maxNumberOfThreads();
    config.setMaxNumberOfThreads(1);
    const QImage single = d.doc->projection(rect, scale);
    config.setMaxNumberOfThreads(limit);

    QCOMPARE(threaded.size(), single.size());
    QVERIFY(threaded.height() >= 2 * 32 * 2); // enough rows for several stripes
    QCOMPARE(threaded.convertToFormat(QImage::Format_ARGB32), single.convertToFormat(QImage::Format_ARGB32));
}

void TestDocumentScaledProjection::testOverflowGuard()
{
    using namespace KisAgentScaledRead;

    // Within the limit: the requested size.
    QCOMPARE(safeOutputSize(QSize(6000, 4500), QSize(1568, 1176)), QSize(1568, 1176));
    QVERIFY(sourcePixelsPerOutputPixel(QSize(6000, 4500), QSize(1568, 1176)) <= 25);

    // 100000 x 100000 into one pixel would gather 1e10 source pixels and overflow the 64-bit sums: read larger.
    const QSize huge(100000, 100000);
    QVERIFY(sourcePixelsPerOutputPixel(huge, QSize(1, 1)) > maxSourcePixelsPerOutputPixel);
    const QSize safe = safeOutputSize(huge, QSize(1, 1));
    QVERIFY(sourcePixelsPerOutputPixel(huge, safe) <= maxSourcePixelsPerOutputPixel);
    QVERIFY(safe.width() <= 8 && safe.height() <= 8);

    // A small limit, so the arithmetic shows: aspect kept, never past the source.
    const QSize grown = safeOutputSize(QSize(1000, 500), QSize(4, 2), 1000);
    QVERIFY2(sourcePixelsPerOutputPixel(QSize(1000, 500), grown) <= 1000,
             qPrintable(QString("%1x%2").arg(grown.width()).arg(grown.height())));
    QVERIFY(qAbs(double(grown.width()) / grown.height() - 2.0) < 0.2);
    QCOMPARE(safeOutputSize(QSize(10, 10), QSize(1, 1), 1), QSize(10, 10));
}

void TestDocumentScaledProjection::testOutsideTheImage()
{
    // A rect reaching past the image reads the projection's default pixel there, as projection(x, y, w, h) does.
    PatternDocument d(QSize(300, 200));
    const QRect rect(200, 120, 200, 160); // half outside on the right and bottom
    const QImage view = d.doc->projection(rect, 0.5);
    QCOMPARE(view.size(), QSize(100, 80));
    QCOMPARE(view.pixelColor(90, 70).alpha(), 0);
    QVERIFY(view.pixelColor(10, 10).alpha() > 0);
    const QImage reference = d.doc->projection(rect.x(), rect.y(), rect.width(), rect.height())
                                 .scaled(view.size(), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
    int maxDiff = 0;
    double meanDiff = 0;
    compare(view, reference, &maxDiff, &meanDiff);
    QVERIFY2(maxDiff <= 2, qPrintable(QString("largest channel difference %1").arg(maxDiff)));
}

void TestDocumentScaledProjection::testOtherColorSpaces_data()
{
    QTest::addColumn<QString>("model");
    QTest::addColumn<QString>("depth");
    QTest::addColumn<bool>("otherProfile");

    QTest::newRow("RGBA float 32") << "RGBA" << "F32" << false;
    QTest::newRow("RGBA 8, not sRGB") << "RGBA" << "U8" << true;
    QTest::newRow("Gray 8") << "GRAYA" << "U8" << false;
    QTest::newRow("Gray 16") << "GRAYA" << "U16" << false;
}

void TestDocumentScaledProjection::testOtherColorSpaces()
{
    // Converted to 8-bit sRGB as projection(x, y, w, h) converts, then averaged: a smooth downscale of the full read.
    QFETCH(QString, model);
    QFETCH(QString, depth);
    QFETCH(bool, otherProfile);

    QString profile;
    if (otherProfile) {
        const QString srgb = KoColorSpaceRegistry::instance()->rgb8()->profile()->name();
        for (const QString &name : Krita().profiles(model, depth)) {
            const KoColorProfile *p = KoColorSpaceRegistry::instance()->profileByName(name);
            if (p && p->isSuitableForOutput() && name != srgb && !name.contains("sRGB", Qt::CaseInsensitive)) {
                profile = name;
                break;
            }
        }
        if (profile.isEmpty()) QSKIP("no RGB profile other than sRGB");
    }
    const KoColorSpace *cs = KoColorSpaceRegistry::instance()->colorSpace(model, depth, profile);
    QVERIFY(cs);

    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    KisImageSP image = new KisImage(0, 300, 200, cs, "test");
    KisPaintLayerSP layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
    KisFillPainter gc(layer->paintDevice());
    gc.fillRect(0, 0, 300, 200, KoColor(QColor(40, 90, 200), cs));
    gc.fillRect(50, 30, 101, 77, KoColor(QColor(250, 200, 10), cs));
    gc.fillRect(170, 100, 7, 63, KoColor(QColor(10, 220, 120), cs));
    gc.end();
    image->addNode(layer);
    KisPaintLayerSP top = new KisPaintLayer(image, "top", OPACITY_OPAQUE_U8 / 2);
    top->paintDevice()->fill(QRect(0, 120, 300, 40), KoColor(QColor(255, 0, 255), cs));
    image->addNode(top);
    kisdoc->setCurrentImage(image);
    {
        Document doc(kisdoc.data(), false);
        doc.refreshProjection();
        const QImage view = doc.projection(QRect(0, 0, 300, 200), 0.3);
        QCOMPARE(view.size(), QSize(90, 60));
        const QImage reference = doc.projection(0, 0, 300, 200).scaled(view.size(), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
        int maxDiff = 0;
        double meanDiff = 0;
        compare(view, reference, &maxDiff, &meanDiff);
        qDebug() << cs->name() << cs->profile()->name() << "max" << maxDiff << "mean" << meanDiff;
        QVERIFY2(maxDiff <= 2, qPrintable(QString("%1: largest channel difference %2").arg(cs->name()).arg(maxDiff)));
        QVERIFY2(meanDiff <= 0.5, qPrintable(QString("%1: mean channel difference %2").arg(cs->name()).arg(meanDiff)));
    }
    KisPart::instance()->removeDocument(kisdoc.data(), false);
}

KISTEST_MAIN(TestDocumentScaledProjection)
