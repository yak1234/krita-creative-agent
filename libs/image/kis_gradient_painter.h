/*
 *  SPDX-FileCopyrightText: 2004 Adrian Page <adrian@pagenet.plus.com>
 *  SPDX-FileCopyrightText: 2021 L. E. Segovia <amy@amyspark.me>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KIS_GRADIENT_PAINTER_H_
#define KIS_GRADIENT_PAINTER_H_

#include <QScopedPointer>

#include <KoColor.h>

#include "kis_types.h"
#include "kis_painter.h"

#include <kritaimage_export.h>


/**
 *  XXX: Docs!
 */
class KRITAIMAGE_EXPORT KisGradientPainter : public KisPainter
{

public:

    KisGradientPainter();
    KisGradientPainter(KisPaintDeviceSP device);
    KisGradientPainter(KisPaintDeviceSP device, KisSelectionSP selection);

    ~KisGradientPainter() override;

    enum enumGradientShape {
        GradientShapeLinear,
        GradientShapeBiLinear,
        GradientShapeRadial,
        GradientShapeSquare,
        GradientShapeConical,
        GradientShapeConicalSymetric,
        GradientShapeSpiral,
        GradientShapeReverseSpiral,
        GradientShapePolygonal
    };

    enum enumGradientRepeat {
        GradientRepeatNone,
        GradientRepeatForwards,
        GradientRepeatAlternate
    };

    enum enumDither {
        DitherNone,
        DitherBlueNoise,
        DitherBayer2,
        DitherBayer4,
        DitherBayer8
    };

    static constexpr int defaultDitherSteps = 2;

    void setGradientShape(enumGradientShape shape);

    void precalculateShape();

    /**
     * Paint a gradient in the rect between startx, starty, width and height.
     */
    bool paintGradient(const QPointF& gradientVectorStart,
                       const QPointF& gradientVectorEnd,
                       enumGradientRepeat repeat,
                       double antiAliasThreshold,
                       bool reverseGradient,
                       qint32 startx,
                       qint32 starty,
                       qint32 width,
                       qint32 height,
                       enumDither dither = DitherNone,
                       int ditherSteps = defaultDitherSteps);

    // convenience overload
    bool paintGradient(const QPointF& gradientVectorStart,
                       const QPointF& gradientVectorEnd,
                       enumGradientRepeat repeat,
                       double antiAliasThreshold,
                       bool reverseGradient,
                       const QRect &applyRect,
                       enumDither dither = DitherNone,
                       int ditherSteps = defaultDitherSteps);

    template <class T> 
    bool paintGradient(const QPointF& gradientVectorStart,
                       const QPointF& gradientVectorEnd,
                       enumGradientRepeat repeat,
                       double antiAliasThreshold,
                       bool reverseGradient,
                       enumDither dither,
                       int ditherSteps,
                       const QRect &applyRect,
                       T & paintPolicy);

    static bool isBayerDither(enumDither dither);

private:
    struct Private;
    const QScopedPointer<Private> m_d;
};
#endif //KIS_GRADIENT_PAINTER_H_
