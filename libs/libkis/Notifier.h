/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_NOTIFIER_H
#define LIBKIS_NOTIFIER_H

#include <QObject>

#include "kritalibkis_export.h"
#include <kis_types.h>
#include "libkis.h"
#include <KisView.h>

class KisMainWindow;
class KisDocument;

/**
 * The Notifier can be used to be informed of state changes in the Krita application.
 */
class KRITALIBKIS_EXPORT Notifier : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(Notifier)

    Q_PROPERTY(bool Active READ active WRITE setActive)

public:
    explicit Notifier(QObject *parent = 0);
    ~Notifier() override;

    /**
     * @return true if the Notifier is active.
     */
    bool active() const;
    
    /**
     * Enable or disable the Notifier
     */
    void setActive(bool value);

Q_SIGNALS:

    /**
     * @brief applicationClosing is emitted when the application is about to close. This
     * happens after any documents and windows are closed.
     */
    void applicationClosing();

    /**
     * @brief imageCreated is emitted whenever a new image is created and registered with
     * the application.
     */
    void imageCreated(Document *image);

    /**
     * @brief imageSaved is emitted whenever a document is saved.
     * @param filename the filename of the document that has been saved.
     */
    void imageSaved(const QString &filename);

    /**
     * @brief imageClosed is emitted whenever the last view on an image is closed. The image
     * does not exist anymore in Krita
     * @param filename the filename of the image.
     */
    void imageClosed(const QString &filename);

    /**
     * @brief viewCreated is emitted whenever a new view is created.
     * @param view the view
     */
    void viewCreated(View *view);

    /**
     * @brief viewClosed is emitted whenever a view is closed
     * @param view the view
     */
    void viewClosed(View *view);

    /**
     * @brief windowCreated is emitted whenever a window is being created
     * @param window the window; this is called from the constructor of the window, before the xmlgui file is loaded
     */
    void windowIsBeingCreated(Window *window);

    /**
     * @brief windowIsCreated is emitted after main window is completely created
     */
    void windowCreated();

    /**
     * @brief configurationChanged is emitted every time Krita's configuration
     * has changed.
     */
    void configurationChanged();

    // Change events (krita-fork 2.2 and 2.8; wired in NotifierExtras.cpp).
    //
    // Delivery: each is emitted in the GUI thread, in the order the changes happened, whichever thread made them.
    // Repeated image, pixel, property and selection reports arriving close together are merged into one event,
    // unless a node was added or removed, or an undo step, modified flag, active node, tool or preset change came
    // between them.
    //
    // Objects: the Document and Node passed are made for the call and deleted when it returns. Use them inside the
    // slot; a kept reference raises RuntimeError in Python. To recognise a node later, compare with == or keep its
    // uniqueId(); for a document, compare with == against Krita.instance().documents().
    //
    // Events of a document start once it is open: opened, created (Krita.createDocument()), or shown in a view.

    /**
     * @brief imageChanged is emitted when an area of the image has been recomposited, as Krita's own canvas
     * receives it. Updates arriving in one pass of the event loop are united.
     * @param document the document
     * @param rect the changed area, in image pixels
     * @param source "agent" while the document's agent switch is on or an agent move or job is open, else "artist"
     */
    void imageChanged(Document *document, const QRect &rect, const QString &source);

    /**
     * @brief nodeAdded is emitted after a node was added to the document's node tree (also by undo or redo).
     */
    void nodeAdded(Document *document, Node *node);

    /**
     * @brief nodeRemoved is emitted after a node was removed from the document's node tree (also by undo or redo).
     */
    void nodeRemoved(Document *document, Node *node);

    /**
     * @brief nodeChanged is emitted when a node's properties changed: name, visibility, opacity, blending mode,
     * locks and the like. Pixel changes are reported by nodePixelsChanged.
     */
    void nodeChanged(Document *document, Node *node);

    /**
     * @brief nodePixelsChanged is emitted when a node asked for an area to be redrawn because what it shows there
     * changed (its pixels, or a mask's or filter's effect). Requests arriving in one pass of the event loop are
     * united per node and source.
     * @param rect the area, in image pixels
     * @param source "agent" or "artist", as for imageChanged
     */
    void nodePixelsChanged(Document *document, Node *node, const QRect &rect, const QString &source);

    /**
     * @brief selectionChanged is emitted when the document's global selection changed (set, replaced, edited or
     * removed). Changes in one pass of the event loop are reported once.
     */
    void selectionChanged(Document *document);

    /**
     * @brief undoIndexChanged is emitted when the document's undo stack moved: a new step, an undo or a redo.
     * @param index the undo stack's new index (the number of steps done)
     */
    void undoIndexChanged(Document *document, int index);

    /**
     * @brief documentModified is emitted when the document's modified flag changes: true after the first change
     * since it was saved or opened, false when it is saved.
     */
    void documentModified(Document *document, bool modified);

    /**
     * @brief activeNodeChanged is emitted when a window's active node changed (it needs a window showing the
     * document).
     * @param node the new active node, or None
     */
    void activeNodeChanged(Document *document, Node *node);

    /**
     * @brief toolChanged is emitted when the active tool changed.
     * @param document the document of the canvas the tool works on, or None
     * @param toolId the tool's id, as Krita.action names use it (e.g. "KritaShape/KisToolBrush")
     */
    void toolChanged(Document *document, const QString &toolId);

    /**
     * @brief brushPresetChanged is emitted when a window's current brush preset changed.
     * @param document the document of the window's active view, or None
     * @param presetName the preset's name
     */
    void brushPresetChanged(Document *document, const QString &presetName);

private Q_SLOTS:

    void imageCreated(KisDocument *document);

    void viewCreated(KisView *view);
    void viewClosed(KisView *view);

    void windowIsBeingCreated(KisMainWindow *window);


private:
    struct Private;
    Private *const d;

};

#endif // LIBKIS_NOTIFIER_H
