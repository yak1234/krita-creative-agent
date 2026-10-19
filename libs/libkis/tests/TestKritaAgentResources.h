/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_KRITA_AGENT_RESOURCES_H
#define TEST_KRITA_AGENT_RESOURCES_H

#include <QObject>

/**
 * Brush tips and presets made by scripts (krita-fork 5.1): Krita::createBrushTip() and Krita::createPreset() add
 * resources that are in the resource database at once, tagged "Agent", and paint.
 */
class TestKritaAgentResources : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testBrushTipFromImageAlphaKeepsTheAlpha();
    void testBrushTipFromImageStampKeepsThePixels();
    void testBrushTipIsSavedAndListedAtOnce();
    void testBrushTipFromDocumentArea();
    void testBrushTipRejectsBadInput();
    void testPresetIsInTheResourceModelAtOnce();
    void testPresetFromXml();
    void testPresetRejectsBadInput();
    void testPresetPaintsAStrokeThroughNodePaintLine();
    void testSameNameAsABuiltInPresetLeavesItAlone();
    void testSameNameAsAnArtistTipLeavesItAlone();
    void testReplacingAnAgentTipKeepsOneResource();
    void testReplacingATipChangesItsPresets();
    void testTipApplicationLivesInTheDatabase();
};

#endif
