/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISTEMPORARYHOMEUITEST_H
#define KISTEMPORARYHOMEUITEST_H

#include <QApplication>
#include <QClipboard>
#include <QFile>
#include <QGuiApplication>
#include <QMimeData>

#include "KisTemporaryHomeTest.h"

namespace KisTemporaryHomeTest
{
/**
 * Points fontconfig at one font in the temporary home (DejaVu Sans from the source tree), unless FONTCONFIG_FILE is
 * set. A new home has no resource database, and building one makes Krita render a sample of every installed font;
 * with the system's fonts that crashes in KoSvgTextShape (seen on macOS, October 2026), and the test should not
 * depend on the fonts installed anyway.
 */
inline void useOneFont(const QString &home)
{
    if (!qgetenv("FONTCONFIG_FILE").isEmpty()) return;
    const QString fonts = home + QStringLiteral("/test-fonts");
    QDir().mkpath(fonts);
    QFile::copy(QStringLiteral(SYSTEM_RESOURCES_DATA_DIR "../../libs/flake/tests/data/fonts/DejaVuSans.ttf"),
                fonts + QStringLiteral("/DejaVuSans.ttf"));
    QFile config(home + QStringLiteral("/test-fonts.conf"));
    if (!config.open(QIODevice::WriteOnly)) return;
    config.write(QStringLiteral("<?xml version=\"1.0\"?>\n<!DOCTYPE fontconfig SYSTEM \"fonts.dtd\">\n<fontconfig>\n"
                                "  <dir>%1</dir>\n  <cachedir>%2</cachedir>\n</fontconfig>\n")
                     .arg(fonts, home + QStringLiteral("/test-fonts-cache"))
                     .toUtf8());
    config.close();
    qputenv("FONTCONFIG_FILE", QFile::encodeName(config.fileName()));
}
}

/**
 * KISTEST_MAIN for tests that need Krita's resources (include it after testui.h, which defines registerResources()),
 * run in a temporary home as KIS_TEMPORARY_HOME_TEST_MAIN does: KISTEST_MAIN alone creates the resource database and
 * copies resources under the user's real home (~/.qttest in Qt's test mode); this one starts the test again with HOME
 * and CFFIXED_USER_HOME in a new temporary folder, refuses to run if the standard paths still point outside it, and
 * removes the folder when done. Fontconfig sees one font, DejaVu Sans (see useOneFont()).
 *
 * Windows never show on screen: QT_QPA_PLATFORM defaults to "offscreen" (set it to override). Offscreen has no
 * clipboard data until some is set, and Krita's clipboard reads it while a main window is built, so the main sets an
 * empty one; offscreen's clipboard lives in the test process.
 */
#define KISTEST_TEMPORARY_HOME_MAIN(TestObject)                                                                        \
    int main(int argc, char *argv[])                                                                                   \
    {                                                                                                                  \
        const QByteArray home = qgetenv("KIS_TEMPORARY_TEST_HOME");                                                    \
        if (home.isEmpty() || qgetenv("HOME") != home) {                                                               \
            return KisTemporaryHomeTest::startInTemporaryHome(argv);                                                   \
        }                                                                                                              \
        KisTemporaryHomeTest::useOneFont(QString::fromLocal8Bit(home));                                                \
        if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {                                                          \
            qputenv("QT_QPA_PLATFORM", "offscreen");                                                                   \
        }                                                                                                              \
        qputenv("LANGUAGE", "en");                                                                                     \
        QLocale::setDefault(QLocale(QLocale::English, QLocale::UnitedStates));                                         \
        qputenv("QT_LOGGING_RULES", "");                                                                               \
        qputenv("EXTRA_RESOURCE_DIRS", QByteArray(KRITA_RESOURCE_DIRS_FOR_TESTS));                                     \
        qputenv("KRITA_PLUGIN_PATH", QByteArray(KRITA_PLUGINS_DIR_FOR_TESTS));                                         \
        QStandardPaths::setTestModeEnabled(true);                                                                      \
        KisSynchronizedConnectionBase::setAutoModeForUnittestsEnabled(true);                                           \
        int result = 1;                                                                                                \
        {                                                                                                              \
            QApplication app(argc, argv);                                                                              \
            app.setAttribute(Qt::AA_Use96Dpi, true);                                                                   \
            if (QGuiApplication::platformName() == QLatin1String("offscreen")) {                                       \
                /* Krita's clipboard reads the system clipboard's data, which offscreen has none of until set; */      \
                /* offscreen keeps it in this process, so the user's clipboard is never touched. */                    \
                QApplication::clipboard()->setMimeData(new QMimeData());                                               \
            }                                                                                                          \
            const QString homePath = QString::fromLocal8Bit(home);                                                     \
            const QList<QStandardPaths::StandardLocation> locations = {QStandardPaths::GenericConfigLocation,          \
                                                                       QStandardPaths::GenericDataLocation,            \
                                                                       QStandardPaths::GenericCacheLocation,           \
                                                                       QStandardPaths::AppDataLocation};               \
            bool contained = QDir::cleanPath(QDir::homePath()) == QDir::cleanPath(homePath);                           \
            for (QStandardPaths::StandardLocation location : locations) {                                              \
                contained = contained                                                                                  \
                    && KisTemporaryHomeTest::isInside(QStandardPaths::writableLocation(location), homePath);           \
            }                                                                                                          \
            if (!contained) {                                                                                          \
                fprintf(stderr, "Standard paths are not inside the temporary home %s: refusing to run\n",             \
                        home.constData());                                                                             \
            } else {                                                                                                   \
                registerResources();                                                                                   \
                TestObject test;                                                                                       \
                result = QTest::qExec(&test, argc, argv);                                                              \
            }                                                                                                          \
        }                                                                                                              \
        QDir(QString::fromLocal8Bit(home)).removeRecursively();                                                        \
        return result;                                                                                                 \
    }

/// The name this main had on agent/undo: the same main.
#define KIS_OFFSCREEN_UI_TEST_MAIN(TestObject) KISTEST_TEMPORARY_HOME_MAIN(TestObject)

#endif // KISTEMPORARYHOMEUITEST_H
