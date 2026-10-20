/*
 * SPDX-FileCopyrightText: 2025 Krita Developers
 * SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Ported from Krita-Revamp (10zindraws / Tenzin Rangdol, GPL-3.0), commits b908ad5 and 681ef9f. See AGENT-FORK.md,
 * "Ported from Krita-Revamp: preset persistence".
 */
#ifndef KIS_PAINTOP_PRESET_SESSION_STORAGE_H
#define KIS_PAINTOP_PRESET_SESSION_STORAGE_H

#include <QObject>
#include <QScopedPointer>
#include <QString>

#include "kritaui_export.h"
#include "kis_types.h"

class QTimer;

/**
 * @brief Stores brush preset tweaks persistently across Krita sessions
 *
 * This class manages the storage and retrieval of user modifications to brush
 * presets. When users tweak brush settings, those changes are saved to a
 * configuration file that persists across Krita restarts.
 *
 * The original preset settings remain intact on disk - this only stores the
 * modifications. When the user presses "Reload the brush preset" or saves the
 * preset, the tweaks for that preset are cleared and the saved version is the
 * baseline again.
 *
 * Krita Agent changes to Revamp's version:
 *  - The file is "presetTweaksrc" in the build's own settings folder (KisAppIdentity), never stock Krita's.
 *  - Only the artist's tweaks are stored. Two guards, because the plugin's flows (paint passes, set_brush,
 *    configure_brush, the eraser toggles) mostly run outside any agent move and never call setAgentActive:
 *    (1) saveTweaks() and loadTweaks() do nothing while an agent move, an asynchronous stroke job or the script's
 *    agent switch is open on a document (KisAgentHooks::agentWorkOpen());
 *    (2) a preset a script changed is marked (markScriptChanged(), called before the change by every libkis View
 *    brush setter and by Preset.fromXML): it is not saved while the settings differ from what they were before the
 *    script's first change. The mark ends when the settings are back as they were (restore_brush), when the stored
 *    tweaks replace them, or on Reload and Save. A script selecting a preset (ScriptSelection) gets it as saved.
 *    loadTweaks() also never overwrites a preset that is dirty: newer state in memory wins.
 *  - The file is written a moment after the last change (a slider drag changes the preset many times a second), and
 *    at once by sync(), clearTweaks() and on quit.
 */
class KRITAUI_EXPORT KisPaintOpPresetSessionStorage : public QObject
{
    Q_OBJECT

public:
    /**
     * @return the singleton instance, storing in configFileName()
     */
    static KisPaintOpPresetSessionStorage *instance();

    /**
     * @return the name of the config file as KConfig resolves it ("presetTweaksrc", with the build's settings folder
     * before it when it has its own identity)
     */
    static QString defaultConfigFileName();

    /**
     * @param configFileName a KConfig file name (resolved against the generic config location); the default is the
     * singleton's. Tests give their own.
     */
    explicit KisPaintOpPresetSessionStorage(const QString &configFileName = defaultConfigFileName());
    ~KisPaintOpPresetSessionStorage() override;

    /// The full path of the file this storage writes.
    QString filePath() const;

    /**
     * Save the current state of a preset's settings to session storage.
     * This is called whenever preset settings are modified by the artist.
     *
     * @param preset The preset whose current settings should be saved
     * @return true if saved; false if there was nothing to save it under (a preset not in the database yet), an
     * agent was working, or a script had changed the preset (see the class comment)
     */
    bool saveTweaks(KisPaintOpPresetSP preset);

    /**
     * Load previously saved tweaks for a preset.
     * This is called when switching to a preset to restore any saved tweaks.
     *
     * @param preset The preset to load tweaks for
     * @return true if tweaks were found and loaded, false otherwise
     */
    bool loadTweaks(KisPaintOpPresetSP preset);

    /**
     * Check if a preset has any saved tweaks.
     *
     * @param preset The preset to check
     * @return true if there are saved tweaks for this preset
     */
    bool hasTweaks(KisPaintOpPresetSP preset) const;

    /**
     * Clear saved tweaks for a preset.
     * This is called when the user presses "Reload the brush preset" or
     * when a preset is saved/overwritten.
     *
     * @param preset The preset whose tweaks should be cleared
     */
    void clearTweaks(KisPaintOpPresetSP preset);

    /**
     * Krita Agent: \p preset was changed by a script (not by the artist): its in-memory settings are not the artist's
     * tweak, so saveTweaks() refuses it until its tweaks are cleared or loaded. GUI thread.
     */
    void markScriptChanged(KisPaintOpPresetSP preset);
    bool isScriptChanged(KisPaintOpPresetSP preset) const;

    /// A script is selecting a brush preset (View.setCurrentBrushPreset): loadTweaks() loads nothing until the end, so
    /// the script gets the preset as saved. Nests. Use ScriptSelection.
    void beginScriptSelection();
    void endScriptSelection();
    class ScriptSelection
    {
    public:
        explicit ScriptSelection(KisPaintOpPresetSessionStorage *storage) : m_storage(storage) { m_storage->beginScriptSelection(); }
        ~ScriptSelection() { m_storage->endScriptSelection(); }
    private:
        KisPaintOpPresetSessionStorage *m_storage;
    };

    /**
     * Force syncing the configuration to disk.
     */
    void sync();

    /**
     * The key of a preset's group in the config file ("Preset_<resourceId>_<md5>": the resource id and the MD5 of
     * the saved file, so a preset changed on disk starts without the old tweaks). Empty for a preset not in the
     * database.
     */
    QString tweakKey(KisPaintOpPresetSP preset) const;

Q_SIGNALS:
    /**
     * Emitted when preset tweaks are saved.
     * This signal is used by components that need to update when brush
     * settings are modified (like stroke preview cache invalidation).
     *
     * @param presetName The name of the preset whose tweaks were saved
     */
    void sigTweaksSaved(const QString &presetName);

    /**
     * Emitted when preset tweaks are cleared (preset reloaded to defaults).
     *
     * @param presetName The name of the preset whose tweaks were cleared
     */
    void sigTweaksCleared(const QString &presetName);

private:
    KisPaintOpPresetSessionStorage(const KisPaintOpPresetSessionStorage &) = delete;
    KisPaintOpPresetSessionStorage &operator=(const KisPaintOpPresetSessionStorage &) = delete;

    void scheduleSync();

    struct Private;
    const QScopedPointer<Private> m_d;
};

#endif // KIS_PAINTOP_PRESET_SESSION_STORAGE_H
