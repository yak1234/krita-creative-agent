/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef KISCLIPPINGUTILSTEST_H
#define KISCLIPPINGUTILSTEST_H

#include <functional>
#include <simpletest.h>
#include <testutil.h>
#include "kis_group_layer.h"

class KisNodeJugglerCompressed;

/// Clipping masks of the layers docker (ported from Krita-Revamp): the rules, the juggler's enableInheritAlpha, the clip action.
class KisClippingUtilsTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void init();
    void cleanup();

    void testPredicates();
    void testNewLayerRule();
    void testDropRules();
    void testPlanClipToLayerBelow();
    void testPlanWithNoLayerBelowOrOnMasks();

    void testJugglerDefaultKeepsAlphaAsIs();
    void testJugglerEnableInheritAlphaMoveCopyAdd();
    void testApplyGroupAndClip();
    void testApplyGroupAndClipChain();
    void testApplyClipInPlaceAndRelease();
    void testApplyJoinGroup();
    void testClipToKeepsAgentStyleClipStackUntouched();
    void testDropBelowTheBaseGoesUnderTheGroup();
    void testNoBaseToClipToIsRefusedWithAReason();
    void testGroupAndClipMovesBlendModeAndOpacityToTheGroup();

private:
    KisPaintLayerSP newLayer(const QString &name, bool inheritAlpha = false);
    bool runJuggler(const std::function<void(KisNodeJugglerCompressed *)> &fn);
    QStringList hierarchy() const;

    QScopedPointer<TestUtil::MaskParent> p;
    KisPaintLayerSP base;
};

#endif
