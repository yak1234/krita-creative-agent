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
