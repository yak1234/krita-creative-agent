/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AGENT_STROKE_POINTS_H
#define AGENT_STROKE_POINTS_H

#include <QJsonArray>
#include <brushengine/kis_paint_information.h>

/**
 * paintStrokes' points as Krita's brush engine reads them, apart from the document so stroke_points_selftest.cpp can
 * check them on their own. A point is inline in the stroke's JSON, from index `at` of its array:
 *
 *   x, y, pressure?, xTilt?, yTilt?, rotation?, speed?, timeMs?
 *
 * the start's array from 0 and each segment's from 4 (after c1x, c1y, c2x, c2y). A value left off, and every value
 * after it, takes the default a mouse gives Krita and the Python API paints with: pressure 1, tilt 0, rotation 0,
 * speed 0, time 0. Each is in the units Krita's tablet input gives KisPaintInformation
 * (KisPaintingInformationBuilder::createPaintingInformation), so the dynamic sensors read it as a pen's:
 *   - pressure 0..1;
 *   - xTilt, yTilt in degrees, -60..60, as QTabletEvent's (the X/Y-tilt sensors read 1 - |tilt| / 60, tilt elevation
 *     KisPaintInformation::tiltElevation(info, 60, 60), tilt direction atan2(-xTilt, yTilt));
 *   - rotation in degrees, -180..180, as QTabletEvent's (the rotation sensor reads rotation / 180);
 *   - speed 0..1: Krita's own is the view's pixels per millisecond over the "maxAllowedSpeedValue" setting (30), capped
 *     at 1, and the speed sensor reads it as given (drawingSpeed());
 *   - timeMs, milliseconds since the stroke began (the time sensor reads currentTime(); timed spacing, the airbrush,
 *     paints by it).
 * Out-of-range values are brought into range: clamped, rotation wrapped. Between two points Krita eases every one of
 * them along the curve (KisPaintInformation::mix in KisPaintOpUtils::paintBezierCurve).
 */
namespace AgentStroke
{
KisPaintInformation point(const QJsonArray &values, int at);
}

#endif
