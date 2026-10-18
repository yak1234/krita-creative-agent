/*
 *  SPDX-FileCopyrightText: 2017 Dmitry Kazakov <dimula73@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef KISHANDLESTYLE_H
#define KISHANDLESTYLE_H

#include <QVector>
#include <QPen>
#include <QBrush>

#include "kritaglobal_export.h"

struct KRITAGLOBAL_EXPORT KisHandlePalette
{
    KisHandlePalette()
        : primaryColor(QColor(0, 0, 90, 180))
        , secondaryColor(QColor(0, 0, 255, 127))
        , gradientFillColor(QColor(255, 197, 39))
        , highlightColor(QColor(255, 100, 100))
        , highlightOutlineColor(QColor(155, 0, 0))
        , selectionColor(QColor(164, 227, 243))
        , white(Qt::white)
        , black(Qt::black)
    {
    }

    QColor primaryColor;
    QColor secondaryColor;
    QColor gradientFillColor;
    QColor highlightColor;
    QColor highlightOutlineColor;
    QColor selectionColor;
    QColor white;
    QColor black;
};

/**
 * A special class that defines a set of predefined styles for painting handles.
 * Please use static methods for requesting standard krita styles.
 */
class KRITAGLOBAL_EXPORT KisHandleStyle
{
public:

    /**
     * Default style that does *no* change to the painter. That is, the painter
     * will paint with its current pen and brush.
     */
    static KisHandleStyle& inheritStyle();

    /**
     * Main style. Used for showing a single selection or a boundary box of
     * multiple selected objects.
     */
    static KisHandleStyle& primarySelection(KisHandlePalette palette = KisHandlePalette());

    /**
     * Secondary style. Used for highlighting objects inside a multiple
     * selection.
     */
    static KisHandleStyle& secondarySelection(KisHandlePalette palette = KisHandlePalette());

    /**
     * Style for painting gradient handles
     */
    static KisHandleStyle& gradientHandles(KisHandlePalette palette = KisHandlePalette());

    /**
     * Style for painting linear gradient arrows
     */
    static KisHandleStyle& gradientArrows(KisHandlePalette palette = KisHandlePalette());

    /**
     * Same as primary style, but the handles are filled with red color to show
     * that the user is hovering them.
     */
    static KisHandleStyle& highlightedPrimaryHandles(KisHandlePalette palette = KisHandlePalette());

    /**
     * Same as primary style, but the handles are filled with red color to show
     * that the user is hovering them and the outline is solid
     */
    static KisHandleStyle& highlightedPrimaryHandlesWithSolidOutline(KisHandlePalette palette = KisHandlePalette());

    /**
     * Used for nodes, which control points are highlighted (the node itself
     * is not highlighted)
     */
    static KisHandleStyle& partiallyHighlightedPrimaryHandles(KisHandlePalette palette = KisHandlePalette());

    /**
     * Same as primary style, but the handles are filled with green color to show
     * that they are selected.
     */
    static KisHandleStyle& selectedPrimaryHandles(KisHandlePalette palette = KisHandlePalette());

    struct IterationStyle {
        IterationStyle() : isValid(false) {}
        IterationStyle(const QPen &pen, const QBrush &brush)
            : isValid(true),
              stylePair(pen, brush)
        {
        }

        bool isValid;
        QPair<QPen, QBrush> stylePair;
    };

    QVector<IterationStyle> handleIterations;
    QVector<IterationStyle> lineIterations;
};

#endif // KISHANDLESTYLE_H
