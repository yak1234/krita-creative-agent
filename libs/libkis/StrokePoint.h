/*
 *  SPDX-FileCopyrightText: 2026 Riki
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_STROKE_POINT_H
#define LIBKIS_STROKE_POINT_H

#include <QPointF>

#include "kritalibkis_export.h"

/**
 * A complete input sample for Node::paintStroke().
 *
 * Time is the number of milliseconds since the beginning of the stroke and
 * speed is normalized to the range [0, 1], as it is for normal canvas input.
 * Pressure is the final pressure passed to the brush engine.
 */
class KRITALIBKIS_EXPORT StrokePoint
{
public:
    StrokePoint(const QPointF &position = QPointF(),
                qreal pressure = 1.0,
                qreal xTilt = 0.0,
                qreal yTilt = 0.0,
                qreal rotation = 0.0,
                qreal tangentialPressure = 0.0,
                qreal time = 0.0,
                qreal speed = 0.0)
        : m_position(position)
        , m_pressure(pressure)
        , m_xTilt(xTilt)
        , m_yTilt(yTilt)
        , m_rotation(rotation)
        , m_tangentialPressure(tangentialPressure)
        , m_time(time)
        , m_speed(speed)
    {
    }

    const QPointF &position() const { return m_position; }
    qreal pressure() const { return m_pressure; }
    qreal xTilt() const { return m_xTilt; }
    qreal yTilt() const { return m_yTilt; }
    qreal rotation() const { return m_rotation; }
    qreal tangentialPressure() const { return m_tangentialPressure; }
    qreal time() const { return m_time; }
    qreal speed() const { return m_speed; }

    void setPosition(const QPointF &value) { m_position = value; }
    void setPressure(qreal value) { m_pressure = value; }
    void setXTilt(qreal value) { m_xTilt = value; }
    void setYTilt(qreal value) { m_yTilt = value; }
    void setRotation(qreal value) { m_rotation = value; }
    void setTangentialPressure(qreal value) { m_tangentialPressure = value; }
    void setTime(qreal value) { m_time = value; }
    void setSpeed(qreal value) { m_speed = value; }

private:
    QPointF m_position;
    qreal m_pressure;
    qreal m_xTilt;
    qreal m_yTilt;
    qreal m_rotation;
    qreal m_tangentialPressure;
    qreal m_time;
    qreal m_speed;
};

#endif
