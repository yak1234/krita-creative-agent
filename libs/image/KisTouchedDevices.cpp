/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisTouchedDevices.h"

#include <QMutexLocker>

namespace KisTouchedDevices
{

namespace
{
thread_local Set *s_recording = nullptr;
thread_local const Report *s_report = nullptr;
}

void Set::insert(const KisPaintDevice *device)
{
    QMutexLocker locker(&m_mutex);
    m_devices.insert(device);
}

QSet<const KisPaintDevice *> Set::devices() const
{
    QMutexLocker locker(&m_mutex);
    return m_devices;
}

Recording::Recording(SetSP set)
    : m_previous(s_recording)
{
    s_recording = set.data();
}

Recording::~Recording()
{
    s_recording = m_previous;
}

void noteChanged(const KisPaintDevice *device)
{
    if (s_recording && device) {
        s_recording->insert(device);
    }
}

Report::Report(const KUndo2Command *command, const QSet<const KisPaintDevice *> &devices)
    : m_previous(s_report)
    , m_command(command)
    , m_devices(devices)
{
    s_report = this;
}

Report::~Report()
{
    s_report = m_previous;
}

bool reported(const KUndo2Command *command, QSet<const KisPaintDevice *> *devices)
{
    for (const Report *report = s_report; report; report = report->previous()) {
        if (report->command() == command) {
            if (devices) {
                *devices += report->devices();
            }
            return true;
        }
    }
    return false;
}

} // namespace KisTouchedDevices
