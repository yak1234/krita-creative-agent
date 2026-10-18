/*
 *  SPDX-FileCopyrightText: 2025 Dmitry Kazakov <dimula73@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISSURFACECOLORIMETRYICCUTILS_H
#define KISSURFACECOLORIMETRYICCUTILS_H

#include "KisSurfaceColorimetry.h"
#include <KoColorProfileConstants.h>
#include <KoColorProfileQuery.h>

namespace KisSurfaceColorimetry
{
    using namespace KoColorimetryUtils;

    KRITASURFACECOLORMANAGEMENTAPI_EXPORT
    ColorPrimaries namedPrimariesToPigmentPrimaries(NamedPrimaries primaries);

    KRITASURFACECOLORMANAGEMENTAPI_EXPORT
    TransferCharacteristics namedTransferFunctionToPigmentTransferFunction(NamedTransferFunction transfer);

    KRITASURFACECOLORMANAGEMENTAPI_EXPORT
    KoColorProfileQuery colorSpaceToRequest(ColorSpace cs);
}

#endif /* KISSURFACECOLORIMETRYICCUTILS_H */
