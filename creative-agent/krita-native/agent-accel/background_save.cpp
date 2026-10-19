/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "background_save.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>

#include <cerrno>
#include <cstdio>
#include <cstring>

namespace AgentSave
{
static QString prefix(const QString &target)
{
    return QStringLiteral(".") + QFileInfo(target).fileName() + QStringLiteral(".agent-save-");
}

QString temporaryPath(const QString &target, int job)
{
    const QFileInfo info(target);
    const QString suffix = info.suffix().isEmpty() ? QString() : QStringLiteral(".") + info.suffix();
    return info.dir().filePath(prefix(target) + QString::number(job) + suffix);
}

int removeStale(const QString &target)
{
    const QFileInfo info(target);
    QDir folder = info.dir();
    int removed = 0;
    const QStringList found = folder.entryList(QStringList{prefix(target) + QStringLiteral("*")}, QDir::Files | QDir::Hidden);
    for (const QString &name : found) {
        if (name != info.fileName() && folder.remove(name)) removed++;
    }
    return removed;
}

bool complete(const QString &temporary, const QString &target, bool exported, const QString &exportError, QString *error)
{
    QString why;
    if (!exported) {
        why = exportError.isEmpty() ? QStringLiteral("Krita could not write the painting.") : exportError;
    } else if (!QFileInfo(temporary).isFile()) {
        why = QStringLiteral("Krita reported the save finished, but its file is missing.");
    } else if (std::rename(QFile::encodeName(temporary).constData(), QFile::encodeName(target).constData()) != 0) {
        // POSIX rename replaces the target in one step on the same disk: on failure the target is untouched.
        why = QStringLiteral("Could not replace the painting with the new save: %1").arg(QString::fromLocal8Bit(std::strerror(errno)));
    } else {
        if (error) error->clear();
        return true;
    }
    QFile::remove(temporary);
    if (error) *error = why;
    return false;
}

QString statusJson(const Job &job)
{
    static const char *const states[] = {"running", "done", "failed"};
    return QString::fromUtf8(QJsonDocument(QJsonObject{
        {"job", job.id}, {"state", QLatin1String(states[job.state])}, {"ms", qint64(job.ms)}, {"startMs", qint64(job.startMs)},
        {"error", job.error}, {"file", job.file}, {"clean", job.clean}}).toJson(QJsonDocument::Compact));
}
}
