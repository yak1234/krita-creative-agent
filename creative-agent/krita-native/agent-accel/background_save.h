/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AGENT_BACKGROUND_SAVE_H
#define AGENT_BACKGROUND_SAVE_H

#include <QString>

/**
 * The file side of saveInBackground (agent_accel.h), apart from Krita so background_save_selftest.cpp runs it without
 * Krita. Krita writes the copy of the document to a temporary file beside the painting; only a finished, verified
 * copy replaces the painting, by one rename on the same disk, so the painting on disk is always either the previous
 * save or the new one, never a part-written file. Krita's own save on macOS writes the whole file to the system
 * temporary folder and then deletes the painting and copies it over (KisImportExportManager::doExportImpl: QSaveFile
 * is off on macOS), which loses the painting if the copy fails half-way.
 */
namespace AgentSave
{
/// Where job `job` writes before the rename: a hidden file beside `target` (the same disk, so the rename is atomic, and
/// the same folder, so file layers' relative paths stay right), with the target's suffix for Krita's file type.
QString temporaryPath(const QString &target, int job);

/// Remove what earlier jobs left beside `target` (a crash mid-save); never the target itself.
int removeStale(const QString &target);

/// The end of a job: when Krita's export of the temporary file succeeded, rename it over `target`; otherwise, or when
/// the rename fails, remove the temporary file and leave `target` as it was. Returns true only when `target` now holds
/// the new save; `error` says why not.
bool complete(const QString &temporary, const QString &target, bool exported, const QString &exportError, QString *error);

/// One job as saveStatus reports it.
struct Job {
    enum State { Running, Done, Failed };
    int id = 0;
    State state = Running;
    QString file;                 ///< the painting the job saves
    QString error;                ///< empty unless failed
    qint64 startMs = 0;           ///< what saveInBackground held Krita's main thread for (waiting, copying, starting)
    qint64 ms = 0;                ///< from the request to the end (or until now while running)
    bool clean = false;           ///< Krita's document was marked unmodified (nothing changed while it saved)
};

/// {"job", "state": "running" | "done" | "failed", "ms", "startMs", "error", "file", "clean"} as compact JSON.
QString statusJson(const Job &job);
}

#endif
