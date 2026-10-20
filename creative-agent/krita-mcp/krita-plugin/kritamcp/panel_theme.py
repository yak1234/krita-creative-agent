# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Creative Agent panel's colours, without Qt.

The panel offers three choices: 'Match <app>' (the 'system' mode), Dark and Light. Dark and Light are the panel's own
neutral colours. 'Match' follows the application: when the app shows one of Toska's colour themes (Toska Night, Toska
Day: krita/data/themes/ToskaNight.colors, ToskaDay.colors) the panel takes Toska's colours, built from the same palette as
those files (tests/test_toska_theme.py checks that they agree); any other app theme gets Dark or Light by the lightness of
the app's window colour, as before.

Which theme the app shows: when the app palette is known, its exact window colour alone decides (#141b25 Toska Night,
#efe8dc Toska Day, anything else Dark or Light by lightness). Krita applies a new palette before it saves the theme's name
(KisMainWindow::slotThemeChanged, through a queued connection), so during and right after a palette change the saved name
is the old one. The saved name decides only when there is no palette.
"""

PANEL_KEYS = ('bg', 'surface', 'raised', 'border', 'text', 'muted', 'hover', 'accent', 'button', 'buttonText')

DARK = {'bg': '#1e1f22', 'surface': '#28292d', 'raised': '#313338', 'border': '#42444b', 'text': '#e7e8eb',
        'muted': '#a7aab3', 'hover': '#3b3e45', 'accent': '#b9c7e8', 'button': '#e1e5ee', 'buttonText': '#24272d'}
LIGHT = {'bg': '#f7f7f8', 'surface': '#ffffff', 'raised': '#e9ebee', 'border': '#d3d6dc', 'text': '#24272e',
         'muted': '#646a76', 'hover': '#dee2e9', 'accent': '#3c5c91', 'button': '#313946', 'buttonText': '#ffffff'}

# From the Toska palette (night navy, ember, cream, steel blue). Each value is the .colors file's role named beside it,
# except the border: steel blue (#475d74 at night, the same hue lighter by day).
TOSKA_NIGHT = {
    'bg': '#141b25',          # Colors:Window BackgroundNormal
    'surface': '#0e141c',     # Colors:View BackgroundNormal
    'raised': '#1f2a38',      # Colors:Button BackgroundNormal
    'border': '#475d74',      # steel blue
    'text': '#e9e3d8',        # Colors:Window ForegroundNormal
    'muted': '#93a0af',       # Colors:Button ForegroundInactive
    'hover': '#2a3748',       # Colors:Button BackgroundAlternate
    'accent': '#e65d3f',      # Colors:Window ForegroundActive (ember)
    'button': '#b8432a',      # Colors:Selection BackgroundNormal
    'buttonText': '#fff4e6',  # Colors:Selection ForegroundNormal
}
TOSKA_DAY = {
    'bg': '#efe8dc',
    'surface': '#f8f4ec',
    'raised': '#e2d8c6',
    'border': '#a0b2c5',
    'text': '#1b2430',
    'muted': '#4d5967',
    'hover': '#d8ccb6',
    'accent': '#b03c26',
    'button': '#c4432a',
    'buttonText': '#fff8ee',
}
TOSKA_THEMES = {'Toska Night': (TOSKA_NIGHT, True), 'Toska Day': (TOSKA_DAY, False)}
TOSKA_WINDOWS = {'#141b25': 'Toska Night', '#efe8dc': 'Toska Day'}   # Colors:Window BackgroundNormal of each file


def _rgb(color):
    text = str(color or '').strip().lower()
    if len(text) != 7 or not text.startswith('#'):
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None


def lightness(color):
    """HSL lightness of '#rrggbb' (0..255), or None when it is not such a colour. Within one of QColor.lightness(), which
    rounds through 16-bit floats: the panel passes Qt's own value when it has one."""
    rgb = _rgb(color)
    return None if rgb is None else (max(rgb) + min(rgb) + 1) // 2


def toska_theme(window=None, theme_name=None):
    """'Toska Night', 'Toska Day' or None: the Toska theme the app shows. A known window colour decides alone; the saved
    theme name only without one."""
    rgb = _rgb(window)
    if rgb is not None:
        return TOSKA_WINDOWS.get('#%02x%02x%02x' % rgb)
    name = theme_name.strip() if isinstance(theme_name, str) else ''
    return name if name in TOSKA_THEMES else None


def panel_colors(mode, window=None, theme_name=None, window_lightness=None):
    """(colours, dark) for the panel. mode is 'system' (Match), 'dark' or 'light'; window is the app palette's window
    colour as '#rrggbb' and window_lightness its QColor.lightness(); theme_name is the app's saved colour theme
    ([theme] Theme in kritarc)."""
    if mode == 'dark':
        return dict(DARK), True
    if mode == 'light':
        return dict(LIGHT), False
    toska = toska_theme(window, theme_name)
    if toska:
        colors, dark = TOSKA_THEMES[toska]
        return dict(colors), dark
    level = window_lightness if isinstance(window_lightness, int) and not isinstance(window_lightness, bool) else lightness(window)
    dark = True if level is None else level < 128
    return dict(DARK if dark else LIGHT), dark
