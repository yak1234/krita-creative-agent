/*
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "TestColorSpaceRegistry.h"

#include <lcms2.h>

#include <KoColorProfile.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <simpletest.h>
#include <testpigment.h>

#include <kis_debug.h>
#include <qimage_test_util.h>
#include <KoColorSpaceEngine.h>
#include <KisAdaptedLock.h>

void TestColorSpaceRegistry::testConstruction()
{
    KoColorSpaceRegistry *instance = KoColorSpaceRegistry::instance();
    Q_ASSERT(instance);
}

void TestColorSpaceRegistry::testRgbU8()
{
    const QString colorSpaceId = KoColorSpaceRegistry::instance()->colorSpaceId(RGBAColorModelID,
                                                                                Integer8BitsColorDepthID);

    const KoColorSpace *colorSpace = KoColorSpaceRegistry::instance()->rgb8();
    QVERIFY(colorSpace != 0);

    const KoColorProfile *profile = colorSpace->profile();
    QVERIFY(profile != 0);

    QCOMPARE(profile->name(), KoColorSpaceRegistry::instance()->defaultProfileForColorSpace(colorSpaceId));

    cmsHPROFILE lcmsProfile = cmsCreate_sRGBProfile();
    QString testProfileName = "TestRGBU8ProfileName";

    cmsWriteTag(lcmsProfile, cmsSigProfileDescriptionTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceModelDescTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceMfgDescTag, "");

}

void TestColorSpaceRegistry::testRgbU16()
{
    const QString colorSpaceId = KoColorSpaceRegistry::instance()->colorSpaceId(RGBAColorModelID,
                                                                                Integer16BitsColorDepthID);

    const KoColorSpace *colorSpace = KoColorSpaceRegistry::instance()->rgb16();
    QVERIFY(colorSpace != 0);

    const KoColorProfile *profile = colorSpace->profile();
    QVERIFY(profile != 0);

    QCOMPARE(profile->name(), KoColorSpaceRegistry::instance()->defaultProfileForColorSpace(colorSpaceId));

    cmsHPROFILE lcmsProfile = cmsCreate_sRGBProfile();
    QString testProfileName = "TestRGBU16ProfileName";

    cmsWriteTag(lcmsProfile, cmsSigProfileDescriptionTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceModelDescTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceMfgDescTag, "");

}

void TestColorSpaceRegistry::testLab()
{
    const QString colorSpaceId = KoColorSpaceRegistry::instance()->colorSpaceId(LABAColorModelID,
                                                                                Integer16BitsColorDepthID);

    const KoColorSpace *colorSpace = KoColorSpaceRegistry::instance()->lab16();
    QVERIFY(colorSpace != 0);

    const KoColorProfile *profile = colorSpace->profile();
    QVERIFY(profile != 0);

    QCOMPARE(profile->name(), KoColorSpaceRegistry::instance()->defaultProfileForColorSpace(colorSpaceId));

    cmsCIExyY whitepoint;
    whitepoint.x = 0.33;
    whitepoint.y = 0.33;
    whitepoint.Y = 1.0;

    cmsHPROFILE lcmsProfile = cmsCreateLab4Profile(&whitepoint);
    QString testProfileName = "TestLabProfileName";

    cmsWriteTag(lcmsProfile, cmsSigProfileDescriptionTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceModelDescTag, testProfileName.toLatin1().constData());
    cmsWriteTag(lcmsProfile, cmsSigDeviceMfgDescTag, "");

}

void TestColorSpaceRegistry::testColorProfileAliasAddUnique()
{
    auto *registry = KoColorSpaceRegistry::instance();

    const QString aliasSource = "test_alias.icc";
    const QString aliasDestination = registry->p2020G10Profile()->name();

    registry->addProfileAlias(aliasSource, aliasDestination);

    {
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasDestination);
    }

    registry->removeProfileAlias(aliasSource);

    {
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(!profile);
    }

}

void TestColorSpaceRegistry::testColorProfileAliasAddWhenProfileExists()
{
    auto *registry = KoColorSpaceRegistry::instance();

    KoColorProfile *originalProfile = const_cast<KoColorProfile*>(registry->p709G10Profile());

    const QString aliasSource = originalProfile->name();
    const QString aliasDestination = registry->p2020G10Profile()->name();
    KIS_ASSERT(aliasSource != aliasDestination);

    // add alias
    registry->addProfileAlias(aliasSource, aliasDestination);

    {
        /**
         * The alias is added but it takes no effect, since the actual profile
         * with this name already exists
         */
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasSource);
    }

    // now remove the profile
    registry->removeProfile(originalProfile);

    {
        /**
         * The alias is active now!
         */
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasDestination);
    }

    // now remove the alias
    registry->removeProfileAlias(aliasSource);

    {
        /**
         * Nothing is found now. We have removed both, the profile and the alias
         */
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(!profile);
    }

    // restore the profile
    registry->addProfile(originalProfile);
    {
        // no alias is present now
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasSource);
    }
}

namespace {
struct AliasRemovalAdapter
{
    AliasRemovalAdapter(const QString &aliasSource)
        : m_aliasSource(aliasSource)
    {
        auto *registry = KoColorSpaceRegistry::instance();
        m_originalAliasTarget = registry->profileAlias(aliasSource);
    }

    inline void lock() {
        if (m_originalAliasTarget != m_aliasSource) {
            auto *registry = KoColorSpaceRegistry::instance();
            registry->removeProfileAlias(m_aliasSource);
        }
    }

    inline void unlock() {
        if (m_originalAliasTarget != m_aliasSource) {
            auto *registry = KoColorSpaceRegistry::instance();
            registry->addProfileAlias(m_aliasSource, m_originalAliasTarget);
        }
    }

private:
    QString m_aliasSource;
    QString m_originalAliasTarget;
};

KIS_DECLARE_ADAPTED_LOCK(AliasRemovalLock, AliasRemovalAdapter)
}

void TestColorSpaceRegistry::testColorProfileAliasOverrideByProfile()
{
    /**
     * The profile aliases are considered 'weak', i.e. when a real
     * profile with the same name is loaded, the alias gets overridden.
     *
     * When this explicit profile is unloaded, the alias is expected
     * to be re-enabled again.
     */
    auto *registry = KoColorSpaceRegistry::instance();
    const QString legacyProfileName = "High Dynamic Range UHDTV Wide Color Gamut Display (Rec. 2020) - SMPTE ST 2084 PQ EOTF";
    const QString legacyProfileFileName = "ITUR_2100_PQ_FULL.ICC";

    AliasRemovalLock lock(legacyProfileName);

    QVERIFY(!registry->profileByName(legacyProfileName));

    const QString aliasSource = legacyProfileName;
    const QString aliasDestination = registry->p2020PQProfile()->name();
    KIS_ASSERT(aliasSource != aliasDestination);

    registry->addProfileAlias(legacyProfileName, aliasDestination);

    {
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasDestination);
    }

    {
        const QString profileFilePath = TestUtil::fetchDataFileLazy(legacyProfileFileName);
        KIS_ASSERT(QFile::exists(profileFilePath));

        {
            KoColorSpaceEngine *iccEngine = KoColorSpaceEngineRegistry::instance()->get("icc");
            KIS_ASSERT(iccEngine);
            iccEngine->addProfile(profileFilePath);
        }
    }

    {
        // the profile has overridden the alias
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasSource);
    }

    registry->removeProfile(const_cast<KoColorProfile*>(registry->profileByName(aliasSource)));

    {
        // alias is active again
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(profile);
        QCOMPARE(profile->name(), aliasDestination);
    }

    registry->removeProfileAlias(aliasSource);

    {
        // no alias exists anymore, hence no profile
        auto *profile = registry->profileByName(aliasSource);
        QVERIFY(!profile);
    }
}

KISTEST_MAIN(TestColorSpaceRegistry)
