class StrokePoint
{
%TypeHeaderCode
#include "StrokePoint.h"
%End
public:
    StrokePoint(const QPointF &position = QPointF(),
                qreal pressure = 1.0,
                qreal xTilt = 0.0,
                qreal yTilt = 0.0,
                qreal rotation = 0.0,
                qreal tangentialPressure = 0.0,
                qreal time = 0.0,
                qreal speed = 0.0);
    const QPointF &position() const;
    qreal pressure() const;
    qreal xTilt() const;
    qreal yTilt() const;
    qreal rotation() const;
    qreal tangentialPressure() const;
    qreal time() const;
    qreal speed() const;
    void setPosition(const QPointF &value);
    void setPressure(qreal value);
    void setXTilt(qreal value);
    void setYTilt(qreal value);
    void setRotation(qreal value);
    void setTangentialPressure(qreal value);
    void setTime(qreal value);
    void setSpeed(qreal value);
};
