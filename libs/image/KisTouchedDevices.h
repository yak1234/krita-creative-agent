/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KIS_TOUCHED_DEVICES_H
#define KIS_TOUCHED_DEVICES_H

#include <QMutex>
#include <QSet>
#include <QSharedPointer>

#include "kritaimage_export.h"

class KisPaintDevice;
class KUndo2Command;

/**
 * Which paint devices a stroke's undo step changes, for a history that orders steps per device (Krita Agent).
 *
 * A stroke whose commands only change pixels (a fill, a gradient) lands in the history as one saved macro, whose
 * commands cannot be read from outside. Such a stroke records the devices it changes instead: while a Recording lives
 * on a thread, every transaction made on that thread (KisTransactionData) notes its device. When the stroke hands its
 * step to the history it says so with a Report, which a listener on the same thread reads with reported().
 *
 * Nothing is recorded or reported unless a stroke asks for it
 * (KisStrokeStrategyUndoCommandBased::setReportsTouchedDevices()).
 */
namespace KisTouchedDevices
{

/// The devices one stroke has changed so far, from any of its threads.
class KRITAIMAGE_EXPORT Set
{
public:
    void insert(const KisPaintDevice *device);
    QSet<const KisPaintDevice *> devices() const;

private:
    mutable QMutex m_mutex;
    QSet<const KisPaintDevice *> m_devices;
};
using SetSP = QSharedPointer<Set>;

/// While it lives, the transactions made on this thread note their devices in \p set. Recordings nest.
class KRITAIMAGE_EXPORT Recording
{
public:
    explicit Recording(SetSP set);
    ~Recording();

private:
    Set *m_previous;
    Q_DISABLE_COPY(Recording)
};

/// Called for every transaction made: notes \p device in this thread's recording, if one is open.
KRITAIMAGE_EXPORT void noteChanged(const KisPaintDevice *device);

/// While it lives, \p command (being added to a history on this thread) is reported to have changed only
/// \p devices' pixels.
class KRITAIMAGE_EXPORT Report
{
public:
    Report(const KUndo2Command *command, const QSet<const KisPaintDevice *> &devices);
    ~Report();

    const Report *previous() const { return m_previous; }
    const KUndo2Command *command() const { return m_command; }
    const QSet<const KisPaintDevice *> &devices() const { return m_devices; }

private:
    const Report *m_previous;
    const KUndo2Command *m_command;
    QSet<const KisPaintDevice *> m_devices;
    Q_DISABLE_COPY(Report)
};

/// @return true when \p command is being reported on this thread, with the devices it changed added to \p devices.
KRITAIMAGE_EXPORT bool reported(const KUndo2Command *command, QSet<const KisPaintDevice *> *devices);

} // namespace KisTouchedDevices

#endif // KIS_TOUCHED_DEVICES_H
