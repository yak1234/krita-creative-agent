/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef KIS_AGENT_SCALED_READ_H
#define KIS_AGENT_SCALED_READ_H

#include <QSize>
#include <QtGlobal>

#include "kritalibkis_export.h"

/**
 * Helpers of Document::projection(QRect, scale), exported for its tests.
 */
namespace KisAgentScaledRead
{

/**
 * Most source pixels that may reach one output pixel. The area average sums colour times alpha times two 8-bit
 * area weights, at most 255 * 255 * 256 * 256 (about 4.3e9) per source pixel, in 64-bit sums: 4e9 of them stay
 * below 2^64.
 */
constexpr quint64 maxSourcePixelsPerOutputPixel = 4000000000ULL;

/**
 * The output size to average \p source into so that no output pixel gathers more than \p limit source pixels
 * (counting the partial ones at its edges): \p output itself when it is within the limit, else a larger size of
 * about the same aspect, at most \p source. Document::projection(QRect, scale) reads at that size and scales the
 * result down to \p output with Qt.
 */
KRITALIBKIS_EXPORT QSize safeOutputSize(const QSize &source, const QSize &output,
                                        quint64 limit = maxSourcePixelsPerOutputPixel);

/**
 * How long Document::projection(QRect, scale) tries for its read-only lock before it gives up and returns a null
 * image: 5 s by default. It tries without asking the active tool to end its stroke, so an artist holding the pen
 * through a long stroke makes the read time out instead of being cut short.
 */
constexpr int defaultReadLockTimeoutMs = 5000;
KRITALIBKIS_EXPORT int readLockTimeoutMs();
/// For tests: a shorter timeout.
KRITALIBKIS_EXPORT void setReadLockTimeoutMs(int ms);

/// Source pixels reaching one output pixel, at most: (ceil(w / outW) + 1) * (ceil(h / outH) + 1).
KRITALIBKIS_EXPORT quint64 sourcePixelsPerOutputPixel(const QSize &source, const QSize &output);

}

#endif
