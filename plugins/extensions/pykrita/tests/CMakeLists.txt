# Python-side tests of the krita module: a test binary embeds the interpreter and imports the built module.
set(PYKRITA_TEST_PYQT_DIR "${CMAKE_INSTALL_PREFIX}/lib/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages")

kis_add_tests(
    TestPythonChangeEvents.cpp
    TestPythonAgentMove.cpp
    TestPythonAgentCraft.cpp
    TestPythonFeatures.cpp
    TestPythonAgentTools.cpp
    TestPythonStrokeJobs.cpp
    LINK_LIBRARIES kritalibkis kritatestsdk ${PYTHON_LIBRARY}
    )

foreach(test TestPythonChangeEvents TestPythonAgentMove TestPythonAgentCraft TestPythonFeatures TestPythonAgentTools TestPythonStrokeJobs)
    target_include_directories(${test} SYSTEM PRIVATE "${PYTHON_INCLUDE_DIRS}")
    target_compile_definitions(${test} PRIVATE
        PYKRITA_TEST_MODULE="$<TARGET_FILE:python_module_PyKrita_krita>"
        PYKRITA_TEST_PYQT_DIR="${PYKRITA_TEST_PYQT_DIR}"
        PYKRITA_TEST_AGENTMOVE="${CMAKE_CURRENT_SOURCE_DIR}/../plugin/krita/agentmove.py")
    add_dependencies(${test} python_module_PyKrita_krita)
endforeach()
