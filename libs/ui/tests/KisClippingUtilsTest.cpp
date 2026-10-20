/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "KisClippingUtilsTest.h"

#include <simpletest.h>
#include <functional>

#include "KisClippingUtils.h"
#include "kis_node_juggler_compressed.h"
#include "kis_image.h"
#include "kis_paint_layer.h"
#include "kis_group_layer.h"
#include "kis_transparency_mask.h"
#include <Node.h>
#include <KoCompositeOpRegistry.h>
#include <KoColor.h>
#include <KoColorSpace.h>

using namespace KisClippingUtils;

KisPaintLayerSP KisClippingUtilsTest::newLayer(const QString &name, bool inheritAlpha)
{
    KisPaintLayerSP layer = new KisPaintLayer(p->image, name, OPACITY_OPAQUE_U8);
    if (inheritAlpha) {
        layer->disableAlphaChannel(true);
    }
    return layer;
}

QStringList KisClippingUtilsTest::hierarchy() const
{
    return TestUtil::getHierarchy(p->image->root());
}

// Runs the juggler on the image and waits until its undo step is in.
bool KisClippingUtilsTest::runJuggler(const std::function<void(KisNodeJugglerCompressed *)> &fn)
{
    KisNodeJugglerCompressed juggler(kundo2_i18n("Test"), p->image, nullptr, 600);
    fn(&juggler);
    juggler.end();
    p->image->waitForDone();
    return true;
}

void KisClippingUtilsTest::init()
{
    p.reset(new TestUtil::MaskParent); // image with "paint1"
    base = p->layer;
    p->image->initialRefreshGraph();
}

void KisClippingUtilsTest::cleanup()
{
    base.clear();
    p.reset();
}

void KisClippingUtilsTest::testPredicates()
{
    KisPaintLayerSP clipped = newLayer("clipped", true);
    KisPaintLayerSP plain = newLayer("plain");
    KisGroupLayerSP group = new KisGroupLayer(p->image, "stack", OPACITY_OPAQUE_U8);
    KisPaintLayerSP stackBase = newLayer("stackBase");

    p->image->addNode(group);
    p->image->addNode(stackBase, group);
    p->image->addNode(plain);

    QVERIFY(!hasInheritAlpha(KisNodeSP()));
    QVERIFY(!hasInheritAlpha(plain));
    QVERIFY(!hasInheritAlpha(p->image->root()->firstChild()->parent())); // the root is not a layer with alpha inheritance
    QVERIFY(!isClippingGroup(KisNodeSP()));
    QVERIFY(!isClippingGroup(plain));
    QVERIFY(!isClippingGroup(group));        // its only child does not inherit alpha
    QVERIFY(!isTopClippedLayer(KisNodeSP()));

    p->image->addNode(clipped, group);       // on top of the group's children
    QVERIFY(hasInheritAlpha(clipped));
    QVERIFY(isClippingGroup(group));
    QVERIFY(isTopClippedLayer(clipped));
    QVERIFY(!isTopClippedLayer(stackBase));

    // a clipped layer that is not on top of its group is not "top"
    KisPaintLayerSP above = newLayer("above");
    p->image->addNode(above, group);
    QVERIFY(!isClippingGroup(group));
    QVERIFY(!isTopClippedLayer(clipped));
}

void KisClippingUtilsTest::testNewLayerRule()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "stack", OPACITY_OPAQUE_U8);
    KisPaintLayerSP stackBase = newLayer("stackBase");
    KisPaintLayerSP mid = newLayer("mid", true);
    KisPaintLayerSP top = newLayer("top", true);
    p->image->addNode(group);
    p->image->addNode(stackBase, group);
    p->image->addNode(mid, group);
    p->image->addNode(top, group);

    QVERIFY(isClippingGroup(group));
    // a new layer directly above a middle clipped layer joins the stack
    QVERIFY(shouldEnableInheritAlphaForNewLayer(mid, group, mid));
    // above the top clipped layer it goes outside (no inheritance), above the base nothing changes either
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(top, group, top));
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(stackBase, group, stackBase));
    // placed elsewhere, or missing arguments
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(mid, p->image->root(), group));
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(KisNodeSP(), group, mid));
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(mid, KisNodeSP(), mid));
    QVERIFY(!shouldEnableInheritAlphaForNewLayer(mid, group, KisNodeSP()));
}

void KisClippingUtilsTest::testDropRules()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "stack", OPACITY_OPAQUE_U8);
    KisPaintLayerSP stackBase = newLayer("stackBase");
    KisPaintLayerSP mid = newLayer("mid", true);
    KisPaintLayerSP top = newLayer("top", true);
    p->image->addNode(group);
    p->image->addNode(stackBase, group);
    p->image->addNode(mid, group);
    p->image->addNode(top, group);

    // dropping between base and mid (above the base): the layer above is clipped -> joins
    {
        KisNodeSP parent = group;
        KisNodeSP above = stackBase;
        QVERIFY(adjustDropTarget(&parent, &above));
        QCOMPARE(parent, KisNodeSP(group));
        QCOMPARE(above, KisNodeSP(stackBase));
    }
    // dropping above the top clipped layer lands outside, above the group, not clipped
    {
        KisNodeSP parent = group;
        KisNodeSP above = top;
        QVERIFY(!adjustDropTarget(&parent, &above));
        QCOMPARE(parent, KisNodeSP(p->image->root()));
        QCOMPARE(above, KisNodeSP(group));
    }
    // an ordinary group or null arguments change nothing
    {
        KisNodeSP parent = p->image->root();
        KisNodeSP above = base;
        QVERIFY(!adjustDropTarget(&parent, &above));
        QCOMPARE(parent, KisNodeSP(p->image->root()));
        QCOMPARE(above, KisNodeSP(base));
        QVERIFY(!adjustDropTarget(nullptr, &above));
        QVERIFY(!adjustDropTarget(&parent, nullptr));
        KisNodeSP none;
        QVERIFY(!adjustDropTarget(&none, &above));
    }
    // dropping at the very bottom of the group (no layer to insert above): the bottom child is the base's neighbour
    QVERIFY(shouldEnableInheritAlphaForDrop(group, KisNodeSP()) == hasInheritAlpha(group->firstChild()));
}

void KisClippingUtilsTest::testPlanClipToLayerBelow()
{
    KisPaintLayerSP l2 = newLayer("l2");
    KisPaintLayerSP l3 = newLayer("l3");
    p->image->addNode(l2);
    p->image->addNode(l3);

    // plain layer over a plain layer: group them, base below, active last
    ClipPlan plan = planClipToLayerBelow(l3);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    QCOMPARE(plan.base, KisNodeSP(l2));
    QCOMPARE(plan.stack.size(), 2);
    QCOMPARE(plan.stack.first(), KisNodeSP(l2));
    QCOMPARE(plan.stack.last(), KisNodeSP(l3));

    // a layer that inherits alpha already: the action releases it
    l3->disableAlphaChannel(true);
    plan = planClipToLayerBelow(l3);
    QCOMPARE(plan.action, ClipPlan::Release);
    l3->disableAlphaChannel(false);

    // clipping above an already clipped layer: the base is found below the chain
    l2->disableAlphaChannel(true);
    plan = planClipToLayerBelow(l3);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    QCOMPARE(plan.base, KisNodeSP(base));
    QCOMPARE(plan.stack.size(), 3);
    QCOMPARE(plan.stack.at(0), KisNodeSP(base));
    QCOMPARE(plan.stack.at(1), KisNodeSP(l2));
    QCOMPARE(plan.stack.at(2), KisNodeSP(l3));
    l2->disableAlphaChannel(false);

    // inside a (non-root) group whose bottom is the base: only the property is needed
    KisGroupLayerSP group = new KisGroupLayer(p->image, "g", OPACITY_OPAQUE_U8);
    KisPaintLayerSP gb = newLayer("gb");
    KisPaintLayerSP gt = newLayer("gt");
    p->image->addNode(group);
    p->image->addNode(gb, group);
    p->image->addNode(gt, group);
    plan = planClipToLayerBelow(gt);
    QCOMPARE(plan.action, ClipPlan::ClipInPlace);

    // a group below: clipped to its whole composition, unless the clipping mask view joins clip stacks
    KisPaintLayerSP above = newLayer("above");
    p->image->addNode(above);
    plan = planClipToLayerBelow(above);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    QCOMPARE(plan.base, KisNodeSP(group));

    gt->disableAlphaChannel(true); // now "g" is a clipping group
    QVERIFY(isClippingGroup(group));
    plan = planClipToLayerBelow(above, false);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    plan = planClipToLayerBelow(above, true);
    QCOMPARE(plan.action, ClipPlan::JoinGroup);
    QCOMPARE(plan.group, KisNodeSP(group));
}

void KisClippingUtilsTest::testPlanWithNoLayerBelowOrOnMasks()
{
    // the bottom layer has nothing below it
    QCOMPARE(planClipToLayerBelow(base).action, ClipPlan::None);
    // null, the root, a mask
    QCOMPARE(planClipToLayerBelow(KisNodeSP()).action, ClipPlan::None);
    QCOMPARE(planClipToLayerBelow(p->image->root()).action, ClipPlan::None);
    KisTransparencyMaskSP mask = new KisTransparencyMask(p->image, "mask");
    p->image->addNode(mask, base);
    QCOMPARE(planClipToLayerBelow(mask).action, ClipPlan::None);

    // a layer whose lower neighbour does not exist inside its group
    KisGroupLayerSP group = new KisGroupLayer(p->image, "g", OPACITY_OPAQUE_U8);
    KisPaintLayerSP only = newLayer("only");
    p->image->addNode(group);
    p->image->addNode(only, group);
    QCOMPARE(planClipToLayerBelow(only).action, ClipPlan::None);

    // applying a None plan changes nothing and asks for no juggler
    bool askedForJuggler = false;
    QVERIFY(!applyClipPlan(planClipToLayerBelow(only), p->image, [&] () {
        askedForJuggler = true;
        return static_cast<KisNodeJugglerCompressed*>(nullptr);
    }));
    QVERIFY(!askedForJuggler);
    QVERIFY(!applyClipPlan(ClipPlan(), p->image, [&] () { return static_cast<KisNodeJugglerCompressed*>(nullptr); }));
}

void KisClippingUtilsTest::testJugglerDefaultKeepsAlphaAsIs()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "g", OPACITY_OPAQUE_U8);
    KisPaintLayerSP l2 = newLayer("l2");
    p->image->addNode(group);
    p->image->addNode(l2);
    p->image->initialRefreshGraph();

    // no argument: the parameter defaults to false and the moved layer keeps its alpha channel as it is
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->moveNode(KisNodeList() << l2, group, KisNodeSP());
    });
    QCOMPARE(l2->parent(), KisNodeSP(group));
    QVERIFY(!l2->alphaChannelDisabled());

    // moving a layer that inherits alpha already, flag off: stays inheriting (nothing is cleared)
    KisPaintLayerSP l3 = newLayer("l3", true);
    p->image->addNode(l3);
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->moveNode(KisNodeList() << l3, group, l2, false);
    });
    QVERIFY(l3->alphaChannelDisabled());
}

void KisClippingUtilsTest::testJugglerEnableInheritAlphaMoveCopyAdd()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "g", OPACITY_OPAQUE_U8);
    KisPaintLayerSP l2 = newLayer("l2");
    KisPaintLayerSP l3 = newLayer("l3");
    p->image->addNode(group);
    p->image->addNode(l2);
    p->image->addNode(l3);
    p->image->initialRefreshGraph();

    // move with the flag: the layer lands in the group and inherits alpha
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->moveNode(KisNodeList() << l2, group, KisNodeSP(), true);
    });
    QCOMPARE(l2->parent(), KisNodeSP(group));
    QVERIFY(l2->alphaChannelDisabled());

    // undo is one step and restores both the place and the property
    p->undoStore->undo();
    p->image->waitForDone();
    QCOMPARE(l2->parent(), KisNodeSP(p->image->root()));
    QVERIFY(!l2->alphaChannelDisabled());

    // copy with the flag: the copy inherits alpha, the original does not
    const int before = p->image->root()->childCount();
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->copyNode(KisNodeList() << l3, group, KisNodeSP(), true);
    });
    QCOMPARE(p->image->root()->childCount(), before);   // the copy went into the group, not the root
    QCOMPARE(group->childCount(), 1u);
    QVERIFY(group->firstChild()->inherits("KisPaintLayer"));
    QVERIFY(qobject_cast<KisLayer*>(group->firstChild().data())->alphaChannelDisabled());
    QVERIFY(!l3->alphaChannelDisabled());
    p->undoStore->undo();
    p->image->waitForDone();
    QCOMPARE(group->childCount(), 0u);

    // add with the flag
    KisPaintLayerSP fresh = newLayer("fresh");
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->addNode(KisNodeList() << fresh, group, KisNodeSP(), true);
    });
    QCOMPARE(fresh->parent(), KisNodeSP(group));
    QVERIFY(fresh->alphaChannelDisabled());

    // copy without the flag: unchanged behaviour
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->copyNode(KisNodeList() << l3, p->image->root(), l3);
    });
    KisNodeSP copy = l3->nextSibling();
    QVERIFY(copy);
    QVERIFY(!qobject_cast<KisLayer*>(copy.data())->alphaChannelDisabled());
}

void KisClippingUtilsTest::testApplyGroupAndClip()
{
    KisPaintLayerSP l2 = newLayer("l2");
    KisPaintLayerSP l3 = newLayer("l3");
    p->image->addNode(l2);
    p->image->addNode(l3);
    p->image->initialRefreshGraph();

    const QStringList initial = hierarchy();
    QCOMPARE(initial, QStringList() << "paint1" << "l2" << "l3");

    const ClipPlan plan = planClipToLayerBelow(l3);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);

    QScopedPointer<KisNodeJugglerCompressed> juggler;
    QVERIFY(applyClipPlan(plan, p->image, [&] () {
        juggler.reset(new KisNodeJugglerCompressed(kundo2_i18n("Clip"), p->image, nullptr, 600));
        return juggler.data();
    }));
    QVERIFY(juggler);
    juggler->end();
    p->image->waitForDone();

    // group above, holding l2 (base, bottom) and l3 (clipped, on top)
    QStringList h = hierarchy();
    QCOMPARE(h.size(), 4);
    QCOMPARE(h[0], QString("paint1"));
    QVERIFY(h[1].startsWith("Clipping Group"));
    QCOMPARE(h[2], QString("+l2"));
    QCOMPARE(h[3], QString("+l3"));
    QVERIFY(!l2->alphaChannelDisabled());
    QVERIFY(l3->alphaChannelDisabled());
    QVERIFY(isClippingGroup(l3->parent()));

    // one undo step brings everything back
    p->undoStore->undo();
    p->image->waitForDone();
    QCOMPARE(hierarchy(), initial);
    QVERIFY(!l3->alphaChannelDisabled());
}

void KisClippingUtilsTest::testApplyGroupAndClipChain()
{
    // base <- c1 (clipped) <- active: the new layer is clipped to the same base, in the same group
    KisPaintLayerSP c1 = newLayer("c1", true);
    KisPaintLayerSP active = newLayer("active");
    KisPaintLayerSP below = newLayer("below");
    p->image->addNode(below);
    p->image->addNode(c1);
    p->image->addNode(active);
    p->image->initialRefreshGraph();

    const ClipPlan plan = planClipToLayerBelow(active);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    QCOMPARE(plan.base, KisNodeSP(below));

    QScopedPointer<KisNodeJugglerCompressed> juggler;
    QVERIFY(applyClipPlan(plan, p->image, [&] () {
        juggler.reset(new KisNodeJugglerCompressed(kundo2_i18n("Clip"), p->image, nullptr, 600));
        return juggler.data();
    }));
    juggler->end();
    p->image->waitForDone();

    QStringList h = hierarchy();
    QCOMPARE(h.size(), 5);
    QCOMPARE(h[0], QString("paint1"));
    QVERIFY(h[1].startsWith("Clipping Group"));
    QCOMPARE(h[2], QString("+below"));
    QCOMPARE(h[3], QString("+c1"));
    QCOMPARE(h[4], QString("+active"));
    QVERIFY(c1->alphaChannelDisabled());
    QVERIFY(active->alphaChannelDisabled());
    QVERIFY(!below->alphaChannelDisabled());
}

void KisClippingUtilsTest::testApplyClipInPlaceAndRelease()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "g", OPACITY_OPAQUE_U8);
    KisPaintLayerSP gb = newLayer("gb");
    KisPaintLayerSP gt = newLayer("gt");
    p->image->addNode(group);
    p->image->addNode(gb, group);
    p->image->addNode(gt, group);
    p->image->initialRefreshGraph();

    bool askedForJuggler = false;
    auto noJuggler = [&] () {
        askedForJuggler = true;
        return static_cast<KisNodeJugglerCompressed*>(nullptr);
    };

    QVERIFY(applyClipPlan(planClipToLayerBelow(gt), p->image, noJuggler));
    p->image->waitForDone();
    QVERIFY(gt->alphaChannelDisabled());

    QCOMPARE(planClipToLayerBelow(gt).action, ClipPlan::Release);
    QVERIFY(applyClipPlan(planClipToLayerBelow(gt), p->image, noJuggler));
    p->image->waitForDone();
    QVERIFY(!gt->alphaChannelDisabled());

    QVERIFY(!askedForJuggler); // property changes need no juggler
}

void KisClippingUtilsTest::testApplyJoinGroup()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "stack", OPACITY_OPAQUE_U8);
    KisPaintLayerSP sb = newLayer("sb");
    KisPaintLayerSP sc = newLayer("sc", true);
    KisPaintLayerSP joiner = newLayer("joiner");
    p->image->addNode(group);
    p->image->addNode(sb, group);
    p->image->addNode(sc, group);
    p->image->addNode(joiner);
    p->image->initialRefreshGraph();

    const ClipPlan plan = planClipToLayerBelow(joiner, true);
    QCOMPARE(plan.action, ClipPlan::JoinGroup);

    QScopedPointer<KisNodeJugglerCompressed> juggler;
    QVERIFY(applyClipPlan(plan, p->image, [&] () {
        juggler.reset(new KisNodeJugglerCompressed(kundo2_i18n("Clip"), p->image, nullptr, 600));
        return juggler.data();
    }));
    juggler->end();
    p->image->waitForDone();

    QCOMPARE(joiner->parent(), KisNodeSP(group));
    QCOMPARE(group->lastChild(), KisNodeSP(joiner));
    QVERIFY(joiner->alphaChannelDisabled());
    QVERIFY(isClippingGroup(group));

    p->undoStore->undo();
    p->image->waitForDone();
    QCOMPARE(joiner->parent(), KisNodeSP(p->image->root()));
    QVERIFY(!joiner->alphaChannelDisabled());
}

// An agent builds a clip stack through libkis exactly as the plugin's create_layer does (layer_craft.py): a clip base in
// a group, the clipped layer added on top and Node.setInheritAlpha(True) (clip_to). That path does not go through the layer
// manager or the juggler, so it must work unchanged, and the stack it makes must read as a clip group here.
void KisClippingUtilsTest::testClipToKeepsAgentStyleClipStackUntouched()
{
    KisGroupLayerSP groupLayer = new KisGroupLayer(p->image, "Creative Agent · flat", OPACITY_OPAQUE_U8);
    KisPaintLayerSP flat = newLayer("flat");
    KisPaintLayerSP shadow = newLayer("shadow");
    p->image->addNode(groupLayer);
    p->image->initialRefreshGraph();

    QScopedPointer<Node> group(Node::createNode(p->image, groupLayer));
    QScopedPointer<Node> flatNode(Node::createNode(p->image, flat));
    QScopedPointer<Node> shadowNode(Node::createNode(p->image, shadow));
    QVERIFY(group && flatNode && shadowNode);

    QVERIFY(group->addChildNode(flatNode.data(), nullptr));
    QVERIFY(group->addChildNode(shadowNode.data(), flatNode.data()));
    QVERIFY(!shadowNode->inheritAlpha());
    shadowNode->setInheritAlpha(true);               // clip_to
    p->image->waitForDone();

    QVERIFY(shadowNode->inheritAlpha());
    QVERIFY(shadow->alphaChannelDisabled());
    QVERIFY(!flatNode->inheritAlpha());
    QCOMPARE(hierarchy(), QStringList() << "paint1" << "Creative Agent · flat" << "+flat" << "+shadow");

    // the docker's rules see a clip group with its clipped top layer
    QVERIFY(isClippingGroup(groupLayer));
    QVERIFY(isTopClippedLayer(shadow));
    QVERIFY(!isTopClippedLayer(flat));
    // a layer added above the clipped one inside the group (a second clip_to) keeps the stack readable
    KisPaintLayerSP light = newLayer("light");
    QScopedPointer<Node> lightNode(Node::createNode(p->image, light));
    QVERIFY(group->addChildNode(lightNode.data(), shadowNode.data()));
    lightNode->setInheritAlpha(true);
    p->image->waitForDone();
    QVERIFY(isClippingGroup(groupLayer));
    QVERIFY(isTopClippedLayer(light));
    QVERIFY(!isTopClippedLayer(shadow));

    // and the clip action on an agent-made clipped layer releases only that layer
    const ClipPlan plan = planClipToLayerBelow(light);
    QCOMPARE(plan.action, ClipPlan::Release);
    QVERIFY(applyClipPlan(plan, p->image, [] () { return static_cast<KisNodeJugglerCompressed*>(nullptr); }));
    p->image->waitForDone();
    QVERIFY(!light->alphaChannelDisabled());
    QVERIFY(shadow->alphaChannelDisabled());
}

void KisClippingUtilsTest::testDropBelowTheBaseGoesUnderTheGroup()
{
    KisGroupLayerSP group = new KisGroupLayer(p->image, "stack", OPACITY_OPAQUE_U8);
    KisPaintLayerSP stackBase = newLayer("stackBase");
    KisPaintLayerSP top = newLayer("top", true);
    p->image->addNode(group);
    p->image->addNode(stackBase, group);
    p->image->addNode(top, group);
    QVERIFY(isClippingGroup(group));

    // dropped at the bottom of the group (aboveThis null): outside, directly under the group, never clipped
    KisNodeSP parent = group;
    KisNodeSP above;
    QVERIFY(!adjustDropTarget(&parent, &above));
    QCOMPARE(parent, KisNodeSP(p->image->root()));
    QCOMPARE(above, KisNodeSP(base)); // the layer that was under the group

    // the juggler puts a layer there: it lands below the group, the stack keeps its two layers
    KisPaintLayerSP dropped = newLayer("dropped");
    p->image->addNode(dropped);
    p->image->initialRefreshGraph();
    runJuggler([&] (KisNodeJugglerCompressed *j) {
        j->moveNode(KisNodeList() << dropped, parent, above, false);
    });
    QCOMPARE(group->childCount(), 2u);
    QCOMPARE(dropped->nextSibling(), KisNodeSP(group));
    QVERIFY(!dropped->alphaChannelDisabled());
}

void KisClippingUtilsTest::testNoBaseToClipToIsRefusedWithAReason()
{
    // every layer below is clipped and nothing is under them: the layer would clip to nothing, so nothing is done
    KisPaintLayerSP l2 = newLayer("l2", true);
    KisPaintLayerSP l3 = newLayer("l3");
    base->disableAlphaChannel(true);
    p->image->addNode(l2);
    p->image->addNode(l3);

    const ClipPlan plan = planClipToLayerBelow(l3);
    QCOMPARE(plan.action, ClipPlan::None);
    QVERIFY(!plan.reason.isEmpty());
    QVERIFY(!applyClipPlan(plan, p->image, [] () { return static_cast<KisNodeJugglerCompressed*>(nullptr); }));
    QVERIFY(!l3->alphaChannelDisabled());

    // the other refusals carry a reason too
    QVERIFY(!planClipToLayerBelow(KisNodeSP()).reason.isEmpty());
    base->disableAlphaChannel(false);
    QVERIFY(!planClipToLayerBelow(base).reason.isEmpty());
}

void KisClippingUtilsTest::testGroupAndClipMovesBlendModeAndOpacityToTheGroup()
{
    // a Multiply base over a coloured background: the base keeps its look when it goes into the new (isolated) group
    const KoColorSpace *cs = p->image->colorSpace();
    base->paintDevice()->fill(QRect(0, 0, 512, 512), KoColor(QColor(200, 100, 50), cs));   // the background layer

    KisPaintLayerSP mult = newLayer("mult");
    mult->paintDevice()->fill(QRect(0, 0, 100, 100), KoColor(QColor(128, 128, 255), cs));
    mult->setCompositeOpId(COMPOSITE_MULT);
    mult->setOpacity(128);
    KisPaintLayerSP shadow = newLayer("shadow");
    shadow->paintDevice()->fill(QRect(50, 50, 200, 200), KoColor(QColor(0, 0, 0), cs));
    p->image->addNode(mult);
    p->image->addNode(shadow);
    p->image->initialRefreshGraph();
    p->image->waitForDone();

    auto pixelAt = [&] (int x, int y) {
        p->image->refreshGraphAsync();
        p->image->waitForDone();
        return p->image->projection()->convertToQImage(nullptr, QRect(x, y, 1, 1)).pixelColor(0, 0);
    };
    const QColor beforeBaseOnly = pixelAt(10, 10);     // only the multiplied base over the background there
    QVERIFY(beforeBaseOnly != QColor(200, 100, 50));

    const ClipPlan plan = planClipToLayerBelow(shadow);
    QCOMPARE(plan.action, ClipPlan::GroupAndClip);
    QScopedPointer<KisNodeJugglerCompressed> juggler;
    QVERIFY(applyClipPlan(plan, p->image, [&] () {
        juggler.reset(new KisNodeJugglerCompressed(kundo2_i18n("Clip"), p->image, nullptr, 600));
        return juggler.data();
    }));
    juggler->end();
    p->image->waitForDone();

    KisNodeSP group = mult->parent();
    QVERIFY(group != KisNodeSP(p->image->root()));
    QCOMPARE(group->compositeOpId(), COMPOSITE_MULT);
    QCOMPARE(group->opacity(), quint8(128));
    QCOMPARE(mult->compositeOpId(), COMPOSITE_OVER);
    QCOMPARE(mult->opacity(), OPACITY_OPAQUE_U8);
    QVERIFY(shadow->alphaChannelDisabled());

    // where only the base is (no clipped layer there) the picture is what it was
    const QColor afterBaseOnly = pixelAt(10, 10);
    QVERIFY2(qAbs(afterBaseOnly.red() - beforeBaseOnly.red()) <= 2 &&
             qAbs(afterBaseOnly.green() - beforeBaseOnly.green()) <= 2 &&
             qAbs(afterBaseOnly.blue() - beforeBaseOnly.blue()) <= 2,
             qPrintable(QString("before %1 after %2").arg(beforeBaseOnly.name(), afterBaseOnly.name())));

    // one undo restores the base's own look and the picture
    p->undoStore->undo();
    p->image->waitForDone();
    QCOMPARE(mult->parent(), KisNodeSP(p->image->root()));
    QCOMPARE(mult->compositeOpId(), COMPOSITE_MULT);
    QCOMPARE(mult->opacity(), quint8(128));
    QCOMPARE(pixelAt(10, 10), beforeBaseOnly);
}

SIMPLE_TEST_MAIN(KisClippingUtilsTest)
