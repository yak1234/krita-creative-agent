/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTDOCUMENTFEATUREQUERIES_H
#define TESTDOCUMENTFEATUREQUERIES_H

#include <QObject>

/// Spatial questions about the features (krita-fork 6.4): which features are at a point, overlap or touch, and
/// selections combined from features by name.
class TestDocumentFeatureQueries : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testFeaturesAt();
    void testBadInputIsRefused();
    void testFeaturesOverlapping();
    void testFeaturesTouching();
    void testSelectionByName();
    void testSelectionErrorsReturnNone();
    void testSelectionIsAFreshMaskAndFeaturesAreUnchanged();
    void testQueriesChangeNothing();
    void testQueriesFollowEdits();
    void testQueriesFromAnotherThreadWhileFeaturesChange();
    void testThirtyFeaturesAtFullSize();
};

#endif // TESTDOCUMENTFEATUREQUERIES_H
