/* This file is part of the KDE libraries
   SPDX-FileCopyrightText: 2026 Arkady Flury <arkady.flury@gmail.com>

   SPDX-License-Identifier: LGPL-2.0-only
*/

#ifndef KOSWAPBGFGCOLOURS_H
#define KOSWAPBGFGCOLOURS_H


#include <KoDualColorButton.h>


class KisCanvas2;

class KRITAUI_EXPORT KoSwapBgFgColours : public KoDualColorButton {
    Q_OBJECT
public:
    KoSwapBgFgColours(KisCanvasResourceProvider *canvasResourceProvider,
                      const KoColorDisplayRendererInterface *displayRenderer = 0,
                      QWidget *parent = 0, QWidget *dialogParent = 0);
    void paint_icons(QPainter &painter) override;
    void mouseReleaseEvent( QMouseEvent *event ) override;
    void mousePressEvent( QMouseEvent *event ) override;
    bool event(QEvent *event) override;
    void mouseMoveEvent( QMouseEvent *event ) override;
};

#endif