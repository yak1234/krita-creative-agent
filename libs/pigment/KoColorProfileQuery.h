/*
 *  SPDX-FileCopyrightText: 2026 Wolthera van Hövell tot Westerflier <griffinvalley@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KOCOLORPROFILEQUERY_H
#define KOCOLORPROFILEQUERY_H

#include <KoColorimetryUtils.h>
#include <KoColorProfileConstants.h>
#include <QDebug>

/**
 * @brief The KoColorProfileQuery struct
 *
 * This is a struct that represents the characteristics of
 * a KoColorProfile for either search or generation.
 */
struct KoColorProfileQuery {
    KoColorProfileQuery(ColorPrimaries primaries = PRIMARIES_UNSPECIFIED,
                        TransferCharacteristics transfer = TRC_UNSPECIFIED,
                        std::optional<qreal> hdrReferenceWhite = std::nullopt)
        : primaries(primaries)
        , transfer(transfer)
        , hdrReferenceWhite(hdrReferenceWhite)
    {}

    KoColorProfileQuery(const KoColorProfileQuery &rhs) = default;
    KoColorProfileQuery(KoColorProfileQuery &&rhs) = default;

    KoColorProfileQuery& operator=(const KoColorProfileQuery&rhs) = default;
    KoColorProfileQuery& operator=(KoColorProfileQuery &&rhs) = default;

    KoColorimetryUtils::xy whitePoint {0.0, 0.0}; /// The desired white point of the profile.
    QList<KoColorimetryUtils::xy> rgbColorants; /// Rgb Primaries of the profile. When empty, this is a query for a greyscale profile.

    ColorPrimaries primaries; /// CICP-compatible enum value representing the white point and primaries.
    TransferCharacteristics transfer; /// CICP-compatible enum value representing the transfer function.

    std::optional<double> hdrReferenceWhite; /// Used for PQ profiles.

    inline bool isValid() const {
        return isGrayscale() || isRgb();
    }

    inline bool isGrayscale() const {
        return transfer != TRC_UNSPECIFIED
            && rgbColorants.isEmpty()
            && primaries == PRIMARIES_UNSPECIFIED
            && !(whitePoint == KoColorimetryUtils::xy{0.0, 0.0});
    }

    inline bool isRgb() const {
        return transfer != TRC_UNSPECIFIED
            && (primaries != PRIMARIES_UNSPECIFIED
                || (!rgbColorants.isEmpty() && !(whitePoint == KoColorimetryUtils::xy{0.0, 0.0})));
    }

    inline bool operator==(const KoColorProfileQuery &rhs) const {
        return whitePoint == rhs.whitePoint
            && rgbColorants == rhs.rgbColorants
            && primaries == rhs.primaries
            && transfer == rhs.transfer
            && hdrReferenceWhite == rhs.hdrReferenceWhite;
    }

    inline bool operator!=(const KoColorProfileQuery &rhs) const {
        return !(*this == rhs);
    }

};

inline QDebug operator<<(QDebug debug, const KoColorProfileQuery &value) {
    QDebugStateSaver saver(debug);
    debug.nospace() << "KoColorProfileQuery("
                    << " WhitePoint:" << value.whitePoint
                    << " rgbColorants:" << value.rgbColorants
                    << " primariesType:" << value.primaries
                    << " transferFunction:" << value.transfer
                    << " isGreyscale:" << value.isGrayscale()
                    << " isRgb:" << value.isRgb()
                    << " isValid:" << value.isValid()
                    << ")";
    return debug;
}

#endif // KOCOLORPROFILEQUERY_H
