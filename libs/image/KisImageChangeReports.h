/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISIMAGECHANGEREPORTS_H
#define KISIMAGECHANGEREPORTS_H

#include <QObject>
#include <QRect>
#include <QVector>

#include "kritaimage_export.h"

class KisImage;
class KisNode;

/**
 * Reports which node asked for which area of an image to be redrawn: the per-node half of the change reports that
 * scripts read through libkis (the image half is KisImage::sigImageUpdated).
 *
 * KisImage::requestProjectionUpdate() reports every request here before its update filters run, so a node's pixel
 * change is reported even while projection updates are suspended or dropped. With nothing connected a report costs a
 * function call and Qt's check for receivers.
 *
 * sigNodeDirty is emitted in the thread that requested the update (often a stroke's worker thread): connect with
 * Qt::DirectConnection, keep the slot short and thread-safe, and never touch the node graph from it.
 */
class KRITAIMAGE_EXPORT KisImageChangeReports : public QObject
{
    Q_OBJECT
public:
    static KisImageChangeReports *instance();

    /**
     * Reports that \p node asked for \p rects to be redrawn. \p levelOfDetail is the image's level of detail at the
     * time (KisImage::currentLevelOfDetail()): above 0, the rects are in that reduced resolution (an instant-preview
     * pass) and are reported scaled up to image pixels, as KisImage::sigImageUpdated reports them.
     */
    void reportNodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects, int levelOfDetail);

Q_SIGNALS:
    /// \p rects are in image pixels (level of detail 0).
    void sigNodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects);
};

#endif // KISIMAGECHANGEREPORTS_H
