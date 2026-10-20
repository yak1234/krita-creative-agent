/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISABOUTAGENT_H
#define KISABOUTAGENT_H

#include <QString>

#include "kritaui_export.h"

/**
 * What the About dialog says about a build with its own identity (KRITA_APP_SETTINGS_FOLDER: Toska, which began as Krita Agent): the
 * name, the commit the build came from, the licence and where the corresponding source is. For stock Krita
 * (no settings folder) every function returns an empty string and the dialog is exactly upstream's.
 *
 * A packaged app (agent/package-app.sh) carries its build record in Contents/Resources/BUILD.txt (the one place that names
 * the commit and the address of the source) and the licence notices in Contents/Resources/LICENSES; this reads the first
 * and points at the second.
 */
namespace KisAboutAgent
{
/// The About window's title ("About Toska"), or an empty string for stock Krita.
KRITAUI_EXPORT QString windowTitle();

/// The Help menu's About entry ("&About Toska"), or an empty string for stock Krita (whose entry says "&About Krita").
KRITAUI_EXPORT QString aboutActionText();

/// The one-line description for KAboutData ("Toska is based on Krita, the full-featured digital art studio"), or an empty
/// string for stock Krita.
KRITAUI_EXPORT QString shortDescription();

/// An HTML block for the top of the "Your Rights" tab, or an empty string for stock Krita.
KRITAUI_EXPORT QString licenseHtml();

/// The same block, from the text of Resources/BUILD.txt (an empty text: a build that is not packaged). Does not look at the
/// file system, so it can be tested without an installed Krita (KoResourcePaths::getApplicationRoot() needs one on macOS).
KRITAUI_EXPORT QString licenseHtmlFromRecord(const QString &record);

/// The value of a "key: value" line of the build record text (empty if the key is missing). Exported for
/// KisAboutAgentTest.
KRITAUI_EXPORT QString recordValue(const QString &record, const QString &key);
}

#endif // KISABOUTAGENT_H
