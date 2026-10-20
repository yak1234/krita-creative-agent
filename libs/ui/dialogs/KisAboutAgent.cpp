/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisAboutAgent.h"

#include <QFile>
#include <QRegularExpression>
#include <QTextStream>

#include <KLocalizedString>
#include <KritaVersionWrapper.h>

#include <KisAppIdentity.h>
#include <KoResourcePaths.h>

namespace
{
QString readText(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return QString();
    }
    return QTextStream(&file).readAll();
}
}

QString KisAboutAgent::recordValue(const QString &record, const QString &key)
{
    const QRegularExpression line(QStringLiteral("^%1:[ \\t]*(.*)$").arg(QRegularExpression::escape(key)),
                                  QRegularExpression::MultilineOption);
    const QRegularExpressionMatch match = line.match(record);
    return match.hasMatch() ? match.captured(1).trimmed() : QString();
}

QString KisAboutAgent::windowTitle()
{
    if (KisAppIdentity::settingsFolder().isEmpty()) {
        return QString();
    }
    return i18n("About %1", KisAppIdentity::displayName());
}

QString KisAboutAgent::licenseHtml()
{
    if (KisAppIdentity::settingsFolder().isEmpty()) {
        return QString();
    }
    // <root>/share is Contents/Resources in a packaged app, the install's share folder otherwise.
    return licenseHtmlFromRecord(readText(KoResourcePaths::getApplicationRoot() + QStringLiteral("/share/BUILD.txt")));
}

QString KisAboutAgent::licenseHtmlFromRecord(const QString &record)
{
    if (KisAppIdentity::settingsFolder().isEmpty()) {
        return QString();
    }
    const QString publicCommit = recordValue(record, QStringLiteral("public commit"));
    const QString buildCommit = recordValue(record, QStringLiteral("build commit"));
    const QString source = recordValue(record, QStringLiteral("source"));
    const QString notes = recordValue(record, QStringLiteral("notes"));
    const bool published = !publicCommit.isEmpty() && !publicCommit.startsWith(QStringLiteral("not published"));

    QString html = i18n("<h1 align=\"center\"><b>%1</b></h1>", KisAppIdentity::displayName().toHtmlEscaped());
    html += i18n("<p>%1 is a fork of Krita with the Creative Agent built in. This build is <b>%2</b>.</p>",
                 KisAppIdentity::displayName().toHtmlEscaped(),
                 KritaVersionWrapper::versionString(true).toHtmlEscaped());
    html += i18n("<p>It is free software, released under the GNU General Public License, version 3 or any later "
                 "version. It is a combined work: Krita is GPL-2.0-or-later (its libraries LGPL-2.0-or-later), the "
                 "Creative Agent is GPL-3.0, and the whole is distributed under the GPL-3.0-or-later. "
                 "There is no warranty.</p>");
    if (!buildCommit.isEmpty() && !source.isEmpty()) {
        const QString commit = published ? publicCommit : buildCommit;
        html += i18n("<p><b>Corresponding source:</b> commit <b>%1</b> of <a href=\"%2\">%2</a>%3.</p>",
                     commit.toHtmlEscaped(), source.toHtmlEscaped(),
                     published ? QString() : i18n(" (not published yet)"));
        if (!notes.isEmpty() && notes != QStringLiteral("none")) {
            html += i18n("<p>This build: %1.</p>", notes.toHtmlEscaped());
        }
    } else {
        html += i18n("<p><b>Corresponding source:</b> the Krita Agent git repository, at the commit named in the version "
                     "above. A packaged app names the exact commit and the address of the repository here (this build "
                     "has no Resources/BUILD.txt).</p>");
    }
    html += i18n("<p>The licence texts and the notices of every component are in the application's "
                 "<i>Contents/Resources/LICENSES</i> folder (README.txt and THIRD-PARTY-NOTICES.txt).</p><hr/>");
    return html;
}
