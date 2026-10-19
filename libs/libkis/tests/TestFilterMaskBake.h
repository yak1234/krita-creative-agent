/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_FILTER_MASK_BAKE_H
#define TEST_FILTER_MASK_BAKE_H

#include <QObject>

/**
 * FilterMask::bake() (krita-fork 5.2): a filter mask applied to its layer's pixels and removed, the canvas the same,
 * in one undo step that restores the mask and the pixels.
 */
class TestFilterMaskBake : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testBakeBlurMask();
    void testBakeInvertMaskWithPartialSelection();
    void testBakeKeepsTheMasksAboveIt();
    void testBakeRefusesWhatWouldChangeTheLook();
    void testBakeRefusesInLockedOrHiddenParents();
    void testBakeKeepsASmallLayerSmall();
};

#endif
