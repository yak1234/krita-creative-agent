/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISSPLASHBANNERLAYOUT_H
#define KISSPLASHBANNERLAYOUT_H

#include <QRect>
#include <QRectF>
#include <QSize>
#include <QtMath>

/**
 * Where a build with its own identity (Toska) puts its splash banner. Stock Krita does not use this: its banner keeps
 * upstream's layout in KisSplashScreen::updateSplashImage().
 *
 * Toska's banner (krita/data/splash/toska/banner.svg) is the logo with a light halo around it. The logo's own frame
 * (the element "toska-logo") is placed in the calm left third of the painting: its left edge at kLeft of the splash
 * width, its top at kTop of the splash height, kWidth of the splash width wide. The halo padding around the frame
 * falls outside those numbers, so changing the halo never moves the logo.
 */
namespace KisSplashBannerLayout
{
static constexpr qreal kLeft = 0.035;
static constexpr qreal kTop = 0.30;
static constexpr qreal kWidth = 0.36;

/**
 * The banner widget's geometry for a splash of @p splashSize, given the banner SVG's view box and the bounds of its
 * logo frame in view box units. An empty or out-of-range @p logoBounds means the whole view box is the logo. Returns
 * an empty rectangle for an empty splash or view box.
 */
inline QRect identityBannerGeometry(const QSize &splashSize, const QRectF &viewBox, const QRectF &logoBounds)
{
    if (splashSize.isEmpty() || !viewBox.isValid() || viewBox.width() <= 0 || viewBox.height() <= 0) {
        return QRect();
    }
    QRectF logo = logoBounds;
    if (!logo.isValid() || logo.width() <= 0 || logo.height() <= 0 || !viewBox.contains(logo)) {
        logo = viewBox;
    }
    const qreal scale = kWidth * splashSize.width() / logo.width();
    const qreal left = kLeft * splashSize.width() - (logo.x() - viewBox.x()) * scale;
    const qreal top = kTop * splashSize.height() - (logo.y() - viewBox.y()) * scale;
    return QRect(qRound(left), qRound(top), qRound(viewBox.width() * scale), qRound(viewBox.height() * scale));
}
}

#endif // KISSPLASHBANNERLAYOUT_H
