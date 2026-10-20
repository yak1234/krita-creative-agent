/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "TestPresetSessionStorage.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>
#include <testutil.h>

#include <QDir>
#include <QFile>
#include <QSignalSpy>
#include <QStandardPaths>

#include <KConfig>
#include <KConfigGroup>

#include <KisAgentHooks.h>
#include <KisAppIdentity.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPaintOpPresetSessionStorage.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>

namespace {

/// A preset as the database would hold it: the id and the MD5 of its saved file.
KisPaintOpPresetSP makePreset(int id, const QString &md5)
{
    KisPaintOpPresetSP preset(new KisPaintOpPreset(TestUtil::fetchDataFileLazy("autobrush_300px.kpp")));
    if (!preset->load(KisGlobalResourcesInterface::instance())) return KisPaintOpPresetSP();
    preset->setResourceId(id);
    preset->setMD5Sum(md5);
    preset->setDirty(false);
    return preset;
}

/// The groups of the file as a second reader sees them.
QStringList groupsOf(const QString &path)
{
    KConfig config(path, KConfig::SimpleConfig);
    return config.groupList();
}

bool s_agentWorks = false;
bool agentWorks()
{
    return s_agentWorks;
}

const char *kFile = "presetTweaksrc-test";

} // namespace

void TestPresetSessionStorage::init()
{
    s_agentWorks = false;
    KisAgentHooks::setAgentWorkProbe(&agentWorks);
}

void TestPresetSessionStorage::cleanup()
{
    KisAgentHooks::setAgentWorkProbe(nullptr);
    KisAppIdentity::setSettingsFolderForTesting(QString());
    QFile::remove(QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + "/" + kFile);
}

void TestPresetSessionStorage::testKeyIsResourceIdAndMd5()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "0123abcd");
    QVERIFY(preset);
    QCOMPARE(storage.tweakKey(preset), QString("Preset_7_0123abcd"));

    preset->setMD5Sum(QString());
    QCOMPARE(storage.tweakKey(preset), QString("Preset_7"));

    preset->setResourceId(-1);
    QVERIFY(storage.tweakKey(preset).isEmpty());
    QVERIFY(storage.tweakKey(KisPaintOpPresetSP()).isEmpty());
}

void TestPresetSessionStorage::testSaveLoadClear()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP tweaked = makePreset(7, "m1");
    QVERIFY(tweaked);
    const qreal original = tweaked->settings()->paintOpSize();
    tweaked->settings()->setPaintOpSize(original + 33);
    tweaked->settings()->setPaintOpFlow(0.25);

    QVERIFY(!storage.hasTweaks(tweaked));
    QVERIFY(storage.saveTweaks(tweaked));
    QVERIFY(storage.hasTweaks(tweaked));

    // The next session: the preset comes from its file again.
    KisPaintOpPresetSP fresh = makePreset(7, "m1");
    QVERIFY(fresh);
    QCOMPARE(fresh->settings()->paintOpSize(), original);
    QVERIFY(!fresh->isDirty());
    QVERIFY(storage.loadTweaks(fresh));
    QCOMPARE(fresh->settings()->paintOpSize(), original + 33);
    QCOMPARE(fresh->settings()->paintOpFlow(), 0.25);
    QVERIFY(fresh->isDirty());

    // Another preset is not touched
    KisPaintOpPresetSP other = makePreset(8, "m1");
    QVERIFY(other);
    QVERIFY(!storage.hasTweaks(other));
    QVERIFY(!storage.loadTweaks(other));
    QCOMPARE(other->settings()->paintOpSize(), original);

    // Reload (or Save) clears
    storage.clearTweaks(fresh);
    QVERIFY(!storage.hasTweaks(fresh));
    KisPaintOpPresetSP after = makePreset(7, "m1");
    QVERIFY(!storage.loadTweaks(after));
    QCOMPARE(after->settings()->paintOpSize(), original);
    QVERIFY(!after->isDirty());
    QVERIFY(groupsOf(storage.filePath()).isEmpty());
}

void TestPresetSessionStorage::testReloadFromStorageAndNewInstance()
{
    qreal original = 0;
    {
        KisPaintOpPresetSessionStorage storage(kFile);
        KisPaintOpPresetSP preset = makePreset(7, "m1");
        QVERIFY(preset);
        original = preset->settings()->paintOpSize();
        preset->settings()->setPaintOpSize(original + 5);
        QVERIFY(storage.saveTweaks(preset));
        storage.sync();
    }
    // A restart: a new storage on the same file
    KisPaintOpPresetSessionStorage again(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    QVERIFY(again.loadTweaks(preset));
    QCOMPARE(preset->settings()->paintOpSize(), original + 5);
}

void TestPresetSessionStorage::testSaveGivesTheNewMd5Nothing()
{
    // A preset saved under a new MD5 starts clean: the old tweaks are keyed by the old file.
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "old");
    QVERIFY(preset);
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 9);
    QVERIFY(storage.saveTweaks(preset));

    preset->setMD5Sum("new");
    QVERIFY(!storage.hasTweaks(preset));
    KisPaintOpPresetSP saved = makePreset(7, "new");
    QVERIFY(!storage.loadTweaks(saved));
}

void TestPresetSessionStorage::testClearRemovesEveryMd5OfTheResource()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "old");
    QVERIFY(preset);
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 9);
    QVERIFY(storage.saveTweaks(preset));
    KisPaintOpPresetSP neighbour = makePreset(71, "old"); // "Preset_71_..." is not "Preset_7_..."
    QVERIFY(neighbour);
    neighbour->settings()->setPaintOpSize(3);
    QVERIFY(storage.saveTweaks(neighbour));

    // Save as the dialog does: the file is written, so the preset has the new MD5 when the tweaks are cleared
    preset->setMD5Sum("new");
    storage.clearTweaks(preset);
    const QStringList groups = groupsOf(storage.filePath());
    QCOMPARE(groups, QStringList{"Preset_71_old"});
}

void TestPresetSessionStorage::testConfigFileIsInTheIdentityFolder()
{
    KisAppIdentity::setSettingsFolderForTesting(QStringLiteral("KritaAgentTest"));
    KisAppIdentity::initialize();
    QCOMPARE(KisPaintOpPresetSessionStorage::defaultConfigFileName(), QStringLiteral("KritaAgentTest/presetTweaksrc"));

    KisPaintOpPresetSessionStorage storage; // the build's own file
    const QString config = QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation);
    QCOMPARE(QDir::cleanPath(storage.filePath()), QDir::cleanPath(config + "/KritaAgentTest/presetTweaksrc"));

    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 1);
    QVERIFY(storage.saveTweaks(preset));
    storage.sync();
    QVERIFY(QFile::exists(config + "/KritaAgentTest/presetTweaksrc"));
    // Never stock Krita's folder
    QVERIFY(!QFile::exists(config + "/presetTweaksrc"));

    storage.clearTweaks(preset);
    QFile::remove(config + "/KritaAgentTest/presetTweaksrc");
}

void TestPresetSessionStorage::testUnsavedPresetHasNoTweaks()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(-1, "m1");
    QVERIFY(preset);
    preset->settings()->setPaintOpSize(5);
    QVERIFY(!storage.saveTweaks(preset));
    QVERIFY(!storage.saveTweaks(KisPaintOpPresetSP()));
    QVERIFY(!storage.hasTweaks(preset));
    QVERIFY(!storage.loadTweaks(preset));
    storage.clearTweaks(preset); // no crash
    QVERIFY(groupsOf(storage.filePath()).isEmpty());
}

void TestPresetSessionStorage::testRefusedWhileTheAgentWorks()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 12);

    s_agentWorks = true; // an agent move or job is open
    QVERIFY(!storage.saveTweaks(preset));
    QVERIFY(!storage.hasTweaks(preset));
    storage.sync();
    QVERIFY(groupsOf(storage.filePath()).isEmpty());

    s_agentWorks = false;
    QVERIFY(storage.saveTweaks(preset)); // the artist's own change is saved again
    QVERIFY(storage.hasTweaks(preset));
}

void TestPresetSessionStorage::testScriptChangedPresetIsNeverSaved()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    const QString original = preset->settings()->toXML();

    storage.markScriptChanged(preset); // View.setBrushSize, Preset.fromXML: before the change
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 40);
    QVERIFY(storage.isScriptChanged(preset));
    QVERIFY(!storage.saveTweaks(preset));
    QVERIFY(!storage.hasTweaks(preset));

    // Selecting the preset again with nothing stored leaves the script's values in it: the mark stays
    preset->setDirty(false);
    QVERIFY(!storage.loadTweaks(preset));
    QVERIFY(storage.isScriptChanged(preset));
    QVERIFY(!storage.saveTweaks(preset));

    // restore_brush puts the original settings back: the artist's changes are saved again
    preset->settings()->fromXML(original);
    QVERIFY(storage.saveTweaks(preset));
    QVERIFY(!storage.isScriptChanged(preset));

    // Reload / Save end the mark
    storage.markScriptChanged(preset);
    storage.clearTweaks(preset);
    QVERIFY(!storage.isScriptChanged(preset));

    // A preset outside the database is never marked
    KisPaintOpPresetSP unsaved = makePreset(-1, "m1");
    storage.markScriptChanged(unsaved);
    QVERIFY(!storage.isScriptChanged(unsaved));
}

void TestPresetSessionStorage::testStoredTweaksReplaceAScriptsLeftovers()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP artist = makePreset(7, "m1");
    QVERIFY(artist);
    const qreal original = artist->settings()->paintOpSize();
    artist->settings()->setPaintOpSize(original + 21);
    QVERIFY(storage.saveTweaks(artist));

    KisPaintOpPresetSP preset = makePreset(7, "m1");
    storage.markScriptChanged(preset);
    preset->settings()->setPaintOpSize(original + 99); // a script's leftover
    preset->setDirty(false);                           // (a selection that reloaded the file would be clean)
    QVERIFY(storage.loadTweaks(preset));               // the stored tweaks replace it, and end the mark
    QCOMPARE(preset->settings()->paintOpSize(), original + 21);
    QVERIFY(!storage.isScriptChanged(preset));
}

void TestPresetSessionStorage::testLoadNeverOverwritesNewerMemoryState()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP artist = makePreset(7, "m1");
    QVERIFY(artist);
    const qreal original = artist->settings()->paintOpSize();
    artist->settings()->setPaintOpSize(original + 21);
    QVERIFY(storage.saveTweaks(artist));

    KisPaintOpPresetSP dirty = makePreset(7, "m1");
    dirty->settings()->setPaintOpSize(original + 5);
    dirty->setDirty(true);
    QVERIFY(!storage.loadTweaks(dirty));
    QCOMPARE(dirty->settings()->paintOpSize(), original + 5);
}

void TestPresetSessionStorage::testTransientKeysAreNotStored()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    preset->settings()->setProperty("EraserMode", true);
    preset->settings()->setProperty("CompositeOp", "erase");
    preset->settings()->setPaintOpSize(preset->settings()->paintOpSize() + 1);
    QVERIFY(storage.saveTweaks(preset));
    storage.sync();
    KConfig config(storage.filePath(), KConfig::SimpleConfig);
    const QString xml = config.group(storage.tweakKey(preset)).readEntry("settings", QString());
    QVERIFY(!xml.isEmpty());
    QVERIFY(!xml.contains("name=\"EraserMode\""));
    QVERIFY(!xml.contains("name=\"CompositeOp\""));
}

void TestPresetSessionStorage::testAScriptSelectingAPresetGetsItAsSaved()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP artist = makePreset(7, "m1");
    QVERIFY(artist);
    const qreal original = artist->settings()->paintOpSize();
    artist->settings()->setPaintOpSize(original + 21);
    QVERIFY(storage.saveTweaks(artist));

    {
        KisPaintOpPresetSessionStorage::ScriptSelection selecting(&storage); // View.setCurrentBrushPreset
        KisPaintOpPresetSP preset = makePreset(7, "m1");
        QVERIFY(!storage.loadTweaks(preset));
        QCOMPARE(preset->settings()->paintOpSize(), original);
        {
            KisPaintOpPresetSessionStorage::ScriptSelection nested(&storage);
        }
        QVERIFY(!storage.loadTweaks(preset)); // still inside the outer one
    }
    s_agentWorks = true; // an agent move is open: nothing is loaded either
    KisPaintOpPresetSP during = makePreset(7, "m1");
    QVERIFY(!storage.loadTweaks(during));
    s_agentWorks = false;
    KisPaintOpPresetSP after = makePreset(7, "m1");
    QVERIFY(storage.loadTweaks(after));
    QCOMPARE(after->settings()->paintOpSize(), original + 21);
}

void TestPresetSessionStorage::testSignals()
{
    KisPaintOpPresetSessionStorage storage(kFile);
    KisPaintOpPresetSP preset = makePreset(7, "m1");
    QVERIFY(preset);
    QSignalSpy saved(&storage, &KisPaintOpPresetSessionStorage::sigTweaksSaved);
    QSignalSpy cleared(&storage, &KisPaintOpPresetSessionStorage::sigTweaksCleared);

    storage.clearTweaks(preset); // nothing to clear: no signal
    QCOMPARE(cleared.size(), 0);
    QVERIFY(storage.saveTweaks(preset));
    QCOMPARE(saved.size(), 1);
    QCOMPARE(saved[0][0].toString(), preset->name());
    storage.clearTweaks(preset);
    QCOMPARE(cleared.size(), 1);
}

KISTEST_TEMPORARY_HOME_MAIN(TestPresetSessionStorage)
