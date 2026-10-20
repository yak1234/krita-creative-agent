/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureCommands.h"

#include <klocalizedstring.h>

#include "KisFeatureList.h"
#include "kis_image.h"

namespace {
KisFeatureList *listOf(KisImageWSP image)
{
    KisImageSP strong = image.toStrongRef();
    return strong ? strong->featureList() : nullptr;
}
} // namespace

KisAddFeatureCommand::KisAddFeatureCommand(KisImageWSP image, KisFeatureSP feature, int index, KUndo2Command *parent)
    : KUndo2Command(kundo2_i18n("Add Feature"), parent)
    , m_image(image)
    , m_feature(feature)
    , m_index(index)
{
    // Made on the GUI thread, before its stroke runs: an image operation asked for meanwhile follows the feature.
    if (KisFeatureList *list = listOf(image)) {
        list->setMayHaveFeatures();
    }
}

void KisAddFeatureCommand::redo()
{
    KisFeatureList *list = listOf(m_image);
    if (!list || !m_feature) return;
    list->insertFeature(m_feature, m_index);
}

void KisAddFeatureCommand::undo()
{
    KisFeatureList *list = listOf(m_image);
    if (!list || !m_feature) return;
    list->removeFeature(m_feature->id());
}

KisRemoveFeatureCommand::KisRemoveFeatureCommand(KisImageWSP image, const QUuid &id, KUndo2Command *parent)
    : KUndo2Command(kundo2_i18n("Remove Feature"), parent)
    , m_image(image)
    , m_id(id)
{
}

void KisRemoveFeatureCommand::redo()
{
    KisFeatureList *list = listOf(m_image);
    if (!list) return;
    m_index = list->indexOf(m_id);
    m_removed = list->removeFeature(m_id);
}

void KisRemoveFeatureCommand::undo()
{
    KisFeatureList *list = listOf(m_image);
    if (!list || !m_removed) return;
    list->insertFeature(m_removed, m_index);
    m_removed.clear();
}

KisRenameFeatureCommand::KisRenameFeatureCommand(KisImageWSP image,
                                                 const QUuid &id,
                                                 const QString &newName,
                                                 KUndo2Command *parent)
    : KUndo2Command(kundo2_i18n("Rename Feature"), parent)
    , m_image(image)
    , m_id(id)
    , m_newName(newName)
{
}

void KisRenameFeatureCommand::redo()
{
    KisFeatureList *list = listOf(m_image);
    KisFeatureSP feature = list ? list->feature(m_id) : KisFeatureSP();
    if (!feature) {
        m_haveOldName = false;
        return;
    }
    m_oldName = feature->name();
    m_haveOldName = true;
    feature->setName(m_newName);
}

void KisRenameFeatureCommand::undo()
{
    if (!m_haveOldName) return;
    KisFeatureList *list = listOf(m_image);
    KisFeatureSP feature = list ? list->feature(m_id) : KisFeatureSP();
    if (!feature) return;
    feature->setName(m_oldName);
}

KisSetFeatureProtectedCommand::KisSetFeatureProtectedCommand(KisImageWSP image,
                                                             const QUuid &id,
                                                             bool isProtected,
                                                             KUndo2Command *parent)
    : KUndo2Command(isProtected ? kundo2_i18n("Protect Feature") : kundo2_i18n("Unprotect Feature"), parent)
    , m_image(image)
    , m_id(id)
    , m_new(isProtected)
{
}

void KisSetFeatureProtectedCommand::redo()
{
    KisFeatureList *list = listOf(m_image);
    KisFeatureSP feature = list ? list->feature(m_id) : KisFeatureSP();
    if (!feature) {
        m_haveOld = false;
        return;
    }
    m_old = feature->isProtected();
    m_haveOld = true;
    feature->setProtected(m_new);
}

void KisSetFeatureProtectedCommand::undo()
{
    if (!m_haveOld) return;
    KisFeatureList *list = listOf(m_image);
    KisFeatureSP feature = list ? list->feature(m_id) : KisFeatureSP();
    if (!feature) return;
    feature->setProtected(m_old);
}
