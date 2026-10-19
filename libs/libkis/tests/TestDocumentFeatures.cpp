/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestDocumentFeatures.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QScopedPointer>
#include <QTemporaryDir>

#include <kundo2stack.h>

#include <Document.h>
#include <Feature.h>
#include <Selection.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <KisFeatureList.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>

namespace {

const QSize imageSize(200, 150);

/// A document with an undo stack (the document's own), a red layer under a blue band, added to KisPart so its
/// change report counts revisions, and unmodified.
struct FeaturesDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    KisNodeSP layer;
    QScopedPointer<Document> doc;

    FeaturesDocument()
        : kisdoc(KisPart::instance()->createDocument())
    {
        kisdoc->setFileBatchMode(true); // never a dialog in a test
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), imageSize.width(), imageSize.height(), cs, "features");
        layer = new KisPaintLayer(image, "layer", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(image->bounds(), KoColor(Qt::red, cs));
        layer->paintDevice()->fill(QRect(0, 0, 200, 50), KoColor(Qt::blue, cs));
        image->addNode(layer);
        image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data());
        doc.reset(new Document(kisdoc.data(), false));
        image->refreshGraphAsync();
        settle();
        kisdoc->setModified(false);
    }

    ~FeaturesDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    void settle()
    {
        image->waitForDone();
        for (int i = 0; i < 5; i++) {
            QCoreApplication::sendPostedEvents();
            QCoreApplication::processEvents();
        }
    }

    /// Every pixel of the document: each layer's and the composited image's.
    QByteArray pixels()
    {
        image->waitForDone();
        QByteArray all;
        for (KisNodeSP node : {layer, image->root()->lastChild(), KisNodeSP(image->root())}) {
            KisPaintDeviceSP dev = node == image->root() ? image->projection() : node->paintDevice();
            QByteArray bytes(imageSize.width() * imageSize.height() * 4, 0);
            dev->readBytes(reinterpret_cast<quint8 *>(bytes.data()), image->bounds());
            all += bytes;
        }
        return all;
    }

    int undoSteps()
    {
        return kisdoc->undoStack()->count();
    }

    void undo()
    {
        kisdoc->undoStack()->undo();
        settle();
    }

    void redo()
    {
        kisdoc->undoStack()->redo();
        settle();
    }

    QStringList names()
    {
        QStringList result;
        const QList<Feature *> features = doc->features();
        for (Feature *f : features) {
            result << f->name();
        }
        qDeleteAll(features);
        return result;
    }
};

Selection *rectSelection(const QRect &rect)
{
    Selection *selection = new Selection();
    selection->select(rect.x(), rect.y(), rect.width(), rect.height(), 255);
    return selection;
}

} // namespace

void TestDocumentFeatures::testAddFeature()
{
    FeaturesDocument d;
    QVERIFY(d.doc->features().isEmpty());

    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data(), "artist", "kept", true));
    QVERIFY(feature);
    QCOMPARE(feature->name(), QString("Sky"));
    QCOMPARE(feature->kind(), QString("sky"));
    QCOMPARE(feature->author(), QString("artist"));
    QCOMPARE(feature->state(), QString("kept"));
    QVERIFY(feature->isProtected());
    QCOMPARE(feature->bounds(), QRect(0, 0, 200, 50));
    QCOMPARE(feature->area(), qint64(200 * 50));
    QCOMPARE(feature->meanColor(), QColor(Qt::blue));
    QVERIFY(!feature->id().isEmpty());
    QVERIFY(feature->isInDocument());

    // The defaults: an agent's proposal, not protected.
    QScopedPointer<Selection> ground(rectSelection(QRect(0, 50, 200, 100)));
    QScopedPointer<Feature> proposal(d.doc->addFeature("Ground", "ground", ground.data()));
    QVERIFY(proposal);
    QCOMPARE(proposal->author(), QString("agent"));
    QCOMPARE(proposal->state(), QString("proposed"));
    QVERIFY(!proposal->isProtected());
    QCOMPARE(proposal->meanColor(), QColor(Qt::red));

    QCOMPARE(d.names(), QStringList({"Sky", "Ground"}));
    QScopedPointer<Feature> found(d.doc->feature("Sky"));
    QVERIFY(found);
    QVERIFY(*found == *feature);
    QVERIFY(*found != *proposal);
    QVERIFY(!d.doc->feature("Moon"));
}

void TestDocumentFeatures::testAddChangesNoPixelAndIsOneUndoStep()
{
    FeaturesDocument d;
    const QByteArray before = d.pixels();
    const qint64 revision = d.doc->revision();
    const int steps = d.undoSteps();
    QVERIFY(!d.kisdoc->isModified());

    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data()));
    QVERIFY(feature);
    d.settle();

    QCOMPARE(d.undoSteps(), steps + 1);
    QVERIFY(d.kisdoc->isModified());
    QVERIFY(d.pixels() == before);
    QCOMPARE(d.doc->revision(), revision);

    d.undo();
    QVERIFY(d.names().isEmpty());
    QVERIFY(!feature->isInDocument());
    QVERIFY(!d.kisdoc->isModified());
    QVERIFY(d.pixels() == before);

    d.redo();
    QCOMPARE(d.names(), QStringList({"Sky"}));
    QVERIFY(feature->isInDocument());
    QVERIFY(d.pixels() == before);
    QCOMPARE(d.doc->revision(), revision);

    // The revision does count a real change, so the comparisons above mean something.
    d.layer->paintDevice()->fill(QRect(0, 0, 5, 5), KoColor(Qt::green, d.layer->colorSpace()));
    d.layer->setDirty(QRect(0, 0, 5, 5));
    d.settle();
    QVERIFY(d.doc->revision() > revision);
}

void TestDocumentFeatures::testRemoveChangesNoPixelAndIsOneUndoStep()
{
    FeaturesDocument d;
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Selection> ground(rectSelection(QRect(0, 50, 200, 100)));
    QScopedPointer<Feature> skyFeature(d.doc->addFeature("Sky", "sky", sky.data()));
    QScopedPointer<Feature> groundFeature(d.doc->addFeature("Ground", "ground", ground.data()));
    d.settle();
    d.kisdoc->setModified(false);

    const QByteArray before = d.pixels();
    const qint64 revision = d.doc->revision();
    const int steps = d.undoSteps();

    QVERIFY(d.doc->removeFeature("Sky"));
    d.settle();
    QCOMPARE(d.names(), QStringList({"Ground"}));
    QCOMPARE(d.undoSteps(), steps + 1);
    QVERIFY(d.kisdoc->isModified());
    QVERIFY(d.pixels() == before);
    QCOMPARE(d.doc->revision(), revision);
    QVERIFY(!skyFeature->isInDocument());

    d.undo();
    // Back in its place, with its mask and properties.
    QCOMPARE(d.names(), QStringList({"Sky", "Ground"}));
    QVERIFY(skyFeature->isInDocument());
    QCOMPARE(skyFeature->bounds(), QRect(0, 0, 200, 50));
    QVERIFY(d.pixels() == before);

    QVERIFY(!d.doc->removeFeature("Moon"));
}

void TestDocumentFeatures::testRenameIsOneUndoStepAndFeatureFollows()
{
    FeaturesDocument d;
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Selection> ground(rectSelection(QRect(0, 50, 200, 100)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data()));
    QScopedPointer<Feature> other(d.doc->addFeature("Ground", "ground", ground.data()));
    d.settle();
    d.kisdoc->setModified(false);
    const QByteArray before = d.pixels();
    const int steps = d.undoSteps();

    QVERIFY(d.doc->renameFeature("Sky", "Evening sky"));
    d.settle();
    QCOMPARE(feature->name(), QString("Evening sky"));
    QCOMPARE(d.names(), QStringList({"Evening sky", "Ground"}));
    QCOMPARE(d.undoSteps(), steps + 1);
    QVERIFY(d.kisdoc->isModified());
    QVERIFY(d.pixels() == before);

    d.undo();
    QCOMPARE(feature->name(), QString("Sky"));

    QVERIFY(!d.doc->renameFeature("Sky", "Ground")); // taken
    QVERIFY(!d.doc->renameFeature("Sky", ""));       // empty
    QVERIFY(!d.doc->renameFeature("Moon", "Sun"));   // no such feature
    QVERIFY(d.doc->renameFeature("Sky", "Sky"));     // nothing to do
    QCOMPARE(d.undoSteps(), steps + 1);
}

void TestDocumentFeatures::testRejectedCallsChangeNothing()
{
    FeaturesDocument d;
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Feature> first(d.doc->addFeature("Sky", "sky", sky.data()));
    QVERIFY(first);
    d.settle();
    const int steps = d.undoSteps();

    QVERIFY(!d.doc->addFeature("Sky", "sky", sky.data()));                   // name taken
    QVERIFY(!d.doc->addFeature("", "sky", sky.data()));                      // no name
    QVERIFY(!d.doc->addFeature("Moon", "moon", nullptr));                    // no mask
    QVERIFY(!d.doc->addFeature("Moon", "moon", sky.data(), "robot"));        // unknown author
    QVERIFY(!d.doc->addFeature("Moon", "moon", sky.data(), "agent", "maybe")); // unknown state

    d.settle();
    QCOMPARE(d.undoSteps(), steps);
    QCOMPARE(d.names(), QStringList({"Sky"}));
}

void TestDocumentFeatures::testMaskIsCutToTheDocumentAndCopied()
{
    FeaturesDocument d;
    QScopedPointer<Selection> wide(rectSelection(QRect(-50, 100, 400, 100)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Band", "test", wide.data()));
    QVERIFY(feature);
    QCOMPARE(feature->bounds(), QRect(0, 100, 200, 50));
    QCOMPARE(feature->area(), qint64(200 * 50));

    // Changing the selection afterwards does not change the feature.
    wide->clear();
    QScopedPointer<Selection> mask(feature->mask());
    QVERIFY(mask);
    const QByteArray bytes = mask->pixelData(0, 100, 200, 50);
    QCOMPARE(bytes, QByteArray(200 * 50, char(255)));
    QCOMPARE(mask->pixelData(0, 0, 200, 100), QByteArray(200 * 100, char(0)));

    // Nor does changing the copy it hands out.
    mask->clear();
    QScopedPointer<Selection> again(feature->mask());
    QCOMPARE(again->pixelData(0, 100, 200, 50), QByteArray(200 * 50, char(255)));
}

void TestDocumentFeatures::testFeaturesSurviveSaveAndOpen()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.filePath("features.kra");
    {
        FeaturesDocument d;
        QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
        QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data(), "artist", "kept", true));
        QVERIFY(feature);
        d.settle();
        QVERIFY(d.kisdoc->exportDocumentSync(path, d.kisdoc->nativeFormatMimeType()));
    }

    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY(loaded->loadNativeFormat(path));
    Document doc(loaded.data(), false);
    QScopedPointer<Feature> sky(doc.feature("Sky"));
    QVERIFY(sky);
    QCOMPARE(sky->kind(), QString("sky"));
    QCOMPARE(sky->author(), QString("artist"));
    QCOMPARE(sky->state(), QString("kept"));
    QVERIFY(sky->isProtected());
    QCOMPARE(sky->bounds(), QRect(0, 0, 200, 50));
    QCOMPARE(sky->meanColor(), QColor(Qt::blue));
}

void TestDocumentFeatures::testAddAndRenameInAgentMoveAreOneStep()
{
    FeaturesDocument d;
    const QByteArray before = d.pixels();
    const int steps = d.undoSteps();

    QVERIFY(d.doc->beginAgentMove("find the sky"));
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data()));
    QVERIFY(feature);
    QVERIFY(d.doc->renameFeature("Sky", "Evening sky"));
    QVERIFY(d.doc->agentMoveOpen());
    QVERIFY(d.doc->endAgentMove());
    d.settle();

    // One step, the move's, holding both commands.
    QCOMPARE(d.undoSteps(), steps + 1);
    QCOMPARE(d.doc->undoText(steps), QString("Agent: find the sky"));
    QCOMPARE(d.names(), QStringList({"Evening sky"}));
    QVERIFY(d.pixels() == before);

    // One undo removes both.
    d.undo();
    QVERIFY(d.names().isEmpty());
    QVERIFY(!feature->isInDocument());
    QVERIFY(d.pixels() == before);

    d.redo();
    QCOMPARE(d.names(), QStringList({"Evening sky"}));
}

void TestDocumentFeatures::testWhitespaceNamesAreRejected()
{
    FeaturesDocument d;
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QVERIFY(!d.doc->addFeature("   ", "sky", sky.data()));
    QVERIFY(!d.doc->addFeature("\t\n", "sky", sky.data()));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky", "sky", sky.data()));
    QVERIFY(feature);
    d.settle();
    const int steps = d.undoSteps();

    QVERIFY(!d.doc->renameFeature("Sky", " "));
    QVERIFY(!d.doc->renameFeature("Sky", "\t"));
    d.settle();
    QCOMPARE(d.undoSteps(), steps);
    QCOMPARE(d.names(), QStringList({"Sky"}));
}

void TestDocumentFeatures::testNamesAreTrimmed()
{
    // "Sky" and "Sky " would look the same in every list: names lose their outer spaces.
    FeaturesDocument d;
    QScopedPointer<Selection> sky(rectSelection(QRect(0, 0, 200, 50)));
    QScopedPointer<Feature> feature(d.doc->addFeature("Sky ", "sky", sky.data()));
    QVERIFY(feature);
    QCOMPARE(feature->name(), QString("Sky"));
    QVERIFY(!d.doc->addFeature(" Sky", "sky", sky.data()));
    QVERIFY(!d.doc->addFeature("Sky", "sky", sky.data()));

    QVERIFY(d.doc->renameFeature("Sky", "  Evening sky\t"));
    QCOMPARE(feature->name(), QString("Evening sky"));
    QScopedPointer<Selection> ground(rectSelection(QRect(0, 50, 200, 100)));
    QScopedPointer<Feature> other(d.doc->addFeature("Ground", "ground", ground.data()));
    QVERIFY(other);
    QVERIFY(!d.doc->renameFeature("Ground", "Evening sky "));
    QCOMPARE(d.names(), QStringList({"Evening sky", "Ground"}));
}

void TestDocumentFeatures::testInvertedSelectionGivesABoundedMask()
{
    // An inverted selection is "everything but the sky" out to infinity (its default pixel is selected). The feature
    // keeps only the document's part, so a larger canvas does not select its new borders.
    FeaturesDocument d;
    QScopedPointer<Selection> notSky(rectSelection(QRect(0, 0, 200, 50)));
    notSky->invert();
    QScopedPointer<Feature> feature(d.doc->addFeature("Ground", "ground", notSky.data()));
    QVERIFY(feature);
    QCOMPARE(feature->bounds(), QRect(0, 50, 200, 100));
    QCOMPARE(feature->area(), qint64(200 * 100));
    {
        QScopedPointer<Selection> mask(feature->mask());
        QVERIFY(mask);
        QCOMPARE(mask->pixelData(-20, -20, 10, 10), QByteArray(100, char(0)));
    }

    d.doc->resizeImage(-10, -20, 230, 190);
    d.settle();
    QCOMPARE(d.image->size(), QSize(230, 190));
    QCOMPARE(feature->bounds(), QRect(10, 70, 200, 100));
    QCOMPARE(feature->area(), qint64(200 * 100));
}

KISTEST_TEMPORARY_HOME_MAIN(TestDocumentFeatures)
