/* This file is part of the KDE libraries

   SPDX-FileCopyrightText: 1999 Daniel M. Duley <mosfet@kde.org>
   SPDX-FileCopyrightText: 2006 Tobias Koenig <tokoe@kde.org>

   SPDX-License-Identifier: LGPL-2.0-only
*/

#ifndef KORESETBGFGCOLOURS_H
#define KORESETBGFGCOLOURS_H


#include <KoDualColorButton.h>

#include <kis_canvas2.h>
class KisCanvas2;

class KRITAUI_EXPORT KoResetBgFgColours : public KoDualColorButton {
    Q_OBJECT
public:
    KoResetBgFgColours(KisCanvasResourceProvider *canvasResourceProvider,
                      const KoColorDisplayRendererInterface *displayRenderer = 0,
                      QWidget *parent = 0, QWidget *dialogParent = 0);
    void paint_icons(QPainter &painter) override;
    void mouseReleaseEvent( QMouseEvent *event ) override;
    void mousePressEvent( QMouseEvent *event ) override;
    bool event(QEvent *event) override;
    void mouseMoveEvent( QMouseEvent *event ) override;
};

#endif