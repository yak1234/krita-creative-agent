# Toska welcome page artwork

`toska-welcome.jpg` (the welcome page background) is artwork owned by the artist, licence to be decided. No licence
is granted for it by this repository's code licences; ask the artist before reusing it.

It is the web-sized copy of `creative-agent/docs/branding/toska-welcome-source.png` (1774 x 887, kept there as the
source), made by `make_welcome.py` (code, GPL-3.0-or-later):

    uv run --with pillow python krita/data/welcome/toska/make_welcome.py \
        creative-agent/docs/branding/toska-welcome-source.png krita/data/welcome/toska/toska-welcome.jpg

`../welcome-toska.qrc` gives it the alias `:/welcome/toska-welcome.jpg`, compiled into the build named Toska only.
`KisWelcomePageWidget` draws it to cover the page, anchored right so the moon and the stroke stay in view, under a
darkening of the window colour on the left (`libs/ui/KisWelcomeBackgroundLayout.h`). See AGENT-FORK.md, "Welcome page".
