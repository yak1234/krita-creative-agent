/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTDOCUMENTCHANGES_H
#define TESTDOCUMENTCHANGES_H

#include <QObject>

/// Document.revision(), changedRect() and the change source (krita-fork 2.2).
class TestDocumentChanges : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testRevisionStartsPositiveAndStaysWithoutChanges();
    void testRevisionIncreasesOnPixelChange();
    void testChangedRectIsExactlyTheChangedArea();
    void testChangedRectUnitesAreasSinceRevision();
    void testChangedRectIsWholeImageWhenHistoryIsGone();
    void testLongStrokeKeepsItsHistory();
    void testResizeChangesWholeImage();
    void testWrappersShareTheReport();
    void testSourceIsAgentWhileActive();
    void testAgentWorkNests();
    void testSourceIsTakenWhenTheChangeIsRequested();
    void testArtistRequestStaysArtistWhenAgentStartsLater();
    void testNodePixelsCarryTheSource();
    void testLevelOfDetailReportsAreInImagePixels();
    void benchmarkRevisionAgainstHash();
    void benchmarkDirtyRequests();
};

#endif // TESTDOCUMENTCHANGES_H
