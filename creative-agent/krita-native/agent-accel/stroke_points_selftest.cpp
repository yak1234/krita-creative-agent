/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
// paintStrokes' inline points (stroke_points.h) against what Krita's brush engine reads from them, without Krita
// running: build.sh builds and runs it after the helper. Exits 1 on any difference.
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtMath>
#include <cstdio>

#include "stroke_points.h"

static int failures = 0;

static void expect(bool ok, const char *what)
{
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

static bool near(qreal a, qreal b)
{
    return qAbs(a - b) < 1e-9;
}

static QJsonArray json(const char *text)
{
    return QJsonDocument::fromJson(QByteArray("{\"a\":") + text + "}").object().value("a").toArray();
}

/// Every value a point carries, in the order the inline format sends them.
static bool reads(const KisPaintInformation &pi, qreal x, qreal y, qreal pressure, qreal xTilt, qreal yTilt, qreal rotation, qreal speed, qreal time)
{
    const bool ok = near(pi.pos().x(), x) && near(pi.pos().y(), y) && near(pi.pressure(), pressure) && near(pi.xTilt(), xTilt)
        && near(pi.yTilt(), yTilt) && near(pi.rotation(), rotation) && near(pi.drawingSpeed(), speed) && near(pi.currentTime(), time);
    if (!ok) {
        std::printf("     read %g, %g, pressure %g, tilt %g %g, rotation %g, speed %g, time %g\n", pi.pos().x(), pi.pos().y(),
                    pi.pressure(), pi.xTilt(), pi.yTilt(), pi.rotation(), pi.drawingSpeed(), pi.currentTime());
    }
    return ok;
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    using AgentStroke::point;

    // Today's formats, unchanged: a point alone is a mouse's, at full pressure.
    expect(reads(point(json("[10, 20]"), 0), 10, 20, 1, 0, 0, 0, 0, 0), "x, y alone: full pressure, no tilt, rotation, speed or time");
    expect(reads(point(json("[10, 20, 0.4]"), 0), 10, 20, 0.4, 0, 0, 0, 0, 0), "pressure alone, as protocol 4");
    expect(reads(point(json("[1, 2, 3, 4, 50, 60, 0.3]"), 4), 50, 60, 0.3, 0, 0, 0, 0, 0), "a segment's end from index 4");

    // The pen beyond pressure (protocol 5).
    expect(reads(point(json("[10, 20, 0.4, 30, -45, 90, 0.5, 250]"), 0), 10, 20, 0.4, 30, -45, 90, 0.5, 250),
           "pressure, tilt x and y, rotation, speed and time");
    expect(reads(point(json("[1, 2, 3, 4, 50, 60, 0.3, -20, 10, -120, 0.8, 1500]"), 4), 50, 60, 0.3, -20, 10, -120, 0.8, 1500),
           "the same on a segment's end");
    expect(reads(point(json("[10, 20, 0.4, 30, -45]"), 0), 10, 20, 0.4, 30, -45, 0, 0, 0), "values left off take their defaults");

    // Brought into Krita's ranges.
    expect(reads(point(json("[0, 0, 2, 99, -99, 0, 3, -5]"), 0), 0, 0, 1, 60, -60, 0, 1, 0),
           "clamped: pressure 0..1, tilt -60..60, speed 0..1, time from 0");
    expect(near(point(json("[0, 0, 1, 0, 0, 270]"), 0).rotation(), -90) && near(point(json("[0, 0, 1, 0, 0, -190]"), 0).rotation(), 170),
           "rotation wraps into -180..180");

    // What the sensors then see: Krita's own conventions for these values.
    const KisPaintInformation upright = point(json("[0, 0, 1, 0, 0]"), 0);
    const KisPaintInformation flat = point(json("[0, 0, 1, 60, 0]"), 0);
    expect(near(KisPaintInformation::tiltElevation(upright, 60, 60, true), 1) && near(KisPaintInformation::tiltElevation(flat, 60, 60, true), 0),
           "tilt elevation (the tilt-elevation sensor): 1 upright, 0 at 60 degrees");
    const KisPaintInformation middle = KisPaintInformation::mix(0.5, point(json("[0, 0, 1, 0, 0, 0, 0, 0]"), 0),
                                                                point(json("[100, 0, 1, 40, -20, 60, 1, 400]"), 0));
    expect(reads(middle, 50, 0, 1, 20, -10, 30, 0.5, 200), "Krita eases tilt, rotation, speed and time between two points");

    std::printf("%s\n", failures ? "FAILED" : "all passed");
    return failures ? 1 : 0;
}
