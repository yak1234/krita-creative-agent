kis_add_tests(
    kis_kra_loader_test.cpp
    LINK_LIBRARIES kritaui kritalibkra kritatestsdk
    )


kis_add_test(
    kis_kra_saver_test.cpp
    LINK_LIBRARIES kritaui kritalibkra kritatransformmaskstubs
    )

# Krita Agent: the feature map in a .kra (krita-fork 6.1), run in a temporary home.
kis_add_test(
    KisKraFeaturesTest.cpp
    TEST_NAME KisKraFeaturesTest
    LINK_LIBRARIES kritaui kritalibkra kritatestsdk ${QUAZIP_LIBRARIES}
    )
