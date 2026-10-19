/*
 *  SPDX-FileCopyrightText: 2017 Wolthera van Hövell tot Westerflier <griffinvalley@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_FILTERMASK_H
#define LIBKIS_FILTERMASK_H

#include <QObject>
#include "Node.h"
#include "Filter.h"

#include <kis_types.h>

#include "kritalibkis_export.h"
#include "libkis.h"

/**
 * @brief The FilterMask class
 * A filter mask, unlike a filter layer, will add a non-destructive filter
 * to the composited image of the node it is attached to.
 *
 * You can set grayscale pixeldata on the filter mask to adjust where the filter is applied.
 *
 * Filtermasks can be animated.
 */

class KRITALIBKIS_EXPORT FilterMask : public Node
{
    Q_OBJECT
    Q_DISABLE_COPY(FilterMask)

public:
    explicit FilterMask(KisImageSP image, QString name, Filter &filter, QObject *parent = 0);
    explicit FilterMask(KisImageSP image, KisFilterMaskSP mask, QObject *parent=0);
    ~FilterMask() override;
public Q_SLOTS:

    /**
     * @brief type Krita has several types of nodes, split in layers and masks. Group
     * layers can contain other layers, any layer can contain masks.
     *
     * @return The type of the node. Valid types are:
     * <ul>
     *  <li>paintlayer
     *  <li>grouplayer
     *  <li>filelayer
     *  <li>filterlayer
     *  <li>filllayer
     *  <li>clonelayer
     *  <li>vectorlayer
     *  <li>transparencymask
     *  <li>filtermask
     *  <li>transformmask
     *  <li>selectionmask
     *  <li>colorizemask
     * </ul>
     *
     * If the Node object isn't wrapping a valid Krita layer or mask object, and
     * empty string is returned.
     */
    QString type() const override;

    void setFilter(Filter &filter);
    Filter *filter();

    /**
     * @brief bake applies this filter mask to its layer's pixels and removes the mask, as one undo step ("Bake
     * Filter Mask"). The canvas looks the same afterwards. The layer stays the same layer (same name, id, other
     * masks and style); only its pixels change. The call waits until it is done.
     *
     * The mask is applied by Krita's own mask code, as when it renders the layer, over the layer's content and as
     * far as the filter reaches (a blur's halo); only a filter that changes transparent pixels (needsTransparentPixels)
     * covers the whole image. Tiles left empty are not kept, so a small layer stays small.
     *
     * The filter runs over that area in one piece, while the canvas renders it tile by tile: a filter whose result
     * depends on the whole area (auto-contrast, for one) can differ slightly from what the mask showed, as with
     * Krita's Flatten Layer.
     *
     * Inside Document.beginAgentMove() ... endAgentMove() (or beginUndoMacro()), the bake is part of that one step.
     *
     * (Krita Agent, krita-fork 5.2; implemented in FilterMaskBake.cpp.)
     *
     * @return false, changing nothing, when the mask cannot be baked without changing how the layer looks: its
     * layer is not a paint layer (a group, a file layer, ...) or is animated; the mask, its layer or a group above
     * them is locked or hidden (the artist could not edit it either); or another visible effect mask (a filter,
     * transparency or transform mask) applies before it (below it in the stack): bake that one first. A refusal for a
     * lock or a hidden group also writes a warning to the log.
     */
    bool bake();
};

#endif // LIBKIS_FILTERMASK_H


