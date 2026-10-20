/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Document methods whose cost grows with the area a script touches, not with the image size
// (Krita Agent, openspec change krita-fork, capability agent-speed-api). Kept apart from
// Document.cpp so the upstream file carries only their declarations.

#include "ScriptWaits.h"
#include <kis_processing_applicator.h>
#include "Document.h"
#include "KisAgentReadLock.h"
#include "KisAgentScaledRead.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QPointer>
#include <QThread>
#include <QRect>

#include <QImage>
#include <QtConcurrent/QtConcurrentMap>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <utility>
#include <vector>

#include <KisDocument.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_image_config.h>
#include <kis_abstract_projection_plane.h>
#include <kis_layer_utils.h>
#include <kis_node.h>
#include <kis_paint_device.h>

namespace {

/// Where a source pixel's span falls in the output along one axis: its first output pixel, and the share of
/// the source pixel (out of 256) that lies in it; the rest lies in the next output pixel.
struct AxisSplit {
    int first;
    int weight; // 0..256
};

/// For \p in source pixels scaled to \p out output pixels (out <= in): output pixel i covers source span
/// [i * in / out, (i + 1) * in / out), so a source pixel covers at most two output pixels.
std::vector<AxisSplit> splitAxis(int in, int out)
{
    std::vector<AxisSplit> split(in);
    for (int x = 0; x < in; ++x) {
        const qint64 first = qint64(x) * out / in;
        // Length of [x, x + 1) inside output pixel `first`, in units of 1/out source pixels.
        const qint64 inside = qMin<qint64>(out, (first + 1) * in - qint64(x) * out);
        split[x].first = int(first);
        split[x].weight = int((inside * 256 + out / 2) / out);
    }
    return split;
}

/// Area-weighted sums for one row of output pixels: alpha-weighted colour, alpha, and coverage.
struct RowSums {
    explicit RowSums(int n) : v(size_t(n) * 5, 0), n(n) {}
    std::vector<quint64> v; // per output pixel: b, g, r, a, w
    int n;

    void clear() { std::fill(v.begin(), v.end(), 0); }

    void add(const RowSums &h, quint64 weight)
    {
        quint64 *d = v.data();
        const quint64 *s = h.v.data();
        for (size_t i = 0; i < v.size(); ++i) d[i] += s[i] * weight;
    }

    /// Writes the averages as non-premultiplied BGRA, the byte order of QImage::Format_ARGB32 here.
    void write(quint8 *dst) const
    {
        const quint64 *s = v.data();
        for (int i = 0; i < n; ++i, s += 5, dst += 4) {
            const quint64 alpha = s[3];
            const quint64 cover = s[4];
            if (!alpha || !cover) {
                dst[0] = dst[1] = dst[2] = dst[3] = 0;
                continue;
            }
            dst[0] = quint8(qMin<quint64>(255, (s[0] + alpha / 2) / alpha));
            dst[1] = quint8(qMin<quint64>(255, (s[1] + alpha / 2) / alpha));
            dst[2] = quint8(qMin<quint64>(255, (s[2] + alpha / 2) / alpha));
            dst[3] = quint8(qMin<quint64>(255, (alpha + cover / 2) / cover));
        }
    }
};

/// Sums one 8-bit BGRA source row across, into \p row (cleared first).
inline void sumRow(const quint8 *p, int rw, const AxisSplit *xs, RowSums &row)
{
    row.clear();
    quint64 *v = row.v.data();
    for (int x = 0; x < rw; ++x, p += 4) {
        const quint64 alpha = p[3];
        const AxisSplit s = xs[x];
        quint64 *o = v + size_t(s.first) * 5;
        const quint64 w0 = quint64(s.weight);
        const quint64 aw0 = alpha * w0;
        o[0] += p[0] * aw0;
        o[1] += p[1] * aw0;
        o[2] += p[2] * aw0;
        o[3] += aw0;
        o[4] += w0;
        if (s.weight < 256) {
            const quint64 w1 = 256 - w0;
            const quint64 aw1 = alpha * w1;
            o[5] += p[0] * aw1;
            o[6] += p[1] * aw1;
            o[7] += p[2] * aw1;
            o[8] += aw1;
            o[9] += w1;
        }
    }
}

/// Everything a stripe of output rows needs to read its source rows.
struct ScaledReadJob {
    KisPaintDeviceSP dev;
    QRect rect;
    const KoColorSpace *srcCs;
    const KoColorSpace *dstCs;
    bool convert;
    const AxisSplit *xs;
    const AxisSplit *ys;
    int outW;
    uchar *bits;          // the output image's pixels, taken once so threads never call QImage::scanLine()
    qsizetype bytesPerLine;
};

/// Computes output rows [j0, j1) of the job: reads, a few hundred kilobytes at a time, the source rows that
/// cover them, and keeps two output rows of sums.
void readStripe(const ScaledReadJob &job, int j0, int j1)
{
    const int rw = job.rect.width();
    const int rh = job.rect.height();
    const int outW = job.outW;
    const AxisSplit *ys = job.ys;

    // Source rows reaching into the stripe: the last row of output row j0 - 1 may spill into j0.
    int yBegin = 0;
    while (yBegin < rh && ys[yBegin].first < j0 - 1) ++yBegin;
    int yEnd = yBegin;
    while (yEnd < rh && ys[yEnd].first < j1) ++yEnd;
    if (yBegin >= yEnd) return;

    const int srcPixelSize = job.srcCs->pixelSize();
    const int chunkRows = qBound(1, int((256 << 10) / qMax<qint64>(1, qint64(rw) * srcPixelSize)), yEnd - yBegin);
    std::vector<quint8> srcBuf(size_t(rw) * chunkRows * srcPixelSize);
    std::vector<quint8> rgbBuf(job.convert ? size_t(rw) * chunkRows * 4 : 0);

    RowSums row(outW);
    RowSums cur(outW);   // output row `current`
    RowSums next(outW);  // output row `current + 1`
    int current = j0;

    for (int y0 = yBegin; y0 < yEnd; y0 += chunkRows) {
        const int n = qMin(chunkRows, yEnd - y0);
        job.dev->readBytes(srcBuf.data(), job.rect.x(), job.rect.y() + y0, rw, n);
        const quint8 *rgb = srcBuf.data();
        if (job.convert) {
            job.srcCs->convertPixelsTo(srcBuf.data(), rgbBuf.data(), job.dstCs, rw * n,
                                       KoColorConversionTransformation::internalRenderingIntent(),
                                       KoColorConversionTransformation::internalConversionFlags());
            rgb = rgbBuf.data();
        }

        for (int k = 0; k < n; ++k) {
            const AxisSplit s = ys[y0 + k];
            if (s.first < j0) {
                // The previous stripe's row: only the part spilling into j0 is ours.
                if (s.weight < 256) {
                    sumRow(rgb + size_t(k) * rw * 4, rw, job.xs, row);
                    cur.add(row, quint64(256 - s.weight));
                }
                continue;
            }
            if (s.first > current) {
                cur.write(job.bits + current * job.bytesPerLine);
                std::swap(cur, next);
                next.clear();
                current = s.first;
            }
            sumRow(rgb + size_t(k) * rw * 4, rw, job.xs, row);
            cur.add(row, quint64(s.weight));
            if (s.weight < 256 && s.first + 1 < j1) {
                next.add(row, quint64(256 - s.weight));
            }
        }
    }
    cur.write(job.bits + current * job.bytesPerLine);
}

/**
 * Reads \p rect of \p dev scaled down to \p outSize by area averaging, as a smooth downscale does, without copying
 * the full-size rect. Output rows are split into stripes computed in parallel; each stripe reads 256 KB of source
 * rows at a time (plus as much again converted, when the device is not 8-bit sRGB), converts them to 8-bit sRGB as
 * Document::projection(x, y, w, h) does, and keeps three rows of sums (one source row summed across, and two output
 * rows): 5 x 8 bytes per output pixel each, 120 bytes per output column per stripe. Each output pixel is the average of the source area it covers, partial pixels
 * at its edges weighted by their share; colours are weighted by alpha, so transparent pixels do not darken their
 * neighbours.
 */
QImage readScaledAreaAverage(KisPaintDeviceSP dev, const QRect &rect, const QSize &outSize)
{
    QImage out(outSize, QImage::Format_ARGB32);
    if (out.isNull()) return QImage();

    const std::vector<AxisSplit> xs = splitAxis(rect.width(), outSize.width());
    const std::vector<AxisSplit> ys = splitAxis(rect.height(), outSize.height());

    ScaledReadJob job;
    job.dev = dev;
    job.rect = rect;
    job.srcCs = dev->colorSpace();
    job.dstCs = KoColorSpaceRegistry::instance()->rgb8(static_cast<const KoColorProfile *>(nullptr));
    job.convert = !(*job.srcCs == *job.dstCs);
    job.xs = xs.data();
    job.ys = ys.data();
    job.outW = outSize.width();
    job.bits = out.bits();
    job.bytesPerLine = out.bytesPerLine();

    // Stripes of at least 32 output rows, no more than Krita's thread limit (Preferences, Performance). They run on
    // Qt's global thread pool, the calling thread taking part, so the read finishes even when no thread is free
    // and a failure to start one never stops Krita.
    const int outH = outSize.height();
    const int threads = qBound(1, qMin(KisImageConfig(true).maxNumberOfThreads(), outH / 32), 16);
    std::vector<std::pair<int, int>> stripes;
    stripes.reserve(threads);
    for (int t = 0; t < threads; ++t) {
        stripes.emplace_back(int(qint64(outH) * t / threads), int(qint64(outH) * (t + 1) / threads));
    }
    if (threads == 1) {
        readStripe(job, 0, outH);
    } else {
        QtConcurrent::blockingMap(stripes, [&job](std::pair<int, int> &stripe) {
            readStripe(job, stripe.first, stripe.second);
        });
    }
    return out;
}

} // namespace

namespace {

/**
 * The area a change inside \p rect can reach once composited: blur and other filter masks, adjustment layers
 * (inside pass-through groups too) and layer styles such as a drop shadow spread a change past its own pixels.
 * Without this, a refresh of exactly the written rect would leave their halo outside it stale. As the content of
 * any layer may have changed inside \p rect, every rendered node's change rect is taken, as filthy and as lying
 * above the filthy node, and repeated until the area stops growing (an effect's spread can feed the next one's).
 * Clone layers need nothing here: the refresh regenerates them from their sources within the crop rect.
 */
QRect grownByEffects(KisImageSP image, QRect area)
{
    const QRect bounds = image->bounds();
    for (int pass = 0; pass < 16; ++pass) {
        QRect grown = area;
        KisLayerUtils::recursiveApplyNodes(image->root(), [&](KisNodeSP node) {
            if (!node->visible(true)) return;
            KisAbstractProjectionPlaneSP plane = node->projectionPlane();
            if (!plane) return;
            grown |= plane->changeRect(area, KisNode::N_FILTHY);
            grown |= plane->changeRect(area, KisNode::N_ABOVE_FILTHY);
        });
        grown &= bounds;
        if (grown == area) break;
        area = grown;
    }
    return area;
}

} // namespace

quint64 KisAgentScaledRead::sourcePixelsPerOutputPixel(const QSize &source, const QSize &output)
{
    if (output.isEmpty()) return 0;
    const quint64 cx = quint64((source.width() + output.width() - 1) / output.width()) + 1;
    const quint64 cy = quint64((source.height() + output.height() - 1) / output.height()) + 1;
    return cx * cy;
}

QSize KisAgentScaledRead::safeOutputSize(const QSize &source, const QSize &output, quint64 limit)
{
    QSize size = output;
    while (sourcePixelsPerOutputPixel(source, size) > limit
           && (size.width() < source.width() || size.height() < source.height())) {
        const double factor = std::sqrt(double(sourcePixelsPerOutputPixel(source, size)) / double(limit));
        const double grow = qMax(1.01, factor);
        size = QSize(qMin(source.width(), qMax(size.width() + 1, int(std::ceil(size.width() * grow)))),
                     qMin(source.height(), qMax(size.height() + 1, int(std::ceil(size.height() * grow)))));
    }
    return size;
}

void Document::refreshProjection(const QRect &rect)
{
    QPointer<KisDocument> doc = document();
    if (!doc || !doc->image()) return;
    KisImageSP image = doc->image();

    QRect area = rect.normalized() & image->bounds();
    if (area.isEmpty()) return;
    area = grownByEffects(image, area);

    ScriptWaits::run(image, "Document.refreshProjection()", [&]() {
        // The same recomposition as refreshProjection(), limited to the area. The crop rect is the image, as for
        // KisImage::refreshGraphAsync(root): clone layers read their sources' projections within it.
        image->refreshGraphAsync(KisNodeSP(), area, image->bounds());
    });
}

namespace {

thread_local bool s_inScaledRead = false;

} // namespace

QImage Document::projection(const QRect &rect, qreal scale) const
{
    QPointer<KisDocument> doc = document();
    if (!doc || !doc->image()) return QImage();
    if (rect.isEmpty() || !(scale > 0)) return QImage();
    KisImageSP image = doc->image();

    // The read takes the projection's colour space and pixel size once and then reads from several threads: a
    // colour-space conversion or a resize running meanwhile would change the device under it (and overflow the
    // read buffers), and a job half done (a conversion that has not recomposited yet) would show a view that is
    // neither the old image nor the new one. So it holds a read-only barrier lock, which waits for the queued jobs
    // and keeps any new one from starting until the read ends. barrierLock() would ask the active tool to end its
    // stroke (the artist's, mid-drag); tryBarrierLock() does not, so it is retried, as KisDocument's undo stack
    // does, until it succeeds or the timeout passes (null image: try again later, or read at full size).
    if (s_inScaledRead) return QImage(); // re-entered from the events processed while waiting
    s_inScaledRead = true;
    struct InReadReset {
        ~InReadReset() { s_inScaledRead = false; }
    } inReadReset;

    if (!KisAgentReadLock::tryLock(image, KisAgentScaledRead::readLockTimeoutMs())) {
        return QImage();
    }
    struct Unlock {
        KisImageSP image;
        ~Unlock() { image->unlock(); }
    } unlock{image};

    if (scale >= 1.0) {
        return image->convertToQImage(rect, nullptr);
    }
    const QSize outSize(qMax(1, qRound(rect.width() * scale)), qMax(1, qRound(rect.height() * scale)));
    // An output pixel gathering billions of source pixels would overflow the sums: average into a larger image
    // first, then let Qt scale that down.
    const QSize readSize = KisAgentScaledRead::safeOutputSize(rect.size(), outSize);
    QImage view = readScaledAreaAverage(image->projection(), rect, readSize);
    if (readSize != outSize && !view.isNull()) {
        view = view.scaled(outSize, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
    }
    return view;
}

namespace {
std::atomic<int> s_readLockTimeoutMs(KisAgentScaledRead::defaultReadLockTimeoutMs);
}

int KisAgentScaledRead::readLockTimeoutMs()
{
    return s_readLockTimeoutMs.load();
}

void KisAgentScaledRead::setReadLockTimeoutMs(int ms)
{
    s_readLockTimeoutMs = qMax(0, ms);
}
