# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The creative agent's parts that build with Krita Agent (this fork), added from plugins/extensions/CMakeLists.txt
# (AGENT-FORK.md, "Upstream files we edit"). Switched off, the build is upstream's.
option(KRITA_AGENT_NATIVE_HELPER "Build the creative agent's native helper (creative-agent/krita-native/agent-accel) as a Krita plugin" ON)
add_feature_info("Creative agent native helper" KRITA_AGENT_NATIVE_HELPER
                 "Krita internals for the creative agent's Python plugin: pen strokes, selections, background save, region refresh")
if (KRITA_AGENT_NATIVE_HELPER)
    add_subdirectory(krita-native/agent-accel)
endif()

# The creative agent's Python plugin ships inside the app, beside Krita's own bundled plugins, so a build is usable without
# a separate install step (krita-fork 1.5). Krita finds it as a system plugin; a copy in the artist's own pykrita folder
# (what scripts/install.py --krita fork writes) is found first and shadows this one: remove it to use the shipped one.
# Enabling it on a fresh settings folder is the new-install defaults' job (task 3.3).
option(KRITA_AGENT_PLUGIN "Install the creative agent's Python plugin (creative-agent/krita-mcp/krita-plugin) with Krita" ON)
add_feature_info("Creative agent plugin" KRITA_AGENT_PLUGIN "The agent's bridge and tools, installed into share/krita/pykrita")
if (KRITA_AGENT_PLUGIN)
    install(DIRECTORY krita-mcp/krita-plugin/kritamcp
            DESTINATION ${KDE_INSTALL_DATADIR}/krita/pykrita
            PATTERN "__pycache__" EXCLUDE
            PATTERN "*.pyc" EXCLUDE)
    install(FILES krita-mcp/krita-plugin/kritamcp.desktop
            DESTINATION ${KDE_INSTALL_DATADIR}/krita/pykrita)
endif()
