/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_SCRIPTWAITS_H
#define LIBKIS_SCRIPTWAITS_H

#include <QList>
#include <functional>
#include <kis_types.h>
#include <processing/KisToolFunctions.h>

#include "kritalibkis_export.h"

/**
 * How libkis calls wait for their own work (Krita Agent, krita-fork 2.9).
 *
 * A call never waits for the whole image (KisImage::waitForDone(), which asks the artist's open strokes to end and
 * never returns while the artist holds the pen down). It waits for its own stroke only, at most
 * KisToolFunctions::waitLimit() (60 s unless set). On the GUI thread it handles events meanwhile (except socket
 * notifiers, so no new script command arrives in the middle of this one), so an artist holding the pen can lift it and
 * the call's stroke, queued behind the artist's, can run; a wait inside another wait does not handle events.
 */
namespace ScriptWaits
{

/// Waits for \p completion's stroke, at most the wait limit. @return whether it finished.
KRITALIBKIS_EXPORT bool wait(KisToolFunctions::CompletionSP completion);

/**
 * Waits for the stroke of \p call (a libkis call, for the warning) as wait() does. When it has not finished in time
 * it is cancelled (nothing it did stays), a warning says why, and false is returned.
 */
KRITALIBKIS_EXPORT bool waitForStroke(KisToolFunctions::CompletionSP completion, const char *call);

/**
 * For strokes libkis does not hold (an image operation started just before): queues a stroke that does nothing,
 * never asks open strokes to end, and ends after everything queued before it, and waits for it as wait() does; then
 * waits for the image's redraws too (until it is idle: up to the wait limit while redraws are queued, but only
 * briefly, 2 s, when the image is busy only with strokes, such as one the artist is drawing).
 *
 * When the stroke queue does not reach the marker within the wait limit (a stroke the artist is drawing holds it
 * back), the strokes in \p started are cancelled: the operation never runs, a warning says so, and false is returned.
 * Returns true when the work has run, the image is idle, or the image is locked (a locked image runs nothing until
 * it is unlocked, and nothing is waited for).
 *
 * Note: this makes the call's own work land, not every redraw of the image. A script that reads pixels of the
 * composited image still calls Document.waitForDone() first (which also ends the artist's open strokes).
 */
KRITALIBKIS_EXPORT bool waitForQueuedWork(KisImageSP image, const char *call, const QList<KisStrokeId> &started = QList<KisStrokeId>());

/**
 * Runs \p operation (an upstream call that starts the strokes of an image operation: cropImage(), mergeDown() and the
 * like) with the artist's open strokes never asked to end (KisProcessingApplicator::NoEndRequestsOverride, around the
 * call only: not around the wait, where the GUI thread handles events and the artist may start a stroke), then
 * waitForQueuedWork() with the strokes it started. Returns false when it was cancelled (see there).
 */
KRITALIBKIS_EXPORT bool run(KisImageSP image, const char *call, const std::function<void()> &operation);

} // namespace ScriptWaits

#endif // LIBKIS_SCRIPTWAITS_H
