/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_DOCUMENT_H
#define LIBKIS_DOCUMENT_H

#include <QFileInfo>

#include "kritalibkis_export.h"
#include "libkis.h"

#include "GroupLayer.h"
#include "CloneLayer.h"
#include "FileLayer.h"
#include "FilterLayer.h"
#include "FillLayer.h"
#include "VectorLayer.h"
#include "FilterMask.h"
#include "SelectionMask.h"
#include "TransparencyMask.h"
#include "TransformMask.h"
#include "ColorizeMask.h"

#include "GuidesConfig.h"
#include "GridConfig.h"

class Feature;

class KisDocument;

/**
 * The Document class encapsulates a Krita Document/Image. A Krita document is an Image with
 * a filename. Libkis does not differentiate between a document and an image, like Krita does
 * internally.
 */
class KRITALIBKIS_EXPORT Document : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(Document)

public:
    explicit Document(KisDocument *document, bool ownsDocument, QObject *parent = 0);
    ~Document() override;

    bool operator==(const Document &other) const;
    bool operator!=(const Document &other) const;

public Q_SLOTS:
    // Change reports (krita-fork 2.2; implemented in DocumentChanges.cpp)

    /**
     * @brief revision a counter that increases every time the image changes: each recomposited area Krita reports
     * (the updates that redraw the canvas, from the artist's strokes as well as from scripts), and each change of the
     * image's size or colour space. Reading it costs nothing like hashing the pixels.
     *
     * Compare revisions of the same document only: one counter serves all documents, so a revision of another
     * document says nothing about this one.
     * Wait for the image (waitForDone()) before reading it if a change you made must be counted.
     *
     * @code
     * before = doc.revision()
     * # ... the artist or a script paints ...
     * doc.waitForDone()
     * if doc.revision() != before:
     *     print("changed:", doc.changedRect(before))
     * @endcode
     *
     * @return the current revision, at least 1
     */
    qint64 revision() const;

    /**
     * @brief changedRect the union of the areas of the image changed after revision \p sinceRevision, clipped to the
     * image. An empty rect means nothing changed since then.
     *
     * When that history is gone (too old, or from before the document's change report began) it returns the whole
     * image, so a caller never misses a change. Touching changes (a stroke's) share history, so a revision taken in
     * the middle of a stroke may get a little more than changed since then, never less.
     *
     * @param sinceRevision a value revision() returned earlier for this document
     * @return the changed area in image pixels
     */
    QRect changedRect(qint64 sinceRevision) const;

    /**
     * @brief setAgentActive marks the changes requested from now on as made by the agent ("agent") instead of the
     * artist ("artist"), until called with false. The mark shows in Notifier.imageChanged() and
     * Notifier.nodePixelsChanged(). It applies to the document, not to this wrapper object.
     *
     * A change is marked when its pixels are written and the area is asked to be redrawn, not when Krita later
     * recomposites it: a stroke written while the switch is on stays "agent" even if the switch is off by the time
     * the canvas updates. A stroke still being written after the switch goes off (an asynchronous stroke not waited
     * for) is marked "artist", and anything the artist paints while it is on is marked "agent": switch it off after
     * your work has landed (waitForDone()).
     *
     * The switch does not nest: true twice and false once leaves it off. It belongs to the one script driving the
     * agent; a count would let an unbalanced script mark every later change as the agent's. Agent moves and jobs
     * (C++) nest on their own and keep the document marked while any is open, whatever this switch says.
     *
     * @param active true while the agent is changing the document
     */
    void setAgentActive(bool active);

    /**
     * @return true while changes are marked as the agent's: setAgentActive(true) is in effect, or any agent work is
     * open (an agent move, which implies agent-active, or an asynchronous agent job), whichever started it
     */
    bool agentActive() const;

    /**
     * @return "agent" while the changes are marked as the agent's, else "artist"
     */
    QString changeSource() const;

public Q_SLOTS:
    // The feature map (krita-fork 6.1, 6.2; implemented in DocumentFeatures.cpp)

    /**
     * @brief features the document's features, named regions of the painting such as "Sky" or "Tower 3", in order.
     * A feature describes the painting and never holds its pixels. The caller owns the returned objects.
     * @return a list of Feature objects
     */
    QList<Feature *> features() const;

    /**
     * @brief feature the feature called \p name
     * @return a Feature, or None if the document has no feature of that name
     */
    Feature *feature(const QString &name) const;

    /**
     * @brief addFeature adds a feature: a copy of \p mask cut to the document, measured on the painting (bounds,
     * area, mean colour). It changes no pixel, is one undo step (inside an open agent move or macro, part of its
     * step), and marks the document modified.
     *
     * @code
     * sel = Selection()
     * sel.select(0, 0, doc.width(), 1800, 255)
     * doc.addFeature("Sky", "sky", sel)                      # the agent's proposal
     * doc.addFeature("Moon", "moon", moonSel, "artist", "kept", True)
     * @endcode
     *
     * @param name the feature's name, unique in the document; outer spaces are dropped ("Sky " is "Sky")
     * @param kind what it is: "sky", "building", "figure", "seam", ... (free text)
     * @param mask the region, 255 inside and 0 outside (soft edges in between)
     * @param author "agent" (default) or "artist"
     * @param state "proposed" (default) or "kept"
     * @param isProtected whether the feature is protected
     * @return the new Feature, or None if the name is empty, only spaces or taken, the mask is missing, or author or
     * state is not one of the values above
     */
    Feature *addFeature(const QString &name,
                        const QString &kind,
                        Selection *mask,
                        const QString &author = QString("agent"),
                        const QString &state = QString("proposed"),
                        bool isProtected = false);

    /**
     * @brief renameFeature renames the feature called \p name to \p newName, as one undo step (inside an open agent
     * move or macro, part of its step). No pixel changes.
     * @return true if renamed (or the names are equal); false if there is no such feature, \p newName is empty or
     * only spaces, or another feature has it (outer spaces are dropped, as in addFeature())
     */
    bool renameFeature(const QString &name, const QString &newName);

    /**
     * @brief removeFeature removes the feature called \p name, as one undo step (inside an open agent move or macro,
     * part of its step). No pixel changes; undo brings the feature back as it was.
     * @return false if there is no such feature
     */
    bool removeFeature(const QString &name);

    // Krita Agent: feature builders (krita-fork 6.3; implemented in DocumentFeatureBuilders.cpp). Each returns a new
    // mask (255 inside, 0 outside) to give to addFeature(), built by Krita's own selection logic without a view. None
    // changes a pixel, the selection or the undo history. The caller owns the returned objects.
    //
    // Reading the painting: each call reads the composited image, or the projection of one layer given as "layer" in
    // \p options (its unique id, or its name when no other node has it; not a mask or a group; the layer's own pixels
    // with its effect masks, its opacity, blend mode and visibility not applied). It never asks the artist's open
    // stroke to end and never waits for the pen: it needs the image idle for a moment, and gives None with a warning
    // ("image busy") when it is not within the call's time.
    //
    // Limits: input is capped (256 seeds; 64 colours and points together; 128 outline points; 32 hints; grow, shrink
    // and feather 100 px; search radius 200 px; settle 100 px) and the call has a time limit, "timeoutMs" (default
    // 5000, at most 30000), after which it gives None with a warning. Numbers and points must be finite. Options are
    // checked: an unknown key or a bad value gives None and a warning (Python: the options are a dict).
    //
    // @code
    // sky = doc.maskContiguous([QPointF(40, 30), QPointF(5000, 60)], {"threshold": 12, "grow": 1})
    // doc.addFeature("Sky", "sky", sky)
    // @endcode

    /**
     * @brief maskFromSelection a mask from \p selection, or from the document's selection when none is given, cut
     * to the document
     * @param options "timeoutMs"
     * @return the mask, or None when there is no selection or the image stays busy
     */
    Selection *maskFromSelection(Selection *selection = 0, const QVariantMap &options = QVariantMap()) const;

    /**
     * @brief maskContiguous the contiguous selection tool's region from each seed, together: the pixels joined to a
     * seed whose colour is close to the seed's own.
     * @param seeds one or more points in the document
     * @param options "threshold" (0-255, Krita's colour difference, as the tool's slider (1-100); default 8),
     * "spread" (0-100, default 100: a hard edge), "closeGap" (0-32 pixels), "grow" (pixels, negative shrinks),
     * "stopGrowingAtDarkestPixel", "feather" (pixels), "antiAlias", "within" (a Selection or a feature's name the
     * search stays inside), "layer", "timeoutMs"
     * @return the mask, or None for a seed outside the document, a bad option or input past the limits
     */
    Selection *maskContiguous(const QList<QPointF> &seeds, const QVariantMap &options = QVariantMap()) const;

    /**
     * @brief maskSimilarColor the similar colour selection tool's pixels: all those, joined or not, whose colour is
     * close to any of \p colors. Searched in patches on the thread pool, as the tool does.
     * @param colors the colours to match (may be empty when "points" gives them)
     * @param options "points" (points whose colours are matched too), "threshold" (0-255, default 20), "spread",
     * "grow", "stopGrowingAtDarkestPixel", "feather", "antiAlias", "within", "layer", "timeoutMs", as maskContiguous()
     * @return the mask, or None for no colour, a bad option or input past the limits
     */
    Selection *maskSimilarColor(const QList<QColor> &colors, const QVariantMap &options = QVariantMap()) const;

    /**
     * @brief maskSnapOutline the inside of a closed outline through rough \p points, each stretch between two points
     * traced along the painting's strongest edges by the magnetic selection tool's worker, within "searchRadius" of
     * the straight line between them. Each point first moves to the strongest edge near it; a stretch between two
     * points on the same side of the canvas runs along that side; a stretch that finds no way (within 2 s) is straight.
     * @param points three or more points, in order around the region (points on the canvas edge may be at x = width
     * or y = height)
     * @param options "searchRadius" (pixels the edge may stray from the line between points, 1-200, default 30),
     * "filterRadius" (the edge filter's radius, default 3), "anchorRadius" (how far a point moves to an edge, 0-200,
     * default 10; 0 keeps it), "settle" (pixels, 0-100: the edge is then settled by the colorize mask's lazy brush
     * within this distance of the outline, as maskSegments() splits; default 0, off), "edgeDetection", "edgeSize",
     * "fuzzyRadius", "cleanUp" (for "settle", as maskSegments()), "antiAlias", "layer", "timeoutMs". A mask thinner
     * than twice "settle" is returned unsettled, with a warning.
     * @return the mask, or None for fewer than three points, a point outside the document, a bad option, input past
     * the limits or a call that ran out of time
     */
    Selection *maskSnapOutline(const QList<QPointF> &points, const QVariantMap &options = QVariantMap()) const;

    /**
     * @brief maskSegments splits the painting into one region per hint with the colorize mask's lazy brush: each
     * pixel joins the hint it reaches across the weakest edges. A hint is a few strokes inside its region; later
     * hints win where hints overlap.
     * @param hints two to 32 Selections, one per region
     * @param options "rect" ([x, y, w, h], the part split; default the whole document), "edgeDetection" (default
     * True, for paintings; False for clean line art), "edgeSize" (0.5-100, default 4 pixels: the scale of the edges it
     * looks for; the split lands within about that of a sharp boundary, so a smaller size is tighter on clean edges),
     * "fuzzyRadius", "cleanUp" (0-1), "layer", "timeoutMs"
     * @return one mask per hint, in order; an empty list for a bad hint or option, input past the limits or a call
     * that ran out of time (its stroke is then cancelled)
     */
    QList<Selection *> maskSegments(const QList<Selection *> &hints, const QVariantMap &options = QVariantMap()) const;

public Q_SLOTS:
    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * The horizontal guides.
     * @return a list of the horizontal positions of guides.
     */
    Q_DECL_DEPRECATED QList<qreal> horizontalGuides() const;
    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * The vertical guide lines.
     * @return a list of vertical guides.
     */
    Q_DECL_DEPRECATED QList<qreal> verticalGuides() const;

    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * Returns guide visibility.
     * @return whether the guides are visible.
     */
    Q_DECL_DEPRECATED bool guidesVisible() const;
    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * Returns guide lockedness.
     * @return whether the guides are locked.
     */
    Q_DECL_DEPRECATED bool guidesLocked() const;

    /**
     * @brief clone create a shallow clone of this document.
     * @return a new Document that should be identical to this one in every respect.
     */
    Document *clone() const;

    /**
     * Batchmode means that no actions on the document should show dialogs or popups.
     * @return true if the document is in batchmode.
     */
    bool batchmode() const;

    /**
     * Set batchmode to @p value. If batchmode is true, then there should be no popups
     * or dialogs shown to the user.
     */
    void setBatchmode(bool value);

    /**
     * @brief activeNode retrieve the node that is currently active in the currently active window
     * @return the active node. If there is no active window, the first child node is returned.
     */
    Node* activeNode() const;

    /**
     * @brief setActiveNode make the given node active in the currently active view and window
     * @param value the node to make active.
     */
    void setActiveNode(Node* value);

    /**
     * @brief toplevelNodes return a list with all top level nodes in the image graph
     */
    QList<Node*> topLevelNodes() const;

    /**
     * @brief nodeByName searches the node tree for a node with the given name and returns it
     * @param name the name of the node
     * @return the first node with the given name or 0 if no node is found
     */
    Node *nodeByName(const QString &name) const;

    /**
     * @brief nodeByUniqueID searches the node tree for a node with the given name and returns it.
     * @param uuid the unique id of the node
     * @return the node with the given unique id, or 0 if no node is found.
     */
    Node *nodeByUniqueID(const QUuid &id) const;

    /**
     * colorDepth A string describing the color depth of the image:
     * <ul>
     * <li>U8: unsigned 8 bits integer, the most common type</li>
     * <li>U16: unsigned 16 bits integer</li>
     * <li>F16: half, 16 bits floating point. Only available if Krita was built with OpenEXR</li>
     * <li>F32: 32 bits floating point</li>
     * </ul>
     * @return the color depth.
     */
    QString colorDepth() const;

    /**
     * @brief colorModel retrieve the current color model of this document:
     * <ul>
     * <li>A: Alpha mask</li>
     * <li>RGBA: RGB with alpha channel (The actual order of channels is most often BGR!)</li>
     * <li>XYZA: XYZ with alpha channel</li>
     * <li>LABA: LAB with alpha channel</li>
     * <li>CMYKA: CMYK with alpha channel</li>
     * <li>GRAYA: Gray with alpha channel</li>
     * <li>YCbCrA: YCbCr with alpha channel</li>
     * </ul>
     * @return the internal color model string.
     */
    QString colorModel() const;

    /**
     * @return the name of the current color profile
     */
    QString colorProfile() const;

    /**
     * @brief setColorProfile set the color profile of the image to the given profile. The profile has to
     * be registered with krita and be compatible with the current color model and depth; the image data
     * is <i>not</i> converted.
     * @param colorProfile
     * @return false if the colorProfile name does not correspond to to a registered profile or if assigning
     * the profile failed.
     */
    bool setColorProfile(const QString &colorProfile);

    /**
     * @brief setColorSpace convert the nodes and the image to the given colorspace. The conversion is
     * done with Perceptual as intent, High Quality and No LCMS Optimizations as flags and no blackpoint
     * compensation.
     *
     * @param colorModel A string describing the color model of the image:
     * <ul>
     * <li>A: Alpha mask</li>
     * <li>RGBA: RGB with alpha channel (The actual order of channels is most often BGR!)</li>
     * <li>XYZA: XYZ with alpha channel</li>
     * <li>LABA: LAB with alpha channel</li>
     * <li>CMYKA: CMYK with alpha channel</li>
     * <li>GRAYA: Gray with alpha channel</li>
     * <li>YCbCrA: YCbCr with alpha channel</li>
     * </ul>
     * @param colorDepth A string describing the color depth of the image:
     * <ul>
     * <li>U8: unsigned 8 bits integer, the most common type</li>
     * <li>U16: unsigned 16 bits integer</li>
     * <li>F16: half, 16 bits floating point. Only available if Krita was built with OpenEXR</li>
     * <li>F32: 32 bits floating point</li>
     * </ul>
     * @param colorProfile a valid color profile for this color model and color depth combination.
     * @return false the combination of these arguments does not correspond to a colorspace.
     */
    bool setColorSpace(const QString &colorModel, const QString &colorDepth, const QString &colorProfile);

    /**
     * @brief backgroundColor returns the current background color of the document. The color will
     * also include the opacity.
     *
     * @return QColor
     */
    QColor backgroundColor();

    /**
     * @brief setBackgroundColor sets the background color of the document. It will trigger a projection
     * update.
     *
     * @param color A QColor. The color will be converted from sRGB.
     * @return bool
     */
    bool setBackgroundColor(const QColor &color);

    /**
     * @brief documentInfo creates and XML document representing document and author information.
     * @return a string containing a valid XML document with the right information about the document
     * and author. The DTD can be found here:
     *
     * https://phabricator.kde.org/source/krita/browse/master/krita/dtd/
     *
     * @code
     * <?xml version="1.0" encoding="UTF-8"?>
     * <!DOCTYPE document-info PUBLIC '-//KDE//DTD document-info 1.1//EN' 'http://www.calligra.org/DTD/document-info-1.1.dtd'>
     * <document-info xmlns="http://www.calligra.org/DTD/document-info">
     * <about>
     *  <title>My Document</title>
     *   <description></description>
     *   <subject></subject>
     *   <abstract><![CDATA[]]></abstract>
     *   <keyword></keyword>
     *   <initial-creator>Unknown</initial-creator>
     *   <editing-cycles>1</editing-cycles>
     *   <editing-time>35</editing-time>
     *   <date>2017-02-27T20:15:09</date>
     *   <creation-date>2017-02-27T20:14:33</creation-date>
     *   <language></language>
     *  </about>
     *  <author>
     *   <full-name>Boudewijn Rempt</full-name>
     *   <initial></initial>
     *   <author-title></author-title>
     *   <email></email>
     *   <telephone></telephone>
     *   <telephone-work></telephone-work>
     *   <fax></fax>
     *   <country></country>
     *   <postal-code></postal-code>
     *   <city></city>
     *   <street></street>
     *   <position></position>
     *   <company></company>
     *  </author>
     * </document-info>
     * @endcode
     *
     */
    QString documentInfo() const;

    /**
     * @brief setDocumentInfo set the Document information to the information contained in document
     * @param document A string containing a valid XML document that conforms to the document-info DTD
     * that can be found here:
     *
     * https://phabricator.kde.org/source/krita/browse/master/krita/dtd/
     */
    void setDocumentInfo(const QString &document);

    /**
     * @return the full path to the document, if it has been set.
     */
    QString fileName() const;

    /**
     * @brief setFileName set the full path of the document to @param value
     */
    void setFileName(QString value);

    /**
     * @return the height of the image in pixels
     */
    int height() const;

    /**
     * @brief setHeight resize the document to @param value height. This is a canvas resize, not a scale.
     */
    void setHeight(int value);

    /**
     * @return the name of the document. This is the title field in the @ref documentInfo
     */
    QString name() const;

    /**
     * @brief setName sets the name of the document to @p value. This is the title field in the @ref documentInfo
     */
    void setName(QString value);

    /**
     * @return the resolution in pixels per inch
     */
    int resolution() const;
    /**
     * @brief setResolution set the resolution of the image; this does not scale the image
     * @param value the resolution in pixels per inch
     */
    void setResolution(int value);

    /**
     * @brief rootNode the root node is the invisible group layer that contains the entire node
     * hierarchy.
     * @return the root of the image
     */
    Node* rootNode() const;

    /**
     * @brief selection Create a Selection object around the global selection, if there is one.
     * @return the global selection or None if there is no global selection.
     */
    Selection* selection() const;

    /**
     * @brief setSelection set or replace the global selection
     * @param value a valid selection object.
     */
    void setSelection(Selection* value);

    /**
     * @return the width of the image in pixels.
     */
    int width() const;

    /**
     * @brief setWidth resize the document to @param value width. This is a canvas resize, not a scale.
     */
    void setWidth(int value);

    /**
     * @return the left edge of the canvas in pixels.
     */
    int xOffset() const;

    /**
     * @brief setXOffset sets the left edge of the canvas to @p x.
     */
    void setXOffset(int x);

    /**
     * @return the top edge of the canvas in pixels.
     */
    int yOffset() const;

    /**
     * @brief setYOffset sets the top edge of the canvas to @p y.
     */
    void setYOffset(int y);

    /**
     * @return xRes the horizontal resolution of the image in pixels
     * per inch
     */

    double xRes() const;

    /**
     * @brief setXRes set the horizontal resolution of the image to
     * xRes in pixels per inch
     */
    void setXRes(double xRes) const;

    /**
     * @return yRes the vertical resolution of the image in pixels per
     * inch
     */
    double yRes() const;

    /**
     * @brief setYRes set the vertical resolution of the image to yRes
     * in pixels per inch
     */
    void setYRes(double yRes) const;

    /**
     * @brief pixelData reads the given rectangle from the image projection and returns it as a byte
     * array. The pixel data starts top-left, and is ordered row-first.
     *
     * The byte array can be interpreted as follows: 8 bits images have one byte per channel,
     * and as many bytes as there are channels. 16 bits integer images have two bytes per channel,
     * representing an unsigned short. 16 bits float images have two bytes per channel, representing
     * a half, or 16 bits float. 32 bits float images have four bytes per channel, representing a
     * float.
     *
     * You can read outside the image boundaries; those pixels will be transparent black.
     *
     * The order of channels is:
     *
     * <ul>
     * <li>Integer RGBA: Blue, Green, Red, Alpha
     * <li>Float RGBA: Red, Green, Blue, Alpha
     * <li>LabA: L, a, b, Alpha
     * <li>CMYKA: Cyan, Magenta, Yellow, Key, Alpha
     * <li>XYZA: X, Y, Z, A
     * <li>YCbCrA: Y, Cb, Cr, Alpha
     * </ul>
     *
     * The byte array is a copy of the original image data. In Python, you can use bytes, bytearray
     * and the struct module to interpret the data and construct, for instance, a Pillow Image object.
     *
     * @param x x position from where to start reading
     * @param y y position from where to start reading
     * @param w row length to read
     * @param h number of rows to read
     * @return a QByteArray with the pixel data. The byte array may be empty.
     */
    QByteArray pixelData(int x, int y, int w, int h) const;

    /**
     * @brief close Close the document: remove it from Krita's internal list of documents and
     * close all views. If the document is modified, you should save it first. There will be
     * no prompt for saving.
     *
     * After closing the document it becomes invalid.
     *
     * @return true if the document is closed.
     */
    bool close();

    /**
     * @brief crop the image to rectangle described by @p x, @p y,
     * @p w and @p h
     * @param x x coordinate of the top left corner
     * @param y y coordinate of the top left corner
     * @param w width
     * @param h height
     */
    void crop(int x, int y, int w, int h);

    /**
     * @brief exportImage export the image, without changing its URL to the given path.
     * @param filename the full path to which the image is to be saved
     * @param exportConfiguration a configuration object appropriate to the file format.
     * An InfoObject will used to that configuration.
     *
     * The supported formats have specific configurations that must be used when in
     * batchmode. They are described below:
     *
     *\b png
     * <ul>
     * <li>alpha: bool (True or False)
     * <li>compression: int (1 to 9)
     * <li>forceSRGB: bool (True or False)
     * <li>indexed: bool (True or False)
     * <li>interlaced: bool (True or False)
     * <li>saveSRGBProfile: bool (True or False)
     * <li>transparencyFillcolor: rgb (Ex:[255,255,255])
     * </ul>
     *
     *\b jpeg
     * <ul>
     * <li>baseline: bool (True or False)
     * <li>exif: bool (True or False)
     * <li>filters: bool (['ToolInfo', 'Anonymizer'])
     * <li>forceSRGB: bool (True or False)
     * <li>iptc: bool (True or False)
     * <li>is_sRGB: bool (True or False)
     * <li>optimize: bool (True or False)
     * <li>progressive: bool (True or False)
     * <li>quality: int (0 to 100)
     * <li>saveProfile: bool (True or False)
     * <li>smoothing: int (0 to 100)
     * <li>subsampling: int (0 to 3)
     * <li>transparencyFillcolor: rgb (Ex:[255,255,255])
     * <li>xmp: bool (True or False)
     * </ul>
     * @return true if the export succeeded, false if it failed.
     */
    bool exportImage(const QString &filename, const InfoObject &exportConfiguration);

    /**
     * @brief flatten all layers in the image
     */
    void flatten();

    // Krita Agent: merge kept work (krita-fork 5.2; implemented in DocumentAgentCraft.cpp).

    /**
     * @brief mergeGroups merges \p nodes (groups, or any layers) into one paint layer, exactly as they render: each
     * with its masks, layer styles, opacity and blending mode, as Krita's Merge with Layer Below on selected layers
     * (or Flatten Layer, for one group) does. It is one undo step.
     *
     * The merged layer takes the place of the topmost of them. The canvas looks the same afterwards when no visible
     * layer that is not merged lies between them in the stack (a layer between them would end up below all of the
     * merged content, as with Krita's merge), and when they blend in the Normal mode (another mode, or a pass-through
     * group, blends against the other merged nodes only, not against the layers below, as in Krita). Hidden nodes
     * in the list are left as they are (Krita's own merge would delete them). The call waits until the merge is done.
     *
     * One plain paint layer with no masks and no style is merged already: it is returned as it is, with no undo
     * step. One vector, fill, clone or file layer with no masks and no style is not converted: the call returns 0.
     *
     * As Krita's merge does, the merged layer becomes the selected layer in the views showing the document (the
     * artist's layer selection changes).
     *
     * Inside beginAgentMove() ... endAgentMove() (or beginUndoMacro()), the merge is part of that one step.
     *
     * @code
     * merged = doc.mergeGroups([groupA, groupB])
     * @endcode
     *
     * @param nodes layers of this document, none an ancestor of another
     * @return the merged layer, or 0 when nothing was merged: an empty list, a node that is not a layer of this
     * document, a node inside another listed one, a listed node that is locked or inside a locked group, a visible
     * listed node inside a hidden group, or only hidden nodes
     */
    Node *mergeGroups(const QList<Node *> &nodes);

    /**
     * @brief resizeImage resizes the canvas to the given left edge, top edge, width and height.
     * Note: This doesn't scale, use scale image for that.
     * @param x the new left edge
     * @param y the new top edge
     * @param w the new width
     * @param h the new height
     */
    void resizeImage(int x, int y, int w, int h);

    /**
    * @brief scaleImage
    * @param w the new width
    * @param h the new height
    * @param xres the new xres
    * @param yres the new yres
    * @param strategy the scaling strategy. There's several ones amongst these that aren't available in the regular UI.
    * The list of filters is extensible and can be retrieved with Krita::filter
    * <ul>
    * <li>Hermite</li>
    * <li>Bicubic - Adds pixels using the color of surrounding pixels. Produces smoother tonal gradations than Bilinear.</li>
    * <li>Box - Replicate pixels in the image. Preserves all the original detail, but can produce jagged effects.</li>
    * <li>Bilinear - Adds pixels averaging the color values of surrounding pixels. Produces medium quality results when the image is scaled from half to two times the original size.</li>
    * <li>Bell</li>
    * <li>BSpline</li>
    * <li>Kanczos3 - Offers similar results than Bicubic, but maybe a little bit sharper. Can produce light and dark halos along strong edges.</li>
    * <li>Mitchell</li>
    * </ul>
    */
   void scaleImage(int w, int h, int xres, int yres, QString strategy);

   /**
    * @brief rotateImage
    * Rotate the image by the given radians.
    * @param radians the amount you wish to rotate the image in radians
    */
   void rotateImage(double radians);

   /**
    * @brief shearImage shear the whole image.
    * @param angleX the X-angle in degrees to shear by
    * @param angleY the Y-angle in degrees to shear by
    */
   void shearImage(double angleX, double angleY);

    /**
     * @brief save the image to its currently set path. The modified flag of the
     * document will be reset
     * @return true if saving succeeded, false otherwise.
     */
    bool save();

    /**
     * @brief saveAs save the document under the @p filename. The document's
     * filename will be reset to @p filename.
     * @param filename the new filename (full path) for the document
     * @return true if saving succeeded, false otherwise.
     */
    bool saveAs(const QString &filename);

    /**
     * @brief createNode create a new node of the given type. The node is not added
     * to the node hierarchy; you need to do that by finding the right parent node,
     * getting its list of child nodes and adding the node in the right place, then
     * calling Node::SetChildNodes
     *
     * @param name The name of the node
     *
     * @param nodeType The type of the node. Valid types are:
     * <ul>
     *  <li>paintlayer
     *  <li>grouplayer
     *  <li>filelayer
     *  <li>filterlayer
     *  <li>filllayer
     *  <li>clonelayer
     *  <li>vectorlayer
     *  <li>transparencymask
     *  <li>filtermask
     *  <li>transformmask
     *  <li>selectionmask
     * </ul>
     *
     * When relevant, the new Node will have the colorspace of the image by default;
     * that can be changed with Node::setColorSpace.
     *
     * The settings and selections for relevant layer and mask types can also be set
     * after the Node has been created.
     *
@code
d = Application.createDocument(1000, 1000, "Test", "RGBA", "U8", "", 120.0)
root = d.rootNode();
print(root.childNodes())
l2 = d.createNode("layer2", "paintLayer")
print(l2)
root.addChildNode(l2, None)
print(root.childNodes())
@endcode
     *
     *
     * @return the new Node.
     */
    Node* createNode(const QString &name, const QString &nodeType);
    /**
     * @brief createGroupLayer
     * Returns a grouplayer object. Grouplayers are nodes that can have
     * other layers as children and have the passthrough mode.
     * @param name the name of the layer.
     * @return a GroupLayer object.
     */
    GroupLayer* createGroupLayer(const QString &name);
    /**
     * @brief createFileLayer returns a layer that shows an external image.
     * @param name name of the file layer.
     * @param fileName the absolute filename of the file referenced. Symlinks will be resolved.
     * @param scalingMethod how the dimensions of the file are interpreted
     *        can be either "None", "ImageToSize" or "ImageToPPI"
     * @param scalingFilter filter used to scale the file
     *        can be "Bicubic", "Hermite", "NearestNeighbor", "Bilinear", "Bell", "BSpline", "Lanczos3", "Mitchell"
     * @return a FileLayer
     */
    FileLayer* createFileLayer(const QString &name, const QString fileName, const QString scalingMethod, const QString scalingFilter = "Bicubic");

    /**
     * @brief createFilterLayer creates a filter layer, which is a layer that represents a filter
     * applied non-destructively.
     * @param name name of the filterLayer
     * @param filter the filter that this filter layer will us.
     * @param selection the selection.
     * @return a filter layer object.
     */
    FilterLayer* createFilterLayer(const QString &name, Filter &filter, Selection &selection);

    /**
     * @brief createFillLayer creates a fill layer object, which is a layer
     * @param name
     * @param generatorName - name of the generation filter.
     * @param configuration - the configuration for the generation filter.
     * @param selection - the selection.
     * @return a filllayer object.
     *
     * @code
     * from krita import *
     * d = Krita.instance().activeDocument()
     * i = InfoObject();
     * i.setProperty("pattern", "Cross01.pat")
     * s = Selection();
     * s.select(0, 0, d.width(), d.height(), 255)
     * n = d.createFillLayer("test", "pattern", i, s)
     * r = d.rootNode();
     * c = r.childNodes();
     * r.addChildNode(n, c[0])
     * d.refreshProjection()
     * @endcode
     */
    FillLayer* createFillLayer(const QString &name, const QString generatorName, InfoObject &configuration, Selection &selection);

    /**
     * @brief createCloneLayer
     * @param name
     * @param source
     * @return
     */
    CloneLayer* createCloneLayer(const QString &name, const Node* source);

    /**
     * @brief createVectorLayer
     * Creates a vector layer that can contain vector shapes.
     * @param name the name of this layer.
     * @return a VectorLayer.
     */
    VectorLayer* createVectorLayer(const QString &name);

    /**
     * @brief createFilterMask
     * Creates a filter mask object that much like a filterlayer can apply a filter non-destructively.
     * @param name the name of the layer.
     * @param filter the filter assigned.
     * @param selection the selection to be used by the filter mask
     * @return a FilterMask
     */
    FilterMask* createFilterMask(const QString &name, Filter &filter, Selection &selection);

    /**
     * @brief createFilterMask
     * Creates a filter mask object that much like a filterlayer can apply a filter non-destructively.
     * @param name the name of the layer.
     * @param filter the filter assigned.
     * @param selection_source a node from which the selection should be initialized
     * @return a FilterMask
     */
    FilterMask* createFilterMask(const QString &name, Filter &filter, const Node* selection_source);

    /**
     * @brief createSelectionMask
     * Creates a selection mask, which can be used to store selections.
     * @param name - the name of the layer.
     * @return a SelectionMask
     */
    SelectionMask* createSelectionMask(const QString &name);

    /**
     * @brief createTransparencyMask
     * Creates a transparency mask, which can be used to assign transparency to regions.
     * @param name - the name of the layer.
     * @return a TransparencyMask
     */
    TransparencyMask* createTransparencyMask(const QString &name);

    /**
     * @brief createTransformMask
     * Creates a transform mask, which can be used to apply a transformation non-destructively.
     * @param name - the name of the layer mask.
     * @return a TransformMask
     */
    TransformMask* createTransformMask(const QString &name);

    /**
     * @brief createColorizeMask
     * Creates a colorize mask, which can be used to color fill via keystrokes.
     * @param name - the name of the layer.
     * @return a TransparencyMask
     */
    ColorizeMask* createColorizeMask(const QString &name);

    /**
     * @brief projection creates a QImage from the rendered image or
     * a cutout rectangle.
     */
    QImage projection(int x = 0, int y = 0, int w = 0, int h = 0) const;

    /**
     * @brief projection reads \p rect of the rendered image scaled by \p scale, without first
     * copying the full-size area. The time grows with the area of \p rect (a fast read of a few
     * rows at a time), not with the image's; memory stays near the size of the result: besides
     * it, each of at most Krita's thread limit of stripes holds a 256 KB row buffer (twice that
     * when the image is not 8-bit sRGB) and three rows of sums, 120 bytes per output column.
     *
     * Each output pixel is the average of the pixels it covers (an area average, weighted by
     * alpha), as a smooth downscale of projection(x, y, w, h) would give, in the same colours.
     * The result is round(rect.width() * scale) by round(rect.height() * scale) pixels, at
     * least 1 by 1. A \p scale of 1 or more reads the rect at full size (no upscaling).
     *
     * @code
     * side = 1568
     * view = d.projection(d.bounds(), side / max(d.width(), d.height()))
     * @endcode
     *
     * The read is consistent: it waits for the image's queued work, as waitForDone() does,
     * and holds a read-only lock while it reads, so no job can change the image under it. It
     * never asks a tool to end its stroke: while a stroke stays open (the artist holding the
     * pen) it keeps waiting, for at most 5 seconds, and then returns a null QImage; try again
     * later or read projection(x, y, w, h) instead. It also returns a null QImage when called
     * again from within a read (from events processed while it waits).
     *
     * @param rect the area in image pixels; it is not clipped: pixels outside the image read as
     * the projection's default pixel (transparent in a normal image), as with
     * projection(x, y, w, h)
     * @param scale output size over input size, above 0
     * @return the scaled image, or a null QImage for an empty rect, a scale of 0 or less, or a
     * read that could not lock the image within 5 seconds
     */
    QImage projection(const QRect &rect, qreal scale) const;

    /**
     * @brief thumbnail create a thumbnail of the given dimensions.
     *
     * If the requested size is too big a null QImage is created.
     *
     * @return a QImage representing the layer contents.
     */
    QImage thumbnail(int w, int h) const;


    /**
     * [low-level] Lock the image without waiting for all the internal job queues are processed
     *
     * WARNING: Don't use it unless you really know what you are doing! Use barrierLock() instead!
     *
     * Waits for all the **currently running** internal jobs to complete and locks the image
     * for writing. Please note that this function does **not** wait for all the internal
     * queues to process, so there might be some non-finished actions pending. It means that
     * you just postpone these actions until you unlock() the image back. Until then, then image
     * might easily be frozen in some inconsistent state.
     *
     * The only sane usage for this function is to lock the image for **emergency**
     * processing, when some internal action or scheduler got hung up, and you just want
     * to fetch some data from the image without races.
     *
     * In all other cases, please use barrierLock() instead!
     */
    void lock();

    /**
     * Unlocks the image and starts/resumes all the pending internal jobs. If the image
     * has been locked for a non-readOnly access, then all the internal caches of the image
     * (e.g. lod-planes) are reset and regeneration jobs are scheduled.
     */
    void unlock();

    /**
     * Wait for all the internal image jobs to complete and return without locking
     * the image. This function is handy for tests or other synchronous actions,
     * when one needs to wait for the result of his actions.
     */
    void waitForDone();

    /**
     * @brief Tries to lock the image without waiting for the jobs to finish
     *
     * Same as barrierLock(), but doesn't block execution of the calling thread
     * until all the background jobs are finished. Instead, in case of presence of
     * unfinished jobs in the queue, it just returns false
     *
     * @return whether the lock has been acquired
     */
    bool tryBarrierLock();

    /**
     * Starts a synchronous recomposition of the projection: everything will
     * wait until the image is fully recomputed.
     */
    void refreshProjection();

    /**
     * Starts a synchronous recomposition of the projection inside \p rect only (in image
     * pixels, clipped to the image), and waits until it is done. The cost grows with the
     * area of \p rect, not with the size of the image, so a script that knows what it
     * changed should pass that area instead of calling refreshProjection().
     *
     * The area is grown by what a change inside it can reach once composited: the halo of a
     * blur filter mask or adjustment layer, a drop shadow or another layer style. So passing
     * exactly the pixels written is enough; the refresh covers their effects too.
     *
     * An empty rect, or one entirely outside the image, does nothing and does not wait.
     *
     * Like refreshProjection(), it waits with waitForDone(), so it also waits for
     * whatever else the image is doing at the time.
     *
     * Node.setPixelData() composites its own area by itself: after it, call waitForDone(), not
     * refreshProjection(rect), which would composite the same area a second time. Use this
     * for changes Krita was not told about.
     *
     * @code
     * d.refreshProjection(QRect(x, y, w, h))  # recomposites (x, y, w, h) and what its effects reach
     * @endcode
     */
    void refreshProjection(const QRect &rect);

    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * replace all existing horizontal guides with the entries in the list.
     * @param lines a list of floats containing the new guides.
     */
    Q_DECL_DEPRECATED void setHorizontalGuides(const QList<qreal> &lines);
    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * replace all existing horizontal guides with the entries in the list.
     * @param lines a list of floats containing the new guides.
     */
    Q_DECL_DEPRECATED void setVerticalGuides(const QList<qreal> &lines);

    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * set guides visible on this document.
     * @param visible whether or not the guides are visible.
     */
    Q_DECL_DEPRECATED void setGuidesVisible(bool visible);

    /**
     * @brief DEPRECATED - use guidesConfig() instead
     * set guides locked on this document
     * @param locked whether or not to lock the guides on this document.
     */
    Q_DECL_DEPRECATED void setGuidesLocked(bool locked);

    /**
     * @brief modified returns true if the document has unsaved modifications.
     */
    bool modified() const;

    /**
     * @brief setModified sets the modified status of the document
     * @param modified if true, the document is considered modified and closing it will ask for saving.
     */
    void setModified(bool modified);

    /**
     * @brief bounds return the bounds of the image
     * @return the bounds
     */
    QRect bounds() const;

    /****
     * Animation Related API
     *****/


    /**
     * @brief Import an image sequence of files from a directory. This will grab all
     * images from the directory and import them with a potential offset (firstFrame)
     * and step (images on 2s, 3s, etc)
     * @returns whether the animation import was successful
     */
    bool importAnimation(const QList<QString> &files, int firstFrame, int step);

    /**
     * @brief frames per second of document
     * @return the fps of the document
     */
    int framesPerSecond();

    /**
     * @brief set frames per second of document
     */
    void setFramesPerSecond(int fps);

    /**
     * @brief set start time of animation
     */
    void setFullClipRangeStartTime(int startTime);

    /**
     * @brief get the full clip range start time
     * @return full clip range start time
     */
    int fullClipRangeStartTime();

    /**
     * @brief set full clip range end time
     */
    void setFullClipRangeEndTime(int endTime);

    /**
     * @brief get the full clip range end time
     * @return full clip range end time
     */
    int fullClipRangeEndTime();

    /**
     * @brief get total frame range for animation
     * @return total frame range for animation
     */
    int animationLength();

    /**
     * @brief set temporary playback range of document
     */
    void setPlayBackRange(int start, int stop);

    /**
     * @brief get start time of current playback
     * @return start time of current playback
     */
    int playBackStartTime();

    /**
     * @brief get end time of current playback
     * @return end time of current playback
     */
    int playBackEndTime();

    /**
     * @brief get current frame selected of animation
     * @return current frame selected of animation
     */
    int currentTime();

    /**
     * @brief set current time of document's animation
     */
    void setCurrentTime(int time);

    /**
     * @brief annotationTypes returns the list of annotations present in the document.
     * Each annotation type is unique.
     */
    QStringList annotationTypes() const;

    /**
     * @brief annotationDescription gets the pretty description for the current annotation
     * @param type the type of the annotation
     * @return a string that can be presented to the user
     */
    QString annotationDescription(const QString &type) const;

    /**
     * @brief annotation the actual data for the annotation for this type. It's a simple
     * QByteArray, what's in it depends on the type of the annotation
     * @param type the type of the annotation
     * @return a bytearray, possibly empty if this type of annotation doesn't exist
     */
    QByteArray annotation(const QString &type);

    /**
     * @brief setAnnotation Add the given annotation to the document
     * @param type the unique type of the annotation
     * @param description the user-visible description of the annotation
     * @param annotation the annotation itself
     */
    void setAnnotation(const QString &type, const QString &description, const QByteArray &annotation);

    /**
     * @brief removeAnnotation remove the specified annotation from the image
     * @param type the type defining the annotation
     */
    void removeAnnotation(const QString &type);

    /**
     * @brief Allow to activate/deactivate autosave for document
     * When activated, it will use default Krita autosave settings
     * It means that even when autosave is set to True, under condition Krita will not proceed to automatic save of document:
     * - autosave is globally deactivated
     * - document is read-only
     *
     * Being able to deactivate autosave on a document can make sense when a plugin use internal document
     * (document is not exposed in a view, only created for internal process purposes)
     *
     * @param active True to activate autosave
     */
    void setAutosave(bool active);

    /**
     * @brief Return autosave status for document
     * Notes:
     * - returned value is Autosave flag value
     *   Even if autosave is set to True, under condition Krita will not proceed to automatic save of document:
     *   - autosave is globally deactivated
     *   - document is read-only
     * - When autosave is set to False, Krita never execute automatic save for document
     *
     * @return True if autosave is active, otherwise False
     */
    bool autosave();

    /**
     * @brief Returns a GuidesConfig guides configuration for current document
     * @return a GuidesConfig object with guides configuration
     */
    GuidesConfig *guidesConfig();

    /**
     * @brief Set guides configuration for current document
     * @param guidesConfig a GuidesConfig object to apply for guides configuration
     *
     * To modify/set guides property on a document
@code
# get document (create one or get active one for example)
newDoc = Krita.instance().createDocument(500, 500, "Test", "RGBA", "U8", "", 300)

# retrieve document guides configuration
newDocGuides = newDoc.guidesConfig()

# update properties
newDocGuides.setColor(QColor('#ff00ff'))
newDocGuides.setLineType('dotted')
newDocGuides.setVisible(True)
newDocGuides.setLocked(True)
newDocGuides.setSnap(True)
newDocGuides.setHorizontalGuides([100,200])

# set guides configuration to document
newDoc.setGuidesConfig(newDocGuides)
@endcode
     */
    void setGuidesConfig(GuidesConfig *guidesConfig);

    /**
     * @brief Returns a GridConfig grid configuration for current document
     * @return a GridConfig object with grid configuration
     */
    GridConfig *gridConfig();

    /**
     * @brief Set grid configuration for current document
     * @param gridConfig a GridConfig object to apply for grid configuration
     *
     * To modify/set grid property on a document
@code
# get document (create one or get active one for example)
newDoc = Krita.instance().createDocument(500, 500, "Test", "RGBA", "U8", "", 300)

# retrieve document grid configuration
newDocGrid = newDoc.gridConfig()

# update properties
newDocGrid.setColorMain(QColor('#ff00ff'))
newDocGrid.setLineTypeMain('dashed')
newDocGrid.setVisible(True)
newDocGrid.setAngleLeft(30)
newDocGrid.setAngleRight(15)
newDocGrid.setType('isometric')

# set grid configuration to document
newDoc.setGridConfig(newDocGrid)
@endcode
     */
    void setGridConfig(GridConfig *gridConfig);

    /**
     * @brief Return current audio level for document
     * @return A value between 0.0 and 1.0 (1.0 = 100%)
     */
    qreal audioLevel() const;

    /**
     * @brief Set current audio level for document
     * @param level Audio volume between 0.0 and 1.0 (1.0 = 100%)
     */
    void setAudioLevel(const qreal level);

    /**
     * @brief Return a list of current audio tracks for document
     * @return List of absolute path/file name of audio files
     */
    QList<QString> audioTracks() const;

    /**
     * @brief Set a list of audio tracks for document
     * Note: the function allows to add more than one file while from Krita's UI, importing a file
     * will replace the complete list
     *
     * The reason why this method let the ability to provide more than one file is related to
     * the internal's Krita method from KisDocument class:
     * void KisDocument::setAudioTracks(QVector<QFileInfo> f)
     *
     * @param files List of absolute path/file name of audio files
     * @return True if all files from list have been added, otherwise False (a file was not found)
     */
    bool setAudioTracks(const QList<QString> files) const;

    // Krita Agent: undo history and agent moves (DocumentHistory.cpp).

    /**
     * @brief undoCount the number of steps in the document's undo history, the ones that can be
     * redone included. While a macro or an agent move is open, it is counted as the last step.
     */
    int undoCount() const;

    /**
     * @brief undoText the name of step \p index (0 is the oldest), as the Undo History docker
     * shows it; an empty string when there is no such step.
     */
    QString undoText(int index) const;

    /**
     * @brief undoIndex the number of steps applied: steps 0 to undoIndex() - 1 are done, the
     * rest can be redone.
     */
    int undoIndex() const;

    /**
     * @brief setUndoIndex undoes or redoes steps until \p index steps are applied, as clicking
     * a step in the Undo History docker does.
     *
     * It first waits for the image's queued work to finish (Krita would otherwise cancel it),
     * without asking any stroke to end, for up to 3 seconds, handling input meanwhile (so an
     * artist holding the pen down can lift it); it refuses if the image is still busy. The undo and redo work itself is
     * queued like painting: call waitForDone() before reading pixels.
     *
     * @return false, changing nothing, when \p index is outside 0 to undoCount(), or a macro or
     * an agent move is open
     */
    bool setUndoIndex(int index);

    /**
     * @brief cleanIndex the undo index at which the document was last saved (or created), or
     * -1 when that state is no longer in the history.
     */
    int cleanIndex() const;

    /**
     * @brief beginUndoMacro groups the script's work until endUndoMacro() into one undo step
     * named \p name: its strokes (the paint* calls), new layers and other Node edits run as
     * strokes, filters started with Filter.startFilter(), and pixel writes (inside a macro or an
     * agent move, Node.setPixelData() is undoable and queued after the script's earlier strokes,
     * like painting: read pixels after waitForDone()). A macro opened inside an open one joins it.
     * The artist's work meanwhile keeps its own steps; see beginAgentMove().
     *
     * @return false without an image
     */
    bool beginUndoMacro(const QString &name);

    /**
     * @brief endUndoMacro closes the innermost macro. It returns at once; the step lands in the
     * history when the strokes queued in it have finished (waitForDone() waits for that). An empty
     * macro adds no step.
     * @return false when no macro is open, or the innermost open step is an agent move
     */
    bool endUndoMacro();

    /**
     * @brief beginAgentMove opens an agent move: everything done until endAgentMove() becomes
     * one undo step named "Agent: <name>", however many strokes, layers, pixel writes and filters
     * it holds, so a move never uses up Krita's undo limit and one undo removes all of it.
     *
     * Scripted strokes without a name of their own are named after the move. The step appears in
     * the Undo History docker as "Agent: <name>" once the move ends. The artist's work during the
     * move keeps its own steps, and undo stays available. When the artist changes a layer the
     * move has already changed, the move's work so far becomes a step first, and the rest follows
     * as "Agent: <name> (cont.)", so each layer's changes undo in the order they were made.
     *
     * A move left open closes by itself, with a warning: when the document is saved (not
     * exported), when the history moves on an idle image (undo, redo, a step chosen in the Undo
     * History docker), and after 120 seconds without script work (queued work counts). Its work
     * so far becomes a step; the move stays open for the script (agentMoveOpen(), the same
     * agentMoveId()), its next work continues it as "Agent: <name> (cont.)", and endAgentMove()
     * ends it. In Python, prefer the context manager, which ends only its own move, also on
     * exceptions:
     *
     * @code
     * with d.agentMove("paint sky"):
     *     for points in strokes:
     *         layer.paintPolylineStroke(points)
     * @endcode
     *
     * @return false, opening nothing, without an image, or when an agent move or a macro is
     * already open (agent moves are always top-level steps)
     */
    bool beginAgentMove(const QString &name);

    /**
     * @brief endAgentMove closes the open agent move. It returns at once; the move's step lands in
     * the history when the strokes queued in it have finished (waitForDone() waits for that). An
     * empty move adds no step and leaves the document unmodified.
     * @return false when no agent move is open, a macro opened inside it is still open, the
     * document's image was replaced, or the document was closed
     */
    bool endAgentMove();

    /**
     * @brief agentMoveOpen whether an agent move is open on this document (through any Document
     * object for it). An open move is agent work: from beginAgentMove() until its step has landed,
     * agentActive() is true and changeSource() is "agent".
     */
    bool agentMoveOpen() const;

    /**
     * @brief agentMoveName the name of the open agent move, or an empty string.
     */
    QString agentMoveName() const;

    /**
     * @brief agentMoveId a number for the open agent move, the same for its whole life (a move
     * that closed by itself and continues keeps it), new for each beginAgentMove(); 0 when no
     * move is open. A script checks it to end only its own move.
     */
    int agentMoveId() const;

private:

    friend class Krita;
    friend class Window;
    friend class Filter;
    friend class View;
    friend class VectorLayer;
    friend class Shape;
    QPointer<KisDocument> document() const;
    void setOwnsDocument(bool ownsDocument);

private:
    struct Private;
    Private *const d;

};

#endif // LIBKIS_DOCUMENT_H
