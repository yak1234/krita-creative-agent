/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "KisFeatureImageCommandTest.h"

#include <QTest>

#include <cmath>

#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorConversionTransformation.h>

#include <KisFeature.h>
#include <KisFeatureImageCommand.h>
#include <KisFeatureList.h>
#include <kis_filter_strategy.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_processing_applicator.h>
#include <kis_selection.h>
#include <kis_undo_stores.h>
#include <KisFeatureCommands.h>
#include <KoMixColorsOp.h>
#include <commands/kis_node_opacity_command.h>
#include <processing/kis_mirror_processing_visitor.h>

#include <KisTemporaryHomeTest.h>
#include <KoTestConfig.h>

namespace {

/// The area every mask is compared over: larger than any image here, so a mask moved off the image shows.
const QRect wholeArea(-100, -100, 600, 600);

/// A 200 x 100 painting: red on the left half, blue on the right, a green square at (20, 20, 40, 40). Two features:
/// "Square" (the green square exactly) and "Band" (80, 70, 40, 20), half red and half blue.
struct OpsImage {
    KisSurrogateUndoStore *undoStore;
    KisImageSP image;
    KisPaintLayerSP layer;

    explicit OpsImage(bool withFeatures = true)
        : undoStore(new KisSurrogateUndoStore())
    {
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(undoStore, 200, 100, cs, "features");
        layer = new KisPaintLayer(image, "painting", OPACITY_OPAQUE_U8);
        layer->paintDevice()->fill(QRect(0, 0, 100, 100), KoColor(Qt::red, cs));
        layer->paintDevice()->fill(QRect(100, 0, 100, 100), KoColor(Qt::blue, cs));
        layer->paintDevice()->fill(QRect(20, 20, 40, 40), KoColor(Qt::green, cs));
        image->addNode(layer);
        image->initialRefreshGraph();
        image->waitForDone();
        if (!withFeatures) return;
        add("Square", QRect(20, 20, 40, 40));
        add("Band", QRect(80, 70, 40, 20));
    }

    void add(const QString &name, const QRect &rect)
    {
        KisPixelSelectionSP mask = new KisPixelSelection();
        mask->select(rect, MAX_SELECTED);
        KisFeatureSP feature = new KisFeature(name, "test", mask);
        feature->measure(image->projection());
        image->featureList()->insertFeature(feature);
    }

    /// The feature called \p name; a missing one is an empty stand-in, so a test fails instead of crashing.
    KisFeatureSP feature(const QString &name) const
    {
        KisFeatureSP found = image->featureList()->featureByName(name);
        return found ? found : KisFeatureSP(new KisFeature("missing " + name, "missing", KisPixelSelectionSP()));
    }

    void undo()
    {
        undoStore->undo();
        image->waitForDone();
    }

    void redo()
    {
        undoStore->redo();
        image->waitForDone();
    }
};

/// What a feature is at one moment: its properties and every byte of its mask.
struct Snapshot {
    QSize imageSize;
    QList<KisFeature::Properties> properties;
    QList<QByteArray> masks;

    static Snapshot of(const OpsImage &o)
    {
        Snapshot s;
        s.imageSize = o.image->size();
        Q_FOREACH (KisFeatureSP f, o.image->featureList()->features()) {
            s.properties << f->properties();
            QByteArray bytes(wholeArea.width() * wholeArea.height(), 0);
            f->mask()->readBytes(reinterpret_cast<quint8 *>(bytes.data()), wholeArea);
            s.masks << bytes;
        }
        return s;
    }

    bool operator==(const Snapshot &rhs) const
    {
        return imageSize == rhs.imageSize && properties == rhs.properties && masks == rhs.masks;
    }
};

/// The pixels where the feature's mask (at half or more) and the painting's green disagree, inside the image.
int mismatch(const OpsImage &o, const QString &name)
{
    const QRect rect = o.image->bounds();
    QByteArray mask(rect.width() * rect.height(), 0);
    KisFeatureSP feature = o.feature(name);
    if (!feature) return -1;
    feature->mask()->readBytes(reinterpret_cast<quint8 *>(mask.data()), rect);
    QByteArray paint(rect.width() * rect.height() * 4, 0);
    o.layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(paint.data()), rect);
    int count = 0;
    for (int i = 0; i < rect.width() * rect.height(); i++) {
        const quint8 b = quint8(paint[4 * i]), g = quint8(paint[4 * i + 1]), r = quint8(paint[4 * i + 2]);
        const quint8 a = quint8(paint[4 * i + 3]);
        const bool green = a >= 128 && g >= 128 && r < 128 && b < 128;
        const bool selected = quint8(mask[i]) >= 128;
        count += green != selected ? 1 : 0;
    }
    return count;
}

QColor toQColor(const KoColor &color)
{
    QColor c;
    color.toQColor(&c);
    return c;
}

/// Undo puts the features back as they were before the operation, and redo as they were after it.
void checkUndoRedo(OpsImage &o, const Snapshot &before, const Snapshot &after)
{
    QVERIFY(!(before == after));
    o.undo();
    QVERIFY(Snapshot::of(o) == before);
    o.redo();
    QVERIFY(Snapshot::of(o) == after);
    o.undo();
    QVERIFY(Snapshot::of(o) == before);
}

} // namespace

void KisFeatureImageCommandTest::initTestCase()
{
    // The colour-space plugins and the profiles they need, from the build's own folders as KISTEST_MAIN finds them,
    // before the colour-space registry's first use: plugins without their profiles cannot convert colours.
    qputenv("EXTRA_RESOURCE_DIRS", QByteArray(KRITA_RESOURCE_DIRS_FOR_TESTS));
    qputenv("KRITA_PLUGIN_PATH", QByteArray(KRITA_PLUGINS_DIR_FOR_TESTS));
}

void KisFeatureImageCommandTest::testCrop()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);
    QCOMPARE(toQColor(o.feature("Band")->meanColor()), QColor(128, 0, 128));

    o.image->cropImage(QRect(10, 5, 90, 90));
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(90, 90));
    QCOMPARE(o.feature("Square")->bounds(), QRect(10, 15, 40, 40));
    QCOMPARE(o.feature("Square")->area(), qint64(1600));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(toQColor(o.feature("Square")->meanColor()), QColor(Qt::green));
    // The band's blue half is cut away: measured again on the cropped painting, it is red.
    QCOMPARE(o.feature("Band")->bounds(), QRect(70, 65, 20, 20));
    QCOMPARE(o.feature("Band")->area(), qint64(400));
    QCOMPARE(toQColor(o.feature("Band")->meanColor()), QColor(Qt::red));

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testCanvasResizeGrows()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->resizeImage(QRect(-30, -10, 300, 150));
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(300, 150));
    QCOMPARE(o.feature("Square")->bounds(), QRect(50, 30, 40, 40));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(o.feature("Band")->bounds(), QRect(110, 80, 40, 20));
    QCOMPARE(o.feature("Band")->area(), qint64(800));
    QCOMPARE(o.feature("Band")->meanColor(), before.properties[1].meanColor);

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testCanvasResizeShrinks()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->resizeImage(QRect(0, 0, 90, 100));
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(90, 100));
    QCOMPARE(o.feature("Square")->bounds(), QRect(20, 20, 40, 40));
    // Cut to the canvas, and measured on what is left of it.
    QCOMPARE(o.feature("Band")->bounds(), QRect(80, 70, 10, 20));
    QCOMPARE(o.feature("Band")->area(), qint64(200));
    QCOMPARE(toQColor(o.feature("Band")->meanColor()), QColor(Qt::red));

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testScale()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->scaleImage(QSize(400, 200), o.image->xRes(), o.image->yRes(),
                        KisFilterStrategyRegistry::instance()->value("NearestNeighbor"));
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(400, 200));
    QCOMPARE(o.feature("Square")->bounds(), QRect(40, 40, 80, 80));
    QCOMPARE(o.feature("Square")->area(), qint64(6400));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(toQColor(o.feature("Square")->meanColor()), QColor(Qt::green));
    QCOMPARE(o.feature("Band")->bounds(), QRect(160, 140, 80, 40));

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testRotate90()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->rotateImage(M_PI / 2);
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(100, 200));
    // Clockwise: (x, y) goes to (99 - y, x).
    QCOMPARE(o.feature("Square")->bounds(), QRect(40, 20, 40, 40));
    QCOMPARE(o.feature("Square")->area(), qint64(1600));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(o.feature("Band")->bounds(), QRect(10, 80, 20, 40));
    QCOMPARE(o.feature("Band")->meanColor(), before.properties[1].meanColor);

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testRotateFreeAngle()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->rotateImage(M_PI / 6);
    o.image->waitForDone();

    QVERIFY(o.image->size() != QSize(200, 100));
    // Resampled like the painting: they agree but for the edge pixels (the square's perimeter is 160).
    const int edge = mismatch(o, "Square");
    QVERIFY2(edge <= 160, qPrintable(QString::number(edge)));
    const qint64 area = o.feature("Square")->area();
    QVERIFY2(qAbs(area - 1600) <= 160, qPrintable(QString::number(area)));
    const QColor mean = toQColor(o.feature("Square")->meanColor());
    QVERIFY2(mean.green() >= 200 && mean.red() <= 60 && mean.blue() <= 60, qPrintable(mean.name()));

    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testShear()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    o.image->shear(20, 0);
    o.image->waitForDone();

    QVERIFY(o.image->size().width() > 200);
    const int edge = mismatch(o, "Square");
    QVERIFY2(edge <= 160, qPrintable(QString::number(edge)));
    const qint64 area = o.feature("Square")->area();
    QVERIFY2(qAbs(area - 1600) <= 160, qPrintable(QString::number(area)));

    checkUndoRedo(o, before, Snapshot::of(o));
}

namespace {
/// What KisNodeManager::mirrorNodes() does (libs/ui), with the same ending.
void mirror(OpsImage &o, KisNodeList nodes, Qt::Orientation orientation, KisSelectionSP selection)
{
    KisProcessingApplicator applicator(o.image, nodes, KisProcessingApplicator::RECURSIVE, KisImageSignalVector(),
                                       kundo2_noi18n("Mirror"));
    KisProcessingVisitorSP visitor = selection ? new KisMirrorProcessingVisitor(selection, orientation)
                                               : new KisMirrorProcessingVisitor(o.image->bounds(), orientation);
    if (!selection) {
        applicator.applyVisitorAllFrames(visitor, KisStrokeJobData::CONCURRENT);
    } else {
        applicator.applyVisitor(visitor, KisStrokeJobData::CONCURRENT);
    }
    KisFeatureImageCommand::endMirrorApplicator(applicator, o.image, nodes, selection, orientation);
    o.image->waitForDone();
}
} // namespace

void KisFeatureImageCommandTest::testMirror()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);

    mirror(o, {o.image->root()}, Qt::Horizontal, nullptr);
    QCOMPARE(o.feature("Square")->bounds(), QRect(140, 20, 40, 40));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(o.feature("Band")->bounds(), QRect(80, 70, 40, 20));
    checkUndoRedo(o, before, Snapshot::of(o));

    mirror(o, {o.image->root()}, Qt::Vertical, nullptr);
    QCOMPARE(o.feature("Square")->bounds(), QRect(20, 40, 40, 40));
    QCOMPARE(mismatch(o, "Square"), 0);
    QCOMPARE(o.feature("Band")->bounds(), QRect(80, 10, 40, 20));
    checkUndoRedo(o, before, Snapshot::of(o));
}

void KisFeatureImageCommandTest::testMirrorOfSelectedAreaLeavesMasks()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);
    KisSelectionSP selection = new KisSelection();
    selection->pixelSelection()->select(QRect(0, 0, 100, 100), MAX_SELECTED);

    mirror(o, {o.image->root()}, Qt::Horizontal, selection);
    QVERIFY(Snapshot::of(o) == before);
    mirror(o, {KisNodeSP(o.layer)}, Qt::Horizontal, nullptr);
    QVERIFY(Snapshot::of(o) == before);
}

void KisFeatureImageCommandTest::testColorSpaceConversionMeasuresAgain()
{
    OpsImage o;
    const Snapshot before = Snapshot::of(o);
    const KoColorSpace *rgb16 = KoColorSpaceRegistry::instance()->rgb16();
    QVERIFY(rgb16);

    o.image->convertImageColorSpace(rgb16, KoColorConversionTransformation::internalRenderingIntent(),
                                    KoColorConversionTransformation::internalConversionFlags());
    o.image->waitForDone();

    QCOMPARE(*o.image->colorSpace(), *rgb16);
    Q_FOREACH (KisFeatureSP f, o.image->featureList()->features()) {
        QVERIFY(f->properties().hasMeanColor);
        QCOMPARE(*f->meanColor().colorSpace(), *rgb16);
    }
    QCOMPARE(o.feature("Square")->meanColor(), KoColor(Qt::green, rgb16));
    // The band's mean is a mix, and mixing is done in the new colour space (rgb16's profile may be linear, so it is
    // not the 8-bit mean converted): it is what measuring the converted painting gives.
    const KisFeature::Properties remeasured = KisFeature::measureMask(o.feature("Band")->mask(), o.image->projection());
    QVERIFY(remeasured.hasMeanColor);
    QCOMPARE(o.feature("Band")->meanColor(), remeasured.meanColor);
    QCOMPARE(o.feature("Square")->bounds(), QRect(20, 20, 40, 40));

    checkUndoRedo(o, before, Snapshot::of(o));
    QCOMPARE(*o.feature("Square")->meanColor().colorSpace(), *KoColorSpaceRegistry::instance()->rgb8());
}

void KisFeatureImageCommandTest::testImageWithoutFeatures()
{
    // Upstream's path exactly: no command joins the operation, and no measuring stroke follows it.
    OpsImage o(false);
    const int commands = KisFeatureImageCommand::commandsCreated();
    const int strokes = KisFeatureImageCommand::measureStrokesStarted();
    o.image->cropImage(QRect(10, 5, 90, 90));
    o.image->waitForDone();
    QCOMPARE(o.image->size(), QSize(90, 90));
    QVERIFY(o.image->featureList()->isEmpty());
    o.undo();
    QCOMPARE(o.image->size(), QSize(200, 100));
    QVERIFY2(KisFeatureImageCommand::commandsCreated() == commands,
             qPrintable(QString("commands %1 -> %2").arg(commands).arg(KisFeatureImageCommand::commandsCreated())));
    QVERIFY2(KisFeatureImageCommand::measureStrokesStarted() == strokes, "measure strokes");

    // With features, one of each per operation.
    OpsImage withFeatures;
    withFeatures.image->cropImage(QRect(10, 5, 90, 90));
    withFeatures.image->waitForDone();
    QVERIFY2(KisFeatureImageCommand::commandsCreated() == commands + 1,
             qPrintable(QString("with features: commands %1 -> %2").arg(commands)
                            .arg(KisFeatureImageCommand::commandsCreated())));
    QVERIFY2(KisFeatureImageCommand::measureStrokesStarted() == strokes + 1, "with features: measure strokes");
}

void KisFeatureImageCommandTest::testCropAfterQueuedUndoOfRemove()
{
    // The list is empty when the crop is asked for, but an undo queued before it brings a feature back: the crop
    // must still move that feature.
    OpsImage o;
    o.image->featureList()->removeFeature(o.feature("Band")->id());
    KisFeatureSP square = o.feature("Square");
    KisProcessingApplicator::runSingleCommandStroke(o.image, new KisRemoveFeatureCommand(o.image, square->id()));
    o.image->waitForDone();
    QVERIFY(o.image->featureList()->isEmpty());

    o.image->barrierLock(); // holds the queue, so the undo is still waiting when the crop is asked for
    o.undoStore->undo();
    o.image->cropImage(QRect(10, 5, 90, 90));
    o.image->unlock();
    o.image->waitForDone();

    QCOMPARE(o.image->size(), QSize(90, 90));
    QVERIFY(o.image->featureList()->featureByName("Square"));
    QCOMPARE(o.feature("Square")->bounds(), QRect(10, 15, 40, 40));
    QCOMPARE(mismatch(o, "Square"), 0);
}

void KisFeatureImageCommandTest::testLayerRotateAndShearLeaveMasks()
{
    // Operations on layers, not the image, move the painting under the features like any other edit: the masks
    // stay byte for byte, and nothing joins or follows the operation.
    OpsImage o;
    const Snapshot before = Snapshot::of(o);
    const int commands = KisFeatureImageCommand::commandsCreated();
    const int strokes = KisFeatureImageCommand::measureStrokesStarted();

    o.image->rotateNode(o.layer, M_PI / 6, nullptr);
    o.image->waitForDone();
    o.image->shearNode(o.layer, 20, 0, nullptr);
    o.image->waitForDone();
    o.image->rotateNode(o.image->root(), M_PI / 2, nullptr);
    o.image->waitForDone();

    QVERIFY(Snapshot::of(o) == before);
    QCOMPARE(KisFeatureImageCommand::commandsCreated(), commands);
    QCOMPARE(KisFeatureImageCommand::measureStrokesStarted(), strokes);
}

void KisFeatureImageCommandTest::testUndoAfterALaterStep()
{
    // Crop, then another step: undoing back past both puts the features back; undoing only the later one keeps them
    // cropped.
    OpsImage o;
    const Snapshot before = Snapshot::of(o);
    o.image->cropImage(QRect(10, 5, 90, 90));
    o.image->waitForDone();
    const Snapshot cropped = Snapshot::of(o);

    KisProcessingApplicator::runSingleCommandStroke(o.image,
                                                    new KisNodeOpacityCommand(o.layer, 128));
    o.image->waitForDone();
    QCOMPARE(int(o.layer->opacity()), 128);

    o.undo();
    QCOMPARE(int(o.layer->opacity()), int(OPACITY_OPAQUE_U8));
    QVERIFY(Snapshot::of(o) == cropped);
    o.undo();
    QVERIFY(Snapshot::of(o) == before);
    o.redo();
    QVERIFY(Snapshot::of(o) == cropped);
    o.redo();
    QCOMPARE(int(o.layer->opacity()), 128);
    QVERIFY(Snapshot::of(o) == cropped);
}

void KisFeatureImageCommandTest::testConvertedMeanIsTheMixOfConvertedColors()
{
    OpsImage o;
    const KoColorSpace *rgb16 = KoColorSpaceRegistry::instance()->rgb16();
    QVERIFY(rgb16);
    o.image->convertImageColorSpace(rgb16, KoColorConversionTransformation::internalRenderingIntent(),
                                    KoColorConversionTransformation::internalConversionFlags());
    o.image->waitForDone();

    // The band is half red, half blue: its mean is the even mix of the two colours as converted.
    const KoColorSpace *rgb8 = KoColorSpaceRegistry::instance()->rgb8();
    KoColor red(Qt::red, rgb8);
    red.convertTo(rgb16);
    KoColor blue(Qt::blue, rgb8);
    blue.convertTo(rgb16);
    QScopedPointer<KoMixColorsOp::Mixer> mixer(rgb16->mixColorsOp()->createMixer());
    const qint16 weight = 255;
    mixer->accumulate(red.data(), &weight, 255, 1);
    mixer->accumulate(blue.data(), &weight, 255, 1);
    KoColor expected(rgb16);
    mixer->computeMixedColor(expected.data());

    QVERIFY(o.image->featureList()->featureByName("Band"));
    QCOMPARE(o.feature("Band")->meanColor(), expected);
}

KIS_TEMPORARY_HOME_TEST_MAIN(KisFeatureImageCommandTest)
