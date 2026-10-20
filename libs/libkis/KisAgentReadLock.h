/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef KIS_AGENT_READ_LOCK_H
#define KIS_AGENT_READ_LOCK_H

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QThread>

#include <kis_image.h>

/**
 * A read-only barrier lock on an image that never asks the artist's tool to end its stroke (krita-fork 2.3, 6.3).
 *
 * KisImage::barrierLock() and waitForDone() ask the open strokes to end: the artist's brush stroke, mid-drag, would be
 * cut, and the call can wait as long as the pen is down. tryBarrierLock(true) asks nobody, so it is retried until it
 * succeeds or the timeout passes, processing non-input events on the GUI thread between tries (a job may wait for
 * the GUI) and sleeping a millisecond.
 */
namespace KisAgentReadLock
{

/// Takes the lock for at most \p timeoutMs; returns whether the image is locked (the caller then calls image->unlock()).
inline bool tryLock(KisImageSP image, int timeoutMs)
{
    QElapsedTimer timer;
    timer.start();
    const bool guiThread = QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread();
    while (!image->tryBarrierLock(true)) {
        if (timer.elapsed() >= timeoutMs) return false;
        if (guiThread) {
            QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents);
        }
        QThread::msleep(1);
    }
    return true;
}

/// The lock held for a scope: `Scoped lock(image, 2000); if (!lock.locked()) ...`.
class Scoped
{
public:
    Scoped(KisImageSP image, int timeoutMs)
        : m_image(image)
        , m_locked(tryLock(image, timeoutMs))
    {
    }
    ~Scoped()
    {
        if (m_locked) m_image->unlock();
    }
    Scoped(const Scoped &) = delete;
    Scoped &operator=(const Scoped &) = delete;

    bool locked() const { return m_locked; }

private:
    KisImageSP m_image;
    bool m_locked;
};

} // namespace KisAgentReadLock

#endif // KIS_AGENT_READ_LOCK_H
