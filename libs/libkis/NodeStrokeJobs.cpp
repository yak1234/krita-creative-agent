/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Node::paintStrokes(): asynchronous stroke jobs with full pen input (Krita Agent, openspec change krita-fork, task
// 2.4, capability agent-speed-api). Kept apart from Node.cpp so the upstream file carries only the declaration.

#include "Node.h"
#include "Selection.h"
#include "StrokeJob.h"
#include "StrokeJobShared.h"
#include "DocumentHistory.h"

#include <QColor>
#include <QCoreApplication>
#include <QDebug>
#include <QElapsedTimer>
#include <QHash>
#include <QPointer>
#include <QThread>
#include <QTimer>
#include <QVariantList>

#include <cmath>

#include <KisAsynchronousStrokeUpdateHelper.h>
#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisImageChangeReports.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KisView.h>
#include <KisViewManager.h>
#include <KoCanvasResourceProvider.h>
#include <KoCanvasResourcesIds.h>
#include <KoColor.h>
#include <KoColorModelStandardIds.h>
#include <KoColorSpace.h>
#include <brushengine/kis_paint_information.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>
#include <kis_canvas_resource_provider.h>
#include <kis_image.h>
#include <kis_node.h>
#include <kis_paint_device.h>
#include <kis_resources_snapshot.h>
#include <kis_selection.h>
#include <kundo2stack.h>
#include <resources/KoAbstractGradient.h>
#include <resources/KoPattern.h>

namespace {

/// The most strokes one job takes, and the most points one stroke takes: a job is refused whole above them.
const int kMaxStrokes = 10000;
const int kMaxPoints = 10000;

const char *const kPenLists[] = {"pressure", "tilt", "rotation", "speed", "time_ms"};

bool readNumbers(const QVariant &value, QVector<qreal> &out)
{
    out.clear();
    const QVariantList list = value.toList();
    for (const QVariant &item : list) {
        bool ok = false;
        const qreal number = item.toDouble(&ok);
        if (!ok || !std::isfinite(number)) return false;
        out << number;
    }
    return true;
}

/**
 * The point \p index of \p stroke: its x and y from \p inline_ (from \p at), then its pen input, from the stroke's
 * per-point lists when given (pressure, tilt [x, y], rotation, speed, time_ms), else inline after x and y (pressure,
 * xTilt, yTilt, rotation, speed, timeMs, as the native helper reads them), else a mouse's: pressure 1, the rest 0.
 * Values are brought into range as the helper does (krita-native/agent-accel/stroke_points.h). The lists' lengths
 * are checked by the caller.
 */
bool readPoint(const QVariantMap &stroke, const QVector<qreal> &inline_, int at, int index, KisPaintInformation &out,
               QString &error)
{
    if (inline_.size() < at + 2) {
        error = QStringLiteral("a point needs x and y");
        return false;
    }
    auto inlineValue = [&inline_, at] (int offset, qreal fallback) {
        return inline_.size() > at + offset ? inline_[at + offset] : fallback;
    };
    auto listValue = [&stroke, index, &error] (const char *key, int component, qreal fallback, bool &ok) {
        ok = true;
        const QVariant list = stroke.value(QLatin1String(key));
        if (!list.isValid() || list.isNull()) return fallback;
        QVariant value = list.toList().value(index);
        if (component >= 0) {
            const QVariantList pair = value.toList();
            if (pair.size() != 2) {
                ok = false;
                error = QStringLiteral("each '%1' value is a pair [x, y]").arg(QLatin1String(key));
                return fallback;
            }
            value = pair[component];
        }
        bool number = false;
        const qreal result = value.toDouble(&number);
        if (!number || !std::isfinite(result)) {
            ok = false;
            error = QStringLiteral("'%1' holds a value that is not a number").arg(QLatin1String(key));
            return fallback;
        }
        return result;
    };
    bool ok1, ok2, ok3, ok4, ok5, ok6;
    const qreal pressure = listValue("pressure", -1, inlineValue(2, 1.0), ok1);
    const qreal xTilt = listValue("tilt", 0, inlineValue(3, 0.0), ok2);
    const qreal yTilt = listValue("tilt", 1, inlineValue(4, 0.0), ok3);
    const qreal rotation = listValue("rotation", -1, inlineValue(5, 0.0), ok4);
    const qreal speed = listValue("speed", -1, inlineValue(6, 0.0), ok5);
    const qreal timeMs = listValue("time_ms", -1, inlineValue(7, 0.0), ok6);
    if (!(ok1 && ok2 && ok3 && ok4 && ok5 && ok6)) return false;

    const qreal turned = std::fmod(rotation + 180.0, 360.0);
    out = KisPaintInformation(QPointF(inline_[at], inline_[at + 1]),
                              qBound(0.0, pressure, 1.0),
                              qBound(-60.0, xTilt, 60.0),
                              qBound(-60.0, yTilt, 60.0),
                              (turned < 0 ? turned + 360.0 : turned) - 180.0,
                              0.0,                       // tangential pressure (an airbrush wheel)
                              1.0,                       // perspective: off the perspective grid
                              qMax(0.0, timeMs),
                              qBound(0.0, speed, 1.0));
    return true;
}

bool readColor(const QVariant &value, QColor &out)
{
    if (value.userType() == QMetaType::QColor) {
        out = value.value<QColor>();
    } else {
        out = QColor(value.toString());
    }
    return out.isValid();
}

/**
 * Reads \p value into \p out. Points (and control points) must lie inside \p bounds grown by one brush size (the
 * stroke's, else \p presetSize), as creative_validation allows: a stroke may run past the edge, Krita clips it.
 */
bool readStroke(const QVariant &value, const QVariantMap &defaults, const QRect &bounds, qreal presetSize,
                StrokeJobInput &out, QString &error)
{
    QVariantMap stroke = value.toMap();
    if (stroke.isEmpty()) {
        error = QStringLiteral("a stroke is a map with 'points', or 'start' and 'segments'");
        return false;
    }
    for (auto it = defaults.constBegin(); it != defaults.constEnd(); ++it) {
        if (!stroke.contains(it.key())) stroke.insert(it.key(), it.value());
    }

    struct Number { const char *key; qreal *target; qreal low; qreal high; };
    for (const Number &number : {Number{"size", &out.size, 0.01, 10000.0}, Number{"opacity", &out.opacity, 0.0, 1.0},
                                 Number{"flow", &out.flow, 0.0, 1.0}}) {
        const QVariant given = stroke.value(QLatin1String(number.key));
        if (!given.isValid() || given.isNull()) continue;
        bool ok = false;
        const qreal read = given.toDouble(&ok);
        if (!ok || !std::isfinite(read)) {
            error = QStringLiteral("'%1' is not a number").arg(QLatin1String(number.key));
            return false;
        }
        *number.target = qBound(number.low, read, number.high);
    }
    if (stroke.contains(QStringLiteral("color"))) {
        if (!readColor(stroke.value(QStringLiteral("color")), out.color)) {
            error = QStringLiteral("'color' is not a colour");
            return false;
        }
    } else {
        out.color = Qt::black;
    }

    const bool lines = stroke.contains(QStringLiteral("points"));
    if (!lines && !stroke.contains(QStringLiteral("start"))) {
        error = QStringLiteral("a stroke needs 'points', or 'start' and 'segments'");
        return false;
    }
    const QVariantList points = stroke.value(QStringLiteral("points")).toList();
    const QVariantList segments = stroke.value(QStringLiteral("segments")).toList();
    const int count = lines ? points.size() : segments.size() + 1;
    if (lines && points.isEmpty()) {
        error = QStringLiteral("'points' is empty");
        return false;
    }
    if (count > kMaxPoints) {
        error = QStringLiteral("%1 points, more than the %2 a stroke takes").arg(count).arg(kMaxPoints);
        return false;
    }
    for (const char *key : kPenLists) {
        const QVariant list = stroke.value(QLatin1String(key));
        if (list.isValid() && !list.isNull() && list.toList().size() != count) {
            error = QStringLiteral("'%1' has %2 values for %3 points (one per point: the start, then each end)")
                        .arg(QLatin1String(key)).arg(list.toList().size()).arg(count);
            return false;
        }
    }

    QVector<qreal> numbers;
    KisPaintInformation info;
    if (lines) {
        for (int i = 0; i < points.size(); i++) {
            if (!readNumbers(points[i], numbers) || !readPoint(stroke, numbers, 0, i, info, error)) {
                if (error.isEmpty()) error = QStringLiteral("a point holds a value that is not a number");
                return false;
            }
            out.points << info;
        }
    } else {
        out.cubic = true;
        if (!readNumbers(stroke.value(QStringLiteral("start")), numbers) || !readPoint(stroke, numbers, 0, 0, info, error)) {
            if (error.isEmpty()) error = QStringLiteral("'start' holds a value that is not a number");
            return false;
        }
        out.points << info;
        for (int i = 0; i < segments.size(); i++) {
            if (!readNumbers(segments[i], numbers) || numbers.size() < 6) {
                error = QStringLiteral("a segment is [c1x, c1y, c2x, c2y, x, y, pen input...]");
                return false;
            }
            if (!readPoint(stroke, numbers, 4, i + 1, info, error)) return false;
            out.controls << QPointF(numbers[0], numbers[1]) << QPointF(numbers[2], numbers[3]);
            out.points << info;
        }
    }

    const qreal margin = out.size > 0 ? out.size : presetSize;
    const QRectF allowed = QRectF(bounds).adjusted(-margin, -margin, margin, margin);
    auto inside = [&allowed] (const QPointF &point) {
        return point.x() >= allowed.left() && point.x() <= allowed.right()
            && point.y() >= allowed.top() && point.y() <= allowed.bottom();
    };
    for (const KisPaintInformation &point : out.points) {
        if (!inside(point.pos())) {
            error = QStringLiteral("point (%1, %2) is outside the image and one brush size around it")
                        .arg(point.pos().x()).arg(point.pos().y());
            return false;
        }
    }
    for (const QPointF &control : out.controls) {
        if (!inside(control)) {
            error = QStringLiteral("control point (%1, %2) is outside the image and one brush size around it")
                        .arg(control.x()).arg(control.y());
            return false;
        }
    }
    return true;
}

KisDocument *documentOf(KisImageSP image)
{
    Q_FOREACH (QPointer<KisDocument> document, KisPart::instance()->documents()) {
        if (document && document->image().data() == image.data()) return document;
    }
    return nullptr;
}

KisPaintOpPresetSP viewPreset()
{
    KisMainWindow *window = KisPart::instance()->currentMainwindow();
    KisView *view = window ? window->activeView() : nullptr;
    if (!view || !view->viewManager()) return KisPaintOpPresetSP();
    return view->viewManager()->canvasResourceProvider()->resourceManager()
        ->resource(KoCanvasResource::CurrentPaintOpPreset).value<KisPaintOpPresetSP>();
}

/// Deletes a QObject in its own thread: the last holder of a job's resources may be a worker thread.
void deleteLaterDeleter(KoCanvasResourceProvider *object)
{
    object->deleteLater();
}

bool onGuiThread()
{
    return QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread();
}

/**
 * The jobs painting on one image, and what Krita asks of them (GUI thread). The artist comes first:
 *  - the artist's undo during a job (KisImage::sigUndoDuringStrokeRequested, which Krita sends before it tries the
 *    undo and drops it on a busy image) stops every job on the image, each keeping a whole prefix, and then carries
 *    out that undo once the image is idle, unless Krita managed it at once;
 *  - a closing document (KisImage::sigAboutToBeDeleted, before Krita waits for the image's work) stops them too, so
 *    closing waits for at most the strokes painting now.
 */
class StrokeJobImageGuard : public QObject
{
public:
    static StrokeJobImageGuard *forImage(KisImageSP image)
    {
        StrokeJobImageGuard *guard = registry().value(image.data());
        if (!guard) {
            guard = new StrokeJobImageGuard(image);
            registry().insert(image.data(), guard);
        }
        return guard;
    }

    void add(StrokeJobFeeder *feeder)
    {
        m_feeders << feeder;
    }

    void feederFinished(StrokeJobFeeder *feeder)
    {
        m_feeders.removeAll(feeder);
        maybeUndo();
        maybeRetire();
    }

private:
    explicit StrokeJobImageGuard(KisImageSP image)
        : m_image(image)
        , m_key(image.data())
    {
        connect(image.data(), &KisImage::sigUndoDuringStrokeRequested, this, [this] () { undoRequested(); },
                Qt::DirectConnection);
        connect(image.data(), &KisImage::sigAboutToBeDeleted, this, [this] () { stopAll(); }, Qt::DirectConnection);
        connect(image.data(), &QObject::destroyed, this, [this] () {
            if (registry().value(m_key) == this) registry().remove(m_key);
            deleteLater();
        }, Qt::DirectConnection);
        connect(&m_idleTimer, &QTimer::timeout, this, [this] () { maybeUndo(); });
        m_idleTimer.setInterval(10);
    }

    ~StrokeJobImageGuard() override
    {
        if (registry().value(m_key) == this) registry().remove(m_key);
    }

    static QHash<KisImage *, StrokeJobImageGuard *> &registry()
    {
        static QHash<KisImage *, StrokeJobImageGuard *> guards;
        return guards;
    }

    QList<QPointer<StrokeJobFeeder>> active() const
    {
        QList<QPointer<StrokeJobFeeder>> running;
        for (const QPointer<StrokeJobFeeder> &feeder : m_feeders) {
            if (feeder && !feeder->finished()) running << feeder;
        }
        return running;
    }

    void stopAll()
    {
        for (const QPointer<StrokeJobFeeder> &feeder : active()) {
            if (!feeder) continue;
            feeder->shared()->cancelRequested = true;
            feeder->pump(); // drops what is not queued yet; may finish the feeder
        }
    }

    void undoRequested()
    {
        if (active().isEmpty() || m_undoPending) return;
        stopAll();
        KisImageSP image = m_image;
        KisDocument *document = image ? documentOf(image) : nullptr;
        if (!document) return;
        // Krita tries the undo right after this signal and drops it on a busy image; it is carried out here, after
        // the jobs have stopped, unless the history moved back at once.
        const int index = document->undoStack()->index();
        QPointer<KisDocument> target(document);
        m_undoPending = true;
        QMetaObject::invokeMethod(this, [this, target, index] () {
            if (!target || target->undoStack()->index() < index) {
                m_undoPending = false; // Krita undid at once
            } else {
                m_undoDocument = target;
                m_undoClock.start();
            }
            maybeUndo();
            maybeRetire();
        }, Qt::QueuedConnection);
    }

    void maybeUndo()
    {
        if (!m_undoPending || !m_undoDocument || !active().isEmpty()) {
            m_idleTimer.stop();
            return;
        }
        KisImageSP image = m_image;
        // The stopped jobs' steps land through queued strokes: undo once they have.
        if (image && !image->isIdle() && m_undoClock.elapsed() < 10000) {
            if (!m_idleTimer.isActive()) m_idleTimer.start();
            return;
        }
        m_idleTimer.stop();
        m_undoPending = false;
        QPointer<KisDocument> document = m_undoDocument;
        m_undoDocument.clear();
        if (document) document->undoStack()->undo();
        maybeRetire();
    }

    void maybeRetire()
    {
        if (!active().isEmpty() || m_undoPending) return;
        if (registry().value(m_key) == this) registry().remove(m_key);
        deleteLater();
    }

    KisImageWSP m_image;
    KisImage *m_key;
    QList<QPointer<StrokeJobFeeder>> m_feeders;
    bool m_undoPending = false;
    QPointer<KisDocument> m_undoDocument;
    QElapsedTimer m_undoClock;
    QTimer m_idleTimer;
};

} // namespace

// ---- StrokeJobFeeder ------------------------------------------------------------------------------------------------

StrokeJobFeeder::StrokeJobFeeder(QSharedPointer<StrokeJobShared> shared, KisImageSP image, KisNodeSP node,
                                 KisDocument *document)
    : m_shared(shared)
    , m_image(image)
    , m_node(node)
    , m_document(document)
{
    m_shared->setFeeder(this);
}

StrokeJobFeeder::~StrokeJobFeeder()
{
    m_shared->setFeeder(nullptr);
}

void StrokeJobFeeder::start()
{
    if (KisImageSP image = m_image) {
        StrokeJobImageGuard::forImage(image)->add(this);
    }
    pump();
}

void StrokeJobFeeder::pump()
{
    if (m_finished) return;
    if (!KisImageSP(m_image)) {
        m_shared->cancelRequested = true;
    }
    if (m_shared->cancelRequested && m_next < m_shared->total) {
        const int dropped = m_shared->total - m_next;
        m_next = m_shared->total;
        m_shared->dropUnqueued(dropped);
    }
    const int outstanding = m_next - m_shared->endedCount(); // queued, not ended yet
    if (m_next < m_shared->total) {
        // Topped up to kWindow once half of it has painted: the queue never runs dry between batches (so a fast
        // brush is not slowed), and an artist's stroke never waits behind more than kWindow job strokes.
        if (outstanding <= kWindow / 2) queueWindow(kWindow - outstanding);
        return;
    }
    if (outstanding > 0) return;
    finish();
}

KisResourcesSnapshotSP StrokeJobFeeder::snapshotFor(const StrokeJobInput &input)
{
    // One brush per size, flow, opacity and colour, shared by the job's strokes that use it (a snapshot costs a
    // preset copy; the strokes only read it, one at a time).
    const QString presetKey = QStringLiteral("%1/%2").arg(input.size).arg(input.flow);
    KisPaintOpPresetSP preset = m_presets.value(presetKey);
    if (!preset) {
        preset = basePreset->clone().dynamicCast<KisPaintOpPreset>();
        if (input.size > 0) preset->settings()->setPaintOpSize(input.size);
        if (input.flow >= 0) preset->settings()->setPaintOpFlow(input.flow);
        preset->settings()->setPaintOpCompositeOp(compositeOp);
        m_presets.insert(presetKey, preset);
    }
    const QString key = QStringLiteral("%1/%2/%3").arg(presetKey).arg(input.opacity).arg(input.color.rgba());
    KisResourcesSnapshotSP snapshot = m_snapshots.value(key);
    if (snapshot) return snapshot;

    KisImageSP image = m_image;
    KoCanvasResourceProvider *resources = m_shared->resources.data();
    resources->setResource(KoCanvasResource::CurrentKritaNode, QVariant::fromValue(m_node));
    resources->setResource(KoCanvasResource::CurrentPaintOpPreset, QVariant::fromValue(preset));
    resources->setResource(KoCanvasResource::ForegroundColor, QVariant::fromValue(KoColor(input.color, image->colorSpace())));
    resources->setResource(KoCanvasResource::Opacity, input.opacity >= 0 ? input.opacity : preset->settings()->paintOpOpacity());
    resources->setResource(KoCanvasResource::EraserMode, false);
    resources->setResource(KoCanvasResource::CurrentCompositeOp, compositeOp);
    snapshot = new KisResourcesSnapshot(image, m_node, resources);
    snapshot->setStrokeStyle(KisPainter::StrokeStyleBrush);
    snapshot->setFillStyle(KisPainter::FillStyleNone);
    snapshot->setSelectionOverride(clip);
    snapshot->setPostExecutionUndoAdapterOverride(hold ? hold->adapter() : nullptr);
    m_snapshots.insert(key, snapshot);
    return snapshot;
}

void StrokeJobFeeder::queueWindow(int count)
{
    KisImageSP image = m_image;
    if (!image) return;
    const int end = qMin(m_next + count, m_shared->total);
    for (int i = m_next; i < end; i++) {
        const StrokeJobInput &input = inputs[i];
        KisStrokeId id = image->startStroke(new StrokeJobStrokeStrategy(snapshotFor(input), strokeName, m_shared, i));
        if (input.points.size() == 1) {
            image->addJob(id, new FreehandStrokeStrategy::Data(0, input.points[0]));
        } else {
            for (int p = 1; p < input.points.size(); p++) {
                if (input.cubic) {
                    image->addJob(id, new FreehandStrokeStrategy::Data(0, input.points[p - 1], input.controls[2 * (p - 1)],
                                                                       input.controls[2 * (p - 1) + 1], input.points[p]));
                } else {
                    image->addJob(id, new FreehandStrokeStrategy::Data(0, input.points[p - 1], input.points[p]));
                }
            }
        }
        image->addJob(id, new KisAsynchronousStrokeUpdateHelper::UpdateData(true));
        image->endStroke(id);
    }
    m_next = end;
    if (hold) hold->touch();
    if (m_next == m_shared->total) {
        // Everything is queued: let go of what only queueing needed (the strokes keep their own snapshots).
        m_presets.clear();
        m_snapshots.clear();
        inputs.clear();
        inputs.squeeze();
        basePreset.clear();
        clip.clear();
        if (KoCanvasResourceProvider *resources = m_shared->resources.data()) {
            resources->setResource(KoCanvasResource::CurrentKritaNode, QVariant::fromValue(KisNodeSP()));
            resources->setResource(KoCanvasResource::CurrentPaintOpPreset, QVariant::fromValue(KisPaintOpPresetSP()));
        }
    }
}

void StrokeJobFeeder::finish()
{
    m_finished = true;
    if (hold) {
        hold->release(); // the job's own step lands now; a move's waits for its end
        hold.reset();
    }
    if (KisImageSP image = m_image) {
        StrokeJobImageGuard::forImage(image)->feederFinished(this);
    }
    m_shared->setFeeder(nullptr);
    deleteLater();
}

// ---- Node::paintStrokes ---------------------------------------------------------------------------------------------

StrokeJob *Node::paintStrokes(const QVariantList &strokes, const QVariantMap &options, Selection *selection)
{
    QString name = options.value(QStringLiteral("name")).toString();
    auto refuse = [&name] (const QString &error) {
        qWarning() << "Node.paintStrokes refused:" << error;
        return new StrokeJob(StrokeJobShared::failed(error, name));
    };

    if (!onGuiThread()) return refuse(QStringLiteral("paintStrokes() is for the GUI thread"));
    KisImageSP image = this->image();
    KisNodeSP target = this->node();
    if (!image || !target) return refuse(QStringLiteral("the node is not in a document"));
    KisPaintDeviceSP device = target->paintDevice();
    if (!device || target->inherits("KisShapeLayer") || target->inherits("KisCloneLayer")
        || target->inherits("KisGroupLayer")) {
        return refuse(QStringLiteral("the node has no pixels to paint (a paint layer or mask is needed)"));
    }
    if (!target->isEditable(false)) return refuse(QStringLiteral("the node is locked"));
    if (strokes.size() > kMaxStrokes) {
        return refuse(QStringLiteral("%1 strokes, more than the %2 a job takes").arg(strokes.size()).arg(kMaxStrokes));
    }

    // The brush: the preset named, else the active view's (its preset only: none of the view's other state).
    KisPaintOpPresetSP base;
    const QString presetName = options.value(QStringLiteral("preset")).toString();
    if (!presetName.isEmpty()) {
        base = KisGlobalResourcesInterface::instance()->source(ResourceType::PaintOpPresets)
                   .bestMatch(QString(), QString(), presetName).dynamicCast<KisPaintOpPreset>();
        if (!base || !base->valid()) return refuse(QStringLiteral("no brush preset is named \"%1\"").arg(presetName));
    } else {
        base = viewPreset();
        if (!base) return refuse(QStringLiteral("no preset given, and no active view to take one from"));
    }
    if (base->paintOp().id() == QLatin1String("mypaintbrush") && device->colorSpace()->colorModelId() != RGBAColorModelID) {
        return refuse(QStringLiteral("MyPaint brushes paint RGBA layers only"));
    }
    const QString compositeOp = options.contains(QStringLiteral("compositeOp"))
        ? options.value(QStringLiteral("compositeOp")).toString()
        : base->settings()->paintOpCompositeOp();
    if (!device->colorSpace()->hasCompositeOp(compositeOp)) {
        return refuse(QStringLiteral("unknown blending mode \"%1\"").arg(compositeOp));
    }

    // Every stroke is read before any is queued: a job paints all its strokes or is refused whole.
    QVariantMap defaults;
    for (const char *key : {"color", "size", "opacity", "flow"}) {
        if (options.contains(QLatin1String(key))) defaults.insert(QLatin1String(key), options.value(QLatin1String(key)));
    }
    QVector<StrokeJobInput> inputs;
    inputs.reserve(strokes.size());
    const QRect bounds = image->bounds();
    const qreal presetSize = base->settings()->paintOpSize();
    for (int i = 0; i < strokes.size(); i++) {
        StrokeJobInput input;
        QString error;
        if (!readStroke(strokes[i], defaults, bounds, presetSize, input, error)) {
            return refuse(QStringLiteral("stroke %1: %2").arg(i).arg(error));
        }
        inputs << input;
    }

    QSharedPointer<StrokeJobShared> shared(new StrokeJobShared());
    shared->total = inputs.size();
    shared->image = image;
    shared->node = target.data();

    // The job's own brush resources, never the view's: no mirror, no eraser or alpha lock from the view, the
    // selection given or none, and the preset's own blending mode unless the job names one.
    shared->resources = QSharedPointer<KoCanvasResourceProvider>(new KoCanvasResourceProvider(), deleteLaterDeleter);
    KoCanvasResourceProvider *resources = shared->resources.data();
    KisViewManager::initializeResourceManager(resources);
    resources->setResource(KoCanvasResource::BackgroundColor, QVariant::fromValue(KoColor(Qt::white, image->colorSpace())));
    if (KoPatternSP pattern = KisGlobalResourcesInterface::instance()->source<KoPattern>(ResourceType::Patterns).fallbackResource()) {
        resources->setResource(KoCanvasResource::CurrentPattern, QVariant::fromValue(pattern));
    }
    if (KoAbstractGradientSP gradient = KisGlobalResourcesInterface::instance()->source<KoAbstractGradient>(ResourceType::Gradients).fallbackResource()) {
        resources->setResource(KoCanvasResource::CurrentGradient, QVariant::fromValue(gradient));
    }
    resources->setResource(KoCanvasResource::MirrorHorizontal, false);
    resources->setResource(KoCanvasResource::MirrorVertical, false);
    resources->setResource(KoCanvasResource::GlobalAlphaLock, false);

    // Undo: the job holds the step it joins (an open agent move or macro), or a step of its own named by "name",
    // until its last stroke has ended, so strokes queued in later windows still join it.
    KisDocument *document = documentOf(image);
    if (document) DocumentHistory::of(document);
    if (name.isEmpty()) name = QStringLiteral("Scripted Brush Strokes");
    QSharedPointer<ScriptStepHold> hold = DocumentHistory::holdStep(image, name, device);
    shared->name = hold ? hold->stepName() : name;

    QWeakPointer<StrokeJobShared> weak = shared;
    shared->dirtyConnection = QObject::connect(KisImageChangeReports::instance(), &KisImageChangeReports::sigNodeDirty,
        [weak] (KisImage *dirtyImage, KisNode *dirtyNode, const QVector<QRect> &rects) {
            if (QSharedPointer<StrokeJobShared> job = weak.toStrongRef()) job->nodeDirty(dirtyImage, dirtyNode, rects);
        });

    StrokeJob *job = new StrokeJob(shared);
    StrokeJobFeeder *feeder = new StrokeJobFeeder(shared, image, target, document);
    feeder->inputs = inputs;
    feeder->basePreset = base;
    feeder->compositeOp = compositeOp;
    feeder->clip = selection && selection->selection() ? new KisSelection(*selection->selection()) : nullptr;
    feeder->hold = hold;
    feeder->strokeName = hold ? kundo2_noi18n(hold->stepName()) : kundo2_noi18n(name);
    feeder->start();
    return job;
}
