/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureImageCommand.h"

#include <QVector>

#include <atomic>

#include <kundo2magicstring.h>

#include "KisFeature.h"
#include "KisFeatureList.h"
#include "KisRunnableBasedStrokeStrategy.h"
#include "KisRunnableStrokeJobData.h"
#include "kis_image.h"
#include "kis_pixel_selection.h"
#include "kis_processing_applicator.h"
#include "kis_selection.h"
#include "kis_transform_worker.h"

namespace {

/// A feature's mask and measured properties at one moment, to put back on undo or redo.
struct FeatureState {
    KisFeatureSP feature;
    KisPixelSelectionSP mask;
    KisFeature::Properties properties;
};

std::atomic<int> s_commandsCreated {0};
std::atomic<int> s_measureStrokesStarted {0};

void apply(const QVector<FeatureState> &states)
{
    Q_FOREACH (const FeatureState &state, states) {
        KisFeatureSP feature = state.feature;
        feature->setMaskAndProperties(state.mask, state.properties);
    }
}

} // namespace

/// Shared by the command and the measuring stroke that follows it (the command may be deleted first, by the undo
/// stack's limit). Each is used in one stroke job at a time, never two at once.
struct KisFeatureImageCommand::Shared {
    KisImageWSP image;
    MaskTransform transform;
    bool done {false};
    /// Set by undo(), cleared by redo(): the measuring stroke updates the features only while the command is done
    /// (the masks alone cannot tell, since a colour-space conversion keeps them).
    bool undone {false};
    QVector<FeatureState> before;
    QVector<FeatureState> after;
};

KisFeatureImageCommand::KisFeatureImageCommand(KisImageWSP image, MaskTransform transform, KUndo2Command *parent)
    : KUndo2Command(parent)
    , m_d(new Shared)
{
    m_d->image = image;
    m_d->transform = transform;
    s_commandsCreated++;
}

KisFeatureImageCommand::~KisFeatureImageCommand()
{
}

void KisFeatureImageCommand::redo()
{
    m_d->undone = false;
    if (m_d->done) {
        apply(m_d->after);
        return;
    }
    m_d->done = true;

    KisImageSP image = m_d->image.toStrongRef();
    if (!image) return;

    // A barrier job after the operation's own: the image has its new bounds.
    const QRect bounds = image->bounds();

    Q_FOREACH (KisFeatureSP feature, image->featureList()->features()) {
        const FeatureState before {feature, feature->mask(), feature->properties()};

        KisPixelSelectionSP mask = before.mask;
        if (m_d->transform) {
            mask = new KisPixelSelection(*before.mask);
            m_d->transform(mask);
            // A feature describes the painting: nothing of it lies outside the document.
            mask->crop(bounds);
            mask->invalidateOutlineCache();
        }
        // Bounds and area now; the mean colour is measured after the stroke (measureAfterStroke()).
        KisFeature::Properties properties = KisFeature::measureMask(mask, KisPaintDeviceSP());
        properties.meanColor = before.properties.meanColor;
        properties.hasMeanColor = before.properties.hasMeanColor;

        const FeatureState after {feature, mask, properties};
        feature->setMaskAndProperties(after.mask, after.properties);
        m_d->before << before;
        m_d->after << after;
    }
}

void KisFeatureImageCommand::undo()
{
    m_d->undone = true;
    apply(m_d->before);
}

int KisFeatureImageCommand::commandsCreated()
{
    return s_commandsCreated;
}

int KisFeatureImageCommand::measureStrokesStarted()
{
    return s_measureStrokesStarted;
}

namespace {

/// The stroke that measures after an operation: not an edit, so it keeps the redo history and lets other strokes go
/// on.
class MeasureStrokeStrategy : public KisRunnableBasedStrokeStrategy
{
public:
    MeasureStrokeStrategy()
        : KisRunnableBasedStrokeStrategy(QLatin1String("KisFeatureImageMeasure"), kundo2_noi18n("Measure features"))
    {
        enableJob(JOB_DOSTROKE);
        setClearsRedoOnStart(false);
        setRequestsOtherStrokesToEnd(false);
    }
};

/// Measures the mean colours of \p shared's features on the refreshed projection, in a stroke of its own after the
/// operation's, and keeps them as the state the command's redo puts back.
void measureAfterStroke(KisImageSP image, QSharedPointer<KisFeatureImageCommand::Shared> shared)
{
    s_measureStrokesStarted++;
    const KisStrokeId id = image->startStroke(new MeasureStrokeStrategy());
    const KisImageWSP weakImage = image;
    // A barrier waits for the update jobs queued before it: the projection is refreshed when it runs.
    image->addJob(id, new KisRunnableStrokeJobData(
                          [weakImage, shared]() {
                              KisImageSP image = weakImage.toStrongRef();
                              // Nothing to measure: no features when the command ran.
                              if (!image || shared->after.isEmpty()) return;
                              KisPaintDeviceSP projection = image->projection();
                              for (FeatureState &state : shared->after) {
                                  state.properties = KisFeature::measureMask(state.mask, projection);
                                  // Undone already (the operation's stroke was cancelled): keep it for redo only.
                                  if (!shared->undone) {
                                      KisFeatureSP feature = state.feature;
                                      feature->setMaskAndProperties(state.mask, state.properties);
                                  }
                              }
                          },
                          KisStrokeJobData::BARRIER));
    image->endStroke(id);
}

} // namespace

void KisFeatureImageCommand::endApplicator(KisProcessingApplicator &applicator,
                                           KisImageSP image,
                                           MaskTransform transform)
{
    // Upstream's path only when no feature can exist when the command would run: the list has never held one and
    // no add command was made for it, so no queued stroke (an undo of "Remove Feature", a queued add) can fill it
    // before the operation runs. (The image is never idle here: the applicator has queued its own stroke.)
    if (!image || !image->featureList()->mayHaveFeatures()) {
        applicator.end();
        return;
    }
    KisFeatureImageCommand *command = new KisFeatureImageCommand(image, transform);
    QSharedPointer<Shared> shared = command->m_d;
    applicator.applyCommand(command, KisStrokeJobData::BARRIER);
    applicator.end();
    measureAfterStroke(image, shared);
}

void KisFeatureImageCommand::endMirrorApplicator(KisProcessingApplicator &applicator,
                                                 KisImageSP image,
                                                 const KisNodeList &nodes,
                                                 KisSelectionSP selection,
                                                 Qt::Orientation orientation)
{
    if (!image || selection || nodes.size() != 1 || nodes.first() != KisNodeSP(image->root())) {
        applicator.end();
        return;
    }
    // KisMirrorProcessingVisitor's axis for the image's bounds.
    const QRect bounds = image->bounds();
    const qreal axis = orientation == Qt::Horizontal ? bounds.x() + 0.5 * bounds.width()
                                                     : bounds.y() + 0.5 * bounds.height();
    endApplicator(applicator, image, mirrorTransform(axis, orientation));
}

KisFeatureImageCommand::MaskTransform KisFeatureImageCommand::cropTransform(const QRect &newRect)
{
    return [newRect](KisPixelSelectionSP mask) {
        mask->crop(newRect);
        mask->moveTo(mask->x() - newRect.x(), mask->y() - newRect.y());
    };
}

KisFeatureImageCommand::MaskTransform KisFeatureImageCommand::workerTransform(qreal scaleX, qreal scaleY,
                                                                              qreal shearX, qreal shearY,
                                                                              qreal rotation,
                                                                              qreal translateX, qreal translateY,
                                                                              KisFilterStrategy *filter)
{
    return [=](KisPixelSelectionSP mask) {
        KisTransformWorker worker(mask, scaleX, scaleY, shearX, shearY, rotation, translateX, translateY, nullptr,
                                  filter);
        worker.run();
    };
}

KisFeatureImageCommand::MaskTransform KisFeatureImageCommand::mirrorTransform(qreal axis, Qt::Orientation orientation)
{
    return [axis, orientation](KisPixelSelectionSP mask) {
        KisTransformWorker::mirror(mask, axis, orientation);
    };
}
