/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
// The selection builders against the plugin's Python steps (test_region_craft.py), without Krita running:
// build.sh builds and runs it after the helper. Exits 1 on the first difference.
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>
#include <cstdio>

#include "selection_builders.h"

static int failures = 0;

static void expect(bool ok, const char *what)
{
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

static QByteArray bytes(std::initializer_list<int> values)
{
    QByteArray out;
    for (int v : values) out.append(char(v));
    return out;
}

static QByteArray answer(const QRect &rect, const QByteArray &mask)
{
    return AgentSelection::header(rect) + mask;
}

// ----- buildMask: a whole select's seed and colour steps in one call (buildSelection) -------------------------------

/// 8-bit B, G, R, A pixels for a picture drawn with one letter per pixel: S sky, W wall, D a darker sky, T transparent.
static QByteArray picture(const char *const *rows, int w, int h)
{
    QByteArray out;
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            switch (rows[y][x]) {
            case 'S': out.append(bytes({60, 20, 10, 255})); break;
            case 'D': out.append(bytes({56, 18, 8, 255})); break;
            case 'T': out.append(bytes({60, 20, 10, 0})); break;
            default: out.append(bytes({20, 20, 20, 255})); break;
            }
        }
    }
    return out;
}

static QByteArray build(const QByteArray &bgra, const QRect &area, const char *json, QString *error = nullptr)
{
    QString parseError;
    const QVector<AgentSelection::Step> steps = AgentSelection::parseSteps(QByteArray(json), area, &parseError);
    if (error) *error = parseError;
    if (!parseError.isEmpty()) return QByteArray();
    return AgentSelection::packMask(AgentSelection::buildMask(reinterpret_cast<const quint8 *>(bgra.constData()), area, steps), area);
}

/// One step on its own the protocol-3 way (colourMaskBytes, then Krita's scanline fill for a seed), as a full mask over
/// `area`: what the plugin's per-step path puts in each Selection.
static QByteArray oneStep(const QByteArray &bgra, const QRect &area, const AgentSelection::Step &step)
{
    using namespace AgentSelection;
    QByteArray matching(area.width() * area.height(), '\0');
    QColor wanted = step.colour;
    if (step.seeded) {
        const quint8 *pixel = reinterpret_cast<const quint8 *>(bgra.constData()) + 4 * ((step.seed.y() - area.y()) * area.width() + step.seed.x() - area.x());
        wanted = QColor(pixel[2], pixel[1], pixel[0]);
    }
    colourMaskBytes(reinterpret_cast<const quint8 *>(bgra.constData()), area.width() * area.height(), wanted, step.tolerance,
                    reinterpret_cast<quint8 *>(matching.data()));
    for (int y = area.top(); y <= area.bottom(); y++) {
        for (int x = area.left(); x <= area.right(); x++) {
            if (!step.bounds.contains(x, y)) matching[(y - area.y()) * area.width() + x - area.x()] = 0;
        }
    }
    if (!step.seeded) return matching;
    const QByteArray joined = joinSeed(matching, area, step.seed);
    QByteArray full(area.width() * area.height(), '\0');
    qint32 r[4];
    for (int i = 0; i < 4; i++) r[i] = qFromLittleEndian<qint32>(joined.constData() + 4 * i);
    for (int row = 0; row < r[3]; row++) {
        for (int col = 0; col < r[2]; col++) {
            full[(r[1] - area.y() + row) * area.width() + r[0] - area.x() + col] = joined[HEADER + row * r[2] + col];
        }
    }
    return full;
}

static void buildTests()
{
    using namespace AgentSelection;
    // A sky across the top and down the left, a wall, a sky-coloured window cut off at the right, a darker sky band
    // within tolerance 4 of the sky, and a transparent pixel of the sky's colour.
    const char *const rows[] = {"SSSSWW",
                                "SWWWSW",
                                "SWWWWS",
                                "DDTWWW"};
    const QRect area(0, 0, 6, 4);
    const QByteArray image = picture(rows, 6, 4);
    auto pick = [] (const char *const *marks) {           // the expected mask, with x for selected
        QByteArray out;
        for (int y = 0; y < 4; y++) for (int x = 0; x < 6; x++) out.append(marks[y][x] == 'x' ? char(255) : char(0));
        return out;
    };
    auto expectMask = [&] (const char *json, const char *const *marks, const char *what) {
        expect(build(image, area, json) == packMask(pick(marks), area), what);
    };

    {   const char *const m[] = {"xxxx..", "x.....", "x.....", "......"};
        expectMask(R"([{"seed":[2,0],"tolerance":0}])", m, "one seed step is the magic wand"); }
    {   const char *const m[] = {"xxxx..", "x.....", "x.....", "xx...."};
        expectMask(R"([{"seed":[2,0],"tolerance":4}])", m, "the default tolerance is 24 only when none is given, here 4 joins the darker band"); }
    {   const char *const m[] = {"xxxx..", "x.....", "x.....", "xx...."};
        expectMask(R"([{"seed":[2,0]}])", m, "the default tolerance is 24"); }
    {   const char *const m[] = {"xxxx..", "x...x.", "x....x", "......"};
        expectMask(R"([{"color":"#0a143c","tolerance":0}])", m, "a colour step is not joined, and transparent never matches"); }
    {   const char *const m[] = {"xxxx..", "x...x.", "x.....", "......"};
        expectMask(R"([{"seed":[2,0],"tolerance":0},{"seed":[4,1],"tolerance":0}])", m, "a later step adds by default"); }
    {   const char *const m[] = {"......", "....x.", ".....x", "......"};
        expectMask(R"([{"color":"#0a143c","tolerance":0},{"seed":[0,0],"tolerance":0,"mode":"subtract"}])", m, "subtract"); }
    {   const char *const m[] = {"xx....", "x.....", "x.....", "......"};
        expectMask(R"([{"seed":[0,0],"tolerance":0},{"color":"#0a143c","tolerance":0,"bounds":[0,0,2,3],"mode":"intersect"}])", m,
                   "intersect, with a colour step's bounds"); }
    {   const char *const m[] = {"......", "....x.", "......", "......"};
        expectMask(R"([{"seed":[0,0],"tolerance":0},{"seed":[4,1],"tolerance":0,"mode":"replace","bounds":[4,1,1,1]},{"seed":[4,1],"mode":"intersect"}])",
                   m, "replace drops what came before; intersect keeps the overlap"); }
    {   const char *const m[] = {"xx....", "x.....", "......", "......"};
        expectMask(R"([{"seed":[0,0],"tolerance":0,"bounds":[0,0,2,2]}])", m, "a seed's fill stays inside its bounds"); }
    {   const char *const m[] = {"xxxx..", "x.....", "x.....", "......"};
        expectMask(R"([{"seed":[2,0],"tolerance":0,"mode":"add"}])", m, "the first step replaces whatever its mode"); }
    expect(build(image, area, R"([{"seed":[2,3],"tolerance":0}])") == header(QRect(0, 0, 0, 0)), "a transparent seed selects nothing");
    expect(build(image, area, R"([{"seed":[0,0],"tolerance":0},{"seed":[0,0],"tolerance":0,"mode":"subtract"}])") == header(QRect(0, 0, 0, 0)),
           "subtracting everything leaves nothing");

    QString error;
    for (const char *bad : {"[]", "{}", R"([{"tolerance":3}])", R"([{"seed":[0,0],"color":"#000000"}])", R"([{"seed":[9,0]}])",
                            R"([{"seed":[0,0],"bounds":[2,0,2,2]}])", R"([{"color":"blue"}])", R"([{"seed":[0,0],"mode":"xor"}])",
                            R"([{"seed":[0,0],"tolerance":300}])", R"([{"seed":[0,0],"bounds":[0,0,0,2]}])", "not json"}) {
        build(image, area, bad, &error);
        if (error.isEmpty()) std::printf("     accepted: %s\n", bad);
        expect(!error.isEmpty(), "a malformed step is refused (the plugin then builds step by step)");
    }

    // Against the protocol-3 builders (Krita's scanline fill), combined the plugin's way, on a seeded random picture of
    // three close colours: a maze of edges for the fill, every mode, with and without bounds.
    const int W = 61, H = 47;
    QByteArray noise;
    quint32 state = 7;
    auto next = [&state] { state = state * 1103515245u + 12345u; return (state >> 16) & 0x7fff; };
    const quint8 palette[4][4] = {{60, 20, 10, 255}, {50, 25, 14, 255}, {200, 200, 200, 255}, {60, 20, 10, 0}};
    for (int i = 0; i < W * H; i++) noise.append(reinterpret_cast<const char *>(palette[next() % 4 == 0 ? 2 : next() % 7 == 0 ? 3 : next() % 2]), 4);
    const QRect canvas(0, 0, W, H);
    const char *modes[] = {"replace", "add", "subtract", "intersect"};
    int agreed = 0, trials = 300;
    for (int trial = 0; trial < trials; trial++) {
        QString json = QStringLiteral("[");
        const int count = 1 + next() % 5;
        for (int s = 0; s < count; s++) {
            QRect bounds = canvas;
            if (next() % 2) {
                const int x = next() % W, y = next() % H;
                bounds = QRect(x, y, 1 + next() % (W - x), 1 + next() % (H - y));
            }
            const int sx = bounds.x() + next() % bounds.width(), sy = bounds.y() + next() % bounds.height();
            QString step = next() % 3 ? QStringLiteral("{\"seed\":[%1,%2]").arg(sx).arg(sy)
                                      : QStringLiteral("{\"color\":\"#0a143c\"");
            step += QStringLiteral(",\"tolerance\":%1").arg(next() % 2 ? 0 : 12);
            if (bounds != canvas) step += QStringLiteral(",\"bounds\":[%1,%2,%3,%4]").arg(bounds.x()).arg(bounds.y()).arg(bounds.width()).arg(bounds.height());
            if (s && next() % 4) step += QStringLiteral(",\"mode\":\"%1\"").arg(QLatin1String(modes[next() % 4]));
            json += (s ? QStringLiteral(",") : QString()) + step + QStringLiteral("}");
        }
        json += QStringLiteral("]");
        QString parseError;
        const QVector<Step> steps = parseSteps(json.toUtf8(), canvas, &parseError);
        if (!parseError.isEmpty()) { std::printf("     refused %s: %s\n", qPrintable(json), qPrintable(parseError)); continue; }
        QByteArray expected;
        for (int s = 0; s < steps.size(); s++) {
            const QByteArray mask = oneStep(noise, canvas, steps[s]);
            if (s == 0 || steps[s].mode == Replace) { expected = mask; continue; }
            for (int i = 0; i < mask.size(); i++) {
                const quint8 a = quint8(expected[i]), b = quint8(mask[i]);
                expected[i] = char(steps[s].mode == Add ? qMin(255, a + b) : steps[s].mode == Subtract ? qMax(0, a - b) : qMin(a, b));
            }
        }
        if (build(noise, canvas, json.toUtf8().constData()) == packMask(expected, canvas)) agreed++;
        else if (trials - agreed < 4) std::printf("     differs: %s\n", qPrintable(json));
    }
    std::printf("     %d of %d random step lists agree with the step-by-step builders\n", agreed, trials);
    expect(agreed == trials, "every random step list selects what the step-by-step builders and their combining select");
}

/// --bench: 8 unbounded seed steps on a 6000x4500 picture of noisy stripes, as the live New Moscow measurement.
static void bench()
{
    using namespace AgentSelection;
    const int W = 6000, H = 4500;
    QByteArray image(W * H * 4, '\0');
    quint8 *p = reinterpret_cast<quint8 *>(image.data());
    quint32 state = 11;
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++, p += 4) {
            state = state * 1103515245u + 12345u;
            const int band = (y / 900) % 5, jitter = (state >> 16) % 20;   // stripes 900 rows deep, each one joined region
            p[0] = quint8(40 * band + jitter); p[1] = quint8(30 + 20 * band); p[2] = quint8(200 - 30 * band); p[3] = 255;
        }
    }
    const QRect canvas(0, 0, W, H);
    QString json = QStringLiteral("[");
    for (int s = 0; s < 8; s++) json += QStringLiteral("%1{\"seed\":[%2,%3]}").arg(QLatin1String(s ? "," : "")).arg(250 + 700 * s).arg(150 + 500 * s);
    json += QStringLiteral("]");
    QJsonObject timings;
    QElapsedTimer clock;
    clock.start();
    QString error;
    const QVector<Step> steps = parseSteps(json.toUtf8(), canvas, &error);
    const QByteArray answer = packMask(buildMask(reinterpret_cast<const quint8 *>(image.constData()), canvas, steps, &timings), canvas);
    std::printf("     bench: 8 seed steps on %dx%d in %lld ms (%s), answer %lld bytes\n", W, H, clock.elapsed(),
                QJsonDocument(timings).toJson(QJsonDocument::Compact).constData(), qint64(answer.size()));
    clock.restart();
    for (const Step &step : steps) oneStep(image, canvas, step);
    std::printf("     bench: the same 8 steps through the protocol-3 builders in %lld ms\n", clock.elapsed());
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    using namespace AgentSelection;

    // colour_mask: transparent never matches; each channel within the tolerance (test_colour_range_selects...).
    const QByteArray pixels = bytes({10, 20, 30, 255, 12, 22, 33, 255, 10, 20, 30, 0, 90, 20, 30, 255});
    quint8 out[4];
    colourMaskBytes(reinterpret_cast<const quint8 *>(pixels.constData()), 4, QColor(30, 20, 10), 0, out);
    expect(QByteArray(reinterpret_cast<char *>(out), 4) == bytes({255, 0, 0, 0}), "colour mask, tolerance 0");
    colourMaskBytes(reinterpret_cast<const quint8 *>(pixels.constData()), 4, QColor(30, 20, 10), 3, out);
    expect(QByteArray(reinterpret_cast<char *>(out), 4) == bytes({255, 255, 0, 0}), "colour mask, tolerance 3");

    // connected_mask: a sky along the top and down the left; a window joined only diagonally stays out.
    const QByteArray mask = bytes({255, 255, 255, 255, 0, 0,
                                   255, 0, 0, 0, 255, 0,
                                   255, 0, 0, 0, 0, 255});
    const QRect rect(10, 20, 6, 3);                       // anywhere on the canvas
    expect(joinSeed(mask, rect, QPoint(12, 20)) == answer(QRect(10, 20, 4, 3), bytes({255, 255, 255, 255, 255, 0, 0, 0, 255, 0, 0, 0})),
           "seed joins the sky through edge neighbours only, cropped to it");
    expect(joinSeed(mask, rect, QPoint(11, 21)) == header(QRect(0, 0, 0, 0)), "a seed on an unmatched pixel selects nothing");
    expect(joinSeed(mask, rect, QPoint(15, 22)) == answer(QRect(15, 22, 1, 1), bytes({255})), "the window alone");
    expect(joinSeed(mask, QRect(10, 20, 6, 1), QPoint(12, 20)) == answer(QRect(10, 20, 4, 1), bytes({255, 255, 255, 255})),
           "the fill stays inside its bounds");

    // A ring: the fill goes round, and the hole stays out.
    const QByteArray ring = bytes({255, 255, 255,
                                   255, 0, 255,
                                   255, 255, 255});
    expect(joinSeed(ring, QRect(0, 0, 3, 3), QPoint(2, 2)) == answer(QRect(0, 0, 3, 3), ring), "a ring, joined all round");
    // A U whose arms meet only below: a scanline fill must go down and back up.
    const QByteArray cup = bytes({255, 0, 255,
                                  255, 0, 255,
                                  255, 255, 255});
    expect(joinSeed(cup, QRect(0, 0, 3, 3), QPoint(2, 0)) == answer(QRect(0, 0, 3, 3), cup), "a cup, from the top of one arm");

    expect(packMask(bytes({0, 0, 0, 0, 255, 0, 0, 255, 0}), QRect(5, 5, 3, 3)) == answer(QRect(6, 6, 1, 2), bytes({255, 255})),
           "packMask crops to the selected pixels");
    expect(packMask(QByteArray(9, '\0'), QRect(5, 5, 3, 3)) == header(QRect(0, 0, 0, 0)), "nothing selected");

    const QJsonObject square = QJsonDocument::fromJson(outlineJson(answer(QRect(2, 3, 2, 2), bytes({255, 255, 255, 255}))).toUtf8()).object();
    std::printf("     outline of a 2x2 square at (2, 3): %s\n", QJsonDocument(square).toJson(QJsonDocument::Compact).constData());
    expect(square.value("polygons").toArray().size() == 1, "a square's outline is one polygon");
    expect(QJsonDocument::fromJson(outlineJson(header(QRect(0, 0, 3, 3))).toUtf8()).object().contains("error"), "a short mask is refused");

    buildTests();
    if (argc > 1 && QByteArray(argv[1]) == "--bench") bench();

    std::printf("%s\n", failures ? "FAILED" : "all passed");
    return failures ? 1 : 0;
}
