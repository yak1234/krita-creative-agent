/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisImageChangeReports.h"

#include <QGlobalStatic>
#include <QMetaMethod>

#include "kis_lod_transform.h"

Q_GLOBAL_STATIC(KisImageChangeReports, s_instance)

KisImageChangeReports *KisImageChangeReports::instance()
{
    return s_instance;
}

void KisImageChangeReports::reportNodeDirty(KisImage *image, KisNode *node, const QVector<QRect> &rects,
                                            int levelOfDetail)
{
    if (!node || rects.isEmpty()) return;
    if (!isSignalConnected(QMetaMethod::fromSignal(&KisImageChangeReports::sigNodeDirty))) return;
    if (levelOfDetail <= 0) {
        Q_EMIT sigNodeDirty(image, node, rects);
        return;
    }
    QVector<QRect> scaled;
    scaled.reserve(rects.size());
    for (const QRect &rect : rects) {
        scaled.append(KisLodTransform::upscaledRect(rect, levelOfDetail));
    }
    Q_EMIT sigNodeDirty(image, node, scaled);
}
