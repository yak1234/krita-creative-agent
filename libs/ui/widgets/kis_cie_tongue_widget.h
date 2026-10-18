/* 
 * SPDX-FileCopyrightText: 2015 Wolthera van Hövell tot Westerflier <griffinvalley@gmail.com>
 *
 * Based on the Digikam CIE Tongue widget
 * SPDX-FileCopyrightText: 2006-2013 Gilles Caulier <caulier dot gilles at gmail dot com>
 *
 * Any source code are inspired from lprof project and
 * SPDX-FileCopyrightText: 1998-2001 Marti Maria
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 **/
 
#ifndef KIS_CIETONGUEWIDGET_H
#define KIS_CIETONGUEWIDGET_H
 
// Qt includes

#include "KoColorimetryUtils.h"
#include <QWidget>
#include <QColor>
#include <QPaintEvent>
 
// KDE includes

#include <KoColor.h>
#include <KoColorSpace.h>
  
#include <kritaui_export.h>

class KRITAUI_EXPORT KisCIETongueWidget : public QWidget
{
    Q_OBJECT
 
public:
 
    KisCIETongueWidget(QWidget *parent = nullptr);
    ~KisCIETongueWidget() override;
 
    //this expects a qvector <double> (9), qvector <double> (3) and whether or not there's profile data?;
    void setProfileData(QVector<KoColorimetryUtils::xyY> p, KoColorimetryUtils::xyY w, bool profileData = false);
    void setGamut(QPolygonF gamut);
    void setRGBData(KoColorimetryUtils::xyY whitepoint, QVector<KoColorimetryUtils::xyY> colorants);
    void setCMYKData(KoColorimetryUtils::xyY whitepoint);
    void setXYZData(KoColorimetryUtils::xyY whitepoint);
    void setGrayData(KoColorimetryUtils::xyY whitepoint);
    void setLABData(KoColorimetryUtils::xyY whitepoint);
    void setYCbCrData(KoColorimetryUtils::xyY whitepoint);
    void setProfileDataAvailable(bool dataAvailable);
 
    void loadingStarted();
    void loadingFailed();
    void uncalibratedColor();
    
    enum model {RGBA, CMYKA, XYZA, LABA, GRAYA, YCbCrA};
 
protected:
 
    int  grids(double val) const;
 
    void outlineTongue();
    void fillTongue();
    void drawTongueAxis();
    void drawTongueGrid();
    void drawLabels();
 
    QRgb colorByCoord(double x, double y);
    void drawSmallEllipse(QPointF xy, int r, int g, int b, int sz);
 
    void resizeEvent(QResizeEvent* event) override;
    void paintEvent(QPaintEvent*) override;
 
private:
 
    void drawColorantTriangle();
    void drawGamut();
    void drawWhitePoint();
    void drawPatches();
    void updatePixmap();
 
    void mapPoint(int& icx, int& icy, QPointF xy);
    void biasedLine(int x1, int y1, int x2, int y2);
    void biasedText(int x, int y, const QString& txt);
 
private :
 
    class Private;
    Private* const d {nullptr};
};
 
#endif /* KISCIETONGUEWIDGET_H */
