/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATURECOMMANDS_H
#define KISFEATURECOMMANDS_H

#include <QString>
#include <QUuid>

#include <kundo2command.h>

#include "KisFeature.h"
#include "kis_types.h"
#include "kritaimage_export.h"

/**
 * Undo commands that change an image's feature list (KisImage::featureList()). None of them touches a pixel. Run
 * one through KisProcessingApplicator::runSingleCommandStroke() (or push it with the image's undo adapter) to make
 * one undo step that marks the document modified like any other change.
 *
 * They hold the image weakly and do nothing once it is gone.
 */

/// Adds a feature to the list, at \p index or at the end.
class KRITAIMAGE_EXPORT KisAddFeatureCommand : public KUndo2Command
{
public:
    KisAddFeatureCommand(KisImageWSP image, KisFeatureSP feature, int index = -1, KUndo2Command *parent = nullptr);
    void redo() override;
    void undo() override;

private:
    KisImageWSP m_image;
    KisFeatureSP m_feature;
    int m_index;
};

/// Removes a feature from the list; undo puts it back where it was, mask and properties unchanged.
class KRITAIMAGE_EXPORT KisRemoveFeatureCommand : public KUndo2Command
{
public:
    KisRemoveFeatureCommand(KisImageWSP image, const QUuid &id, KUndo2Command *parent = nullptr);
    void redo() override;
    void undo() override;

private:
    KisImageWSP m_image;
    QUuid m_id;
    KisFeatureSP m_removed;
    int m_index {-1};
};

/// Renames a feature.
class KRITAIMAGE_EXPORT KisRenameFeatureCommand : public KUndo2Command
{
public:
    KisRenameFeatureCommand(KisImageWSP image, const QUuid &id, const QString &newName, KUndo2Command *parent = nullptr);
    void redo() override;
    void undo() override;

private:
    KisImageWSP m_image;
    QUuid m_id;
    QString m_newName;
    QString m_oldName;
    bool m_haveOldName {false};
};

#endif // KISFEATURECOMMANDS_H
