/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_DOCUMENT_REGION_REFRESH_H
#define TEST_DOCUMENT_REGION_REFRESH_H

#include <QObject>

/**
 * Region refresh in libkis: Document::refreshProjection(QRect) recomposites only the given rect, and
 * Node::setPixelData() marks only its own rect dirty.
 */
class TestDocumentRegionRefresh : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testRefreshProjectionRectUpdatesOnlyThatRect();
    void testRefreshProjectionRectIsClippedToTheImage();
    void testRefreshProjectionEmptyRectChangesNothing();
    void testSetPixelDataDirtiesOnlyItsRect();
    void testRefreshProjectionRectGrowsByEffects_data();
    void testRefreshProjectionRectGrowsByEffects();
    void testSetPixelDataOnTransparencyMask();
};

#endif
