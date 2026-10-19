/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "selection_builders.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QElapsedTimer>
#include <QRegularExpression>
#include <QStringList>
#include <QVector>
#include <QtEndian>
#include <cstring>

#include <kis_paint_device.h>
#include <kis_pixel_selection.h>
#include <floodfill/kis_scanline_fill.h>

namespace AgentSelection
{
static constexpr int STRIP = 256;                        // device rows read at a time

void colourMaskBytes(const quint8 *bgra, int count, const QColor &wanted, int tolerance, quint8 *out)
{
    const int r = wanted.red(), g = wanted.green(), b = wanted.blue();
    tolerance = qBound(0, tolerance, 255);
    for (int i = 0; i < count; i++, bgra += 4) {
        out[i] = (bgra[3] && qAbs(bgra[2] - r) <= tolerance && qAbs(bgra[1] - g) <= tolerance && qAbs(bgra[0] - b) <= tolerance) ? 255 : 0;
    }
}

QByteArray colourMask(KisPaintDeviceSP device, const QRect &rect, const QColor &wanted, int tolerance)
{
    QByteArray mask(rect.width() * rect.height(), '\0');
    QVector<quint8> strip(rect.width() * STRIP * 4);
    quint8 *out = reinterpret_cast<quint8 *>(mask.data());
    for (int top = rect.top(); top <= rect.bottom(); top += STRIP) {
        const int rows = qMin(STRIP, rect.bottom() + 1 - top);
        device->readBytes(strip.data(), rect.left(), top, rect.width(), rows);
        colourMaskBytes(strip.constData(), rect.width() * rows, wanted, tolerance, out);
        out += rect.width() * rows;
    }
    return mask;
}

QByteArray header(const QRect &rect)
{
    QByteArray answer(HEADER, '\0');
    const qint32 values[4] = {rect.x(), rect.y(), rect.width(), rect.height()};
    for (int i = 0; i < 4; i++) qToLittleEndian<qint32>(values[i], answer.data() + 4 * i);
    return answer;
}

QByteArray packMask(const QByteArray &mask, const QRect &rect)
{
    const int w = rect.width();
    int left = w, right = -1, top = -1, bottom = -1;
    for (int row = 0; row < rect.height(); row++) {
        const char *line = mask.constData() + row * w;
        int first = 0;
        while (first < w && !line[first]) first++;
        if (first == w) continue;
        int last = w - 1;
        while (!line[last]) last--;
        left = qMin(left, first); right = qMax(right, last);
        if (top < 0) top = row;
        bottom = row;
    }
    if (top < 0) return header(QRect(0, 0, 0, 0));
    const QRect found(rect.x() + left, rect.y() + top, right - left + 1, bottom - top + 1);
    QByteArray answer = header(found);
    answer.reserve(HEADER + found.width() * found.height());
    for (int row = top; row <= bottom; row++) answer.append(mask.constData() + row * w + left, found.width());
    return answer;
}

QByteArray joinSeed(const QByteArray &mask, const QRect &rect, const QPoint &seed)
{
    if (!rect.contains(seed) || !mask[(seed.y() - rect.y()) * rect.width() + (seed.x() - rect.x())]) {
        return header(QRect(0, 0, 0, 0));                 // the seed's own pixel does not match (it is transparent)
    }
    // The mask as a selection, then Krita's scanline fill from the seed over it. Threshold 1 compares the mask's bytes
    // exactly (KisColorSelectionPolicies::SlowDifferencePolicy), so the fill takes the 255s joined to the seed.
    KisPixelSelectionSP matching = new KisPixelSelection();
    matching->writeBytes(reinterpret_cast<const quint8 *>(mask.constData()), rect);
    KisPixelSelectionSP joined = new KisPixelSelection();
    KisScanlineFill fill(matching, seed, rect);
    fill.setThreshold(1);
    fill.fillSelection(joined);
    const QRect extent = joined->selectedExactRect() & rect;
    if (extent.isEmpty()) return header(QRect(0, 0, 0, 0));
    QByteArray answer = header(extent);
    answer.resize(HEADER + extent.width() * extent.height());
    joined->readBytes(reinterpret_cast<quint8 *>(answer.data() + HEADER), extent);
    return answer;
}

static QString failure(const QString &message)
{
    return QString::fromUtf8(QJsonDocument(QJsonObject{{"error", message}}).toJson(QJsonDocument::Compact));
}

QString outlineJson(const QByteArray &headerAndMask)
{
    if (headerAndMask.size() < HEADER) return failure(QStringLiteral("No mask."));
    qint32 values[4];
    for (int i = 0; i < 4; i++) values[i] = qFromLittleEndian<qint32>(headerAndMask.constData() + 4 * i);
    const QRect rect(values[0], values[1], values[2], values[3]);
    if (values[2] < 0 || values[3] < 0 || headerAndMask.size() != HEADER + qint64(values[2]) * values[3]) {
        return failure(QStringLiteral("The mask does not fill its rect."));
    }
    QJsonArray polygons;
    if (!rect.isEmpty()) {
        KisPixelSelectionSP selection = new KisPixelSelection();
        selection->writeBytes(reinterpret_cast<const quint8 *>(headerAndMask.constData() + HEADER), rect);
        Q_FOREACH (const QPolygon &polygon, selection->outline()) {
            QJsonArray points;
            for (const QPoint &point : polygon) points.append(QJsonArray{point.x(), point.y()});
            polygons.append(points);
        }
    }
    return QString::fromUtf8(QJsonDocument(QJsonObject{{"polygons", polygons}}).toJson(QJsonDocument::Compact));
}

QVector<Step> parseSteps(const QByteArray &json, const QRect &canvas, QString *error)
{
    auto refuse = [error] (int index, const QString &message) {
        *error = QStringLiteral("Step %1: %2").arg(index + 1).arg(message);
        return QVector<Step>();
    };
    error->clear();
    QJsonParseError parsed;
    const QJsonDocument document = QJsonDocument::fromJson(json, &parsed);
    if (parsed.error != QJsonParseError::NoError || !document.isArray() || document.array().isEmpty()) {
        *error = QStringLiteral("Give the steps as a JSON list of one or more.");
        return QVector<Step>();
    }
    auto integer = [] (const QJsonValue &value, int *out) {
        const double number = value.toDouble(-1e18);
        if (!value.isDouble() || number != double(int(number))) return false;
        *out = int(number);
        return true;
    };
    QVector<Step> steps;
    const QJsonArray list = document.array();
    for (int index = 0; index < list.size(); index++) {
        const QJsonObject object = list[index].toObject();
        Step step;
        if (object.contains(QStringLiteral("seed")) == object.contains(QStringLiteral("color"))) {
            return refuse(index, QStringLiteral("give a seed or a color"));
        }
        step.bounds = canvas;
        if (object.contains(QStringLiteral("bounds"))) {
            const QJsonArray values = object.value(QStringLiteral("bounds")).toArray();
            int v[4];
            if (values.size() != 4 || !integer(values[0], v) || !integer(values[1], v + 1) || !integer(values[2], v + 2) || !integer(values[3], v + 3)) {
                return refuse(index, QStringLiteral("bounds must be [x, y, w, h]"));
            }
            step.bounds = QRect(v[0], v[1], v[2], v[3]);
            if (v[2] <= 0 || v[3] <= 0 || !canvas.contains(step.bounds)) return refuse(index, QStringLiteral("bounds must lie inside the canvas"));
        }
        if (object.contains(QStringLiteral("tolerance"))) {
            if (!integer(object.value(QStringLiteral("tolerance")), &step.tolerance) || step.tolerance < 0 || step.tolerance > 255) {
                return refuse(index, QStringLiteral("tolerance must be an integer from 0 to 255"));
            }
        }
        if (object.contains(QStringLiteral("seed"))) {
            const QJsonArray values = object.value(QStringLiteral("seed")).toArray();
            int x, y;
            if (values.size() != 2 || !integer(values[0], &x) || !integer(values[1], &y)) return refuse(index, QStringLiteral("seed must be [x, y]"));
            step.seeded = true;
            step.seed = QPoint(x, y);
            if (!step.bounds.contains(step.seed)) return refuse(index, QStringLiteral("the seed must lie inside its bounds"));
        } else {
            const QString colour = object.value(QStringLiteral("color")).toString();
            static const QRegularExpression hex(QStringLiteral("^#[0-9A-Fa-f]{6}$"));
            if (!hex.match(colour).hasMatch()) return refuse(index, QStringLiteral("color must be #rrggbb"));
            step.colour = QColor(colour);
        }
        const QString mode = object.value(QStringLiteral("mode")).toString(index ? QStringLiteral("add") : QStringLiteral("replace"));
        const QStringList modes{QStringLiteral("replace"), QStringLiteral("add"), QStringLiteral("subtract"), QStringLiteral("intersect")};
        if (!modes.contains(mode)) return refuse(index, QStringLiteral("mode must be replace, add, subtract or intersect"));
        step.mode = index ? Mode(modes.indexOf(mode)) : Replace;   // region_craft: the first source replaces, whatever its mode
        steps.append(step);
    }
    return steps;
}

QRect stepsArea(const QVector<Step> &steps)
{
    QRect area;
    for (const Step &step : steps) area |= step.bounds;
    return area;
}

/// The magic wand inside `bounds`: every pixel matching the seed's colour (colourMaskBytes's test) joined to it through
/// edge neighbours, set to 255 in `out` (zeroed, covering `area`). A span fill: each run of matching pixels is filled
/// whole, then the rows above and below are searched along it for runs not yet filled.
static void fillSeed(const quint8 *bgra, const QRect &area, const QRect &bounds, const QPoint &seed, int tolerance, quint8 *out)
{
    const int stride = area.width();
    const quint8 *start = bgra + 4 * ((seed.y() - area.y()) * stride + seed.x() - area.x());
    if (!start[3]) return;                                // a transparent seed matches nothing, not even itself
    const int r = start[2], g = start[1], b = start[0];
    tolerance = qBound(0, tolerance, 255);
    auto matches = [&] (int x, int y) {                   // area coordinates
        const quint8 *p = bgra + 4 * (y * stride + x);
        return p[3] && qAbs(p[2] - r) <= tolerance && qAbs(p[1] - g) <= tolerance && qAbs(p[0] - b) <= tolerance;
    };
    const int left = bounds.left() - area.x(), right = bounds.right() - area.x();
    const int top = bounds.top() - area.y(), bottom = bounds.bottom() - area.y();
    QVector<QPoint> todo{QPoint(seed.x() - area.x(), seed.y() - area.y())};
    while (!todo.isEmpty()) {
        const QPoint at = todo.takeLast();
        const int y = at.y();
        quint8 *row = out + y * stride;
        if (row[at.x()]) continue;                        // filled since it was found
        int a = at.x(), z = at.x();
        while (a > left && !row[a - 1] && matches(a - 1, y)) a--;
        while (z < right && !row[z + 1] && matches(z + 1, y)) z++;
        memset(row + a, 255, z - a + 1);
        for (const int near : {y - 1, y + 1}) {
            if (near < top || near > bottom) continue;
            const quint8 *other = out + near * stride;
            bool inRun = false;
            for (int x = a; x <= z; x++) {
                const bool open = !other[x] && matches(x, near);
                if (open && !inRun) todo.append(QPoint(x, near));
                inRun = open;
            }
        }
    }
}

QByteArray buildMask(const quint8 *bgra, const QRect &area, const QVector<Step> &steps, QJsonObject *timings)
{
    QElapsedTimer clock;
    qint64 fill = 0, combine = 0;
    const int w = area.width(), size = w * area.height();
    QByteArray result(size, '\0'), mask(size, '\0');
    quint8 *acc = reinterpret_cast<quint8 *>(result.data()), *one = reinterpret_cast<quint8 *>(mask.data());
    for (int index = 0; index < steps.size(); index++) {
        const Step &step = steps[index];
        clock.start();
        // The step's own mask, over the whole area: 0 outside its bounds. The first replacing step fills `acc` itself.
        const bool direct = step.mode == Replace;
        quint8 *target = direct ? acc : one;
        memset(target, 0, size);
        if (step.seeded) {
            fillSeed(bgra, area, step.bounds, step.seed, step.tolerance, target);
        } else {
            const int x = step.bounds.x() - area.x();
            for (int y = step.bounds.top() - area.y(); y <= step.bounds.bottom() - area.y(); y++) {
                colourMaskBytes(bgra + 4 * (y * w + x), step.bounds.width(), step.colour, step.tolerance, target + y * w + x);
            }
        }
        fill += clock.nsecsElapsed();
        clock.start();
        if (!direct) {
            // Outside the step's bounds its mask is 0: add and subtract leave `acc` there, intersect clears it.
            const QRect local = step.bounds.translated(-area.topLeft());
            if (step.mode == Intersect) {
                for (int y = 0; y < area.height(); y++) {
                    quint8 *row = acc + y * w;
                    if (y < local.top() || y > local.bottom()) { memset(row, 0, w); continue; }
                    memset(row, 0, local.left());
                    memset(row + local.right() + 1, 0, w - local.right() - 1);
                    const quint8 *with = one + y * w;
                    for (int x = local.left(); x <= local.right(); x++) row[x] = qMin(row[x], with[x]);
                }
            } else {
                for (int y = local.top(); y <= local.bottom(); y++) {
                    quint8 *row = acc + y * w;
                    const quint8 *with = one + y * w;
                    if (step.mode == Add) {
                        for (int x = local.left(); x <= local.right(); x++) row[x] = quint8(qMin(255, row[x] + with[x]));
                    } else {
                        for (int x = local.left(); x <= local.right(); x++) row[x] = quint8(qMax(0, row[x] - with[x]));
                    }
                }
            }
        }
        combine += clock.nsecsElapsed();
    }
    if (timings) {
        timings->insert(QStringLiteral("fill"), qRound(fill / 1e6));
        timings->insert(QStringLiteral("combine"), qRound(combine / 1e6));
    }
    return result;
}
}
