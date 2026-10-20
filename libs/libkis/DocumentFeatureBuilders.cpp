/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Krita Agent: feature builders (openspec change krita-fork, task 6.3, capability canvas-features). Each builds a mask
// for Document.addFeature() with Krita's own selection logic (KisFeatureBuilders), without a view, and changes
// nothing: no pixel, no selection, no undo step. Kept apart from Document.cpp so the upstream file carries only their
// declarations.
//
// How each call treats the artist's painting (the review of 6.3):
// - it never asks the artist's open stroke to end and never waits for the image to be idle (KisImage::waitForDone() does
//   both): it takes a read-only barrier lock with tryBarrierLock, retried until the call's time limit (KisAgentReadLock),
//   copies what it reads (a snapshot sharing the image's tiles), releases the lock, and works on the snapshot;
//   when the image stays busy the call gives up with None and a warning;
// - its input is capped (a call's cost follows its input) and the whole call has a time limit, 5 s unless the script
//   asks for up to 30 s ("timeoutMs"); the GUI thread keeps repainting meanwhile (non-input events are processed).
//   A single flood fill or filter pass runs to its end; the limit is checked between steps.

#include "Document.h"
#include "Feature.h"
#include "KisAgentReadLock.h"
#include "Selection.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QMetaType>
#include <QSet>
#include <QThread>
#include <QUuid>
#include <QtMath>

#include <cmath>
#include <functional>

#include <KisDocument.h>
#include <KisFeature.h>
#include <KisFeatureBuilders.h>
#include <KisFeatureList.h>
#include <KoColor.h>
#include <kis_debug.h>
#include <kis_default_bounds.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_layer.h>
#include <kis_layer_utils.h>
#include <kis_node.h>
#include <kis_paint_device.h>
#include <kis_pixel_selection.h>
#include <kis_selection.h>

namespace
{

// The largest input a call takes; more is refused with a warning. Each cap is far past what a painting needs.
const int MAX_SEEDS = 256;
const int MAX_COLORS_AND_POINTS = 64;
const int MAX_OUTLINE_POINTS = 128;
const int MAX_HINTS = 32;
const int MAX_REFINEMENT = 100;       // grow, shrink and feather, in pixels
const int MAX_SEARCH_RADIUS = 200;
const int MAX_ANCHOR_RADIUS = 200;
const int MAX_SETTLE = 100;
const int DEFAULT_TIMEOUT_MS = 5000;
const int MAX_TIMEOUT_MS = 30000;
/// Numbers beyond this are no pixel of any painting: refused before they reach an integer.
const double MAX_COORDINATE = 1e9;

bool isGuiThread()
{
    return QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread();
}

/// The time limit of one call. Asked by the builders (shouldStop) every few milliseconds, which also lets the GUI
/// thread process non-input events, so the window repaints.
class Budget
{
public:
    Budget()
    {
        m_started.start();
        m_pumped.start();
    }
    void setLimit(int ms) { m_limitMs = ms; }
    int limitMs() const { return m_limitMs; }
    qint64 elapsedMs() const { return m_started.elapsed(); }
    bool expired() const { return m_started.elapsed() >= m_limitMs; }
    int remainingMs() const { return int(qMax<qint64>(1, m_limitMs - m_started.elapsed())); }
    bool shouldStop()
    {
        if (expired()) return true;
        if (isGuiThread() && m_pumped.elapsed() >= 40) {
            m_pumped.restart();
            QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents);
        }
        return false;
    }

private:
    QElapsedTimer m_started, m_pumped;
    int m_limitMs = DEFAULT_TIMEOUT_MS;
};

/// A builder running on this thread: the events processed while it waits could call another builder, which is refused.
thread_local bool s_building = false;

class Running
{
public:
    explicit Running(const char *call)
        : m_ok(!s_building)
    {
        if (m_ok) {
            s_building = true;
        } else {
            warnScript << call << "refused: another builder is running (called from an event it processed)";
        }
    }
    ~Running()
    {
        if (m_ok) s_building = false;
    }
    Running(const Running &) = delete;
    Running &operator=(const Running &) = delete;
    bool ok() const { return m_ok; }

private:
    bool m_ok;
};

/// Reads a builder's options strictly: an unknown key or a value of the wrong type or out of range is refused with
/// a warning naming the call, so a typo never silently gives a different mask.
class Options
{
public:
    Options(const char *call, const QVariantMap &options, const QStringList &known)
        : m_call(call)
        , m_options(options)
    {
        for (auto it = options.constBegin(); it != options.constEnd(); ++it) {
            if (!known.contains(it.key())) fail(QString("unknown option \"%1\" (known: %2)").arg(it.key(), known.join(", ")));
        }
    }

    bool ok() const { return m_ok; }
    bool has(const QString &key) const { return m_options.contains(key); }
    const char *call() const { return m_call; }

    void fail(const QString &message)
    {
        if (m_ok) warnScript << m_call << "refused:" << message;
        m_ok = false;
    }

    int integer(const QString &key, int fallback, int low, int high)
    {
        if (!has(key)) return fallback;
        bool ok = false;
        const int value = toInteger(m_options.value(key), &ok);
        if (!ok || value < low || value > high) {
            fail(QString("%1 must be a whole number from %2 to %3").arg(key).arg(low).arg(high));
            return fallback;
        }
        return value;
    }

    qreal number(const QString &key, qreal fallback, qreal low, qreal high)
    {
        if (!has(key)) return fallback;
        const QVariant value = m_options.value(key);
        const double number = isNumber(value) ? value.toDouble() : std::numeric_limits<double>::quiet_NaN();
        if (!std::isfinite(number) || number < low || number > high) {
            fail(QString("%1 must be a number from %2 to %3").arg(key).arg(low).arg(high));
            return fallback;
        }
        return number;
    }

    bool boolean(const QString &key, bool fallback)
    {
        if (!has(key)) return fallback;
        const QVariant value = m_options.value(key);
        if (value.userType() != QMetaType::Bool) {
            fail(QString("%1 must be True or False").arg(key));
            return fallback;
        }
        return value.toBool();
    }

    /// More than \p max items of \p what is refused.
    void cap(int count, int max, const char *what)
    {
        if (count > max) fail(QString("%1 %2 given, at most %3 are taken").arg(count).arg(what).arg(max));
    }

    QVariant value(const QString &key) const { return m_options.value(key); }

    static bool isNumber(const QVariant &value)
    {
        switch (value.userType()) {
        case QMetaType::Int:
        case QMetaType::UInt:
        case QMetaType::LongLong:
        case QMetaType::ULongLong:
        case QMetaType::Double:
        case QMetaType::Float:
            return true;
        default:
            return false;
        }
    }

    /// A whole number within a billion (nothing else is a pixel count), or \p ok false.
    static int toInteger(const QVariant &value, bool *ok)
    {
        *ok = false;
        if (!isNumber(value)) return 0;
        const double number = value.toDouble();
        if (!std::isfinite(number) || qAbs(number) > MAX_COORDINATE || number != std::floor(number)) return 0;
        *ok = true;
        return int(number);
    }

    /// A finite point: a QPoint, a QPointF, or a list of two numbers.
    static bool toPoint(const QVariant &value, QPointF *point)
    {
        const int type = value.userType();
        QPointF candidate;
        if (type == QMetaType::QPointF || type == QMetaType::QPoint) {
            candidate = value.toPointF();
        } else if (value.canConvert<QVariantList>() && type != QMetaType::QString) {
            const QVariantList list = value.toList();
            if (list.size() != 2 || !isNumber(list[0]) || !isNumber(list[1])) return false;
            candidate = QPointF(list[0].toDouble(), list[1].toDouble());
        } else {
            return false;
        }
        if (!isCoordinate(candidate)) return false;
        *point = candidate;
        return true;
    }

    static bool isCoordinate(const QPointF &point)
    {
        return std::isfinite(point.x()) && std::isfinite(point.y()) && qAbs(point.x()) <= MAX_COORDINATE
            && qAbs(point.y()) <= MAX_COORDINATE;
    }

private:
    const char *m_call;
    QVariantMap m_options;
    bool m_ok = true;
};

/// The pixel a point lies in, when it lies in \p bounds.
bool pixelIn(const QPointF &point, const QRect &bounds, QPoint *pixel)
{
    if (!Options::isCoordinate(point)) return false;
    if (point.x() < bounds.left() || point.x() >= bounds.right() + 1.0) return false;
    if (point.y() < bounds.top() || point.y() >= bounds.bottom() + 1.0) return false;
    *pixel = QPoint(qFloor(point.x()), qFloor(point.y()));
    return true;
}

/// Reads a Selection's mask (Document, a friend of Selection, passes it).
using Unwrap = std::function<KisPixelSelectionSP(Selection *)>;

/// A Selection's mask, or a feature's when given its name (outer spaces dropped, as for feature names). Nothing (and
/// \p ok false) for anything else.
KisPixelSelectionSP maskOf(KisImageSP image, const QVariant &value, const Unwrap &unwrap, bool *ok)
{
    *ok = true;
    if (value.userType() == QMetaType::QString) {
        KisFeatureSP feature = image->featureList()->featureByName(value.toString().trimmed());
        if (feature) return feature->mask();
    } else if (value.canConvert<QObject *>()) {
        Selection *selection = qobject_cast<Selection *>(value.value<QObject *>());
        KisPixelSelectionSP mask = selection ? unwrap(selection) : KisPixelSelectionSP();
        if (mask) return mask;
    }
    *ok = false;
    return KisPixelSelectionSP();
}

/// The layer \p value names: its unique id (a string "{...}" or a QUuid), or its name when no other node has it. Not
/// a mask, not a group, not the root. Called with the image locked.
KisNodeSP findReferenceLayer(KisImageSP image, const QVariant &value, Options &options)
{
    KisNodeSP node;
    if (value.userType() == QMetaType::QUuid) {
        node = KisLayerUtils::findNodeByUuid(image->root(), value.toUuid());
    } else if (value.userType() == QMetaType::QString) {
        const QString text = value.toString();
        const QUuid uuid(text);
        if (!uuid.isNull()) {
            node = KisLayerUtils::findNodeByUuid(image->root(), uuid);
        } else {
            const QList<KisNodeSP> found = KisLayerUtils::findNodesByName(image->root(), text, true, false);
            if (found.size() > 1) {
                options.fail(QString("%1 layers are called \"%2\": give the layer's unique id (Node.uniqueId()) instead").arg(found.size()).arg(text));
                return KisNodeSP();
            }
            if (!found.isEmpty()) node = found.first();
        }
    } else {
        options.fail("layer must be a layer's unique id or name");
        return KisNodeSP();
    }
    if (!node || node == image->root()) {
        options.fail("layer must name a layer of the document (its unique id, or its name when no other node has it)");
        return KisNodeSP();
    }
    if (!qobject_cast<KisLayer *>(node.data()) || qobject_cast<KisGroupLayer *>(node.data())) {
        options.fail(QString("\"%1\" is a mask or a group: the reference is a layer").arg(node->name()));
        return KisNodeSP();
    }
    return node;
}

/**
 * A snapshot of what a builder reads: the composited image, or the projection of the layer named by "layer" (the
 * layer's own pixels with its effect masks, whatever its opacity, blend mode or visibility: those are not applied).
 * Taken under a read-only barrier lock that never ends the artist's stroke; gives nothing, with a warning, when the
 * image stays busy until the call's time is up. The copy shares the image's tiles and is unaffected by what the artist
 * paints after.
 */
KisPaintDeviceSP referenceSnapshot(KisImageSP image, Options &options, const Budget &budget)
{
    KisAgentReadLock::Scoped lock(image, budget.remainingMs());
    if (!lock.locked()) {
        options.fail(QString("image busy (a stroke or an update is running); not read within %1 ms").arg(budget.limitMs()));
        return KisPaintDeviceSP();
    }
    KisPaintDeviceSP source = image->projection();
    if (options.has("layer")) {
        KisNodeSP node = findReferenceLayer(image, options.value("layer"), options);
        if (!node || !node->projection()) {
            options.fail("layer has no pixels");
            return KisPaintDeviceSP();
        }
        source = node->projection();
    }
    KisPaintDeviceSP snapshot = new KisPaintDevice(*source);
    snapshot->setDefaultBounds(source->defaultBounds());
    return snapshot;
}

KisFeatureBuilders::Refinement refinementOf(Options &options)
{
    KisFeatureBuilders::Refinement refinement;
    refinement.grow = options.integer("grow", 0, -MAX_REFINEMENT, MAX_REFINEMENT);
    refinement.stopGrowingAtDarkestPixel = options.boolean("stopGrowingAtDarkestPixel", false);
    refinement.feather = options.integer("feather", 0, 0, MAX_REFINEMENT);
    refinement.antiAlias = options.boolean("antiAlias", false);
    return refinement;
}

KisFeatureBuilders::Segmentation segmentationOf(Options &options)
{
    KisFeatureBuilders::Segmentation segmentation;
    segmentation.edgeDetection = options.boolean("edgeDetection", true);
    segmentation.edgeSize = options.number("edgeSize", 4.0, 0.5, 100.0);
    segmentation.fuzzyRadius = options.number("fuzzyRadius", 0.0, 0.0, 100.0);
    segmentation.cleanUp = options.number("cleanUp", 0.0, 0.0, 1.0);
    return segmentation;
}

/// "within": the mask a search stays inside.
KisPixelSelectionSP withinOf(KisImageSP image, Options &options, const Unwrap &unwrap)
{
    if (!options.has("within")) return KisPixelSelectionSP();
    bool ok = false;
    KisPixelSelectionSP mask = maskOf(image, options.value("within"), unwrap, &ok);
    if (!ok) options.fail("within must be a Selection or the name of a feature");
    return mask;
}

/// The mask as a new Selection the caller owns, cut to the document.
Selection *toSelection(KisImageSP image, KisPixelSelectionSP mask)
{
    KisPixelSelectionSP bounded = KisFeature::boundedMask(mask, image->bounds());
    KisSelectionSP selection = new KisSelection(KisPaintDeviceSP(bounded), KritaUtils::CopySnapshot,
                                                new KisDefaultBounds(image), KisImageResolutionProxySP());
    return new Selection(selection);
}

KisImageSP imageOf(const QPointer<KisDocument> &document)
{
    if (!document) return KisImageSP();
    return document->image();
}

const QStringList refinementKeys = {"grow", "stopGrowingAtDarkestPixel", "feather", "antiAlias"};
const QStringList segmentationKeys = {"edgeDetection", "edgeSize", "fuzzyRadius", "cleanUp"};

/// A call that ran out of its time gives nothing.
bool outOfTime(const char *call, const Budget &budget)
{
    if (!budget.expired()) return false;
    warnScript << call << "gave up: not done within" << budget.limitMs() << "ms (timeoutMs asks for up to" << MAX_TIMEOUT_MS << ")";
    return true;
}

} // namespace

Selection *Document::maskFromSelection(Selection *selection, const QVariantMap &options) const
{
    static const char *call = "Document.maskFromSelection():";
    Running running(call);
    if (!running.ok()) return nullptr;
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    Options read(call, options, QStringList({"timeoutMs"}));
    Budget budget;
    budget.setLimit(read.integer("timeoutMs", DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS));
    if (!read.ok()) return nullptr;

    if (selection) {
        KisSelectionSP source = selection->selection();
        if (!source) {
            warnScript << call << "refused: the selection is empty";
            return nullptr;
        }
        return toSelection(image, source->projection());
    }
    // The document's own selection, read when the image is idle (a selection change still queued has landed), without
    // asking the artist's stroke to end.
    KisAgentReadLock::Scoped lock(image, budget.remainingMs());
    if (!lock.locked()) {
        read.fail(QString("image busy (a stroke or an update is running); not read within %1 ms").arg(budget.limitMs()));
        return nullptr;
    }
    KisSelectionSP source = image->globalSelection();
    if (!source) {
        warnScript << call << "refused: the document has no selection";
        return nullptr;
    }
    return toSelection(image, source->projection());
}

Selection *Document::maskContiguous(const QList<QPointF> &seeds, const QVariantMap &options) const
{
    static const char *call = "Document.maskContiguous():";
    Running running(call);
    if (!running.ok()) return nullptr;
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    Options read(call, options,
                 QStringList({"threshold", "spread", "closeGap", "layer", "within", "timeoutMs"}) + refinementKeys);
    Budget budget;
    budget.setLimit(read.integer("timeoutMs", DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS));
    KisFeatureBuilders::ColorSearch search;
    search.threshold = read.integer("threshold", 8, 0, 255);    // the contiguous selection tool's defaults
    search.opacitySpread = read.integer("spread", 100, 0, 100);
    search.closeGap = read.integer("closeGap", 0, 0, 32);
    search.refinement = refinementOf(read);
    KisPixelSelectionSP within = withinOf(image, read, [](Selection *s) { return s->selection() ? s->selection()->projection() : KisPixelSelectionSP(); });
    if (seeds.isEmpty()) read.fail("give one or more seed points");
    read.cap(seeds.size(), MAX_SEEDS, "seed points");
    QVector<QPoint> points;
    if (read.ok()) {
        for (const QPointF &seed : seeds) {
            QPoint pixel;
            if (!pixelIn(seed, image->bounds(), &pixel)) {
                read.fail(QString("seed (%1, %2) is not a point inside the document").arg(seed.x()).arg(seed.y()));
                break;
            }
            points << pixel;
        }
    }
    if (!read.ok()) return nullptr;
    KisPaintDeviceSP reference = referenceSnapshot(image, read, budget);
    if (!read.ok()) return nullptr;

    KisPixelSelectionSP mask = KisFeatureBuilders::contiguous(reference, points, image->bounds(), search, within,
                                                              [&budget]() { return budget.shouldStop(); });
    if (outOfTime(call, budget)) return nullptr;
    return toSelection(image, mask);
}

Selection *Document::maskSimilarColor(const QList<QColor> &colors, const QVariantMap &options) const
{
    static const char *call = "Document.maskSimilarColor():";
    Running running(call);
    if (!running.ok()) return nullptr;
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    Options read(call, options,
                 QStringList({"threshold", "spread", "points", "layer", "within", "timeoutMs"}) + refinementKeys);
    Budget budget;
    budget.setLimit(read.integer("timeoutMs", DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS));
    KisFeatureBuilders::ColorSearch search;
    search.threshold = read.integer("threshold", 20, 0, 255);   // the similar colour selection tool's defaults
    search.opacitySpread = read.integer("spread", 100, 0, 100);
    search.refinement = refinementOf(read);
    KisPixelSelectionSP within = withinOf(image, read, [](Selection *s) { return s->selection() ? s->selection()->projection() : KisPixelSelectionSP(); });
    QVector<QPoint> samples;
    if (read.has("points")) {
        const QVariantList list = read.value("points").toList();
        if (list.isEmpty()) read.fail("points must be a list of points");
        read.cap(colors.size() + list.size(), MAX_COLORS_AND_POINTS, "colours and points");
        if (read.ok()) {
            for (const QVariant &item : list) {
                QPointF point;
                QPoint pixel;
                if (!Options::toPoint(item, &point) || !pixelIn(point, image->bounds(), &pixel)) {
                    read.fail("points must be points inside the document");
                    break;
                }
                samples << pixel;
            }
        }
    }
    read.cap(colors.size() + samples.size(), MAX_COLORS_AND_POINTS, "colours and points");
    for (const QColor &color : colors) {
        if (!color.isValid()) read.fail("every colour must be valid");
    }
    if (colors.isEmpty() && samples.isEmpty()) read.fail("give one or more colours, or points to take them from");
    if (!read.ok()) return nullptr;
    KisPaintDeviceSP reference = referenceSnapshot(image, read, budget);
    if (!read.ok()) return nullptr;

    QVector<KoColor> wanted;
    for (const QColor &color : colors) wanted << KoColor(color, reference->colorSpace());
    for (const QPoint &point : samples) wanted << reference->pixel(point);
    KisPixelSelectionSP mask = KisFeatureBuilders::similarColors(reference, wanted, image->bounds(), search, within,
                                                                 [&budget]() { return budget.shouldStop(); });
    if (outOfTime(call, budget)) return nullptr;
    return toSelection(image, mask);
}

Selection *Document::maskSnapOutline(const QList<QPointF> &points, const QVariantMap &options) const
{
    static const char *call = "Document.maskSnapOutline():";
    Running running(call);
    if (!running.ok()) return nullptr;
    KisImageSP image = imageOf(document());
    if (!image) return nullptr;
    Options read(call, options,
                 QStringList({"searchRadius", "filterRadius", "anchorRadius", "settle", "antiAlias", "layer", "timeoutMs"}) + segmentationKeys);
    Budget budget;
    budget.setLimit(read.integer("timeoutMs", DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS));
    KisFeatureBuilders::OutlineSnap snap;
    snap.searchRadius = read.integer("searchRadius", 30, 1, MAX_SEARCH_RADIUS);   // the magnetic selection tool's defaults
    snap.filterRadius = read.number("filterRadius", 3.0, 0.5, 100.0);
    snap.anchorRadius = read.integer("anchorRadius", 10, 0, MAX_ANCHOR_RADIUS);
    const int settle = read.integer("settle", 0, 0, MAX_SETTLE);
    const bool antiAlias = read.boolean("antiAlias", false);
    const KisFeatureBuilders::Segmentation segmentation = segmentationOf(read);
    if (points.size() < 3) read.fail("give three or more points");
    read.cap(points.size(), MAX_OUTLINE_POINTS, "points");
    if (read.ok()) {
        for (const QPointF &point : points) {
            // A point may lie on the far edges (x = width, y = height).
            if (!Options::isCoordinate(point) || point.x() < 0 || point.y() < 0 || point.x() > image->width() || point.y() > image->height()) {
                read.fail(QString("point (%1, %2) is not a point inside the document").arg(point.x()).arg(point.y()));
                break;
            }
        }
    }
    if (!read.ok()) return nullptr;
    KisPaintDeviceSP reference = referenceSnapshot(image, read, budget);
    if (!read.ok()) return nullptr;

    const KisFeatureBuilders::StopFn stop = [&budget]() { return budget.shouldStop(); };
    const QPolygonF outline = KisFeatureBuilders::snapOutline(reference, QVector<QPointF>(points.begin(), points.end()), image->bounds(), snap, stop);
    if (outOfTime(call, budget)) return nullptr;
    KisPixelSelectionSP mask = KisFeatureBuilders::polygonMask(outline, image->bounds(), antiAlias && !settle,
                                                               new KisDefaultBounds(image));
    if (settle > 0) {
        mask = KisFeatureBuilders::settleEdge(image, reference, mask, settle, segmentation, stop);
        if (!mask || outOfTime(call, budget)) {
            if (!budget.expired()) warnScript << call << "the lazy brush was cancelled";
            return nullptr;
        }
        if (antiAlias) {
            KisFeatureBuilders::Refinement smooth;
            smooth.antiAlias = true;
            KisFeatureBuilders::refine(mask, smooth, reference);
        }
    }
    return toSelection(image, mask);
}

QList<Selection *> Document::maskSegments(const QList<Selection *> &hints, const QVariantMap &options) const
{
    static const char *call = "Document.maskSegments():";
    QList<Selection *> result;
    Running running(call);
    if (!running.ok()) return result;
    KisImageSP image = imageOf(document());
    if (!image) return result;
    Options read(call, options, QStringList({"rect", "layer", "timeoutMs"}) + segmentationKeys);
    Budget budget;
    budget.setLimit(read.integer("timeoutMs", DEFAULT_TIMEOUT_MS, 1, MAX_TIMEOUT_MS));
    const KisFeatureBuilders::Segmentation segmentation = segmentationOf(read);
    QRect rect = image->bounds();
    if (read.has("rect")) {
        const QVariant value = read.value("rect");
        QRect given;
        if (value.userType() == QMetaType::QRect) {
            given = value.toRect();
        } else {
            const QVariantList list = value.toList();
            bool ok = list.size() == 4;
            int v[4] = {0, 0, 0, 0};
            for (int i = 0; ok && i < 4; i++) v[i] = Options::toInteger(list[i], &ok);
            if (ok) given = QRect(v[0], v[1], v[2], v[3]);
        }
        if (given.isEmpty() || !image->bounds().contains(given)) read.fail("rect must be [x, y, w, h] inside the document");
        rect = given;
    }
    if (hints.size() < 2) read.fail("give two or more hints, one per region");
    read.cap(hints.size(), MAX_HINTS, "hints");
    QVector<KisPixelSelectionSP> masks;
    if (read.ok()) {
        for (Selection *hint : hints) {
            if (!hint || !hint->selection()) {
                read.fail("every hint must be a Selection");
                break;
            }
            KisPixelSelectionSP mask = hint->selection()->projection();
            if ((mask->selectedExactRect() & rect).isEmpty()) {
                read.fail("every hint must select something inside the rect");
                break;
            }
            masks << mask;
        }
    }
    if (!read.ok()) return result;
    KisPaintDeviceSP reference = referenceSnapshot(image, read, budget);
    if (!read.ok()) return result;

    // The lazy brush runs as a stroke of its own on the snapshot, polled (never waited for through the image) and
    // cancelled when the time is up.
    const QVector<KisPixelSelectionSP> regions = KisFeatureBuilders::segment(image, reference, masks, rect, segmentation,
                                                                             [&budget]() { return budget.shouldStop(); });
    if (outOfTime(call, budget)) return result;
    if (regions.size() != masks.size()) {
        warnScript << call << "the lazy brush was cancelled";
        return result;
    }
    for (KisPixelSelectionSP region : regions) result << toSelection(image, region);
    return result;
}
