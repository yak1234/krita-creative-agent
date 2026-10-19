# Shutdown crash — 2026-09-13

The 15:22:33 macOS report (`krita-2026-09-13-152233.ips`) and captured Python traceback identify the trigger: QProcess emits errorOccurred during dock destruction; the lambda calls setText on an already-deleted QLabel. Krita then crashes in Cocoa activation while displaying its Python exception dialog.

The panel now disconnects companion callbacks on QObject.destroyed (before child destruction), using a free callback rather than a receiver on the dying dock. Error, finished and output handlers also check widget validity. Normal close/hide of the docker does not stop painting.

Applied to repository and installed creative_docker.py; installed SHA256 e2a48f6fd50a7404dff03f32564d9bc53b58c8e3c14a5b371b2a49a07d640fdb. The installed previous file is preserved as creative_docker.py.before-shutdown-fix. This is a direct native-plugin hotfix; the companion release identifier is unchanged.

Validation: ui_shutdown.py passes late-callback handling and five destructions with a live child QProcess, with no uncaught Python errors. ui_smoke.py also passes. Run with `uv run --python 3.13 --with PyQt5 python tests/ui_shutdown.py` from the companion directory. Actual macOS Krita quit/reopen validation is still pending: Krita was intentionally left closed, and no painting was started.
