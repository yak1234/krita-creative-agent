/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef KISKRAFEATURESTEST_H
#define KISKRAFEATURESTEST_H

#include <QObject>

class KisKraFeaturesTest : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testRoundTrip();
    void testMaindocXmlLayout();
    void testNoFeaturesWritesNothing();
    void testNewerVersionLoadsWhatItKnows();
    void testUnreadableVersionIsSkipped();
    void testLoadMeasuresBoundsAndAreaKeepsMeanColor();
    void testDuplicateNamesAreRenamedOnLoad();
    void testBlankAndPaddedNamesOnLoad();
    void testSelectedDefaultPixelIsBoundedOnLoad();
    void testResavingANewerVersionWarns();
    void testMissingMaskIsSkipped();
    void testUnknownElementAndFilesAreIgnored();
};

#endif // KISKRAFEATURESTEST_H
