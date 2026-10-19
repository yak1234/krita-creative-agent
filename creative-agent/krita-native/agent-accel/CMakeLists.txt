# The Creative Agent's native helper: Krita internals the Python API lacks, built against the exact Krita it loads into.
# Built inside a Krita source tree: in Krita Agent (the fork) from creative-agent/CMakeLists.txt, installed with the app
# and its self-tests run by ctest when BUILD_TESTING is on; for stock Krita 5.3.3, build.sh links this folder in as
# plugins/extensions/agentaccel and builds and runs the self-tests itself.
set(kritaagentaccel_SOURCES agent_accel.cpp selection_builders.cpp stroke_points.cpp background_save.cpp region_refresh.cpp)
kis_add_library(kritaagentaccel MODULE ${kritaagentaccel_SOURCES})
target_link_libraries(kritaagentaccel kritaui)
install(TARGETS kritaagentaccel DESTINATION ${KRITA_PLUGIN_INSTALL_DIR})

# The self-tests below build with everything and run under ctest when Krita's tests are on (ctest -R kritaagentaccel);
# otherwise only on request (build.sh).
if (BUILD_TESTING)
    set(AGENT_ACCEL_TEST_EXCLUDE "")
else()
    set(AGENT_ACCEL_TEST_EXCLUDE EXCLUDE_FROM_ALL)
endif()

# The selection builders on their own, against the plugin's Python steps; build.sh builds and runs it. Never installed.
add_executable(kritaagentaccel_selftest ${AGENT_ACCEL_TEST_EXCLUDE} selection_selftest.cpp selection_builders.cpp)
target_link_libraries(kritaagentaccel_selftest kritaimage)
set_target_properties(kritaagentaccel_selftest PROPERTIES MACOSX_BUNDLE FALSE)

# paintStrokes' points as Krita's brush engine reads them (pressure, tilt, rotation, speed, time); build.sh runs it too.
add_executable(kritaagentaccel_pointtest ${AGENT_ACCEL_TEST_EXCLUDE} stroke_points_selftest.cpp stroke_points.cpp)
target_link_libraries(kritaagentaccel_pointtest kritaimage)
set_target_properties(kritaagentaccel_pointtest PROPERTIES MACOSX_BUNDLE FALSE)

# saveInBackground's file side (temporary file, atomic rename, status JSON) without Krita; build.sh runs it too.
add_executable(kritaagentaccel_savetest ${AGENT_ACCEL_TEST_EXCLUDE} background_save_selftest.cpp background_save.cpp)
target_link_libraries(kritaagentaccel_savetest Qt${QT_MAJOR_VERSION}::Core)
set_target_properties(kritaagentaccel_savetest PROPERTIES MACOSX_BUNDLE FALSE)

# refreshRect's area on small images with filter masks, adjustment layers, layer styles, clones, pass-through groups and
# transform masks, against a whole refresh; build.sh runs it too. Krita's transform mask test stubs stand in for the
# transform tool's mask parameters.
add_executable(kritaagentaccel_regiontest ${AGENT_ACCEL_TEST_EXCLUDE} region_refresh_selftest.cpp region_refresh.cpp)
target_link_libraries(kritaagentaccel_regiontest kritaimage kritatransformmaskstubs)
target_include_directories(kritaagentaccel_regiontest PRIVATE ${CMAKE_SOURCE_DIR}/sdk/tests ${CMAKE_BINARY_DIR}/sdk/tests)
set_target_properties(kritaagentaccel_regiontest PROPERTIES MACOSX_BUNDLE FALSE)

if (BUILD_TESTING)
    foreach(selftest kritaagentaccel_selftest kritaagentaccel_pointtest kritaagentaccel_savetest kritaagentaccel_regiontest)
        add_test(NAME ${selftest} COMMAND ${selftest})
    endforeach()
endif()
