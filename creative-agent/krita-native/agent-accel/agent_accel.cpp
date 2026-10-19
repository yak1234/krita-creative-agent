/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "agent_accel.h"

#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QPointer>
#include <QRect>
#include <QTimer>

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QVector>

#include <utility>

#include <kpluginfactory.h>
#include <kundo2magicstring.h>
#include <KoCanvasResourceProvider.h>
#include <KoCanvasResourcesIds.h>
#include <KoColor.h>
#include <KisViewManager.h>
#include <kis_canvas_resource_provider.h>
#include <kis_layer_utils.h>
#include <kis_paintop_preset.h>
#include <kis_paintop_settings.h>
#include <kis_resources_snapshot.h>
#include <KisAsynchronousStrokeUpdateHelper.h>
#include <strokes/freehand_stroke.h>
#include <strokes/KisFreehandStrokeInfo.h>
#include <KisPart.h>
#include <KisDocument.h>
#include <KisMainWindow.h>
#include <KisView.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <KoColorSpace.h>
#include <KisImportExportErrorCode.h>
#include <KisImportExportUtils.h>
#include <kundo2stack.h>
#include "background_save.h"
#include "region_refresh.h"
#include "selection_builders.h"
#include "stroke_points.h"

K_PLUGIN_FACTORY_WITH_JSON(AgentAccelFactory, "kritaagentaccel.json", registerPlugin<AgentAccelPlugin>();)

AgentAccelPlugin::AgentAccelPlugin(QObject *parent, const QVariantList &)
    : KisActionPlugin(parent)
{
    AgentAccelService::ensure();
}

AgentAccelPlugin::~AgentAccelPlugin()
{
}

AgentAccelService::AgentAccelService(QObject *parent)
    : QObject(parent)
{
    setObjectName(QString::fromLatin1(OBJECT_NAME));
}

void AgentAccelService::ensure()
{
    if (!qApp->findChild<AgentAccelService *>(QString::fromLatin1(OBJECT_NAME), Qt::FindDirectChildrenOnly)) {
        new AgentAccelService(qApp);
    }
}

int AgentAccelService::version() const
{
    return 7;                                            // 2: paintStrokes; 3: selectContiguous, selectSimilar, selectionOutline;
                                                         // 4: buildSelection, buildTimings; 5: paintStrokes' points carry
                                                         // tilt, rotation, speed and time (stroke_points.h); 6:
                                                         // saveInBackground, saveStatus; 7: refreshRect grows the rect by
                                                         // the effects that spread it (region_refresh.h), refreshRegion
}

static KisDocument *documentAt(const QString &path)
{
    if (path.isEmpty()) {
        KisMainWindow *window = KisPart::instance()->currentMainwindow();
        KisView *view = window ? window->activeView() : nullptr;
        return view ? view->document() : nullptr;
    }
    Q_FOREACH (QPointer<KisDocument> document, KisPart::instance()->documents()) {
        if (document && document->localFilePath() == path) {
            return document;
        }
    }
    return nullptr;
}

static QString failure(const QString &message)
{
    return QString::fromUtf8(QJsonDocument(QJsonObject{{"error", message}}).toJson(QJsonDocument::Compact));
}

static QJsonArray rectJson(const QRect &rect)
{
    return rect.isEmpty() ? QJsonArray{0, 0, 0, 0} : QJsonArray{rect.x(), rect.y(), rect.width(), rect.height()};
}

QString AgentAccelService::refreshRegion(const QString &path, int x, int y, int w, int h)
{
    KisDocument *document = documentAt(path);
    KisImageSP image = document ? document->image().toStrongRef() : KisImageSP();
    if (!image) return failure(QStringLiteral("No such document."));
    if (w <= 0 || h <= 0) return failure(QStringLiteral("The rect is empty."));
    QElapsedTimer clock;
    clock.start();
    const QRect refreshed = AgentRegion::refresh(image, QRect(x, y, w, h));
    return QString::fromUtf8(QJsonDocument(QJsonObject{{"ms", int(clock.elapsed())}, {"rect", rectJson(refreshed)},
        {"requested", QJsonArray{x, y, w, h}}}).toJson(QJsonDocument::Compact));
}

int AgentAccelService::refreshRect(const QString &path, int x, int y, int w, int h)
{
    const QJsonObject answer = QJsonDocument::fromJson(refreshRegion(path, x, y, w, h).toUtf8()).object();
    return answer.contains(QStringLiteral("error")) ? -1 : answer.value(QStringLiteral("ms")).toInt();
}

QString AgentAccelService::paintStrokes(const QString &path, const QString &layerId, const QString &strokesJson)
{
    QElapsedTimer clock;
    clock.start();
    KisDocument *document = documentAt(path);
    KisImageSP image = document ? document->image().toStrongRef() : KisImageSP();
    if (!image) return failure(QStringLiteral("No such document."));
    KisNodeSP node = KisLayerUtils::recursiveFindNode(image->root(), [&layerId] (KisNodeSP candidate) {
        return candidate->uuid().toString() == layerId;
    });
    if (!node || !node->paintDevice()) return failure(QStringLiteral("No paint layer with that id."));
    KisMainWindow *window = KisPart::instance()->currentMainwindow();
    KisView *view = window ? window->activeView() : nullptr;
    if (!view) return failure(QStringLiteral("No active view for the brush."));
    KoCanvasResourceProvider *resources = view->viewManager()->canvasResourceProvider()->resourceManager();
    KisPaintOpPresetSP base = resources->resource(KoCanvasResource::CurrentPaintOpPreset).value<KisPaintOpPresetSP>();
    if (!base) return failure(QStringLiteral("No brush preset selected."));
    const QJsonArray strokes = QJsonDocument::fromJson(strokesJson.toUtf8()).object().value(QStringLiteral("strokes")).toArray();

    int jobs = 0;
    for (int first = 0; first < strokes.size(); ) {
        const QJsonObject lead = strokes[first].toObject();
        auto sameBrush = [&lead] (const QJsonObject &other) {
            for (const char *key : {"size", "opacity", "flow", "color"}) {
                if (other.value(QLatin1String(key)) != lead.value(QLatin1String(key))) return false;
            }
            return true;
        };
        int last = first + 1;
        while (last < strokes.size() && sameBrush(strokes[last].toObject())) last++;

        // One brush for the group: a copy of the view's preset with this size and flow, never pushed to the view.
        KisPaintOpPresetSP preset = base->clone().dynamicCast<KisPaintOpPreset>();
        if (lead.contains(QStringLiteral("size"))) preset->settings()->setPaintOpSize(lead.value(QStringLiteral("size")).toDouble());
        if (lead.contains(QStringLiteral("flow"))) preset->settings()->setPaintOpFlow(lead.value(QStringLiteral("flow")).toDouble());
        KisResourcesSnapshotSP snapshot(new KisResourcesSnapshot(image, node, resources, nullptr, KisNodeList(), preset));
        if (lead.contains(QStringLiteral("opacity"))) snapshot->setOpacity(lead.value(QStringLiteral("opacity")).toDouble());
        if (lead.contains(QStringLiteral("color"))) {
            snapshot->setFGColorOverride(KoColor(QColor(lead.value(QStringLiteral("color")).toString()), image->colorSpace()));
        }
        snapshot->setStrokeStyle(KisPainter::StrokeStyleBrush);
        snapshot->setFillStyle(KisPainter::FillStyleNone);

        QVector<KisFreehandStrokeInfo *> infos;              // one per stroke: spacing and randomness restart for each
        for (int i = first; i < last; i++) infos.append(new KisFreehandStrokeInfo());
        KisStrokeId stroke = image->startStroke(new FreehandStrokeStrategy(snapshot, infos, kundo2_noi18n("Creative Agent strokes")));
        for (int i = first; i < last; i++) {
            const QJsonObject item = strokes[i].toObject();
            KisPaintInformation previous = AgentStroke::point(item.value(QStringLiteral("start")).toArray(), 0);
            const QJsonArray segments = item.value(QStringLiteral("segments")).toArray();
            for (const QJsonValue &value : segments) {
                const QJsonArray segment = value.toArray();
                if (segment.size() < 6) continue;
                KisPaintInformation next = AgentStroke::point(segment, 4);
                image->addJob(stroke, new FreehandStrokeStrategy::Data(i - first, previous,
                    QPointF(segment[0].toDouble(), segment[1].toDouble()), QPointF(segment[2].toDouble(), segment[3].toDouble()), next));
                previous = next;
            }
        }
        image->addJob(stroke, new KisAsynchronousStrokeUpdateHelper::UpdateData(true));
        image->endStroke(stroke);
        jobs++;
        first = last;
    }
    return QString::fromUtf8(QJsonDocument(QJsonObject{{"status", "ok"}, {"strokes", strokes.size()}, {"jobs", jobs},
        {"ms", int(clock.elapsed())}}).toJson(QJsonDocument::Compact));
}

// ----- selection builders (selection_builders.cpp) ------------------------------------------------------------------

/// The document's image, settled, when its projection is 8-bit RGBA (stored B, G, R, A, as the Python path reads it).
static KisImageSP rgbaImage(const QString &path)
{
    KisDocument *document = documentAt(path);
    KisImageSP image = document ? document->image().toStrongRef() : KisImageSP();
    if (!image || image->projection()->colorSpace()->id() != QLatin1String("RGBA")) return KisImageSP();
    image->waitForDone();
    return image;
}

QByteArray AgentAccelService::selectSimilar(const QString &path, const QString &colour, int tolerance, int bx, int by, int bw, int bh)
{
    KisImageSP image = rgbaImage(path);
    const QColor wanted(colour);
    const QRect rect = image ? QRect(bx, by, bw, bh) & image->bounds() : QRect();
    if (!image || !wanted.isValid() || rect.isEmpty()) return QByteArray();
    return AgentSelection::packMask(AgentSelection::colourMask(image->projection(), rect, wanted, tolerance), rect);
}

QByteArray AgentAccelService::selectContiguous(const QString &path, int x, int y, int tolerance, int bx, int by, int bw, int bh)
{
    KisImageSP image = rgbaImage(path);
    const QRect rect = image ? QRect(bx, by, bw, bh) & image->bounds() : QRect();
    if (!image || !rect.contains(x, y)) return QByteArray();
    KisPaintDeviceSP projection = image->projection();
    quint8 seed[4];
    projection->readBytes(seed, x, y, 1, 1);
    const QByteArray matching = AgentSelection::colourMask(projection, rect, QColor(seed[2], seed[1], seed[0]), tolerance);
    return AgentSelection::joinSeed(matching, rect, QPoint(x, y));
}

QString AgentAccelService::selectionOutline(const QByteArray &headerAndMask)
{
    return AgentSelection::outlineJson(headerAndMask);
}

QByteArray AgentAccelService::buildSelection(const QString &path, const QString &stepsJson)
{
    QElapsedTimer clock, phase;
    clock.start();
    phase.start();
    m_buildTimings = failure(QStringLiteral("No such 8-bit RGBA document."));
    KisImageSP image = rgbaImage(path);                  // waits for Krita to settle
    if (!image) return QByteArray();
    const int wait = int(phase.restart());
    QString error;
    const QVector<AgentSelection::Step> steps = AgentSelection::parseSteps(stepsJson.toUtf8(), image->bounds(), &error);
    if (!error.isEmpty()) {
        m_buildTimings = failure(error);
        return QByteArray();
    }
    QJsonObject timings{{"steps", steps.size()}, {"wait", wait}, {"parse", int(phase.restart())}};
    // The picture once, for every step: the rect their bounds cover together, 8-bit B, G, R, A.
    const QRect area = AgentSelection::stepsArea(steps);
    QByteArray pixels(area.width() * area.height() * 4, '\0');
    image->projection()->readBytes(reinterpret_cast<quint8 *>(pixels.data()), area);
    timings.insert(QStringLiteral("read"), int(phase.restart()));
    const QByteArray mask = AgentSelection::buildMask(reinterpret_cast<const quint8 *>(pixels.constData()), area, steps, &timings);
    pixels.clear();
    phase.restart();
    const QByteArray answer = AgentSelection::packMask(mask, area);
    timings.insert(QStringLiteral("pack"), int(phase.elapsed()));
    timings.insert(QStringLiteral("area"), QJsonArray{area.x(), area.y(), area.width(), area.height()});
    timings.insert(QStringLiteral("total"), int(clock.elapsed()));
    m_buildTimings = QString::fromUtf8(QJsonDocument(timings).toJson(QJsonDocument::Compact));
    return answer;
}

QString AgentAccelService::buildTimings() const
{
    return m_buildTimings;
}

// ----- background save (background_save.h) -------------------------------------------------------------------------

struct AgentAccelService::SaveJob {
    AgentSave::Job job;
    QPointer<KisDocument> document;
    QString temporary;
    QElapsedTimer clock;
    bool starting = true;                                // inside exportDocument: a start that fails may end the job there
    bool touched = false;                                // the document changed after its copy was taken
    QList<QMetaObject::Connection> connections;
};

static const int KEPT_SAVE_JOBS = 64;                    // finished jobs kept for saveStatus

static bool isOpen(KisDocument *document)
{
    Q_FOREACH (QPointer<KisDocument> open, KisPart::instance()->documents()) {
        if (open == document) return true;
    }
    return false;
}

int AgentAccelService::saveInBackground(const QString &path)
{
    QElapsedTimer clock;
    clock.start();
    KisDocument *document = documentAt(path);
    if (!document) return -1;
    const int id = ++m_lastSaveJob;
    QSharedPointer<SaveJob> job(new SaveJob);
    job->clock.start();
    job->job.id = id;
    job->job.file = document->localFilePath();
    job->document = document;
    for (auto it = m_saveJobs.begin(); it != m_saveJobs.end() && m_saveJobs.size() >= KEPT_SAVE_JOBS; ) {
        // Qt 6's QHash iterator only steps forward (++it), so no `it + 1`.
        if (it.value()->job.state == AgentSave::Job::Running) ++it;
        else it = m_saveJobs.erase(it);
    }
    m_saveJobs.insert(id, job);
    auto refuse = [&] (const QString &why) {
        job->job.state = AgentSave::Job::Failed;
        job->job.error = why;
        job->job.ms = job->job.startMs = clock.elapsed();
        return id;
    };
    if (job->job.file.isEmpty()) return refuse(QStringLiteral("The document has no file yet: save it once first."));
    for (const QSharedPointer<SaveJob> &other : std::as_const(m_saveJobs)) {
        if (other != job && other->job.state == AgentSave::Job::Running && other->document == document) {
            return refuse(QStringLiteral("Save job %1 of this document is still running.").arg(other->job.id));
        }
    }
    if (document->isSaving()) return refuse(QStringLiteral("Krita is already saving this document (an autosave or the artist's save)."));
    KisImageSP image = document->image().toStrongRef();
    if (!image) return refuse(QStringLiteral("The document has no image."));
    image->waitForDone();                                // an idle image: Krita copies it without asking to wait
    AgentSave::removeStale(job->job.file);
    job->temporary = AgentSave::temporaryPath(job->job.file, id);
    QFile::remove(job->temporary);
    QByteArray mimeType = document->mimeType();
    if (mimeType.isEmpty()) mimeType = KisDocument::nativeFormatMimeType();

    // Krita ends the save on the main thread: sigCompleteBackgroundSaving reaches this first, then its own
    // slotCompleteSavingDocument, which shows a dialog for a failure or warning unless the document is in batch mode.
    const QString temporary = job->temporary;
    job->connections << connect(document, &KisDocument::sigCompleteBackgroundSaving, this,
        [this, id, temporary] (const KritaUtils::ExportFileJob &done, KisImportExportErrorCode status, const QString &errorMessage, const QString &) {
            if (done.filePath != temporary) return;     // an autosave, or another save of the document
            QSharedPointer<SaveJob> job = m_saveJobs.value(id);
            if (!job) return;
            if (job->document && !job->starting) {
                QPointer<KisDocument> document = job->document;
                const bool batch = document->fileBatchMode();
                document->setFileBatchMode(true);
                QTimer::singleShot(0, document, [document, batch] { if (document) document->setFileBatchMode(batch); });
            }
            finishSave(id, status.isOk(), status.isOk() ? QString() : (errorMessage.isEmpty() ? status.errorMessage() : errorMessage));
        });

    const bool batch = document->fileBatchMode();
    document->setFileBatchMode(true);                    // the copy inherits it: no export dialog, no error dialog
    const bool started = document->exportDocument(temporary, mimeType, false, false, KisPropertiesConfigurationSP());
    document->setFileBatchMode(batch);
    job->starting = false;
    job->job.startMs = clock.elapsed();
    if (job->job.state != AgentSave::Job::Running) return id;      // the start failed and Krita already ended it
    if (!started) {
        finishSave(id, false, document->errorMessage().isEmpty() ? QStringLiteral("Krita could not start the save.") : document->errorMessage());
        return id;
    }
    // Krita copied the image just now: a change from here on is not in this save, so the document stays modified.
    auto touch = [this, id] {
        QSharedPointer<SaveJob> job = m_saveJobs.value(id);
        if (job) job->touched = true;
    };
    job->connections << connect(image.data(), &KisImage::sigImageModified, this, touch);
    job->connections << connect(document->undoStack(), &KUndo2Stack::indexChanged, this, touch);
    job->connections << connect(document, &QObject::destroyed, this, [this, id] {
        finishSave(id, false, QStringLiteral("The document closed before its save finished."));
    });
    return id;
}

void AgentAccelService::finishSave(int id, bool exported, const QString &exportError)
{
    QSharedPointer<SaveJob> job = m_saveJobs.value(id);
    if (!job || job->job.state != AgentSave::Job::Running) return;
    for (const QMetaObject::Connection &connection : std::as_const(job->connections)) disconnect(connection);
    job->connections.clear();
    QString error;
    const bool saved = AgentSave::complete(job->temporary, job->job.file, exported, exportError, &error);
    job->job.state = saved ? AgentSave::Job::Done : AgentSave::Job::Failed;
    job->job.error = error;
    job->job.ms = job->clock.elapsed();
    KisDocument *document = job->document;
    if (saved && !job->touched && document && isOpen(document)) {
        // What Krita's own save does when nothing changed the document while it saved
        // (KisDocument::Private::updateDocumentMetadataOnSaving and slotCompleteSavingDocument).
        document->updateEditingTime(true);
        document->undoStack()->setClean();
        document->setModified(false);
        document->removeAutoSaveFiles(document->localFilePath(), document->isRecovered());
        document->setRecovered(false);
        job->job.clean = !document->isModified();
    }
}

QString AgentAccelService::saveStatus(int jobId) const
{
    QSharedPointer<SaveJob> job = m_saveJobs.value(jobId);
    if (!job) {
        AgentSave::Job unknown;
        unknown.id = jobId;
        unknown.state = AgentSave::Job::Failed;
        unknown.error = QStringLiteral("No such save job.");
        return AgentSave::statusJson(unknown);
    }
    AgentSave::Job now = job->job;
    if (now.state == AgentSave::Job::Running) now.ms = job->clock.elapsed();
    return AgentSave::statusJson(now);
}

#include "agent_accel.moc"
