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
#ifndef KIS_TOOL_FUNCTIONS_H
#define KIS_TOOL_FUNCTIONS_H

#include <QList>
#include <QPoint>
#include <QPointF>
#include <QScopedPointer>
#include <QSharedPointer>
#include <QString>
#include <QStringList>

#include <KoColor.h>
#include <KoCompositeOpRegistry.h>
#include <KisEncloseAndFillPainter.h>
#include <kis_gradient_painter.h>
#include <kis_types.h>
#include <kis_stroke_job_strategy.h>
#include <kundo2magicstring.h>

#include "kritaui_export.h"

class KisStrokeUndoFacade;
class KUndo2Command;

/**
 * Krita's painting tools as functions (Krita Agent, krita-fork 5.3): bucket fill, enclose-and-fill, gradient, smart
 * patch and a node move, on a node, with no tool, view or pointer events.
 *
 * Each function runs the same core code as its tool (FillProcessingVisitor, KisFillPainter,
 * KisEncloseAndFillProcessingVisitor, KisGradientPainter, patchImage(), KisNodeMoveCommand2) in one stroke of its own,
 * which becomes one undo step in \p Target::undoFacade (the image's history when null), named as the tool names it
 * unless \p Target::name is given. The functions queue the stroke and return; a caller that needs the pixels waits
 * on \p Target::completion, which waits for this stroke alone. The stroke never asks the artist's open strokes to
 * end, and reads the selection when it runs. A false return queued nothing, and \p reason, when given, says why.
 *
 * The tool's state that is not the operation's own (the canvas resources, the view's selection, mirror or eraser
 * mode) is never read: colours, options and the selection are arguments.
 */
namespace KisToolFunctions
{

/**
 * The end of one function's stroke, for a caller that waits for it. The stroke reports itself finished when its last
 * job has run and its undo step has been handed on, or cancelled; nothing else in the image is waited for.
 */
class KRITAUI_EXPORT Completion
{
public:
    Completion();
    ~Completion();

    /**
     * Blocks the calling thread (without running its event loop) until the stroke has finished or been cancelled,
     * or \p milliseconds have passed. @return true when it finished; false when it was cancelled or is still queued
     * or running (as when it waits behind a stroke the artist is still drawing).
     */
    bool wait(int milliseconds);

    /// Cancels the stroke if it has not finished: its work so far is undone and nothing joins the history.
    void cancel();

    /// The protected features the stroke kept its writes out of (Target::enforceProtection), set while it ran: valid
    /// once the stroke has finished. Empty when nothing was kept out.
    QStringList keptOut() const;
    /// For the stroke.
    void setKeptOut(const QStringList &names);

    bool finished() const;

    /// For the stroke: it ran (\p finished true) or was cancelled.
    void end(bool finished);

    /// For the function: the stroke being waited for.
    void setStroke(KisImageSP image, KisStrokeId id);

private:
    struct Private;
    const QScopedPointer<Private> d;
    Q_DISABLE_COPY(Completion)
};
using CompletionSP = QSharedPointer<Completion>;

/// How long a script waits for one function's stroke before giving up on it (and cancelling it): 60 s unless set.
KRITAUI_EXPORT void setWaitLimit(int milliseconds);
KRITAUI_EXPORT int waitLimit();

/// Where a function paints, and where its undo step goes.
struct KRITAUI_EXPORT Target {
    KisImageSP image;
    KisNodeSP node;
    /// With overrideSelection, the area the operation is limited to (null: none, the whole layer); without, the
    /// node's image's active selection, as for the tool.
    KisSelectionSP selection;
    bool overrideSelection = false;
    /// The undo facade the step goes to; null for the image's own history.
    KisStrokeUndoFacade *undoFacade = nullptr;
    /// The undo step's name; empty for the tool's.
    KUndo2MagicString name;
    /// When set, told when the stroke ends.
    CompletionSP completion;
    /**
     * Keep the call's writes out of the image's protected features (krita-fork 6.5, KisFeatureProtection): the
     * selection the stroke uses when it runs is the limiting one (or the whole layer) minus the protected features,
     * and a move that would shift pixels under one is refused. The names of the features kept out are told to
     * \p completion (Completion::keptOut()). A call that is a deliberate edit of a protected feature leaves it false.
     */
    bool enforceProtection = false;
};

/**
 * @return true when \p target's node is a layer or mask of its image whose pixels can be changed: it has a paint
 * device the tools paint on, and neither it nor any group above it is locked. Hidden layers can be painted (a script
 * may prepare a layer before showing it). Otherwise false, with the reason in \p reason.
 */
KRITAUI_EXPORT bool canPaint(const Target &target, QString *reason = nullptr);

/// The bucket fill tool's options, with the tool's defaults.
struct KRITAUI_EXPORT FillOptions {
    enum Area {
        Contiguous,    ///< the region around the point (flood fill, or up to boundaryColor)
        SimilarColors, ///< every pixel of a colour similar to the one at the point, within the selection
        WholeSelection ///< all of the selection (or of the layer, with no selection)
    };
    enum Reference {
        CurrentLayer,      ///< regions are found on the layer filled
        AllLayers,         ///< ... on the image's projection
        ColorLabeledLayers ///< ... on the layers with one of referenceLabels as their colour label
    };
    Area area = Contiguous;
    Reference reference = CurrentLayer;
    QList<int> referenceLabels;
    int threshold = 8;      ///< 1 to 100: how different a colour may be and still be filled
    int opacitySpread = 100; ///< 0 to 100: how far the fill's opacity spreads towards the threshold
    int closeGap = 0;       ///< 0 to 32: gaps in a contour up to this size are treated as closed
    bool antiAlias = false;
    int grow = 0;           ///< -400 to 400 pixels: grows (or shrinks) the filled area
    bool stopGrowingAtDarkestPixel = false;
    int feather = 0;        ///< 0 to 400 pixels
    bool useSelectionAsBoundary = true; ///< regions end at the selection's edge, as the tools' default
    bool useBoundaryColor = false; ///< fill up to boundaryColor instead of up to a different colour
    KoColor boundaryColor;
    qreal opacity = 1.0;
    QString compositeOp = COMPOSITE_OVER;
};

/// Fills from \p seed with \p color, as the Fill tool does with a click.
KRITAUI_EXPORT bool fill(const Target &target, const QPoint &seed, const KoColor &color, const FillOptions &options,
                         QString *reason = nullptr);

/// The enclose-and-fill tool's options, with the tool's defaults.
struct KRITAUI_EXPORT EncloseAndFillOptions {
    KisEncloseAndFillPainter::RegionSelectionMethod regions = KisEncloseAndFillPainter::SelectAllRegions;
    KoColor regionColor;
    bool invertRegions = false;
    bool includeContourRegions = false; ///< as the tool's default: regions touching the enclosing contour are left
    bool includeSurroundingRegions = false;
    /// threshold, opacitySpread, closeGap, antiAlias, grow (the tool's "expand"), stopGrowingAtDarkestPixel, feather,
    /// useSelectionAsBoundary, reference, referenceLabels, opacity and compositeOp apply; area and boundary do not.
    FillOptions fill;
};

/// Fills the regions of \p enclosingMask chosen by \p options with \p color, as the Enclose and Fill tool does with
/// a drawn enclosing shape.
KRITAUI_EXPORT bool encloseAndFill(const Target &target, KisPixelSelectionSP enclosingMask, const KoColor &color,
                                   const EncloseAndFillOptions &options, QString *reason = nullptr);

/// The gradient tool's options, with the tool's defaults.
struct KRITAUI_EXPORT GradientOptions {
    KisGradientPainter::enumGradientShape shape = KisGradientPainter::GradientShapeLinear;
    KisGradientPainter::enumGradientRepeat repeat = KisGradientPainter::GradientRepeatNone;
    bool reverse = false;
    double antiAliasThreshold = 0.2;
    KisGradientPainter::enumDither dither = KisGradientPainter::DitherNone;
    int ditherSteps = KisGradientPainter::defaultDitherSteps;
    qreal opacity = 1.0;
    QString compositeOp = COMPOSITE_OVER;
};

/// How far from the origin, in pixels, a gradient's ends may be: 1e6.
KRITAUI_EXPORT qreal coordinateLimit();

/// Paints \p gradient (its foreground and background stops already baked) from \p start to \p end over the
/// selection, or the whole layer, as the Gradient tool does with a drag.
KRITAUI_EXPORT bool gradient(const Target &target, const QPointF &start, const QPointF &end,
                             KoAbstractGradientSP gradient, const GradientOptions &options, QString *reason = nullptr);

/**
 * Inpaints \p area of the node from the paint around it (PatchMatch), as the Smart Patch tool does with a painted
 * mask. Only pixels inside \p area change. \p accuracy (0 to 100) sets how much of the surroundings is searched,
 * \p patchRadius (2 to 8) the size of the patches compared.
 */
/// The largest area smartPatch() takes, in pixels of its bounding rectangle: 512 x 512 (about 5 s at accuracy 50 on an
/// Apple M-series Mac; a megapixel took over 13 s).
KRITAUI_EXPORT int smartPatchAreaLimit();

KRITAUI_EXPORT bool smartPatch(const Target &target, KisPixelSelectionSP area, int accuracy = 50, int patchRadius = 4,
                               QString *reason = nullptr);

/// Moves the node so that its offset becomes \p position, as an undoable step ("Move"). Moving to where it is
/// queues nothing and returns true.
KRITAUI_EXPORT bool moveNode(const Target &target, const QPoint &position, QString *reason = nullptr);

/**
 * Runs \p command (taking it) in a stroke of its own, as KisProcessingApplicator::runSingleCommandStroke() does,
 * but never asking the image's open strokes to end: one undo step named after the command in \p undoFacade (the
 * image's history when null), told to \p completion (if any) when it ends. Returns at once. \p pixelsOnly: the command
 * changes nothing but paint devices' pixels (through transactions), and the step reports which.
 */
KRITAUI_EXPORT void runCommand(KisImageSP image,
                               KUndo2Command *command,
                               KisStrokeUndoFacade *undoFacade,
                               CompletionSP completion,
                               KisStrokeJobData::Sequentiality sequentiality = KisStrokeJobData::SEQUENTIAL,
                               KisStrokeJobData::Exclusivity exclusivity = KisStrokeJobData::NORMAL,
                               bool pixelsOnly = false);

} // namespace KisToolFunctions

#endif // KIS_TOOL_FUNCTIONS_H
