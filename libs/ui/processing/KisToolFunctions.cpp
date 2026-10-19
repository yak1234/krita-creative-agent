/*
 *  SPDX-FileCopyrightText: 2000 John Califf <jcaliff@compuzone.net>
 *  SPDX-FileCopyrightText: 2004 Boudewijn Rempt <boud@valdyas.org>
 *  SPDX-FileCopyrightText: 2004 Bart Coppens <kde@bartcoppens.be>
 *  SPDX-FileCopyrightText: 2002 Patrick Julien <freak@codepimps.org>
 *  SPDX-FileCopyrightText: 2004-2007 Adrian Page <adrian@pagenet.plus.com>
 *  SPDX-FileCopyrightText: 2021 L. E. Segovia <amy@amyspark.me>
 *  SPDX-FileCopyrightText: 2017 Eugene Ingerman
 *  SPDX-FileCopyrightText: 2022 Deif Lou <ginoba@gmail.com>
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
// Krita Agent: Krita's painting tools as functions (krita-fork 5.3).
//
// Each function builds the stroke its tool builds on a click or a drag (KisToolFill::beginFilling and
// addFillingOperation, KisToolEncloseAndFill::slot_delegateTool_enclosingMaskProduced, KisToolGradient::
// endPrimaryAction, KisToolSmartPatch::inpaintImage), from arguments instead of the tool's options and the canvas's
// resources, and sends its undo step to a given facade, so a script's open agent move can collect it. Unlike a tool's
// stroke, it never asks the artist's open strokes to end, and it reads the selection when it runs, after the work
// queued before it.
#include "KisToolFunctions.h"

#include <QDeadlineTimer>
#include <QMutex>
#include <QMutexLocker>
#include <QSharedPointer>
#include <QWaitCondition>

#include <functional>

#include <klocalizedstring.h>

#include <KoAbstractGradient.h>
#include <kis_command_utils.h>
#include <kis_default_bounds.h>
#include <kis_fill_painter.h>
#include <kis_image.h>
#include <kis_inpaint.h>
#include <kis_node.h>
#include <kis_paint_device.h>
#include <kis_pixel_selection.h>
#include <kis_pointer_utils.h>
#include <kis_processing_visitor.h>
#include <kis_selection.h>
#include <kis_stroke_strategy_undo_command_based.h>
#include <kis_transaction.h>
#include <KisImageResolutionProxy.h>
#include <commands_new/KisMergeLabeledLayersCommand.h>
#include <commands_new/kis_node_move_command2.h>
#include <commands_new/kis_processing_command.h>
#include <commands_new/kis_update_command.h>

#include "kis_resources_snapshot.h"
#include "processing/KisEncloseAndFillProcessingVisitor.h"
#include "processing/fill_processing_visitor.h"

namespace KisToolFunctions
{

struct Completion::Private {
    mutable QMutex mutex;
    QWaitCondition ended;
    bool hasEnded = false;
    bool finished = false;
    KisImageWSP image;
    KisStrokeId id;
};

Completion::Completion()
    : d(new Private)
{
}

Completion::~Completion()
{
}

bool Completion::wait(int milliseconds)
{
    QMutexLocker locker(&d->mutex);
    if (!d->hasEnded) {
        d->ended.wait(&d->mutex, QDeadlineTimer(qMax(0, milliseconds)));
    }
    return d->hasEnded && d->finished;
}

void Completion::cancel()
{
    KisImageSP image;
    KisStrokeId id;
    {
        QMutexLocker locker(&d->mutex);
        if (d->hasEnded) return;
        image = d->image;
        id = d->id;
    }
    if (image && id) {
        image->cancelStroke(id);
    }
}

bool Completion::finished() const
{
    QMutexLocker locker(&d->mutex);
    return d->hasEnded && d->finished;
}

void Completion::end(bool finished)
{
    QMutexLocker locker(&d->mutex);
    d->hasEnded = true;
    d->finished = finished;
    d->ended.wakeAll();
}

void Completion::setStroke(KisImageSP image, KisStrokeId id)
{
    QMutexLocker locker(&d->mutex);
    d->image = image;
    d->id = id;
}

namespace
{
int s_waitLimit = 60000;
}

void setWaitLimit(int milliseconds)
{
    s_waitLimit = qMax(1, milliseconds);
}

int waitLimit()
{
    return s_waitLimit;
}

int smartPatchAreaLimit()
{
    // 512 x 512 pixels of the area's bounding rectangle. PatchMatch's time grows with the area (and with accuracy,
    // which widens the region searched around it): measured on an Apple M-series Mac at accuracy 50, a 100 px square
    // took 0.2 s, 200 px 1.3 s, 400 px 4.3 s and 500 px 4.9 s, while a 1 megapixel area took more than 13 s. A seam
    // is a thin strip, well inside the limit; a larger area is patched in pieces.
    return 512 * 512;
}

namespace
{

bool refuse(QString *reason, const QString &why)
{
    if (reason) *reason = why;
    return false;
}

bool isInImage(KisImageSP image, KisNodeSP node)
{
    for (KisNodeSP parent = node->parent(); parent; parent = parent->parent()) {
        if (parent == image->root()) return true;
    }
    return false;
}

/// The tool's stroke strategy, which tells a Completion when it ends.
class CompletingStrategy : public KisStrokeStrategyUndoCommandBased
{
public:
    CompletingStrategy(const KUndo2MagicString &name, KisStrokeUndoFacade *facade, CompletionSP completion)
        : KisStrokeStrategyUndoCommandBased(name, false, facade)
        , m_completion(completion)
    {
        // A script's call never ends the artist's open strokes (a tool's stroke asks them to).
        setRequestsOtherStrokesToEnd(false);
    }

    void finishStrokeCallback() override
    {
        KisStrokeStrategyUndoCommandBased::finishStrokeCallback();
        if (m_completion) m_completion->end(true);
    }

    void cancelStrokeCallback() override
    {
        KisStrokeStrategyUndoCommandBased::cancelStrokeCallback();
        if (m_completion) m_completion->end(false);
    }

private:
    CompletionSP m_completion;
};

/// One stroke whose commands become one undo step called \p name in \p target's facade (or the image's history).
class Stroke
{
public:
    Stroke(const Target &target, const KUndo2MagicString &toolName)
        : m_image(target.image)
    {
        KisStrokeUndoFacade *facade = target.undoFacade ? target.undoFacade : m_image.data();
        CompletingStrategy *strategy =
            new CompletingStrategy(target.name.isEmpty() ? toolName : target.name, facade, target.completion);
        strategy->setSupportsWrapAroundMode(true);
        m_id = m_image->startStroke(strategy);
        if (target.completion) target.completion->setStroke(m_image, m_id);
    }

    void add(KUndo2Command *command,
             KisStrokeJobData::Sequentiality sequentiality = KisStrokeJobData::SEQUENTIAL)
    {
        m_image->addJob(m_id, new KisStrokeStrategyUndoCommandBased::Data(KUndo2CommandSP(command), false,
                                                                          sequentiality, KisStrokeJobData::EXCLUSIVE));
    }

    void end()
    {
        m_image->endStroke(m_id);
    }

private:
    KisImageSP m_image;
    KisStrokeId m_id;
};

/// A command that builds its work when the stroke runs it: \p make returns a command not yet run, which
/// LambdaCommand's store runs then (its push redoes it) and keeps for undo and redo.
KUndo2Command *atRunTime(std::function<KUndo2Command *()> make)
{
    return new KisCommandUtils::LambdaCommand(make);
}

/// The device regions are found on, for \p options' reference. A merge of colour-labelled layers is made by a job
/// added to \p stroke, as the tool does, so it sees every earlier stroke's work.
KisPaintDeviceSP referenceDevice(const Target &target, const FillOptions &options, Stroke &stroke)
{
    switch (options.reference) {
    case FillOptions::AllLayers:
        return target.image->projection();
    case FillOptions::ColorLabeledLayers: {
        KisPaintDeviceSP device =
            KisMergeLabeledLayersCommand::createRefPaintDevice(target.image, "Agent Fill Reference Result Paint Device");
        stroke.add(new KisMergeLabeledLayersCommand(target.image, device, options.referenceLabels,
                                                    KisMergeLabeledLayersCommand::GroupSelectionPolicy_SelectIfColorLabeled));
        return device;
    }
    case FillOptions::CurrentLayer:
    default:
        return target.node->paintDevice();
    }
}

/// A selection with \p mask's pixels and \p image's bounds (a script's selection may have been made without them).
KisSelectionSP selectionOn(KisImageSP image, KisPixelSelectionSP mask)
{
    KisSelectionSP selection = new KisSelection(new KisDefaultBounds(image),
                                                toQShared(new KisImageResolutionProxy(image)));
    selection->pixelSelection()->applySelection(mask, SELECTION_REPLACE);
    return selection;
}

KisResourcesSnapshotSP resourcesFor(const Target &target, const KoColor &color)
{
    KisResourcesSnapshotSP resources = new KisResourcesSnapshot(target.image, target.node);
    resources->setFGColorOverride(color);
    resources->setBGColorOverride(color);
    if (target.overrideSelection) {
        resources->setSelectionOverride(target.selection);
    }
    return resources;
}

/// Changes the node's offset and redraws where it was and where it is.
class MoveNodeCommand : public KUndo2Command
{
public:
    MoveNodeCommand(KisNodeSP node, const QPoint &from, const QPoint &to)
        : KUndo2Command(kundo2_i18n("Move"))
        , m_node(node)
        , m_move(node, from, to)
    {
    }

    void redo() override
    {
        const QRect before = m_node->extent();
        m_move.redo();
        m_node->setDirty(before | m_node->extent());
    }

    void undo() override
    {
        const QRect before = m_node->extent();
        m_move.undo();
        m_node->setDirty(before | m_node->extent());
    }

private:
    KisNodeSP m_node;
    KisNodeMoveCommand2 m_move;
};

} // namespace

bool canPaint(const Target &target, QString *reason)
{
    if (!target.image) return refuse(reason, "there is no image");
    if (!target.node) return refuse(reason, "there is no node");
    if (!isInImage(target.image, target.node)) return refuse(reason, "the node is not in the document");
    if (!target.node->isEditable(false)) {
        return refuse(reason, QString("%1 is locked, or inside a locked group").arg(target.node->name()));
    }
    if (!target.node->paintDevice()) {
        return refuse(reason, QString("%1 has no pixels of its own to paint").arg(target.node->name()));
    }
    return true;
}

bool fill(const Target &target, const QPoint &seed, const KoColor &color, const FillOptions &options, QString *reason)
{
    if (!canPaint(target, reason)) return false;
    const bool wrapAround = target.node->paintDevice()->defaultBounds()->wrapAroundMode();
    if (!wrapAround && !target.image->bounds().contains(seed)) {
        return refuse(reason, "the point is outside the image");
    }

    KisResourcesSnapshotSP resources = resourcesFor(target, color);
    KisNodeSP node = target.node;
    KisImageSP image = target.image;
    QSharedPointer<QRect> dirtyRect(new QRect);
    Stroke stroke(target, kundo2_i18n("Flood Fill"));

    if (options.area == FillOptions::WholeSelection) {
        stroke.add(atRunTime([=]() -> KUndo2Command * {
            FillProcessingVisitor *visitor = new FillProcessingVisitor(nullptr, resources->activeSelection(), resources);
            visitor->setSeedPoint(seed);
            visitor->setSelectionOnly(true);
            visitor->setUseCustomBlendingOptions(true);
            visitor->setCustomOpacity(options.opacity);
            visitor->setCustomCompositeOp(options.compositeOp);
            visitor->setOutDirtyRect(dirtyRect);
            return new KisProcessingCommand(visitor, node);
        }));
    } else if (options.area == FillOptions::Contiguous) {
        KisPaintDeviceSP reference = referenceDevice(target, options, stroke);
        stroke.add(atRunTime([=]() -> KUndo2Command * {
            // The selection as it is when the stroke runs, after the work queued before it.
            KisSelectionSP selection = resources->activeSelection();
            const bool blendingIsNoOp =
                qFuzzyCompare(options.opacity, OPACITY_OPAQUE_F) && options.compositeOp == COMPOSITE_OVER;
            const bool useFastMode = !selection && blendingIsNoOp && options.opacitySpread == 100
                && !options.useSelectionAsBoundary && !options.antiAlias && options.grow == 0 && options.feather == 0
                && options.closeGap == 0 && options.reference == FillOptions::CurrentLayer;

            FillProcessingVisitor *visitor = new FillProcessingVisitor(reference, selection, resources);
            visitor->setSeedPoint(seed);
            visitor->setUseFastMode(useFastMode);
            visitor->setUseCustomBlendingOptions(true);
            visitor->setCustomOpacity(options.opacity);
            visitor->setCustomCompositeOp(options.compositeOp);
            visitor->setRegionFillingMode(options.useBoundaryColor ? KisFillPainter::RegionFillingMode_BoundaryFill
                                                                   : KisFillPainter::RegionFillingMode_FloodFill);
            if (options.useBoundaryColor) {
                visitor->setRegionFillingBoundaryColor(options.boundaryColor);
            }
            visitor->setFillThreshold(options.threshold);
            visitor->setOpacitySpread(options.opacitySpread);
            visitor->setCloseGap(options.closeGap);
            visitor->setUseSelectionAsBoundary(options.useSelectionAsBoundary);
            visitor->setAntiAlias(options.antiAlias);
            visitor->setSizeMod(options.grow);
            visitor->setStopGrowingAtDarkestPixel(options.stopGrowingAtDarkestPixel);
            visitor->setFeather(options.feather);
            visitor->setOutDirtyRect(dirtyRect);
            return new KisProcessingCommand(visitor, node);
        }));
    } else {
        // Similar colours: a mask of every pixel like the one at the point, then a fill of that mask, both made when
        // the stroke runs.
        KisPaintDeviceSP reference = referenceDevice(target, options, stroke);
        stroke.add(atRunTime([=]() -> KUndo2Command * {
            KisSelectionSP selection = resources->activeSelection();
            const KoColor referenceColor = reference->pixel(seed);
            QRect bounds = image->bounds();
            if (selection) {
                bounds = bounds.intersected(selection->projection()->selectedRect());
            }
            KisSelectionSP fillMask = new KisSelection;
            KisFillPainter painter;
            painter.setFillThreshold(options.threshold);
            painter.setOpacitySpread(options.opacitySpread);
            painter.setAntiAlias(options.antiAlias);
            painter.setSizemod(options.grow);
            painter.setStopGrowingAtDarkestPixel(options.stopGrowingAtDarkestPixel);
            painter.setFeather(options.feather);
            painter.createSimilarColorsSelection(fillMask->pixelSelection(), referenceColor, reference, bounds,
                                                 selection ? selection->projection() : nullptr);

            FillProcessingVisitor *visitor = new FillProcessingVisitor(nullptr, fillMask, resources);
            visitor->setSeedPoint(seed);
            visitor->setSelectionOnly(true);
            visitor->setUseCustomBlendingOptions(true);
            visitor->setCustomOpacity(options.opacity);
            visitor->setCustomCompositeOp(options.compositeOp);
            visitor->setOutDirtyRect(dirtyRect);
            return new KisProcessingCommand(visitor, node);
        }));
    }

    stroke.add(new KisUpdateCommand(target.node, dirtyRect, KisImageSP(target.image).data()));
    stroke.end();
    return true;
}

bool encloseAndFill(const Target &target, KisPixelSelectionSP enclosingMask, const KoColor &color,
                    const EncloseAndFillOptions &options, QString *reason)
{
    if (!canPaint(target, reason)) return false;
    if (!enclosingMask || enclosingMask->selectedExactRect().isEmpty()) {
        return refuse(reason, "the enclosing area is empty");
    }

    KisResourcesSnapshotSP resources = resourcesFor(target, color);
    KisNodeSP node = target.node;
    QSharedPointer<QRect> dirtyRect(new QRect);
    Stroke stroke(target, kundo2_i18n("Enclose and Fill"));
    KisPaintDeviceSP reference = referenceDevice(target, options.fill, stroke);
    KisPixelSelectionSP mask = selectionOn(target.image, enclosingMask)->pixelSelection();

    stroke.add(atRunTime([=]() -> KUndo2Command * {
        const FillOptions &fill = options.fill;
        KisProcessingVisitorSP visitor = new KisEncloseAndFillProcessingVisitor(
            reference, mask, resources->activeSelection(), resources, options.regions, options.regionColor,
            options.invertRegions, options.includeContourRegions, options.includeSurroundingRegions, fill.threshold,
            fill.opacitySpread, fill.closeGap, fill.antiAlias, fill.grow, fill.stopGrowingAtDarkestPixel, fill.feather,
            fill.useSelectionAsBoundary, false, false, false, true, fill.opacity, fill.compositeOp, dirtyRect);
        return new KisProcessingCommand(visitor, node);
    }));
    stroke.add(new KisUpdateCommand(target.node, dirtyRect, KisImageSP(target.image).data()));
    stroke.end();
    return true;
}

bool gradient(const Target &target, const QPointF &start, const QPointF &end, KoAbstractGradientSP gradient,
              const GradientOptions &options, QString *reason)
{
    if (!canPaint(target, reason)) return false;
    if (!gradient) return refuse(reason, "there is no gradient");
    if (!qIsFinite(start.x()) || !qIsFinite(start.y()) || !qIsFinite(end.x()) || !qIsFinite(end.y())) {
        return refuse(reason, "the gradient's ends must be finite");
    }
    const qreal far = coordinateLimit();
    if (qAbs(start.x()) > far || qAbs(start.y()) > far || qAbs(end.x()) > far || qAbs(end.y()) > far) {
        return refuse(reason, QString("the gradient's ends must be within %1 pixels of the origin").arg(far));
    }
    if (start == end) return refuse(reason, "the gradient's start and end are the same point");

    KisResourcesSnapshotSP resources = resourcesFor(target, KoColor());
    KisNodeSP node = target.node;
    KisImageSP image = target.image;
    QSharedPointer<QRect> dirtyRect(new QRect);

    Stroke stroke(target, kundo2_i18n("Gradient"));
    stroke.add(new KisCommandUtils::LambdaCommand(
                   [node, image, resources, gradient, start, end, options, dirtyRect]() -> KUndo2Command * {
                       // The selection as it is when the stroke runs, after the work queued before it.
                       KisSelectionSP selection = resources->activeSelection();
                       *dirtyRect = image->bounds();
                       if (selection) *dirtyRect &= selection->selectedExactRect();

                       KisPaintDeviceSP device = node->paintDevice();
                       KisProcessingVisitor::ProgressHelper helper(node);
                       const QRect bounds = device->defaultBounds()->bounds();

                       KisGradientPainter painter(device, selection);
                       painter.setGradient(gradient);
                       painter.setOpacityF(options.opacity);
                       painter.setCompositeOpId(options.compositeOp);
                       const QBitArray lockFlags = resources->channelLockFlags();
                       if (lockFlags.size() > 0) {
                           painter.setChannelFlags(lockFlags);
                       }
                       painter.setProgress(helper.updater());
                       painter.beginTransaction();
                       painter.setGradientShape(options.shape);
                       painter.paintGradient(start, end, options.repeat, options.antiAliasThreshold, options.reverse,
                                             0, 0, bounds.width(), bounds.height(), options.dither,
                                             options.ditherSteps);
                       return painter.endAndTakeTransaction();
                   }),
               KisStrokeJobData::BARRIER);
    stroke.add(new KisUpdateCommand(target.node, dirtyRect, KisImageSP(target.image).data()));
    stroke.end();
    return true;
}

qreal coordinateLimit()
{
    return 1e6;
}

bool smartPatch(const Target &target, KisPixelSelectionSP area, int accuracy, int patchRadius, QString *reason)
{
    if (!canPaint(target, reason)) return false;
    if (!area || area->selectedExactRect().isEmpty()) return refuse(reason, "the area to patch is empty");
    const QRect areaRect = area->selectedExactRect();
    if (qint64(areaRect.width()) * areaRect.height() > smartPatchAreaLimit()) {
        return refuse(reason, QString("the area to patch (%1 x %2 pixels) is larger than %3 pixels; patch it in pieces")
                                  .arg(areaRect.width())
                                  .arg(areaRect.height())
                                  .arg(smartPatchAreaLimit()));
    }

    // The area is both what is patched and all that may change: the patched image is written through it, so its
    // soft edges blend the patch with the paint that was there.
    KisSelectionSP limit = selectionOn(target.image, area);
    KisPaintDeviceSP mask = limit->pixelSelection();
    KisNodeSP node = target.node;
    QSharedPointer<QRect> dirtyRect(new QRect(limit->selectedExactRect()));
    accuracy = qBound(0, accuracy, 99);
    patchRadius = qBound(2, patchRadius, 8);

    Stroke stroke(target, kundo2_i18n("Smart Patch"));
    stroke.add(new KisCommandUtils::LambdaCommand([node, mask, limit, accuracy, patchRadius]() -> KUndo2Command * {
                   KisPaintDeviceSP device = node->paintDevice();
                   KisTransaction transaction(device);
                   patchImage(device, mask, patchRadius, accuracy, limit);
                   return transaction.endAndTake();
               }),
               KisStrokeJobData::BARRIER);
    stroke.add(new KisUpdateCommand(target.node, dirtyRect, KisImageSP(target.image).data()));
    stroke.end();
    return true;
}

bool moveNode(const Target &target, const QPoint &position, QString *reason)
{
    if (!target.image) return refuse(reason, "there is no image");
    if (!target.node) return refuse(reason, "there is no node");
    // The root has no parent, so this refuses it too.
    if (!isInImage(target.image, target.node)) return refuse(reason, "the node is not a layer or mask in the document");
    if (!target.node->isEditable(false)) {
        return refuse(reason, QString("%1 is locked, or inside a locked group").arg(target.node->name()));
    }
    const QPoint current(target.node->x(), target.node->y());
    if (current == position) {
        if (target.completion) target.completion->end(true);
        return true;
    }

    Stroke stroke(target, kundo2_i18n("Move"));
    stroke.add(new MoveNodeCommand(target.node, current, position));
    stroke.end();
    return true;
}

} // namespace KisToolFunctions
