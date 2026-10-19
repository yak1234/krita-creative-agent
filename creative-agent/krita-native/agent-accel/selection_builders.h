/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AGENT_SELECTION_BUILDERS_H
#define AGENT_SELECTION_BUILDERS_H

#include <QByteArray>
#include <QColor>
#include <QJsonObject>
#include <QVector>
#include <QPoint>
#include <QRect>
#include <QString>
#include <kis_types.h>

/**
 * The selection builders behind AgentAccelService::selectContiguous, selectSimilar, selectionOutline and
 * buildSelection, apart from the document so selection_selftest.cpp can run them on its own. A mask is one byte per
 * pixel of a rect, row by row, 255 selected and 0 not; an answer is that mask after a 16-byte header (x, y, w, h as little-endian int32).
 */
namespace AgentSelection
{
static constexpr int HEADER = 16;

/// region_craft.colour_mask on 8-bit B, G, R, A pixels: 255 where B, G and R are each within `tolerance` of `wanted`
/// and alpha is not 0.
void colourMaskBytes(const quint8 *bgra, int count, const QColor &wanted, int tolerance, quint8 *out);
/// colourMaskBytes over `rect` of an 8-bit RGBA device, read in strips.
QByteArray colourMask(KisPaintDeviceSP device, const QRect &rect, const QColor &wanted, int tolerance);
QByteArray header(const QRect &rect);
/// The answer for `mask` covering `rect`, cropped to its selected pixels (w = h = 0 and no bytes when none are).
QByteArray packMask(const QByteArray &mask, const QRect &rect);
/// The answer for the part of `mask` (covering `rect`) joined to `seed` through edge neighbours, as
/// region_craft.connected_mask, by Krita's scanline fill. Nothing when the seed's own pixel is not set.
QByteArray joinSeed(const QByteArray &mask, const QRect &rect, const QPoint &seed);
/// {"polygons": [[[x, y], ...], ...]} from KisPixelSelection::outline() of an answer, or {"error"}.
QString outlineJson(const QByteArray &headerAndMask);

/*
 * A whole select's seed and colour steps in one call (AgentAccelService::buildSelection): the picture read once, every
 * step searched in it, and the steps combined here on byte masks, where the plugin made one Selection per step and
 * merged them in Python.
 */
enum Mode { Replace, Add, Subtract, Intersect };

/// One region_craft seed or colour step, its defaults filled in.
struct Step {
    bool seeded = false;
    QPoint seed;                                          // seeded: the magic wand's pixel
    QColor colour;                                        // not seeded: the colour range's colour
    int tolerance = 24;
    QRect bounds;                                         // where it searches: its bounds, or the canvas
    Mode mode = Replace;
};

/// The steps from JSON, [{"seed": [x, y] | "color": "#rrggbb", "tolerance"?, "bounds"?: [x, y, w, h], "mode"?}], with
/// region_craft's defaults and checks: tolerance 24 (0-255), bounds the canvas (else inside it, the seed inside them),
/// mode replace for the first step and add after; the first step replaces whatever its mode says. Nothing, with
/// `error` set, for anything else (the plugin then builds step by step).
QVector<Step> parseSteps(const QByteArray &json, const QRect &canvas, QString *error);
/// The rect every step searches inside: their bounds together.
QRect stepsArea(const QVector<Step> &steps);
/// The steps' combined mask over `area` (255 selected, 0 not), from 8-bit B, G, R, A pixels covering `area` row by row.
/// A seed step is the magic wand (colourMaskBytes's test, joined through edge neighbours, inside its bounds), a colour
/// step the colour range; each then replaces, adds (a + b, at most 255), subtracts (a - b, at least 0) or intersects
/// (the smaller), byte for byte as KisPixelSelection::applySelection does (libkis Selection.add, subtract, intersect).
/// `timings`, when given, gets the milliseconds of the fills and of the combining.
QByteArray buildMask(const quint8 *bgra, const QRect &area, const QVector<Step> &steps, QJsonObject *timings = nullptr);
}

#endif
