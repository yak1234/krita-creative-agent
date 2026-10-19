/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREIMAGECOMMAND_H
#define KISFEATUREIMAGECOMMAND_H

#include <functional>

#include <QRect>
#include <QSharedPointer>

#include <kundo2command.h>

#include "kis_types.h"
#include "kritaimage_export.h"

class KisFilterStrategy;
class KisProcessingApplicator;

/**
 * Keeps an image's feature masks in step with an operation on the whole image (krita-fork task 6.1b): crop, canvas
 * resize, scale, rotate, shear and mirror move each mask the way the painting moves, cut to the new bounds; after
 * each of them, and after a colour-space conversion, the features are measured again (bounds, area and mean colour,
 * the mean colour in the image's colour space).
 *
 * Masks are not nodes, so the processing visitors of these operations never see them. The operation ends its
 * applicator with endApplicator() instead of KisProcessingApplicator::end(): this command joins the operation's
 * stroke as its last job before the final signals, so the operation and the features' change are one undo step.
 *
 * The mean colour is read from the projection, which is refreshed only after the operation's stroke. So the command
 * moves the masks and measures their bounds and area, and a small stroke started right after the operation's
 * (no undo step of its own, redo history kept) measures the mean colour once the refresh has run, and records it as
 * the state the command's redo puts back. Undo puts each feature's previous mask and properties back; redo puts the
 * new ones back, without measuring.
 */
class KRITAIMAGE_EXPORT KisFeatureImageCommand : public KUndo2Command
{
public:
    /// Changes a feature's mask in place (the command hands it a copy). Called in a stroke job.
    typedef std::function<void(KisPixelSelectionSP mask)> MaskTransform;

    /**
     * @param transform how each mask moves; null when the operation moves no pixel (a colour-space conversion)
     */
    KisFeatureImageCommand(KisImageWSP image, MaskTransform transform, KUndo2Command *parent = nullptr);
    ~KisFeatureImageCommand() override;

    void redo() override;
    void undo() override;

    /**
     * Ends \p applicator as KisProcessingApplicator::end() does; when \p image has features, a
     * KisFeatureImageCommand with \p transform is added first and the mean colours are measured after the stroke.
     * A null \p image (an operation on some layers, not the image), or an image whose list never held a feature
     * (KisFeatureList::mayHaveFeatures()), ends the applicator exactly as upstream does. Otherwise the command reads
     * the list when it runs, so a feature brought back by an undo queued before the operation is moved too.
     */
    static void endApplicator(KisProcessingApplicator &applicator, KisImageSP image, MaskTransform transform);

    /**
     * endApplicator() for KisNodeManager::mirrorNodes(): the masks are mirrored when \p nodes is the image's root
     * alone and there is no \p selection (Mirror Image, Mirror All Layers). Mirroring some layers, or a selected
     * area, changes the painting under the features like any other edit of it, and ends the applicator as upstream.
     */
    static void endMirrorApplicator(KisProcessingApplicator &applicator,
                                    KisImageSP image,
                                    const KisNodeList &nodes,
                                    KisSelectionSP selection,
                                    Qt::Orientation orientation);

    /// The mask transform of a crop or canvas resize to \p newRect (in the old image's coordinates).
    static MaskTransform cropTransform(const QRect &newRect);

    /// The mask transform of KisTransformWorker with these parameters (scale, rotate and shear of the image).
    static MaskTransform workerTransform(qreal scaleX, qreal scaleY,
                                         qreal shearX, qreal shearY,
                                         qreal rotation,
                                         qreal translateX, qreal translateY,
                                         KisFilterStrategy *filter);

    /// The mask transform of a mirror at \p axis (KisTransformWorker::mirror()).
    static MaskTransform mirrorTransform(qreal axis, Qt::Orientation orientation);

    /// How many commands were made, and measuring strokes started, in this process (for tests: an operation on an
    /// image without features adds neither).
    static int commandsCreated();
    static int measureStrokesStarted();

    struct Shared;

private:
    QSharedPointer<Shared> m_d;
};

#endif // KISFEATUREIMAGECOMMAND_H
