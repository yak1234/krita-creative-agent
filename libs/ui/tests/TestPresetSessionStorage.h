/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef TESTPRESETSESSIONSTORAGE_H
#define TESTPRESETSESSIONSTORAGE_H

#include <QObject>

/// KisPaintOpPresetSessionStorage (ported from Krita-Revamp, krita-fork 3.1): the artist's brush tweaks persist.
class TestPresetSessionStorage : public QObject
{
    Q_OBJECT
private Q_SLOTS:
    void init();
    void cleanup();
    void testKeyIsResourceIdAndMd5();
    void testSaveLoadClear();
    void testReloadFromStorageAndNewInstance();
    void testSaveGivesTheNewMd5Nothing();
    void testClearRemovesEveryMd5OfTheResource();
    void testConfigFileIsInTheIdentityFolder();
    void testUnsavedPresetHasNoTweaks();
    void testRefusedWhileTheAgentWorks();
    void testScriptChangedPresetIsNeverSaved();
    void testStoredTweaksReplaceAScriptsLeftovers();
    void testLoadNeverOverwritesNewerMemoryState();
    void testTransientKeysAreNotStored();
    void testAScriptSelectingAPresetGetsItAsSaved();
    void testSignals();
};

#endif
