/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef TESTDOCUMENTFEATURES_H
#define TESTDOCUMENTFEATURES_H

#include <QObject>

class TestDocumentFeatures : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void testAddFeature();
    void testAddChangesNoPixelAndIsOneUndoStep();
    void testRemoveChangesNoPixelAndIsOneUndoStep();
    void testRenameIsOneUndoStepAndFeatureFollows();
    void testRejectedCallsChangeNothing();
    void testMaskIsCutToTheDocumentAndCopied();
    void testFeaturesSurviveSaveAndOpen();
    void testAddAndRenameInAgentMoveAreOneStep();
    void testWhitespaceNamesAreRejected();
    void testNamesAreTrimmed();
    void testInvertedSelectionGivesABoundedMask();
    void testTransientFeatureIsNoUndoStep();
    void testTransientFeatureIsNotSaved();
};

#endif // TESTDOCUMENTFEATURES_H
