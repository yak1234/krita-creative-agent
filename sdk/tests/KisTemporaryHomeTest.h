/*
 *  SPDX-FileCopyrightText: 2026 Krita Agent contributors
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef KISTEMPORARYHOMETEST_H
#define KISTEMPORARYHOMETEST_H

#include <QByteArray>
#include <QCoreApplication>
#include <QDir>
#include <QStandardPaths>
#include <QTest>
#include <QtGlobal>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>

/**
 * A test main that runs the test with a temporary, empty home folder, so the test never reads or writes the user's
 * settings, data, caches or autosaves (not even ~/.qttest).
 *
 * On macOS QStandardPaths asks Foundation, which ignores $HOME: CFFIXED_USER_HOME moves it, but only when set before
 * the process starts. So the test starts itself again with HOME and CFFIXED_USER_HOME set to a new temporary folder,
 * removes that folder when done, and refuses to run if the standard paths still point outside it.
 */
namespace KisTemporaryHomeTest
{
inline bool isInside(const QString &path, const QString &folder)
{
    return QDir::cleanPath(path).startsWith(QDir::cleanPath(folder) + QLatin1Char('/'));
}

inline int startInTemporaryHome(char **argv)
{
    QByteArray tmp = qgetenv("TMPDIR");
    if (tmp.isEmpty()) {
        tmp = "/tmp";
    }
    QByteArray pattern = tmp + "/kis-test-home-XXXXXX";
    char *home = mkdtemp(pattern.data());
    if (!home) {
        perror("mkdtemp");
        return 1;
    }
    setenv("HOME", home, 1);
    setenv("CFFIXED_USER_HOME", home, 1);
    setenv("KIS_TEMPORARY_TEST_HOME", home, 1);
    execv(argv[0], argv);
    perror("execv");
    return 1;
}
}

#define KIS_TEMPORARY_HOME_TEST_MAIN(TestObject)                                                                     \
    int main(int argc, char *argv[])                                                                                   \
    {                                                                                                                  \
        const QByteArray home = qgetenv("KIS_TEMPORARY_TEST_HOME");                                                    \
        if (home.isEmpty() || qgetenv("HOME") != home) {                                                               \
            return KisTemporaryHomeTest::startInTemporaryHome(argv);                                                   \
        }                                                                                                              \
        QStandardPaths::setTestModeEnabled(true);                                                                      \
        int result = 1;                                                                                                \
        {                                                                                                              \
            QCoreApplication app(argc, argv);                                                                          \
            QCoreApplication::setApplicationName(QStringLiteral("krita"));                                             \
            const QString homePath = QString::fromLocal8Bit(home);                                                     \
            const QList<QStandardPaths::StandardLocation> locations = {QStandardPaths::GenericConfigLocation,          \
                                                                       QStandardPaths::GenericDataLocation,            \
                                                                       QStandardPaths::GenericCacheLocation};          \
            bool contained = QDir::cleanPath(QDir::homePath()) == QDir::cleanPath(homePath);                           \
            for (QStandardPaths::StandardLocation location : locations) {                                              \
                contained = contained                                                                                  \
                    && KisTemporaryHomeTest::isInside(QStandardPaths::writableLocation(location), homePath);           \
            }                                                                                                          \
            if (!contained) {                                                                                          \
                fprintf(stderr, "Standard paths are not inside the temporary home %s: refusing to run\n",             \
                        home.constData());                                                                             \
            } else {                                                                                                   \
                TestObject test;                                                                                       \
                result = QTest::qExec(&test, argc, argv);                                                              \
            }                                                                                                          \
        }                                                                                                              \
        QDir(QString::fromLocal8Bit(home)).removeRecursively();                                                        \
        return result;                                                                                                 \
    }

#endif // KISTEMPORARYHOMETEST_H
