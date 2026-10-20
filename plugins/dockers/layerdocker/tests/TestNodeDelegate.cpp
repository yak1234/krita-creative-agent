/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "TestNodeDelegate.h"

#include <QTest>
#include <QImage>
#include <QPainter>
#include <QStyleOptionViewItem>

#include <NodeView.h>
#include <NodeDelegate.h>

#include "KisDocument.h"
#include "KisPart.h"
#include "kis_name_server.h"
#include "flake/kis_shape_controller.h"
#include "kis_undo_adapter.h"
#include "kis_node_model.h"
#include "kis_icon_utils.h"
#include "kis_config.h"

#include <kis_config_notifier.h>
#include <kis_node_view_color_scheme.h>
#include <QSignalSpy>
#include <kis_group_layer.h>
#include <kis_paint_layer.h>
#include <Node.h>

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <testresources.h>

void TestNodeDelegate::init()
{
    m_doc = KisPart::instance()->createDocument();
    m_nameServer = new KisNameServer();
    m_shapeController = new KisShapeController(m_nameServer, m_doc->undoStack());
    initBase();
}

void TestNodeDelegate::setClippingView(bool on)
{
    KisConfig cfg(false);
    cfg.setClippingMaskViewEnabled(on);
    KisConfigNotifier::instance()->notifyConfigChanged();
}

void TestNodeDelegate::cleanup()
{
    setClippingView(false);
    cleanupBase();
    delete m_shapeController;
    delete m_nameServer;
    delete m_doc;
    m_shapeController = nullptr;
    m_nameServer = nullptr;
    m_doc = nullptr;
}

void TestNodeDelegate::testGroupRowHeightFunction()
{
    QCOMPARE(NodeDelegate::groupRowHeight(30, 70), 21);
    QCOMPARE(NodeDelegate::groupRowHeight(30, 100), 30);
    QCOMPARE(NodeDelegate::groupRowHeight(31, 70), 22); // rounds to nearest
    // out-of-range preferences are clamped to 40..100
    QCOMPARE(NodeDelegate::groupRowHeight(30, 10), 12);
    QCOMPARE(NodeDelegate::groupRowHeight(30, 5000), 30);
    QCOMPARE(NodeDelegate::groupRowHeight(30, -5), 12);
    // never zero, never taller than a layer row, also for degenerate bases
    QCOMPARE(NodeDelegate::groupRowHeight(0, 70), 1);
    QCOMPARE(NodeDelegate::groupRowHeight(1, 40), 1);
    QCOMPARE(NodeDelegate::groupRowHeight(-3, 70), 1);
}

void TestNodeDelegate::testGroupRowsAreShorterThanLayerRows()
{
    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);

    constructImage();
    m_shapeController->setImage(m_image);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);

    QAbstractItemDelegate *delegate = view.itemDelegate();
    QVERIFY(delegate);

    const QModelIndex paintIndex = model.indexFromNode(m_layer1);
    const QModelIndex groupIndex = model.indexFromNode(m_layer2);
    const QModelIndex group2Index = model.indexFromNode(m_layer4);
    QVERIFY(paintIndex.isValid());
    QVERIFY(groupIndex.isValid());
    QVERIFY(group2Index.isValid());

    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 200, 40);

    const QSize paintSize = delegate->sizeHint(option, paintIndex);
    const QSize groupSize = delegate->sizeHint(option, groupIndex);
    QVERIFY(paintSize.height() > 0);

    KisConfig cfg(true);
    const int percent = cfg.groupRowHeightPercent();
    QCOMPARE(groupSize.height(), NodeDelegate::groupRowHeight(paintSize.height(), percent));
    if (percent < 100) {
        QVERIFY(groupSize.height() < paintSize.height());
    }
    QCOMPARE(delegate->sizeHint(option, group2Index), groupSize);
    QCOMPARE(groupSize.width(), paintSize.width());

    // the visibility column follows the same rule
    const QModelIndex paintVis = paintIndex.sibling(paintIndex.row(), NodeView::VISIBILITY_COL);
    const QModelIndex groupVis = groupIndex.sibling(groupIndex.row(), NodeView::VISIBILITY_COL);
    if (paintVis.isValid() && groupVis.isValid()) {
        QCOMPARE(delegate->sizeHint(option, groupVis).height(), groupSize.height());
        QCOMPARE(delegate->sizeHint(option, paintVis).height(), paintSize.height());
    }

    // an invalid index is not a group: no crash, the layer row height
    QCOMPARE(delegate->sizeHint(option, QModelIndex()).height(), paintSize.height());
}

void TestNodeDelegate::testHitRectsFollowTheGroupRowHeight()
{
    // The click rectangles are private; paint a group row and a layer row and check that the group row's painted
    // content stays inside its shorter rect (nothing is drawn below it).
    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    constructImage();
    m_shapeController->setImage(m_image);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);

    QAbstractItemDelegate *delegate = view.itemDelegate();
    QVERIFY(delegate);
    const QModelIndex groupIndex = model.indexFromNode(m_layer2);
    QVERIFY(groupIndex.isValid());

    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 200, 40);
    const int h = delegate->sizeHint(option, groupIndex).height();
    QVERIFY(h > 0 && h <= 40);

    QImage img(200, 80, QImage::Format_ARGB32);
    img.fill(Qt::transparent);
    option.rect = QRect(0, 0, 200, h);
    option.state = QStyle::State_Enabled;
    {
        QPainter p(&img);
        delegate->paint(&p, option, groupIndex);
    }
    // below the row (with some slack for a one pixel frame) the image is untouched
    for (int y = h + 2; y < img.height(); y++) {
        for (int x = 0; x < img.width(); x++) {
            QVERIFY2(qAlpha(img.pixel(x, y)) == 0, qPrintable(QString("painted outside the group row at %1,%2").arg(x).arg(y)));
        }
    }
}

void TestNodeDelegate::testGroupRowsPaintAFolderIcon()
{
    if (KisIconUtils::loadIcon("folderClosed").isNull() || KisIconUtils::loadIcon("folderOpened").isNull()) {
        // the icon resources are compiled into the krita program, not into the test programs
        QSKIP("the folder icons are in the application's resources, which this test program does not have");
    }

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    constructImage();
    m_shapeController->setImage(m_image);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);

    QAbstractItemDelegate *delegate = view.itemDelegate();
    QVERIFY(delegate);
    const QModelIndex groupIndex = model.indexFromNode(m_layer2);
    QVERIFY(groupIndex.isValid());

    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 220, 40);
    const int h = delegate->sizeHint(option, groupIndex).height();
    option.rect = QRect(0, 0, 220, h);

    auto render = [&](QStyle::State state) {
        QImage img(220, h + 4, QImage::Format_ARGB32);
        img.fill(Qt::white);
        QStyleOptionViewItem o = option;
        o.state = state | QStyle::State_Enabled;
        QPainter p(&img);
        delegate->paint(&p, o, groupIndex);
        return img;
    };

    const QImage closed = render(QStyle::State_None);
    const QImage opened = render(QStyle::State_Open);
    QVERIFY(closed != opened); // the open and the closed folder differ

    // and a layer row (a thumbnail) does not equal a group row
    const QModelIndex paintIndex = model.indexFromNode(m_layer1);
    QVERIFY(paintIndex.isValid());
    QImage paintRow(220, h + 4, QImage::Format_ARGB32);
    paintRow.fill(Qt::white);
    {
        QStyleOptionViewItem o = option;
        o.state = QStyle::State_Enabled;
        QPainter p(&paintRow);
        delegate->paint(&p, o, paintIndex);
    }
    QVERIFY(paintRow != closed);
}


void TestNodeDelegate::testAltClickBoundaryIgnoresExpandedGroups()
{
    // root, bottom to top: layer1, group layer2 [ga, gb], layer5 (plain, above the group)
    m_image->addNode(m_layer1);
    m_image->addNode(m_layer2);
    KisPaintLayerSP ga = new KisPaintLayer(m_image, "ga", OPACITY_OPAQUE_U8);
    KisPaintLayerSP gb = new KisPaintLayer(m_image, "gb", OPACITY_OPAQUE_U8);
    KisPaintLayerSP above = new KisPaintLayer(m_image, "above", OPACITY_OPAQUE_U8);
    m_image->addNode(ga, m_layer2);
    m_image->addNode(gb, m_layer2);
    m_image->addNode(above);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();

    // rows top first: above, group (expanded: gb, ga), layer1
    const QModelIndex rAbove = model.indexFromNode(above);
    const QModelIndex rGroup = model.indexFromNode(m_layer2);
    const QModelIndex rGb = model.indexFromNode(gb);
    const QModelIndex rGa = model.indexFromNode(ga);
    QVERIFY(rAbove.isValid() && rGroup.isValid() && rGb.isValid() && rGa.isValid());
    const QRect rcGroup = view.visualRect(rGroup);
    const QRect rcGb = view.visualRect(rGb);
    const int x = 60;

    // above | group header: a real boundary between siblings
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(x, rcGroup.top())), rAbove);
    // the group header's bottom touches its first child, not its sibling: no boundary
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, rcGroup.bottom())).isValid());
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, rcGb.top())).isValid() ||
            view.clipBoundaryUpperIndexAt(QPoint(x, rcGb.top())) != rGroup);
    // between the children it is a boundary (siblings, same parent)
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(x, view.visualRect(rGa).top())), rGb);

    // collapsed, the group's bottom edge is a real boundary again (to layer1)
    view.collapse(rGroup);
    const QRect collapsed = view.visualRect(rGroup);
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(x, collapsed.bottom())), rGroup);
    // and the row below an expanded sibling: layer above an expanded group has no boundary at the group's last child
    view.expand(rGroup);
}

namespace {
/// root, bottom to top: layer1, wrapper group [stackBase, clipped], plain layer "above" over the wrapper
struct WrapperStack {
    KisPaintLayerSP stackBase, clipped, above;
};
}

void TestNodeDelegate::testAltClickBoundaryJoinsAClipStackFromTheLayerAbove()
{
    m_image->addNode(m_layer1);
    m_image->addNode(m_layer2);
    WrapperStack w;
    w.stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    w.clipped = new KisPaintLayer(m_image, "clipped", OPACITY_OPAQUE_U8);
    w.above = new KisPaintLayer(m_image, "above", OPACITY_OPAQUE_U8);
    m_image->addNode(w.stackBase, m_layer2);
    m_image->addNode(w.clipped, m_layer2);
    w.clipped->disableAlphaChannel(true);
    m_image->addNode(w.above);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);
    setClippingView(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();

    const QModelIndex rAbove = model.indexFromNode(w.above);
    const QModelIndex rWrapper = model.indexFromNode(m_layer2);
    const QModelIndex rClipped = model.indexFromNode(w.clipped);
    QVERIFY(view.isClippingWrapper(rWrapper));
    QVERIFY(!view.isClippingWrapper(rAbove));

    // the layer above touches the top clipped layer (first child of the hidden wrapper): the boundary's upper layer is
    // the layer above, so the clip action reaches JoinGroup by gesture
    const QRect rcClipped = view.visualRect(rClipped);
    QVERIFY(rcClipped.height() > 0);
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(60, rcClipped.top())), rAbove);
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(60, view.visualRect(rAbove).bottom())), rAbove);
}

void TestNodeDelegate::testCollapsedClipWrapperIsShownExpanded()
{
    m_image->addNode(m_layer2);
    KisPaintLayerSP stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    KisPaintLayerSP clipped = new KisPaintLayer(m_image, "clipped", OPACITY_OPAQUE_U8);
    m_image->addNode(stackBase, m_layer2);
    m_image->addNode(clipped, m_layer2);
    clipped->disableAlphaChannel(true);
    m_layer2->setCollapsed(true);                 // as in an agent's file
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);
    setClippingView(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    const QModelIndex wrapper = model.indexFromNode(m_layer2);
    QVERIFY(wrapper.isValid());
    view.collapseAll();
    QVERIFY(!view.isExpanded(wrapper));

    view.expandClippingWrappers();
    QVERIFY(view.isExpanded(wrapper));
    QVERIFY(view.visualRect(model.indexFromNode(clipped)).height() > 0);   // its stack is on screen
    QVERIFY(m_layer2->collapsed());                                         // the node's own flag is not touched

    // view mode off: nothing is forced
    setClippingView(false);
    view.collapseAll();
    view.expandClippingWrappers();
    QVERIFY(!view.isExpanded(wrapper));
}

void TestNodeDelegate::testKeyboardNavigationSkipsHiddenWrappers()
{
    m_image->addNode(m_layer2);
    KisPaintLayerSP stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    KisPaintLayerSP clipped = new KisPaintLayer(m_image, "clipped", OPACITY_OPAQUE_U8);
    KisPaintLayerSP above = new KisPaintLayer(m_image, "above", OPACITY_OPAQUE_U8);
    KisPaintLayerSP below = new KisPaintLayer(m_image, "below", OPACITY_OPAQUE_U8);
    m_image->addNode(below, m_image->root(), KisNodeSP());
    m_image->addNode(stackBase, m_layer2);
    m_image->addNode(clipped, m_layer2);
    clipped->disableAlphaChannel(true);
    m_image->addNode(above);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);
    setClippingView(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();
    view.show();

    const QModelIndex rWrapper = model.indexFromNode(m_layer2);
    QVERIFY(view.isClippingWrapper(rWrapper));

    // Down from the layer above lands on the top clipped layer, never on the wrapper
    view.setCurrentIndex(model.indexFromNode(above));
    QTest::keyClick(&view, Qt::Key_Down);
    QCOMPARE(view.currentIndex().sibling(view.currentIndex().row(), 0), model.indexFromNode(clipped));
    // and Up from the base goes up through the clipped layer, then over the wrapper to the layer above
    view.setCurrentIndex(model.indexFromNode(stackBase));
    QTest::keyClick(&view, Qt::Key_Up);
    QCOMPARE(view.currentIndex().sibling(view.currentIndex().row(), 0), model.indexFromNode(clipped));
    QTest::keyClick(&view, Qt::Key_Up);
    QCOMPARE(view.currentIndex().sibling(view.currentIndex().row(), 0), model.indexFromNode(above));
    // Down through the whole stack to the layer below the wrapper
    view.setCurrentIndex(model.indexFromNode(stackBase));
    QTest::keyClick(&view, Qt::Key_Down);
    QCOMPARE(view.currentIndex().sibling(view.currentIndex().row(), 0), model.indexFromNode(below));
    view.hide();
}

void TestNodeDelegate::testOnlyAClipStateChangeRelayouts()
{
    m_image->addNode(m_layer2);
    KisPaintLayerSP stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    KisPaintLayerSP top = new KisPaintLayer(m_image, "top", OPACITY_OPAQUE_U8);
    KisPaintLayerSP other = new KisPaintLayer(m_image, "other", OPACITY_OPAQUE_U8);
    m_image->addNode(stackBase, m_layer2);
    m_image->addNode(top, m_layer2);
    m_image->addNode(other);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);
    setClippingView(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();

    const QModelIndex idx = model.indexFromNode(top);
    QVERIFY(idx.isValid());
    QSignalSpy relayouts(view.itemDelegate(), SIGNAL(sizeHintChanged(QModelIndex)));

    // The very first change on a row nobody has touched since the load is a change: no earlier dataChanged for it.
    top->disableAlphaChannel(true);
    Q_EMIT model.dataChanged(idx, idx);
    QVERIFY(relayouts.count() >= 1);
    relayouts.clear();

    // thumbnails during painting: the clip state is unchanged, repeatedly: no relayout
    for (int i = 0; i < 20; i++) {
        Q_EMIT model.dataChanged(idx, idx);
    }
    QCOMPARE(relayouts.count(), 0);

    // and back: the group stops being a wrapper
    top->disableAlphaChannel(false);
    Q_EMIT model.dataChanged(idx, idx);
    QVERIFY(relayouts.count() >= 1);
    relayouts.clear();
    Q_EMIT model.dataChanged(idx, idx);
    QCOMPARE(relayouts.count(), 0);

    // a row that never changes state stays quiet from the start
    const QModelIndex otherIdx = model.indexFromNode(other);
    for (int i = 0; i < 5; i++) {
        Q_EMIT model.dataChanged(otherIdx, otherIdx);
    }
    QCOMPARE(relayouts.count(), 0);
}

void TestNodeDelegate::testKeyboardLeftRightEndSkipHiddenWrappers()
{
    m_image->addNode(m_layer2);
    KisPaintLayerSP stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    KisPaintLayerSP clipped = new KisPaintLayer(m_image, "clipped", OPACITY_OPAQUE_U8);
    KisPaintLayerSP below = new KisPaintLayer(m_image, "below", OPACITY_OPAQUE_U8);
    m_image->addNode(below, m_image->root(), KisNodeSP());
    m_image->addNode(stackBase, m_layer2);
    m_image->addNode(clipped, m_layer2);
    clipped->disableAlphaChannel(true);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);
    setClippingView(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();
    view.show();

    const QModelIndex rWrapper = model.indexFromNode(m_layer2);
    QVERIFY(view.isClippingWrapper(rWrapper));

    // Left on a child goes to its parent, the hidden wrapper: it must not stay there
    view.setCurrentIndex(model.indexFromNode(clipped));
    QTest::keyClick(&view, Qt::Key_Left);
    QVERIFY(view.currentIndex().sibling(view.currentIndex().row(), 0) != rWrapper);
    QVERIFY(view.currentIndex().isValid());
    // End goes to the last row (a real one)
    QTest::keyClick(&view, Qt::Key_End);
    QVERIFY(view.currentIndex().sibling(view.currentIndex().row(), 0) != rWrapper);
    // Right never lands on the wrapper either
    view.setCurrentIndex(model.indexFromNode(below));
    QTest::keyClick(&view, Qt::Key_Right);
    QVERIFY(view.currentIndex().sibling(view.currentIndex().row(), 0) != rWrapper);
    view.hide();
}

void TestNodeDelegate::testGroupRowFloor()
{
    // never below the floor (property icons), never above the layer row
    QCOMPARE(NodeDelegate::groupRowHeight(30, 40, 25), 25);
    QCOMPARE(NodeDelegate::groupRowHeight(30, 70, 25), 25);
    QCOMPARE(NodeDelegate::groupRowHeight(30, 100, 25), 30);
    QCOMPARE(NodeDelegate::groupRowHeight(20, 40, 25), 20);
    QCOMPARE(NodeDelegate::groupRowHeight(30, 70, 1), 21);

    // and in the delegate: a group row is at least as tall as the icons with their borders
    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    constructImage();
    m_shapeController->setImage(m_image);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 200, 40);
    const int group = view.itemDelegate()->sizeHint(option, model.indexFromNode(m_layer2)).height();
    const int layer = view.itemDelegate()->sizeHint(option, model.indexFromNode(m_layer1)).height();
    KisNodeViewColorScheme scm;
    QVERIFY(group >= qMin(layer, scm.iconSize() + 2 * scm.border()));
    QVERIFY(group <= layer);
}

namespace {

/// x of the first column that has anything but the white background, or -1
int leftmostInk(const QImage &img)
{
    for (int x = 0; x < img.width(); x++) {
        for (int y = 0; y < img.height(); y++) {
            if (img.pixel(x, y) != qRgb(255, 255, 255)) return x;
        }
    }
    return -1;
}

}

void TestNodeDelegate::testClippingViewIsOffByDefault()
{
    KisConfig cfg(true);
    QVERIFY(!cfg.clippingMaskViewEnabled(true));
    QVERIFY(!cfg.clippingMaskViewEnabled());
    QCOMPARE(cfg.groupRowHeightPercent(true), 70);
}

void TestNodeDelegate::testClippingViewHidesTheClipGroupAndIndentsClippedLayers()
{
    // root: paint1-like layer1, group layer2 [layer3 as base, mask-less clipped layer4... built by hand]
    constructImage();
    m_shapeController->setImage(m_image);

    KisPaintLayerSP stackBase = new KisPaintLayer(m_image, "stackBase", OPACITY_OPAQUE_U8);
    KisPaintLayerSP clipped = new KisPaintLayer(m_image, "clipped", OPACITY_OPAQUE_U8);
    m_image->addNode(stackBase, m_layer2);
    m_image->addNode(clipped, m_layer2);
    clipped->disableAlphaChannel(true);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.expandAll();

    QAbstractItemDelegate *delegate = view.itemDelegate();
    QVERIFY(delegate);
    const QModelIndex groupIndex = model.indexFromNode(m_layer2);
    const QModelIndex clippedIndex = model.indexFromNode(clipped);
    const QModelIndex baseIndex = model.indexFromNode(stackBase);
    QVERIFY(groupIndex.isValid() && clippedIndex.isValid() && baseIndex.isValid());

    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 220, 40);
    option.state = QStyle::State_Enabled;

    // Off: the group is a visible folder row, clipped layers are drawn like any layer
    const int folderHeight = delegate->sizeHint(option, groupIndex).height();
    QVERIFY(folderHeight > 0);
    const int layerHeight = delegate->sizeHint(option, clippedIndex).height();

    auto renderRow = [&] (const QModelIndex &index, int height, int xOffset = 0) {
        QImage img(220, qMax(1, height) + 4, QImage::Format_ARGB32);
        img.fill(Qt::white);
        QStyleOptionViewItem o = option;
        o.rect = QRect(xOffset, 0, 220 - xOffset, qMax(1, height));
        QPainter p(&img);
        delegate->paint(&p, o, index);
        return img;
    };
    const QImage clippedOff = renderRow(clippedIndex, layerHeight);

    // On: the group that holds a clip stack takes no room and paints nothing
    setClippingView(true);
    QCOMPARE(delegate->sizeHint(option, groupIndex).height(), 0);
    QCOMPARE(delegate->sizeHint(option, groupIndex.sibling(groupIndex.row(), NodeView::VISIBILITY_COL)).height(), 0);
    QImage hidden(220, 10, QImage::Format_ARGB32);
    hidden.fill(Qt::white);
    {
        QStyleOptionViewItem o = option;
        o.rect = QRect(0, 0, 220, 10);
        QPainter p(&hidden);
        delegate->paint(&p, o, groupIndex);
    }
    QCOMPARE(leftmostInk(hidden), -1);

    // clipped layers keep their row height, the base is a plain layer row, other groups still get folder rows
    QCOMPARE(delegate->sizeHint(option, clippedIndex).height(), layerHeight);
    QCOMPARE(delegate->sizeHint(option, baseIndex).height(), layerHeight);
    QCOMPARE(delegate->sizeHint(option, model.indexFromNode(m_layer4)).height(), folderHeight);

    // the clipped layer is moved in a little to make room for the arrow, the base is not
    const QImage clippedOn = renderRow(clippedIndex, layerHeight);
    QVERIFY(leftmostInk(clippedOn) >= 0 && leftmostInk(clippedOff) >= 0);
    QVERIFY(leftmostInk(clippedOn) != leftmostInk(clippedOff) || clippedOn != clippedOff);
    // The tree view hands a child row a rectangle indented by one level; with the group hidden, the delegate takes that
    // level out again, so the base is drawn where a top-level layer would be.
    const QImage baseOn = renderRow(baseIndex, layerHeight, view.indentation());
    setClippingView(false);
    const QImage baseTopLevel = renderRow(baseIndex, layerHeight, 0);
    // (the frame's bottom line starts at the row's own left edge, so compare right of it)
    const QRect rightOfFrame(3 * view.indentation(), 0, 220 - 3 * view.indentation(), baseOn.height());
    QCOMPARE(baseOn.copy(rightOfFrame), baseTopLevel.copy(rightOfFrame));

    // switching back restores the folder row
    QCOMPARE(delegate->sizeHint(option, groupIndex).height(), folderHeight);
}

void TestNodeDelegate::testAgentBuiltClipStackLooksRightInTheDocker()
{
    // The agent's plugin builds a clip stack through libkis (Node.addChildNode + Node.setInheritAlpha, "clip_to") and
    // never touches the layer manager or the juggler. Built that way, the stack must read in the docker like Revamp's.
    m_image->addNode(m_layer1);
    m_image->addNode(m_layer2);
    m_image->addNode(m_layer4);
    m_image->initialRefreshGraph();
    m_shapeController->setImage(m_image);

    KisPaintLayerSP flat = new KisPaintLayer(m_image, "flat", OPACITY_OPAQUE_U8);
    KisPaintLayerSP shadow = new KisPaintLayer(m_image, "shadow", OPACITY_OPAQUE_U8);
    QScopedPointer<Node> group(Node::createNode(m_image, m_layer2));
    QScopedPointer<Node> flatNode(Node::createNode(m_image, flat));
    QScopedPointer<Node> shadowNode(Node::createNode(m_image, shadow));
    QVERIFY(group->addChildNode(flatNode.data(), nullptr));
    QVERIFY(group->addChildNode(shadowNode.data(), flatNode.data()));
    shadowNode->setInheritAlpha(true);
    m_image->waitForDone();

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.expandAll();

    // the model shows the group's children top first: shadow, then flat
    const QModelIndex groupIndex = model.indexFromNode(m_layer2);
    QVERIFY(groupIndex.isValid());
    QCOMPARE(model.rowCount(groupIndex), 2);
    QCOMPARE(model.nodeFromIndex(model.index(0, 0, groupIndex)), KisNodeSP(shadow));
    QCOMPARE(model.nodeFromIndex(model.index(1, 0, groupIndex)), KisNodeSP(flat));
    QVERIFY(shadow->alphaChannelDisabled());
    QVERIFY(!flat->alphaChannelDisabled());

    QAbstractItemDelegate *delegate = view.itemDelegate();
    QVERIFY(delegate);
    QStyleOptionViewItem option;
    option.rect = QRect(0, 0, 220, 40);

    const int folderHeight = delegate->sizeHint(option, groupIndex).height();
    QVERIFY(folderHeight > 0);                          // view off: an ordinary folder row

    setClippingView(true);
    QCOMPARE(delegate->sizeHint(option, groupIndex).height(), 0); // view on: the agent's clip group is the hidden wrapper
    QVERIFY(delegate->sizeHint(option, model.index(0, 0, groupIndex)).height() > 0);
    QVERIFY(delegate->sizeHint(option, model.index(1, 0, groupIndex)).height() > 0);
    // an ordinary group of the same document still draws as a folder
    QCOMPARE(delegate->sizeHint(option, model.indexFromNode(m_layer4)).height(), folderHeight);
}

void TestNodeDelegate::testAltClickBoundaryBetweenRows()
{
    constructImage();
    m_shapeController->setImage(m_image);

    KisNodeModel model(nullptr);
    NodeView view;
    view.setModel(&model);
    model.setDummiesFacade(m_shapeController, m_image, m_shapeController, nullptr, nullptr);
    view.resize(260, 400);
    view.expandAll();

    // root rows, top first: layer4 (group), layer3, layer2 (group), layer1
    const QModelIndex row0 = model.index(0, 0, QModelIndex());
    const QModelIndex row1 = model.index(1, 0, QModelIndex());
    const QModelIndex row2 = model.index(2, 0, QModelIndex());
    QVERIFY(row0.isValid() && row1.isValid() && row2.isValid());
    const QRect r0 = view.visualRect(row0);
    const QRect r1 = view.visualRect(row1);
    const QRect r2 = view.visualRect(row2);
    QVERIFY(r0.height() > 0 && r1.height() > 0);
    QCOMPARE(r0.bottom() + 1, r1.top());

    const int x = 40;
    // just under the top edge of row 1 and just above the bottom edge of row 0 are the same boundary: upper is row 0
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(x, r1.top())), row0);
    QCOMPARE(view.clipBoundaryUpperIndexAt(QPoint(x, r0.bottom())), row0);
    // row 1 (the clone layer) is expanded: its mask sits between it and row 2 on screen, so there is no boundary
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, r2.top())).isValid());
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, r1.bottom())).isValid());
    // the middle of a row is not a boundary
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, r1.center().y())).isValid());
    // the very top of the first row has nothing above it
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, r0.top())).isValid());
    // outside any row
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(x, view.viewport()->height() + 500)).isValid());
    QVERIFY(!view.clipBoundaryUpperIndexAt(QPoint(-50, -50)).isValid());
}

KISTEST_TEMPORARY_HOME_MAIN(TestNodeDelegate)
