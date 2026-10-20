/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISWELCOMEBACKGROUNDLAYOUT_H
#define KISWELCOMEBACKGROUNDLAYOUT_H

#include <QRect>
#include <QSize>
#include <QtGlobal>

/**
 * How a build with its own identity (Toska, KisAppIdentity::hasOwnWelcome()) lays its painting under the welcome
 * page. Stock Krita does not use this: its welcome page has no background picture.
 *
 * Toska's painting (krita/data/welcome/toska/toska-welcome.jpg, 2:1) is dark and empty in its left third, with a red
 * moon high on the right and a cream and ember brush stroke through the middle. It covers the whole page, keeps its
 * aspect ratio, and is anchored to the right edge, so a narrower page crops the empty left side first and the moon
 * and the stroke stay in view. Vertically it is anchored at kAnchorY: a wide, short page crops more of the dark band
 * at the bottom than of the sky, so the moon stays in view up to about a 3.5:1 page.
 *
 * Over it the page lays the window colour: kVeil everywhere, and a left-to-right fade from kLeftShade (at the left
 * edge) to nothing at kLeftFadeEnd of the page width, under the New/Open/help column. A light theme (Toska Day) gets
 * the stronger kVeilLight, because its text is dark and the painting is dark.
 */
namespace KisWelcomeBackgroundLayout
{
inline constexpr qreal kAnchorX = 1.0;          // 0 left, 1 right
inline constexpr qreal kAnchorY = 0.25;         // 0 top, 1 bottom
inline constexpr qreal kVeil = 0.30;            // window colour over the whole painting, dark themes
inline constexpr qreal kVeilLight = 0.62;       // the same on a light theme
inline constexpr qreal kLeftShade = 0.88;       // window colour at the left edge
inline constexpr qreal kLeftFadeEnd = 0.45;     // where the left shade has faded out, as a fraction of the page width

/**
 * The part of an image of @p imageSize to draw scaled over a page of @p targetSize so that it covers the page with
 * its aspect ratio kept, anchored at (kAnchorX, kAnchorY). Returns an empty rectangle for an empty image or page.
 */
inline QRect coverSourceRect(const QSize &imageSize, const QSize &targetSize)
{
    if (imageSize.isEmpty() || targetSize.isEmpty()) {
        return QRect();
    }
    const qreal scale = qMax(qreal(targetSize.width()) / imageSize.width(),
                             qreal(targetSize.height()) / imageSize.height());
    const int width = qBound(1, qRound(targetSize.width() / scale), imageSize.width());
    const int height = qBound(1, qRound(targetSize.height() / scale), imageSize.height());
    const int left = qRound((imageSize.width() - width) * kAnchorX);
    const int top = qRound((imageSize.height() - height) * kAnchorY);
    return QRect(left, top, width, height);
}

/// How much of the window colour lies over the whole painting, by the theme's lightness (QColor::lightness(), 0-255).
inline qreal veilFor(int windowLightness)
{
    return windowLightness > 127 ? kVeilLight : kVeil;
}
}

#endif // KISWELCOMEBACKGROUNDLAYOUT_H
