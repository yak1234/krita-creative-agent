/* This file is part of the KDE libraries
   SPDX-FileCopyrightText: 2026 Arkady Flury <arkady.flury@gmail.com>

   SPDX-License-Identifier: LGPL-2.0-only
*/

#ifndef KOFOREGROUNDCOLOUR_H
#define KOFOREGROUNDCOLOUR_H


#include <KoDualColorButton.h>


class KisCanvas2;

class KRITAUI_EXPORT KoForegroundColour : public KoDualColorButton {
    Q_OBJECT
public:
    KoForegroundColour(KisCanvasResourceProvider *canvasResourceProvider,
                      const KoColorDisplayRendererInterface *displayRenderer = 0,
                      QWidget *parent = 0, QWidget *dialogParent = 0);
    void paint_icons(QPainter &painter) override;
    void mouseReleaseEvent( QMouseEvent *event ) override;
    void mousePressEvent( QMouseEvent *event ) override;
    bool event(QEvent *event) override;
};

#endif