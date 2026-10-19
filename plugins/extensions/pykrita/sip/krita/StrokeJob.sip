// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: LGPL-2.0-or-later
class StrokeJob : QObject
{
%TypeHeaderCode
#include "StrokeJob.h"
%End
    StrokeJob(const StrokeJob & __0);
public:
    virtual ~StrokeJob();
public Q_SLOTS:
    QString state() const;
    int strokesDone() const;
    int strokesTotal() const;
    double progress() const;
    QRect changedRect() const;
    QString errorString() const;
    QString name() const;
    int elapsedMs() const;
    QMap<QString, QVariant> status() const;
    bool wait(int timeoutMs = -1) /ReleaseGIL/;
    bool cancel();
Q_SIGNALS:
    void finished(const QString &state);
    void progressChanged(int done, int total);
private:
};
