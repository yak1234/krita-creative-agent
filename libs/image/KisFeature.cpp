/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeature.h"

#include <QMutexLocker>
#include <QScopedPointer>
#include <QVector>

#include <limits>

#include <mutex>

#include <KoColorSpace.h>
#include <KoColorModelStandardIds.h>
#include <KoMixColorsOp.h>

#include "KisFeatureList.h"
#include "kis_paint_device.h"
#include "kis_painter.h"
#include "kis_pixel_selection.h"
#include "kis_sequential_iterator.h"

bool KisFeature::Properties::operator==(const Properties &rhs) const
{
    if (bounds != rhs.bounds || area != rhs.area || hasMeanColor != rhs.hasMeanColor) {
        return false;
    }
    return !hasMeanColor || meanColor == rhs.meanColor;
}

KisFeature::KisFeature(const QString &name,
                       const QString &kind,
                       KisPixelSelectionSP mask,
                       Author author,
                       State state,
                       bool isProtected,
                       const QUuid &id)
    : m_id(id.isNull() ? QUuid::createUuid() : id)
    , m_name(name)
    , m_kind(kind)
    , m_author(author)
    , m_state(state)
    , m_protected(isProtected)
    , m_mask(mask ? mask : KisPixelSelectionSP(new KisPixelSelection()))
{
}

KisFeature::KisFeature(const KisFeature &rhs)
    : KisShared()
    , m_id(rhs.id())
{
    QMutexLocker l(&rhs.m_mutex);
    m_name = rhs.m_name;
    m_kind = rhs.m_kind;
    m_author = rhs.m_author;
    m_state = rhs.m_state;
    m_protected = rhs.m_protected;
    m_mask = new KisPixelSelection(*rhs.m_mask);
    m_properties = rhs.m_properties;
}

KisFeature::~KisFeature()
{
}

QUuid KisFeature::id() const
{
    return m_id;
}

QString KisFeature::name() const
{
    QMutexLocker l(&m_mutex);
    return m_name;
}

void KisFeature::setName(const QString &name)
{
    {
        QMutexLocker l(&m_mutex);
        if (m_name == name) return;
        m_name = name;
    }
    notifyOwner(false);
}

QString KisFeature::kind() const
{
    QMutexLocker l(&m_mutex);
    return m_kind;
}

void KisFeature::setKind(const QString &kind)
{
    {
        QMutexLocker l(&m_mutex);
        if (m_kind == kind) return;
        m_kind = kind;
    }
    notifyOwner(false);
}

KisFeature::Author KisFeature::author() const
{
    QMutexLocker l(&m_mutex);
    return m_author;
}

void KisFeature::setAuthor(Author author)
{
    {
        QMutexLocker l(&m_mutex);
        if (m_author == author) return;
        m_author = author;
    }
    notifyOwner(false);
}

KisFeature::State KisFeature::state() const
{
    QMutexLocker l(&m_mutex);
    return m_state;
}

void KisFeature::setState(State state)
{
    {
        QMutexLocker l(&m_mutex);
        if (m_state == state) return;
        m_state = state;
    }
    notifyOwner(false);
}

bool KisFeature::isProtected() const
{
    QMutexLocker l(&m_mutex);
    return m_protected;
}

void KisFeature::setProtected(bool value)
{
    {
        QMutexLocker l(&m_mutex);
        if (m_protected == value) return;
        m_protected = value;
    }
    notifyOwner(false);
}

KisPixelSelectionSP KisFeature::mask() const
{
    QMutexLocker l(&m_mutex);
    return m_mask;
}

void KisFeature::setMask(KisPixelSelectionSP mask, KisPaintDeviceSP colorSource)
{
    if (!mask) {
        mask = new KisPixelSelection();
    }
    if (QSharedPointer<KisFeatureOwnerGuard> guard = owner()) {
        std::lock_guard<QRecursiveMutex> l(guard->mutex);
        if (guard->list && guard->list->defaultBounds()) {
            mask->setDefaultBounds(guard->list->defaultBounds());
        }
    }
    // Measured before taking the lock: it reads the whole mask.
    const Properties properties = measureMask(mask, colorSource);
    {
        QMutexLocker l(&m_mutex);
        m_mask = mask;
        m_properties = properties;
    }
    notifyOwner(true);
}

void KisFeature::measure(KisPaintDeviceSP colorSource)
{
    setProperties(measureMask(mask(), colorSource));
}

KisFeature::Properties KisFeature::properties() const
{
    QMutexLocker l(&m_mutex);
    return m_properties;
}

QRect KisFeature::bounds() const
{
    QMutexLocker l(&m_mutex);
    return m_properties.bounds;
}

qint64 KisFeature::area() const
{
    QMutexLocker l(&m_mutex);
    return m_properties.area;
}

KoColor KisFeature::meanColor() const
{
    QMutexLocker l(&m_mutex);
    return m_properties.meanColor;
}

void KisFeature::setProperties(const Properties &properties)
{
    {
        QMutexLocker l(&m_mutex);
        m_properties = properties;
    }
    notifyOwner(true);
}

void KisFeature::setMaskAndProperties(KisPixelSelectionSP mask, const Properties &properties)
{
    if (!mask) {
        mask = new KisPixelSelection();
    }
    {
        QMutexLocker l(&m_mutex);
        m_mask = mask;
        m_properties = properties;
    }
    notifyOwner(true);
}

namespace {

/**
 * The alpha-weighted mean colour of many pixels (Krita's colour mixing), without overflow. A KoMixColorsOp mixer
 * sums colour x alpha x weight in 64-bit integers for integer channels, which overflow after about 8.4 million
 * opaque, fully selected 16-bit pixels. So for 16-bit integer channels each mixer takes at most ChunkPixels pixels;
 * a full one is folded into double sums (its mean colour weighted by its alpha-weighted weight) and a fresh mixer
 * goes on. Other depths use one mixer (8-bit sums cannot overflow, float sums are doubles), so their result is the
 * mixer's own, bit for bit; so is a 16-bit area of one chunk.
 */
class MeanColorAccumulator
{
public:
    /// 2^20 pixels at weight 255 keep a 16-bit mixer's sums below 2^61.
    static const qint64 ChunkPixels = 1 << 20;

    explicit MeanColorAccumulator(const KoColorSpace *cs)
        : m_cs(cs)
        , m_chunkPixels(cs->colorDepthId() == Integer16BitsColorDepthID ? ChunkPixels
                                                                        : std::numeric_limits<qint64>::max())
        , m_colorSums(int(cs->channelCount()), 0.0)
    {
        newMixer();
    }

    void accumulate(const quint8 *pixels, const qint16 *weights, int weightSum, int n)
    {
        if (m_pixelsInMixer > 0 && m_pixelsInMixer + n > m_chunkPixels) {
            fold();
        }
        m_mixer->accumulate(pixels, weights, weightSum, n);
        m_pixelsInMixer += n;
    }

    /// The mean colour, or false when no pixel had any weight.
    bool result(KoColor *color)
    {
        fold();
        if (m_chunks == 0) return false;
        if (m_chunks == 1) {
            *color = m_lastChunk;
            return true;
        }
        const int alphaPos = int(m_cs->alphaPos());
        QVector<float> channels(m_colorSums.size(), 0.0f);
        // Fully transparent everywhere: all channels zero, as the mixer gives.
        if (m_alphaWeightSum > 0) {
            for (int i = 0; i < channels.size(); i++) {
                channels[i] = i == alphaPos ? float(m_alphaWeightSum / m_weightSum)
                                            : float(m_colorSums[i] / m_alphaWeightSum);
            }
        }
        *color = KoColor(m_cs);
        m_cs->fromNormalisedChannelsValue(color->data(), channels);
        return true;
    }

private:
    void newMixer()
    {
        m_mixer.reset(m_cs->mixColorsOp()->createMixer());
        m_pixelsInMixer = 0;
    }

    void fold()
    {
        const qint64 weight = m_mixer->currentWeightsSum();
        if (weight > 0) {
            KoColor chunk(m_cs);
            m_mixer->computeMixedColor(chunk.data());
            QVector<float> channels(m_colorSums.size());
            m_cs->normalisedChannelsValue(chunk.data(), channels);
            const int alphaPos = int(m_cs->alphaPos());
            const double alpha = alphaPos >= 0 && alphaPos < channels.size() ? double(channels[alphaPos]) : 1.0;
            const double alphaWeight = alpha * double(weight);
            for (int i = 0; i < channels.size(); i++) {
                if (i != alphaPos) {
                    m_colorSums[i] += double(channels[i]) * alphaWeight;
                }
            }
            m_alphaWeightSum += alphaWeight;
            m_weightSum += double(weight);
            m_lastChunk = chunk;
            m_chunks++;
        }
        newMixer();
    }

    const KoColorSpace *m_cs;
    const qint64 m_chunkPixels;
    QScopedPointer<KoMixColorsOp::Mixer> m_mixer;
    qint64 m_pixelsInMixer {0};
    int m_chunks {0};
    KoColor m_lastChunk;
    QVector<double> m_colorSums;
    double m_alphaWeightSum {0.0};
    double m_weightSum {0.0};
};

} // namespace

KisFeature::Properties KisFeature::measureMask(KisPixelSelectionSP mask, KisPaintDeviceSP colorSource)
{
    Properties result;
    if (!mask) return result;

    const QRect rect = mask->selectedExactRect();
    if (rect.isEmpty()) return result;
    result.bounds = rect;

    const KoColorSpace *cs = colorSource ? colorSource->colorSpace() : nullptr;
    QScopedPointer<MeanColorAccumulator> mean(cs ? new MeanColorAccumulator(cs) : nullptr);

    // The mask and the painting a run of consecutive pixels at a time (the shorter of the two devices' runs), the
    // runs with a selected pixel going to the mean with the mask's values as weights. The iterators read the tiles
    // in place: no copy of the mask is made.
    KisSequentialConstIterator maskIt(mask, rect);
    QScopedPointer<KisSequentialConstIterator> colorIt(colorSource ? new KisSequentialConstIterator(colorSource, rect)
                                                                   : nullptr);
    QVector<qint16> weights;
    qint64 area = 0;

    int n = 1; // the first step starts the iterators
    while (maskIt.nextPixels(n)) {
        if (colorIt) {
            colorIt->nextPixels(n);
        }
        n = maskIt.nConseqPixels();
        if (colorIt) {
            n = qMin(n, colorIt->nConseqPixels());
        }

        const quint8 *maskPixels = maskIt.rawDataConst();
        int weightSum = 0;
        if (mean) {
            weights.resize(n);
        }
        for (int i = 0; i < n; i++) {
            const quint8 v = maskPixels[i];
            area += v ? 1 : 0;
            if (mean) {
                weights[i] = v;
                weightSum += v;
            }
        }
        if (mean && weightSum > 0) {
            mean->accumulate(colorIt->rawDataConst(), weights.constData(), weightSum, n);
        }
    }
    result.area = area;

    if (mean && mean->result(&result.meanColor)) {
        result.hasMeanColor = true;
    }
    return result;
}

KisPixelSelectionSP KisFeature::boundedMask(KisPixelSelectionSP mask, const QRect &bounds)
{
    if (!mask) return new KisPixelSelection();
    if (mask->defaultPixel().data()[0] == MIN_SELECTED) {
        KisPixelSelectionSP copy = new KisPixelSelection(*mask);
        copy->crop(bounds);
        return copy;
    }
    // A selected default pixel: the document's part, explicitly, on an unselected default.
    KisPixelSelectionSP bounded = new KisPixelSelection(mask->defaultBounds());
    KisPainter::copyAreaOptimized(bounds.topLeft(), mask, bounded, bounds);
    return bounded;
}

QString KisFeature::authorToString(Author author)
{
    return author == Artist ? QStringLiteral("artist") : QStringLiteral("agent");
}

KisFeature::Author KisFeature::authorFromString(const QString &value, Author fallback)
{
    if (value == QLatin1String("artist")) return Artist;
    if (value == QLatin1String("agent")) return Agent;
    return fallback;
}

QString KisFeature::stateToString(State state)
{
    return state == Kept ? QStringLiteral("kept") : QStringLiteral("proposed");
}

KisFeature::State KisFeature::stateFromString(const QString &value, State fallback)
{
    if (value == QLatin1String("kept")) return Kept;
    if (value == QLatin1String("proposed")) return Proposed;
    return fallback;
}

void KisFeature::setOwner(QSharedPointer<KisFeatureOwnerGuard> guard)
{
    QMutexLocker l(&m_mutex);
    m_owner = guard;
}

QSharedPointer<KisFeatureOwnerGuard> KisFeature::owner() const
{
    QMutexLocker l(&m_mutex);
    return m_owner;
}

void KisFeature::notifyOwner(bool boundsChanged)
{
    QSharedPointer<KisFeatureOwnerGuard> guard = owner();
    if (!guard) return;
    // Held while the list is called: the list's destructor waits for it, and clears the link first.
    std::lock_guard<QRecursiveMutex> l(guard->mutex);
    if (guard->list) {
        guard->list->featureChanged(this, boundsChanged);
    }
}
