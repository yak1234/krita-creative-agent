# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The name of the application the panel runs in, for the texts the artist reads.

The fork is called Toska (the artist named it on 2026-10-20) and sets that as the application's display name
(KisAppIdentity::displayName(), through KAboutData); stock Krita's is "Krita". The panel works in both, so it asks instead
of writing either name into its texts. 'Krita' stays where the text is about upstream or the file format itself ('Krita
paintings (*.kra)'), and in anything the painter model reads: the model is told about Krita's toolset.
"""


def product_name(app=None):
    """The application's display name, or 'Krita' when there is none (no application, an empty name, tests)."""
    if app is None:
        try:
            from .qt_compat import QCoreApplication
        except ImportError:
            return 'Krita'
        instance = getattr(QCoreApplication, 'instance', None)
        app = instance() if instance is not None else None
    name = app.applicationDisplayName() if app is not None and hasattr(app, 'applicationDisplayName') else ''
    return (name or '').strip() or 'Krita'
