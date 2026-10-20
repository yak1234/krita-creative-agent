/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "TestLibkisNoView.h"

#include <testui.h>
#include <KisTemporaryHomeUiTest.h>
#include <simpletest.h>

#include <QPainterPath>
#include <QPointer>
#include <QScopedPointer>

#include <Document.h>
#include <Node.h>

#include <KisDocument.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_paint_layer.h>
#include <kundo2stack.h>

void TestLibkisNoView::testPaintWithoutAViewIsRefused()
{
    // No window is ever made in this program: every painting call that needs the view's brush refuses cleanly
    // instead of dereferencing it.
    QVERIFY(!KisPart::instance()->currentMainwindow() || !KisPart::instance()->currentMainwindow()->activeView());

    QPointer<KisDocument> kisdoc = KisPart::instance()->createDocument();
    QVERIFY(kisdoc);
    KisImageSP image = new KisImage(0, 120, 90, KoColorSpaceRegistry::instance()->rgb8(), "noview");
    QVERIFY(image);
    KisNodeSP layer = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
    image->addNode(layer);
    kisdoc->setCurrentImage(image);
    KisPart::instance()->addDocument(kisdoc, false);
    {
        QScopedPointer<Document> doc(new Document(kisdoc, false));
        QVERIFY(doc);
        QScopedPointer<Node> paint(doc->nodeByName("paint"));
        QVERIFY(paint);
        kisdoc->undoStack()->clear();
        QByteArray before(120 * 90 * 4, 0);
        layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(before.data()), image->bounds());

        QCOMPARE(paint->paintAbility(), QString("UNPAINTABLE"));
        paint->paintLine(QPointF(5, 5), QPointF(60, 5), 1.0, 1.0);
        paint->paintRectangle(QRectF(5, 10, 30, 20));
        paint->paintEllipse(QRectF(5, 10, 30, 20));
        paint->paintPolygon(QList<QPointF>({QPointF(5, 5), QPointF(40, 5), QPointF(20, 30)}));
        QPainterPath path;
        path.addRect(QRectF(5, 5, 20, 20));
        paint->paintPath(path);
        paint->paintPolylineStroke(QList<StrokePoint>());
        doc->waitForDone();
        QByteArray after(120 * 90 * 4, 0);
        layer->paintDevice()->readBytes(reinterpret_cast<quint8 *>(after.data()), image->bounds());
        QVERIFY(after == before);
        QCOMPARE(kisdoc->undoStack()->count(), 0);
    }
    KisPart::instance()->removeDocument(kisdoc, false);
    delete kisdoc;
}

KISTEST_TEMPORARY_HOME_MAIN(TestLibkisNoView)
