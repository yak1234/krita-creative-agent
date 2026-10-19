/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
// saveInBackground's file side (background_save.h) without Krita: build.sh builds and runs it after the helper, in a
// temporary folder it removes. Exits 1 on any difference.
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <cstdio>

#include "background_save.h"

static int failures = 0;

static void expect(bool ok, const char *what)
{
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

static void write(const QString &path, const QByteArray &bytes)
{
    QFile file(path);
    file.open(QIODevice::WriteOnly | QIODevice::Truncate);
    file.write(bytes);
}

static QByteArray read(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray("<missing>");
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTemporaryDir folder;                                // removed on exit
    const QString target = folder.filePath(QStringLiteral("painting.kra"));

    // The temporary file: hidden, beside the painting, the painting's type, one per job.
    const QString first = AgentSave::temporaryPath(target, 7);
    expect(QFileInfo(first).absolutePath() == QFileInfo(target).absolutePath(), "the temporary file is beside the painting");
    expect(QFileInfo(first).fileName().startsWith(QLatin1Char('.')), "the temporary file is hidden");
    expect(first.endsWith(QLatin1String(".kra")), "the temporary file keeps the painting's suffix");
    expect(first != AgentSave::temporaryPath(target, 8) && first != target, "each job has its own temporary file");

    // A finished export replaces the painting.
    write(target, "previous");
    write(first, "new");
    QString error;
    expect(AgentSave::complete(first, target, true, QString(), &error), "a finished export is saved");
    expect(read(target) == "new" && error.isEmpty(), "the painting holds the new save");
    expect(!QFile::exists(first), "the temporary file is gone after the rename");

    // A failed export leaves the previous painting and removes the part-written file.
    const QString second = AgentSave::temporaryPath(target, 8);
    write(second, "half");
    expect(!AgentSave::complete(second, target, false, QStringLiteral("disk full"), &error), "a failed export is never saved");
    expect(read(target) == "new", "the previous painting is intact after a failed export");
    expect(!QFile::exists(second), "the part-written file is removed");
    expect(error.contains(QLatin1String("disk full")), "the export's error is reported");

    // An export Krita called finished whose file is missing: failed, painting intact.
    expect(!AgentSave::complete(AgentSave::temporaryPath(target, 9), target, true, QString(), &error), "a missing temporary file is not saved");
    expect(read(target) == "new" && !error.isEmpty(), "the painting is intact and the failure explained");

    // The rename itself fails (the painting's folder is gone): failed, and the temporary file removed.
    const QString elsewhere = folder.filePath(QStringLiteral("gone/painting.kra"));
    const QString third = AgentSave::temporaryPath(target, 10);
    write(third, "orphan");
    expect(!AgentSave::complete(third, elsewhere, true, QString(), &error), "a failed rename is not saved");
    expect(!QFile::exists(third) && !QFile::exists(elsewhere), "nothing is left after a failed rename");

    // Leftovers from a crash are removed; the painting and other files stay.
    write(AgentSave::temporaryPath(target, 11), "crash");
    write(AgentSave::temporaryPath(target, 12), "crash");
    write(folder.filePath(QStringLiteral("other.kra")), "other");
    write(AgentSave::temporaryPath(folder.filePath(QStringLiteral("other.kra")), 13), "other's");
    expect(AgentSave::removeStale(target) == 2, "both leftovers of this painting are removed");
    expect(read(target) == "new" && QFile::exists(folder.filePath(QStringLiteral("other.kra"))), "the painting and other files stay");
    expect(QFile::exists(AgentSave::temporaryPath(folder.filePath(QStringLiteral("other.kra")), 13)), "another painting's job is left alone");

    // saveStatus's JSON.
    AgentSave::Job job;
    job.id = 4; job.file = target; job.startMs = 120; job.ms = 5400; job.state = AgentSave::Job::Done; job.clean = true;
    QJsonObject done = QJsonDocument::fromJson(AgentSave::statusJson(job).toUtf8()).object();
    expect(done.value("job").toInt() == 4 && done.value("state").toString() == "done" && done.value("ms").toInt() == 5400
           && done.value("startMs").toInt() == 120 && done.value("file").toString() == target && done.value("error").toString().isEmpty()
           && done.value("clean").toBool(), "a finished job's status");
    job.state = AgentSave::Job::Failed; job.error = QStringLiteral("disk full"); job.clean = false;
    QJsonObject failed = QJsonDocument::fromJson(AgentSave::statusJson(job).toUtf8()).object();
    expect(failed.value("state").toString() == "failed" && failed.value("error").toString() == "disk full", "a failed job's status");
    job.state = AgentSave::Job::Running; job.error.clear();
    expect(QJsonDocument::fromJson(AgentSave::statusJson(job).toUtf8()).object().value("state").toString() == "running", "a running job's status");

    std::printf("%s: %d failure(s)\n", failures ? "FAILED" : "passed", failures);
    return failures ? 1 : 0;
}
