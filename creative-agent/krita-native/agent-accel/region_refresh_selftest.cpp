/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
// refreshRect's area (region_refresh.h) on small images built here, without Krita running: build.sh builds and runs it
// after the helper. Each scene has an effect that spreads a change outside the rect it was made in. A stroke is written
// straight into a layer's pixels (as the plugin's setPixelData is on stock: nothing marked dirty), the stroke's rect is
// refreshed the helper's way, and the whole projection must equal what a whole-image refresh then gives. A control
// refreshes exactly the stroke's rect (the helper before protocol 7) and must differ, so each scene really has a halo.
// Exits 1 on any difference.
#include <QCoreApplication>
#include <QTransform>
#include <cstdio>
#include <functional>

#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoCompositeOpRegistry.h>
#include <KoUpdater.h>
#include <KisGlobalResourcesInterface.h>
#include <KisLocalStrokeResources.h>
#include <filter/kis_filter.h>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <filter/kis_filter_registry.h>
#include <kis_adjustment_layer.h>
#include <kis_clone_layer.h>
#include <kis_filter_mask.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_psd_layer_style.h>
#include <kis_selection.h>
#include <kis_transform_mask.h>
#include <psd.h>

#include "KisDumbTransformMaskParams.h"
#include "KritaTransformMaskStubs.h"
#include "region_refresh.h"

static int failures = 0;

static void expect(bool ok, const char *what)
{
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) failures++;
}

static const int BLUR = 8;                               // the test blur's radius

/// A box blur of radius BLUR: what Krita's blur filters are to the update scheduler (changedRect and neededRect grow
/// the rect by the radius) without loading Krita's filter plugins.
class BoxBlur : public KisFilter
{
public:
    static constexpr const char *ID = "agentaccel-test-box-blur";
    BoxBlur() : KisFilter(KoID(ID, ID), FiltersCategoryBlurId, QString()) {}

    void processImpl(KisPaintDeviceSP device, const QRect &applyRect, const KisFilterConfigurationSP, KoUpdater *) const override
    {
        const QRect source = applyRect.adjusted(-BLUR, -BLUR, BLUR, BLUR);
        const int pixel = device->pixelSize();
        QVector<quint8> in(source.width() * source.height() * pixel), out(applyRect.width() * applyRect.height() * pixel);
        device->readBytes(in.data(), source);
        const int side = 2 * BLUR + 1;
        for (int y = 0; y < applyRect.height(); y++) {
            for (int x = 0; x < applyRect.width(); x++) {
                for (int c = 0; c < pixel; c++) {
                    int sum = 0;
                    for (int dy = 0; dy < side; dy++) {
                        for (int dx = 0; dx < side; dx++) sum += in[((y + dy) * source.width() + x + dx) * pixel + c];
                    }
                    out[(y * applyRect.width() + x) * pixel + c] = quint8(sum / (side * side));
                }
            }
        }
        device->writeBytes(out.data(), applyRect);
    }
    QRect neededRect(const QRect &rect, const KisFilterConfigurationSP, int) const override { return rect.adjusted(-BLUR, -BLUR, BLUR, BLUR); }
    QRect changedRect(const QRect &rect, const KisFilterConfigurationSP, int) const override { return rect.adjusted(-BLUR, -BLUR, BLUR, BLUR); }
};

static KisFilterConfigurationSP blur()
{
    KisFilterConfigurationSP config(new KisFilterConfiguration(BoxBlur::ID, 1, KisGlobalResourcesInterface::instance()));
    return config->cloneWithResourcesSnapshot();
}

static const QRect IMAGE(0, 0, 256, 256);

struct Scene {
    KisImageSP image;
    KisPaintLayerSP painted;                             // the layer the stroke is written into
};

static Scene empty()
{
    Scene scene;
    scene.image = new KisImage(nullptr, IMAGE.width(), IMAGE.height(), KoColorSpaceRegistry::instance()->rgb8(), "region test");
    KisPaintLayerSP background = new KisPaintLayer(scene.image, "background", OPACITY_OPAQUE_U8);
    background->paintDevice()->fill(IMAGE, KoColor(QColor(230, 220, 200), background->colorSpace()));
    scene.image->addNode(background);
    scene.painted = new KisPaintLayer(scene.image, "painted", OPACITY_OPAQUE_U8);
    return scene;
}

static void blurMask(Scene &scene, KisLayerSP layer)
{
    KisFilterMaskSP mask = new KisFilterMask(scene.image, "blur");
    mask->setFilter(blur());
    scene.image->addNode(mask, layer);
}

static void blurAbove(Scene &scene, KisNodeSP parent = KisNodeSP())
{
    scene.image->addNode(new KisAdjustmentLayer(scene.image, "blur layer", blur(), KisSelectionSP()), parent ? parent : scene.image->root());
}

static void dropShadow(KisLayerSP layer, int distance)
{
    KisPSDLayerStyleSP style(new KisPSDLayerStyle());
    style->setResourcesInterface(QSharedPointer<KisLocalStrokeResources>(new KisLocalStrokeResources()));
    style->dropShadow()->setEffectEnabled(true);
    style->dropShadow()->setUseGlobalLight(false);
    style->dropShadow()->setAngle(135);                  // down and to the right
    style->dropShadow()->setDistance(distance);
    style->dropShadow()->setSize(6);
    style->dropShadow()->setOpacity(80);
    // Without Krita's colour engine plugin (not loaded here) multiply is missing and the default colour cannot be read.
    style->dropShadow()->setBlendMode(COMPOSITE_OVER);
    style->dropShadow()->setColor(KoColor(Qt::black, KoColorSpaceRegistry::instance()->rgb8()));
    layer->setLayerStyle(style);
}

/// The projection's bytes over the whole image.
static QByteArray pixels(KisImageSP image)
{
    QByteArray bytes(IMAGE.width() * IMAGE.height() * 4, '\0');
    image->projection()->readBytes(reinterpret_cast<quint8 *>(bytes.data()), IMAGE);
    return bytes;
}

/// The first pixel where the two projections differ, or (-1, -1).
static QPoint firstDifference(const QByteArray &a, const QByteArray &b)
{
    for (int i = 0; i < a.size(); i++) {
        if (a[i] != b[i]) return QPoint((i / 4) % IMAGE.width(), (i / 4) / IMAGE.width());
    }
    return QPoint(-1, -1);
}

/**
 * Build the scene twice. Once: stroke, the helper's refresh of the stroke's rect, then a whole refresh, which must change
 * nothing. Again: stroke, a refresh of exactly the stroke's rect, then a whole refresh, which must change something.
 * Returns the rect the helper's refresh recomposited.
 */
static QRect check(const char *name, const std::function<Scene()> &build, const QRect &stroke)
{
    QRect refreshed;
    for (bool helper : {true, false}) {
        Scene scene = build();
        scene.image->initialRefreshGraph();
        scene.painted->paintDevice()->fill(stroke, KoColor(QColor(200, 30, 40), scene.painted->colorSpace()));
        if (helper) {
            refreshed = AgentRegion::refresh(scene.image, stroke);
        } else {
            scene.image->refreshGraphAsync(nullptr, stroke);
            scene.image->waitForDone();
        }
        const QByteArray region = pixels(scene.image);
        scene.image->refreshGraphAsync(nullptr);
        scene.image->waitForDone();
        const QPoint at = firstDifference(region, pixels(scene.image));
        const QByteArray what = QByteArray(name) + (helper ? ": the helper's refresh equals a whole refresh"
                                                           : ": control, a refresh of exactly the stroke leaves a stale halo");
        if (helper && at.x() >= 0) std::printf("     first difference at %d, %d\n", at.x(), at.y());
        expect(helper ? at.x() < 0 : at.x() >= 0, what.constData());
    }
    std::printf("     stroke %d, %d %dx%d -> refreshed %d, %d %dx%d\n", stroke.x(), stroke.y(), stroke.width(), stroke.height(),
                refreshed.x(), refreshed.y(), refreshed.width(), refreshed.height());
    return refreshed;
}

/// KisPSDLayerStyle's constructor reads every effect's default colour from XML, which Krita's colour engine plugin
/// reads and the built-in RGB space (all that is loaded here) cannot: one warning per colour. Everything else passes.
static QtMessageHandler qtHandler = nullptr;

static void quietDefaultColours(QtMsgType type, const QMessageLogContext &context, const QString &message)
{
    if (message.contains(QLatin1String("Undefined operation in the RGB"))) return;
    if (qtHandler) qtHandler(type, context, message);
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    qtHandler = qInstallMessageHandler(quietDefaultColours);
    KisFilterRegistry::instance()->add(KisFilterSP(new BoxBlur()));
    TestUtil::registerTransformMaskStubs();
    const QRect stroke(100, 100, 24, 24);
    const QRect halo = stroke.adjusted(-BLUR, -BLUR, BLUR, BLUR);

    QRect done = check("filter mask", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        blurMask(s, s.painted);
        return s;
    }, stroke);
    expect(done == halo, "filter mask: the area is the stroke grown by the blur, no more");

    done = check("adjustment layer", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        blurAbove(s);
        return s;
    }, stroke);
    expect(done.contains(halo), "adjustment layer: the area holds the blur's spread");

    done = check("drop shadow", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        dropShadow(s.painted, 30);
        return s;
    }, stroke);
    expect(done.contains(stroke.translated(21, 21)), "drop shadow: the area holds the shadow");

    done = check("clone layer", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        blurMask(s, s.painted);
        KisCloneLayerSP clone = new KisCloneLayer(s.painted, s.image, "clone", OPACITY_OPAQUE_U8);
        clone->setX(90);
        clone->setY(-60);
        s.image->addNode(clone);
        return s;
    }, QRect(40, 120, 24, 24));
    expect(done.contains(QRect(40, 120, 24, 24).adjusted(-BLUR, -BLUR, BLUR, BLUR).translated(90, -60)),
           "clone layer: the area holds the clone's copy of the blurred stroke");

    check("clone below its source", [] {
        Scene s = empty();
        KisCloneLayerSP clone = new KisCloneLayer(s.painted, s.image, "clone", OPACITY_OPAQUE_U8);
        clone->setX(-70);
        s.image->addNode(clone);
        s.image->addNode(s.painted);
        dropShadow(s.painted, 12);
        blurAbove(s);
        return s;
    }, stroke);

    done = check("clone of a clone", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        blurMask(s, s.painted);
        KisCloneLayerSP first = new KisCloneLayer(s.painted, s.image, "clone", OPACITY_OPAQUE_U8);
        first->setX(60);
        s.image->addNode(first);
        KisCloneLayerSP second = new KisCloneLayer(first, s.image, "clone of the clone", OPACITY_OPAQUE_U8);
        second->setY(70);
        s.image->addNode(second);
        blurMask(s, second);
        return s;
    }, QRect(40, 40, 24, 24));
    expect(done.contains(QRect(40, 40, 24, 24).adjusted(-2 * BLUR, -2 * BLUR, 2 * BLUR, 2 * BLUR).translated(60, 70)),
           "clone of a clone: the area holds the second clone's twice-blurred copy");

    check("pass-through group", [] {
        Scene s = empty();
        KisGroupLayerSP group = new KisGroupLayer(s.image, "pass-through", OPACITY_OPAQUE_U8);
        group->setPassThroughMode(true);
        s.image->addNode(group);
        s.image->addNode(new KisPaintLayer(s.image, "under", OPACITY_OPAQUE_U8), group);
        s.image->addNode(s.painted, group);
        blurMask(s, s.painted);
        blurAbove(s, group);                             // inside the group, over the painted layer
        blurAbove(s);                                    // over the group
        return s;
    }, stroke);

    check("group with a filter mask", [] {
        Scene s = empty();
        KisGroupLayerSP group = new KisGroupLayer(s.image, "group", OPACITY_OPAQUE_U8);
        s.image->addNode(group);
        s.image->addNode(s.painted, group);
        blurMask(s, group);
        return s;
    }, stroke);

    done = check("transform mask", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        KisTransformMaskSP mask = new KisTransformMask(s.image, "move");
        mask->setTransformParams(KisTransformMaskParamsInterfaceSP(new KisDumbTransformMaskParams(QTransform::fromTranslate(60, 30))));
        s.image->addNode(mask, s.painted);
        return s;
    }, stroke);
    expect(done.contains(stroke.translated(60, 30)), "transform mask: the area holds the moved stroke");

    check("shadow under a blur layer", [] {
        Scene s = empty();
        s.image->addNode(s.painted);
        dropShadow(s.painted, 30);
        blurAbove(s);
        return s;
    }, stroke);

    // A stroke at the image's edge: the area is cut to the image; one wholly outside does nothing.
    {
        Scene s = empty();
        s.image->addNode(s.painted);
        blurMask(s, s.painted);
        s.image->initialRefreshGraph();
        expect(AgentRegion::refresh(s.image, QRect(-10, -10, 20, 20)) == QRect(0, 0, 10 + BLUR, 10 + BLUR), "the area is cut to the image");
        expect(AgentRegion::refresh(s.image, QRect(300, 300, 10, 10)).isEmpty(), "a rect outside the image refreshes nothing");
    }

    // Without effects the area is the rect itself.
    {
        Scene s = empty();
        s.image->addNode(s.painted);
        s.image->initialRefreshGraph();
        expect(AgentRegion::refresh(s.image, stroke) == stroke, "plain layers: the area is the rect");
    }

    std::printf("%s: %d failure(s)\n", failures ? "FAILED" : "passed", failures);
    return failures ? 1 : 0;
}
