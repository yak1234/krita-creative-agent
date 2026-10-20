/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATUREQUERIES_H
#define KISFEATUREQUERIES_H

#include <QElapsedTimer>
#include <QList>
#include <QPoint>
#include <QRect>
#include <QString>

#include "KisFeature.h"
#include "kis_types.h"
#include "kritaimage_export.h"

class KisFeatureList;

/**
 * Spatial questions about the features of an image (krita-fork task 6.4, capability canvas-features). Every answer is
 * read from the stored masks (their bounds through the list's R-tree first, then the masks' own tiles), never from the
 * painting's pixels. All of them take any thread, change nothing, and give features in list order.
 */
namespace KisFeatureQueries
{

/// The features whose mask is non-zero at \p point.
KRITAIMAGE_EXPORT QList<KisFeatureSP> featuresAt(const KisFeatureList *list, const QPoint &point);

/// The features whose mask has a pixel in \p rect (a rectangle of the image; the part outside \p bounds is ignored).
KRITAIMAGE_EXPORT QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, const QRect &rect, const QRect &bounds);

/// The features (other than \p feature itself) that share at least one pixel with \p feature's mask.
KRITAIMAGE_EXPORT QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, KisFeatureSP feature);

/// The features that share at least one pixel with \p area (a mask in image coordinates; its selected part counts).
KRITAIMAGE_EXPORT QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, KisPixelSelectionSP area,
                                                          const QRect &bounds);

/// How far apart two features may be and still touch: a gap of this many empty pixels between their masks.
const int kTouchingGap = 1;

/**
 * The features (other than \p feature) that touch \p feature. Two features touch when they share no pixel and some
 * pixel of one lies within kTouchingGap + 1 pixels of a pixel of the other, measured as the larger of the horizontal
 * and vertical distances: directly adjacent (also diagonally), or with at most one empty pixel between them, which is
 * what an anti-aliased or hand-drawn edge leaves. Features that overlap do not touch (they overlap).
 */
KRITAIMAGE_EXPORT QList<KisFeatureSP> featuresTouching(const KisFeatureList *list, KisFeatureSP feature);

/// Whether the masks of \p a and \p b touch, as above.
KRITAIMAGE_EXPORT bool touch(KisFeatureSP a, KisFeatureSP b);

/// The limits of selectionFromExpression(): the most characters, terms and nesting of parentheses it takes, and the
/// time it may run.
const int kMaxExpressionLength = 2000;
const int kMaxExpressionTerms = 64;
const int kMaxExpressionDepth = 16;
const int kMaxExpressionMs = 5000;

/**
 * Combines features by name. The grammar:
 *
 *     expression := term { " " operator " " term }
 *     term       := name | "\"" quoted name "\"" | "(" expression ")"
 *     operator   := "+" (union) | "&" (intersection) | "-" (difference)
 *
 * Operators are always written with a space on each side and apply left to right, with no precedence: "A + B - C"
 * is "(A + B) - C"; parentheses group. A name is the text between operators, trimmed as feature names are, so it may
 * contain spaces and a "-" or "+" or "&" that has no space on both sides ("Tower 3", "Sky-2", "A+B"). A name that
 * contains parentheses or a double quote, or " + ", " & " or " - ", is written in double quotes, inside which
 * \" is a quote and \\ a backslash. Values combine as Krita's selection operations do (union adds and clamps at 255,
 * intersection takes the lower, difference subtracts and clamps at 0).
 *
 * @return the combined mask, a new mask cut to \p bounds, or null with \p error saying why when a name is unknown,
 * the syntax is wrong, a limit (kMaxExpression...) is passed, or the time limit ran out. Never throws.
 */
KRITAIMAGE_EXPORT KisPixelSelectionSP selectionFromExpression(const KisFeatureList *list, const QString &expression,
                                                              const QRect &bounds, QString *error);

} // namespace KisFeatureQueries

#endif // KISFEATUREQUERIES_H
