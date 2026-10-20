/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef __TEST_NODE_DELEGATE_H
#define __TEST_NODE_DELEGATE_H

#include <simpletest.h>
#include "empty_nodes_test.h"

class KisDocument;
class KisNameServer;
class KisShapeController;

/// Folder-style group rows of the layers docker (ported from Krita-Revamp): row height and folder icon.
class TestNodeDelegate : public QObject, public TestUtil::EmptyNodesTest
{
    Q_OBJECT
private Q_SLOTS:
    void init();
    void cleanup();

    void testGroupRowHeightFunction();
    void testGroupRowsAreShorterThanLayerRows();
    void testHitRectsFollowTheGroupRowHeight();
    void testGroupRowsPaintAFolderIcon();

    void testClippingViewIsOffByDefault();
    void testClippingViewHidesTheClipGroupAndIndentsClippedLayers();
    void testAgentBuiltClipStackLooksRightInTheDocker();
    void testAltClickBoundaryBetweenRows();
    void testAltClickBoundaryIgnoresExpandedGroups();
    void testAltClickBoundaryJoinsAClipStackFromTheLayerAbove();
    void testCollapsedClipWrapperIsShownExpanded();
    void testKeyboardNavigationSkipsHiddenWrappers();
    void testKeyboardLeftRightEndSkipHiddenWrappers();
    void testOnlyAClipStateChangeRelayouts();
    void testGroupRowFloor();

private:
    void setClippingView(bool on);
    KisDocument *m_doc {nullptr};
    KisNameServer *m_nameServer {nullptr};
    KisShapeController *m_shapeController {nullptr};
};

#endif
