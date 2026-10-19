/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "stroke_points.h"

#include <QPointF>
#include <cmath>

KisPaintInformation AgentStroke::point(const QJsonArray &values, int at)
{
    // The value at `at + offset`, or the mouse's default when the array stops before it.
    auto value = [&values, at] (int offset, qreal fallback) {
        return values.size() > at + offset ? values[at + offset].toDouble(fallback) : fallback;
    };
    const qreal turned = std::fmod(value(5, 0.0) + 180.0, 360.0);       // -180..180, as QTabletEvent::rotation()
    return KisPaintInformation(QPointF(value(0, 0.0), value(1, 0.0)),
                               qBound(0.0, value(2, 1.0), 1.0),          // pressure
                               qBound(-60.0, value(3, 0.0), 60.0),       // xTilt, degrees
                               qBound(-60.0, value(4, 0.0), 60.0),       // yTilt, degrees
                               (turned < 0 ? turned + 360.0 : turned) - 180.0,
                               0.0,                                      // tangential pressure (an airbrush wheel)
                               1.0,                                      // perspective: off the perspective grid
                               qMax(0.0, value(7, 0.0)),                 // ms since the stroke began
                               qBound(0.0, value(6, 0.0), 1.0));         // speed, as Krita normalises it
}
