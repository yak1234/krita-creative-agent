/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef AGENT_CRAFT_TEST_UTILS_H
#define AGENT_CRAFT_TEST_UTILS_H

#include <QCoreApplication>
#include <QImage>
#include <QScopedPointer>
#include <QString>

#include <Document.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_layer_utils.h>
#include <kundo2stack.h>

/// Helpers shared by the merge and bake tests (krita-fork 5.2).
namespace AgentCraftTest
{

/**
 * A document whose image records undo steps in the document's undo stack, as an opened document does, with a
 * libkis wrapper.
 */
struct UndoableDocument {
    QScopedPointer<KisDocument> kisdoc;
    KisImageSP image;
    QScopedPointer<Document> doc;

    explicit UndoableDocument(const QSize &size = QSize(160, 120))
        : kisdoc(KisPart::instance()->createDocument())
    {
        image = new KisImage(kisdoc->createUndoStore(), size.width(), size.height(),
                             KoColorSpaceRegistry::instance()->rgb8(), "agent craft");
        kisdoc->setCurrentImage(image);
        doc.reset(new Document(kisdoc.data(), false));
    }

    ~UndoableDocument()
    {
        doc.reset();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    /// Recomposites the whole image and waits for it.
    void render()
    {
        image->refreshGraphAsync();
        settle();
    }

    void settle()
    {
        KisLayerUtils::forceAllDelayedNodesUpdate(image->root());
        image->waitForDone();
        QCoreApplication::processEvents();
        image->waitForDone();
    }

    QImage projection() const
    {
        return doc->projection(0, 0, image->width(), image->height());
    }

    int undoCount() const
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
};

/**
 * @return an empty string when \p a and \p b have the same size and differ by at most \p tolerance in every
 * channel of every pixel, else where and how much they differ most
 */
inline QString difference(const QImage &a, const QImage &b, int tolerance = 1)
{
    if (a.size() != b.size()) {
        return QString("sizes differ: %1x%2 and %3x%4").arg(a.width()).arg(a.height()).arg(b.width()).arg(b.height());
    }
    const QImage x = a.convertToFormat(QImage::Format_ARGB32);
    const QImage y = b.convertToFormat(QImage::Format_ARGB32);
    int worst = 0;
    QPoint where;
    for (int row = 0; row < x.height(); row++) {
        for (int col = 0; col < x.width(); col++) {
            const QRgb p = x.pixel(col, row);
            const QRgb q = y.pixel(col, row);
            const int d = qMax(qMax(qAbs(qRed(p) - qRed(q)), qAbs(qGreen(p) - qGreen(q))),
                               qMax(qAbs(qBlue(p) - qBlue(q)), qAbs(qAlpha(p) - qAlpha(q))));
            if (d > worst) {
                worst = d;
                where = QPoint(col, row);
            }
        }
    }
    if (worst <= tolerance) return QString();
    return QString("differ by %1 at %2,%3: %4 and %5")
        .arg(worst)
        .arg(where.x())
        .arg(where.y())
        .arg(x.pixel(where), 8, 16, QChar('0'))
        .arg(y.pixel(where), 8, 16, QChar('0'));
}

/// @return true when \p image has some pixel that is not fully transparent and not the same as the rest
inline bool hasVariedPixels(const QImage &image)
{
    const QImage x = image.convertToFormat(QImage::Format_ARGB32);
    const QRgb first = x.pixel(0, 0);
    for (int row = 0; row < x.height(); row++) {
        for (int col = 0; col < x.width(); col++) {
            if (x.pixel(col, row) != first) return true;
        }
    }
    return false;
}

}

#endif
