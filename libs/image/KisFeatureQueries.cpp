/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureQueries.h"

#include <KisRegion.h>

#include <algorithm>
#include <QByteArray>
#include <QPair>
#include <QSet>
#include <QSharedPointer>

#include "KisFeatureList.h"
#include "kis_pixel_selection.h"

namespace KisFeatureQueries
{

namespace
{

/// \p rect cut to \p bounds, computed in 64 bits so a huge rectangle cannot overflow.
QRect clampedTo(const QRect &rect, const QRect &bounds)
{
    if (rect.isNull() || bounds.isEmpty()) return QRect();
    const qint64 left = qMax<qint64>(qMin<qint64>(rect.x(), qint64(rect.x()) + rect.width()), bounds.left());
    const qint64 right = qMin<qint64>(qMax<qint64>(rect.x(), qint64(rect.x()) + rect.width()) - 1, bounds.right());
    const qint64 top = qMax<qint64>(qMin<qint64>(rect.y(), qint64(rect.y()) + rect.height()), bounds.top());
    const qint64 bottom = qMin<qint64>(qMax<qint64>(rect.y(), qint64(rect.y()) + rect.height()) - 1, bounds.bottom());
    if (left > right || top > bottom) return QRect();
    return QRect(int(left), int(top), int(right - left + 1), int(bottom - top + 1));
}

bool shareAPixel(KisFeatureSP a, KisFeatureSP b)
{
    const QRect common = a->bounds() & b->bounds();
    if (common.isEmpty()) return false;
    return a->hasPixelIn(common, b->mask());
}

} // namespace

QList<KisFeatureSP> featuresAt(const KisFeatureList *list, const QPoint &point)
{
    QList<KisFeatureSP> result;
    Q_FOREACH (KisFeatureSP feature, list->featuresWithBoundsContaining(point)) {
        if (feature->hasPixelIn(QRect(point, QSize(1, 1)))) result << feature;
    }
    return result;
}

QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, const QRect &rect, const QRect &bounds)
{
    QList<KisFeatureSP> result;
    const QRect area = clampedTo(rect, bounds);
    if (area.isEmpty()) return result;
    Q_FOREACH (KisFeatureSP feature, list->featuresWithBoundsIntersecting(area)) {
        if (feature->hasPixelIn(area)) result << feature;
    }
    return result;
}

QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, KisFeatureSP feature)
{
    QList<KisFeatureSP> result;
    if (!feature || feature->bounds().isEmpty()) return result;
    Q_FOREACH (KisFeatureSP other, list->featuresWithBoundsIntersecting(feature->bounds())) {
        if (other != feature && shareAPixel(other, feature)) result << other;
    }
    return result;
}

QList<KisFeatureSP> featuresOverlapping(const KisFeatureList *list, KisPixelSelectionSP area, const QRect &bounds)
{
    QList<KisFeatureSP> result;
    if (!area) return result;
    const QRect extent = clampedTo(area->selectedExactRect(), bounds);
    if (extent.isEmpty()) return result;
    Q_FOREACH (KisFeatureSP feature, list->featuresWithBoundsIntersecting(extent)) {
        if (feature->hasPixelIn(extent & feature->bounds(), area)) result << feature;
    }
    return result;
}

bool touch(KisFeatureSP a, KisFeatureSP b)
{
    if (!a || !b || a == b) return false;
    const int reach = kTouchingGap + 1;
    const QRect ra = a->bounds();
    const QRect rb = b->bounds();
    if (ra.isEmpty() || rb.isEmpty()) return false;
    const QRect zone = ra.adjusted(-reach, -reach, reach, reach);
    if (!zone.intersects(rb)) return false;
    if (shareAPixel(a, b)) return false;

    KisPixelSelectionSP maskA = a->mask();
    KisPixelSelectionSP maskB = b->mask();
    if (!maskA || !maskB) return false;

    // Walk the stored tiles of b near a, and look in a for a pixel within reach of each pixel of b in the tile; tiles
    // with no stored tile of a near them are skipped, so two big features that meet along an edge cost the length of
    // the edge.
    KisRegion regionB = maskB->region();
    regionB &= zone;
    const QVector<QRect> tilesA = maskA->region().rects();
    for (const QRect &tile : regionB.rects()) {
        const QRect around = tile.adjusted(-reach, -reach, reach, reach);
        bool near = false;
        for (const QRect &tileA : tilesA) {
            if (tileA.intersects(around)) {
                near = true;
                break;
            }
        }
        if (!near) continue;

        const int w = around.width();
        QByteArray valuesA(w * around.height(), 0);
        QByteArray valuesB(tile.width() * tile.height(), 0);
        maskA->readBytes(reinterpret_cast<quint8 *>(valuesA.data()), around);
        maskB->readBytes(reinterpret_cast<quint8 *>(valuesB.data()), tile);
        for (int y = 0; y < tile.height(); y++) {
            for (int x = 0; x < tile.width(); x++) {
                if (valuesB[y * tile.width() + x] == 0) continue;
                // The pixel is (x, y) in the tile and (x + reach, y + reach) in `around`.
                for (int dy = 0; dy <= 2 * reach; dy++) {
                    const char *row = valuesA.constData() + (y + dy) * w + x;
                    for (int dx = 0; dx <= 2 * reach; dx++) {
                        if (row[dx] != 0) return true;
                    }
                }
            }
        }
    }
    return false;
}

QList<KisFeatureSP> featuresTouching(const KisFeatureList *list, KisFeatureSP feature)
{
    QList<KisFeatureSP> result;
    if (!feature || feature->bounds().isEmpty()) return result;
    const int reach = kTouchingGap + 1;
    Q_FOREACH (KisFeatureSP other, list->featuresWithBoundsIntersecting(feature->bounds().adjusted(-reach, -reach, reach, reach))) {
        if (other != feature && touch(feature, other)) result << other;
    }
    return result;
}

// ---- the expression ------------------------------------------------------------------------------------------------

namespace
{

enum class Op { Union, Intersect, Subtract };

/// A term, then the operations applied to it left to right. A term is a name or a parenthesised expression.
struct Expression;
struct Term {
    QString name;                          // when `inner` is empty
    QSharedPointer<Expression> inner;
};
struct Expression {
    Term first;
    QList<QPair<Op, Term>> rest;
};

class Parser
{
public:
    Parser(const QString &text, QString *error)
        : m_text(text)
        , m_error(error)
    {
    }

    bool parse(QSharedPointer<Expression> &out)
    {
        out = parseExpression(0);
        if (!out) return false;
        skipSpaces();
        if (m_pos < m_text.size()) return fail(QStringLiteral("unexpected \"%1\" at position %2").arg(m_text[m_pos]).arg(m_pos + 1));
        return true;
    }

    int terms() const { return m_terms; }

private:
    bool fail(const QString &why)
    {
        if (m_error && m_error->isEmpty()) *m_error = why;
        return false;
    }

    void skipSpaces()
    {
        while (m_pos < m_text.size() && m_text[m_pos].isSpace()) m_pos++;
    }

    static bool isOperator(QChar c)
    {
        return c == QLatin1Char('+') || c == QLatin1Char('&') || c == QLatin1Char('-');
    }

    /// Whether an operator with a space on each side starts at \p pos.
    bool operatorAt(int pos) const
    {
        return pos >= 0 && pos + 2 < m_text.size() && m_text[pos].isSpace() && isOperator(m_text[pos + 1])
            && m_text[pos + 2].isSpace();
    }

    QSharedPointer<Expression> parseExpression(int depth)
    {
        if (depth > kMaxExpressionDepth) {
            fail(QStringLiteral("parentheses nested deeper than %1").arg(kMaxExpressionDepth));
            return nullptr;
        }
        QSharedPointer<Expression> expression(new Expression);
        if (!parseTerm(depth, expression->first)) return nullptr;
        while (true) {
            // Spaces, an operator, spaces. The first space was left by the name (or is skipped after a quoted name or
            // a parenthesis).
            const int mark = m_pos;
            skipSpaces();
            if (m_pos >= m_text.size() || m_text[m_pos] == QLatin1Char(')')) {
                return expression;
            }
            if (!isOperator(m_text[m_pos]) || m_pos == mark || m_pos + 1 >= m_text.size() || !m_text[m_pos + 1].isSpace()) {
                fail(QStringLiteral("expected \" + \", \" & \" or \" - \" (with a space on each side) at position %1").arg(m_pos + 1));
                return nullptr;
            }
            const QChar c = m_text[m_pos];
            m_pos++;
            Term term;
            if (!parseTerm(depth, term)) return nullptr;
            expression->rest << qMakePair(c == QLatin1Char('+') ? Op::Union : (c == QLatin1Char('&') ? Op::Intersect : Op::Subtract), term);
        }
    }

    bool parseTerm(int depth, Term &term)
    {
        skipSpaces();
        if (m_pos >= m_text.size()) return fail(QStringLiteral("a name is missing at the end"));
        const QChar c = m_text[m_pos];
        if (c == QLatin1Char('(')) {
            m_pos++;
            term.inner = parseExpression(depth + 1);
            if (!term.inner) return false;
            skipSpaces();
            if (m_pos >= m_text.size() || m_text[m_pos] != QLatin1Char(')')) return fail(QStringLiteral("a closing parenthesis is missing"));
            m_pos++;
            return true;
        }
        if (c == QLatin1Char('"')) {
            m_pos++;
            QString name;
            while (m_pos < m_text.size() && m_text[m_pos] != QLatin1Char('"')) {
                if (m_text[m_pos] == QLatin1Char('\\') && m_pos + 1 < m_text.size()) m_pos++;
                name += m_text[m_pos++];
            }
            if (m_pos >= m_text.size()) return fail(QStringLiteral("a closing quote is missing"));
            m_pos++;
            term.name = name.trimmed();
            if (term.name.isEmpty()) return fail(QStringLiteral("a quoted name is empty"));
            if (++m_terms > kMaxExpressionTerms) return fail(QStringLiteral("more than %1 names").arg(kMaxExpressionTerms));
            return true;
        }
        // An unquoted name runs to the next " op ", a closing parenthesis, or the end.
        const int start = m_pos;
        while (m_pos < m_text.size()) {
            const QChar d = m_text[m_pos];
            if (d == QLatin1Char(')')) break;
            if (d == QLatin1Char('(') || d == QLatin1Char('"')) {
                return fail(QStringLiteral("a name containing %1 must be in double quotes (position %2)").arg(d).arg(m_pos + 1));
            }
            if (d.isSpace() && operatorAt(m_pos)) break;
            m_pos++;
        }
        term.name = m_text.mid(start, m_pos - start).trimmed();
        if (term.name.isEmpty()) return fail(QStringLiteral("a name is missing at position %1").arg(start + 1));
        // "A +" or "A -": an operator with nothing after it is a syntax error, not a feature called "A +".
        if (term.name.size() >= 3 && isOperator(term.name.at(term.name.size() - 1))
            && term.name.at(term.name.size() - 2).isSpace()) {
            return fail(QStringLiteral("an operator at the end has no name after it (\"%1\")").arg(term.name));
        }
        if (++m_terms > kMaxExpressionTerms) return fail(QStringLiteral("more than %1 names").arg(kMaxExpressionTerms));
        return true;
    }

    QString m_text;
    QString *m_error;
    int m_pos = 0;
    int m_terms = 0;
};

class Evaluator
{
public:
    Evaluator(const KisFeatureList *list, const QRect &bounds, QString *error)
        : m_list(list)
        , m_bounds(bounds)
        , m_error(error)
    {
        m_clock.start();
    }

    KisPixelSelectionSP evaluate(const Expression &expression)
    {
        KisPixelSelectionSP result = term(expression.first);
        if (!result) return nullptr;
        for (const QPair<Op, Term> &step : expression.rest) {
            KisPixelSelectionSP right = term(step.second);
            if (!right) return nullptr;
            if (m_clock.elapsed() > kMaxExpressionMs) {
                fail(QStringLiteral("took longer than %1 ms").arg(kMaxExpressionMs));
                return nullptr;
            }
            // `result` may be a feature's own mask: combine into a copy (tiles shared until written).
            if (!m_owned.contains(result.data())) {
                result = new KisPixelSelection(*result);
                m_owned.insert(result.data());
            }
            switch (step.first) {
            case Op::Union:
                result->applySelection(right, SELECTION_ADD);
                break;
            case Op::Intersect:
                result->applySelection(right, SELECTION_INTERSECT);
                break;
            case Op::Subtract:
                result->applySelection(right, SELECTION_SUBTRACT);
                break;
            }
        }
        return result;
    }

private:
    void fail(const QString &why)
    {
        if (m_error && m_error->isEmpty()) *m_error = why;
    }

    KisPixelSelectionSP term(const Term &t)
    {
        if (t.inner) return evaluate(*t.inner);
        KisFeatureSP feature = m_list->featureByName(t.name);
        if (!feature) {
            fail(QStringLiteral("there is no feature called \"%1\"").arg(t.name));
            return nullptr;
        }
        KisPixelSelectionSP mask = feature->mask();
        if (!mask) mask = new KisPixelSelection();
        return mask;
    }

    const KisFeatureList *m_list;
    QRect m_bounds;
    QString *m_error;
    QElapsedTimer m_clock;
    QSet<KisPixelSelection *> m_owned;
};

} // namespace

KisPixelSelectionSP selectionFromExpression(const KisFeatureList *list, const QString &expression, const QRect &bounds,
                                            QString *error)
{
    QString localError;
    QString *why = error ? error : &localError;
    why->clear();
    if (expression.size() > kMaxExpressionLength) {
        *why = QStringLiteral("the expression is %1 characters, more than the %2 allowed").arg(expression.size()).arg(kMaxExpressionLength);
        return nullptr;
    }
    if (expression.trimmed().isEmpty()) {
        *why = QStringLiteral("the expression is empty");
        return nullptr;
    }
    QSharedPointer<Expression> parsed;
    Parser parser(expression, why);
    if (!parser.parse(parsed)) return nullptr;
    Evaluator evaluator(list, bounds, why);
    KisPixelSelectionSP result = evaluator.evaluate(*parsed);
    if (!result) return nullptr;
    return KisFeature::boundedMask(result, bounds);
}

} // namespace KisFeatureQueries
