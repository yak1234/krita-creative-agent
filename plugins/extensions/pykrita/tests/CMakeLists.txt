# Python-side tests of the krita module: a test binary embeds the interpreter and imports the built module.
set(PYKRITA_TEST_PYQT_DIR "${CMAKE_INSTALL_PREFIX}/lib/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages")

kis_add_tests(
    TestPythonChangeEvents.cpp
    LINK_LIBRARIES kritalibkis kritatestsdk ${PYTHON_LIBRARY}
    )

target_include_directories(TestPythonChangeEvents SYSTEM PRIVATE "${PYTHON_INCLUDE_DIRS}")
target_compile_definitions(TestPythonChangeEvents PRIVATE
    PYKRITA_TEST_MODULE="$<TARGET_FILE:python_module_PyKrita_krita>"
    PYKRITA_TEST_PYQT_DIR="${PYKRITA_TEST_PYQT_DIR}")
add_dependencies(TestPythonChangeEvents python_module_PyKrita_krita)
