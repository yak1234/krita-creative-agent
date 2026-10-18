/*
 *  SPDX-FileCopyrightText: 2026 Wolthera van Hövell tot Westerflier <griffinvalley@gmail.com>
 *
 * SPDX-License-Identifier: LGPL-2.1-or-later
 */
#ifndef LCMSPREDFINEDPIPELINEFUNCTIONS_H
#define LCMSPREDFINEDPIPELINEFUNCTIONS_H

#include <lcms2.h>
#include <KoColorProfileConstants.h>

/**
 * @brief The LcmsPredfinedPipelineFunctions class
 * This class defines static functions to help create
 * ICC profiles with LCMS.
 *
 *
 */
class LcmsPredefinedPipelineFunctions
{
public:

/******************
 * Rec2100 PQ dummy functions.
 * PQ cannot be represented correctly in ICC due scaling issues. Therefore, we
 * create a pipeline that's good enough to represent the data in a pinch,
 * but it is combined with cicp values in the profile.
 *****************/

    static bool setPerceptualQuantizerAToBDummyPipeline(cmsHPROFILE iccProfile, cmsTagSignature tag, ColorPrimaries primaries, double diffuseWhiteNits = 80.0);
    static bool setPerceptualQuantizerBToADummyPipeline(cmsHPROFILE iccProfile, cmsTagSignature tag, ColorPrimaries primaries, double diffuseWhiteNits = 80.0);
    /**
     * @brief setDiffuseWhitePerceptualQuantizer
     * This adds a dictionary with an CRWL entry to the profile.
     * @return whether it was successfully written.
     */
    static bool setDiffuseWhitePerceptualQuantizer(cmsHPROFILE iccProfile, double diffuseWhiteNits = 80.0);

};

#endif // LCMSPREDEFINEDPIPELINEFUNCTIONS_H
