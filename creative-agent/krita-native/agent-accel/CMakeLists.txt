# The Creative Agent's native helper: Krita internals the Python API lacks, built against the exact Krita it loads into.
# Built inside a Krita source tree (build.sh links this folder in as plugins/extensions/agentaccel).
set(kritaagentaccel_SOURCES agent_accel.cpp selection_builders.cpp stroke_points.cpp background_save.cpp region_refresh.cpp)
kis_add_library(kritaagentaccel MODULE ${kritaagentaccel_SOURCES})
target_link_libraries(kritaagentaccel kritaui)
install(TARGETS kritaagentaccel DESTINATION ${KRITA_PLUGIN_INSTALL_DIR})

# The selection builders on their own, against the plugin's Python steps; build.sh builds and runs it. Never installed.
add_executable(kritaagentaccel_selftest EXCLUDE_FROM_ALL selection_selftest.cpp selection_builders.cpp)
target_link_libraries(kritaagentaccel_selftest kritaimage)
set_target_properties(kritaagentaccel_selftest PROPERTIES MACOSX_BUNDLE FALSE)

# paintStrokes' points as Krita's brush engine reads them (pressure, tilt, rotation, speed, time); build.sh runs it too.
add_executable(kritaagentaccel_pointtest EXCLUDE_FROM_ALL stroke_points_selftest.cpp stroke_points.cpp)
target_link_libraries(kritaagentaccel_pointtest kritaimage)
set_target_properties(kritaagentaccel_pointtest PROPERTIES MACOSX_BUNDLE FALSE)

# saveInBackground's file side (temporary file, atomic rename, status JSON) without Krita; build.sh runs it too.
add_executable(kritaagentaccel_savetest EXCLUDE_FROM_ALL background_save_selftest.cpp background_save.cpp)
target_link_libraries(kritaagentaccel_savetest Qt${QT_MAJOR_VERSION}::Core)
set_target_properties(kritaagentaccel_savetest PROPERTIES MACOSX_BUNDLE FALSE)

# refreshRect's area on small images with filter masks, adjustment layers, layer styles, clones, pass-through groups and
# transform masks, against a whole refresh; build.sh runs it too. Krita's transform mask test stubs stand in for the
# transform tool's mask parameters.
add_executable(kritaagentaccel_regiontest EXCLUDE_FROM_ALL region_refresh_selftest.cpp region_refresh.cpp)
target_link_libraries(kritaagentaccel_regiontest kritaimage kritatransformmaskstubs)
target_include_directories(kritaagentaccel_regiontest PRIVATE ${CMAKE_SOURCE_DIR}/sdk/tests ${CMAKE_BINARY_DIR}/sdk/tests)
set_target_properties(kritaagentaccel_regiontest PROPERTIES MACOSX_BUNDLE FALSE)
