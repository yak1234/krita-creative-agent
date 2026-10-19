/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TEST_DOCUMENT_SCALED_PROJECTION_H
#define TEST_DOCUMENT_SCALED_PROJECTION_H

#include <QObject>

/**
 * Document::projection(QRect, scale): a scaled view of the composited image, read without copying the full-size
 * canvas first.
 */
class TestDocumentScaledProjection : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testSize_data();
    void testSize();
    void testMatchesSmoothDownscaleOfFullRead_data();
    void testMatchesSmoothDownscaleOfFullRead();
    void testTransparencyIsKept();
    void testSixteenBitDocument();
    void testScaleOneIsTheFullRead();
    void testInvalidArguments();
    void testConversionDuringRead();
    void testOpenStrokeIsNotEnded();
    void testThreadedEqualsSingleThread();
    void testOverflowGuard();
    void testOutsideTheImage();
    void testOtherColorSpaces_data();
    void testOtherColorSpaces();
};

#endif
