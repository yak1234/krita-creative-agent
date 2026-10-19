kis_add_tests(KisSignalAutoConnectionTest.cpp
    KisSignalCompressorTest.cpp
    KisForestTest.cpp
    KisMplTest.cpp
    KisLagerTest.cpp
    KisRectsGridTest.cpp
    KisLazyStorageTest.cpp
    KisValueCacheTest.cpp
    KisHistoryListTest.cpp
    KisAdaptedLockTest.cpp
    KisGlobalTest.cpp
    LINK_LIBRARIES kritaglobal kritatestsdk
    )


# The build's own identity (KisAppIdentity, cmake/modules/KritaAppIdentity.cmake), with Krita's shipped config defaults
kis_add_test(KisAppIdentityTest.cpp "${CMAKE_BINARY_DIR}/krita/krita.qrc" ${KRITA_APP_IDENTITY_QRC}
    TEST_NAME KisAppIdentityTest
    LINK_LIBRARIES kritaglobal kritatestsdk KF${KF_MAJOR}::ConfigCore Qt${QT_MAJOR_VERSION}::Test
    )
