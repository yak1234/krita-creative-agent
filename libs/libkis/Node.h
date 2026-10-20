/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_NODE_H
#define LIBKIS_NODE_H

#include <QObject>
#include <QColor>
#include <QPointF>
#include <QVariantMap>
#include <QVariant>

#include <kis_types.h>

#include "kritalibkis_export.h"
#include "libkis.h"

#include "PaintingResources.h"
#include "StrokePoint.h"

class StrokeJob; // Krita Agent: Node::paintStrokes()

/**
 * Node represents a layer or mask in a Krita image's Node hierarchy. Group layers can contain
 * other layers and masks; layers can contain masks.
 *
 */
class KRITALIBKIS_EXPORT Node : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(Node)

public:
    static Node *createNode(KisImageSP image, KisNodeSP node, QObject *parent = 0);
    ~Node() override;
    bool operator==(const Node &other) const;
    bool operator!=(const Node &other) const;

public Q_SLOTS:

    /**
     * @brief clone clone the current node. The node is not associated with any image.
     */
    Node *clone() const;

    /**
     * @brief alphaLocked checks whether the node is a paint layer and returns whether it is alpha locked
     * @return whether the paint layer is alpha locked, or false if the node is not a paint layer
     */
    bool alphaLocked() const;

    /**
     * @brief setAlphaLocked set the layer to value if the node is paint layer.
     */
    void setAlphaLocked(bool value);

    /**
     * @return the blending mode of the layer. The values of the blending modes are defined in @see KoCompositeOpRegistry.h
     */
    QString blendingMode() const;

    /**
     * @brief setBlendingMode set the blending mode of the node to the given value
     * @param value one of the string values from @see KoCompositeOpRegistry.h
     */
    void setBlendingMode(QString value);

    /**
     * @brief channels creates a list of Channel objects that can be used individually to
     * show or hide certain channels, and to retrieve the contents of each channel in a
     * node separately.
     *
     * Only layers have channels, masks do not, and calling channels on a Node that is a mask
     * will return an empty list.
     *
     * @return the list of channels ordered in by position of the channels in pixel position
     */
    QList<Channel*> channels() const;

    /**
     * @brief childNodes
     * @return returns a list of child nodes of the current node. The nodes are ordered from the bottommost up.
     * The function is not recursive.
     */
    QList<Node*> childNodes() const;

    /**
     * @brief findChildNodes
     * @param name name of the child node to search for. Leaving this blank will return all nodes.
     * @param recursive whether or not to search recursively. Defaults to false.
     * @param partialMatch return if the name partially contains the string (case insensitive). Defaults to false.
     * @param type filter returned nodes based on type
     * @param colorLabelIndex filter returned nodes based on color label index
     * @return returns a list of child nodes and grand child nodes of the current node that match the search criteria.
     */
    QList<Node*> findChildNodes(const QString &name = QString(), bool recursive = false, bool partialMatch = false, const QString &type = QString(), int colorLabelIndex = 0) const;

    /**
     * @brief addChildNode adds the given node in the list of children.
     * @param child the node to be added
     * @param above the node above which this node will be placed
     * @return false if adding the node failed
     */
    bool addChildNode(Node *child, Node *above);

    /**
     * @brief removeChildNode removes the given node from the list of children.
     * @param child the node to be removed
     */
    bool removeChildNode(Node *child);

    /**
     * @brief setChildNodes this replaces the existing set of child nodes with the new set.
     * @param nodes The list of nodes that will become children, bottom-up -- the first node,
     * is the bottom-most node in the stack.
     */
    void setChildNodes(QList<Node*> nodes);

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
     * @return if assigning the color profile worked. Refused (false, with a warning and the features named in
     * Document.lastKeptOut()) when the layer's pixels reach a protected feature; Document.setProtectionSuspended()
     * allows it.
     */
    bool setColorProfile(const QString &colorProfile);

    /**
     * @brief setColorSpace convert the node to the given colorspace
     * @param colorModel A string describing the color model of the node:
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
     * @return true if converted. Refused (false, with a warning and the features named in Document.lastKeptOut())
     * when the layer's pixels reach a protected feature, as setColorProfile().
     */
    bool setColorSpace(const QString &colorModel, const QString &colorDepth, const QString &colorProfile);

    /**
     * @brief Krita layers can be animated, i.e., have frames.
     * @return return true if the layer has frames. Currently, the scripting framework
     * does not give access to the animation features.
     */
    bool animated() const;

    /**
     * @brief enableAnimation make the current layer animated, so it can have frames.
     */
    void enableAnimation() const;

    /**
     * @brief Sets whether or not node should be pinned to the Timeline Docker,
     * regardless of selection activity.
     */
    void setPinnedToTimeline(bool pinned) const;

    /**
     * @return Returns true if node is pinned to the Timeline Docker or false if it is not.
     */
    bool isPinnedToTimeline() const;

    /**
     * Sets the state of the node to the value of @param collapsed
     */
    void setCollapsed(bool collapsed);

    /**
     * returns the collapsed state of this node
     */
    bool collapsed() const;

    /**
     * Sets a color label index associated to the layer.  The actual
     * color of the label and the number of available colors is
     * defined by Krita GUI configuration.
     */
    int colorLabel() const;

    /**
     * @brief setColorLabel sets a color label index associated to the layer.  The actual
     * color of the label and the number of available colors is
     * defined by Krita GUI configuration.
     * @param index an integer corresponding to the set of available color labels.
     */
    void setColorLabel(int index);

    /**
     * @brief inheritAlpha checks whether this node has the inherits alpha flag set
     * @return true if the Inherit Alpha is set
     */
    bool inheritAlpha() const;

    /**
     * set the Inherit Alpha flag to the given value
     */
    void setInheritAlpha(bool value);

    /**
     * @brief locked checks whether the Node is locked. A locked node cannot be changed.
     * @return true if the Node is locked, false if it hasn't been locked.
     */
    bool locked() const;

    /**
     * set the Locked flag to the give value
     */
    void setLocked(bool value);

    /**
     * @brief does the node have any content in it?
     * @return if node has any content in it
     */
    bool hasExtents();


    /**
     * @return the user-visible name of this node.
     */
    QString name() const;

    /**
     * rename the Node to the given name
     */
    void setName(QString name);

    /**
     * return the opacity of the Node. The opacity is a value between 0 and 255.
     */
    int opacity() const;

    /**
     * set the opacity of the Node to the given value. The opacity is a value between 0 and 255.
     */
    void setOpacity(int value);

    /**
     * return the Node that is the parent of the current Node, or 0 if this is the root Node.
     */
    Node* parentNode() const;

    /**
     * @brief type Krita has several types of nodes, split in layers and masks. Group
     * layers can contain other layers, any layer can contain masks.
     *
     * @return The type of the node. Valid types are:
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
     *  <li>colorizemask
     * </ul>
     *
     * If the Node object isn't wrapping a valid Krita layer or mask object, and
     * empty string is returned.
     */
    virtual QString type() const;

    /**
     * @brief icon
     * @return the icon associated with the layer.
     */
    QIcon icon() const;

    /**
     * Check whether the current Node is visible in the layer stack
     */
    bool visible() const;

    /**
     * Check to see if frame number on layer is a keyframe
     */
    bool hasKeyframeAtTime(int frameNumber);

    /**
     * Set the visibility of the current node to @param visible
     */
    void setVisible(bool visible);

    /**
     * @brief pixelData reads the given rectangle from the Node's paintable pixels, if those
     * exist, and returns it as a byte array. The pixel data starts top-left, and is ordered row-first.
     *
     * The byte array can be interpreted as follows: 8 bits images have one byte per channel,
     * and as many bytes as there are channels. 16 bits integer images have two bytes per channel,
     * representing an unsigned short. 16 bits float images have two bytes per channel, representing
     * a half, or 16 bits float. 32 bits float images have four bytes per channel, representing a
     * float.
     *
     * You can read outside the node boundaries; those pixels will be transparent black.
     *
     * The order of channels is:
     *
     * <ul>
     * <li>Integer RGBA: Blue, Green, Red, Alpha
     * <li>Float RGBA: Red, Green, Blue, Alpha
     * <li>GrayA: Gray, Alpha
     * <li>Selection: selectedness
     * <li>LabA: L, a, b, Alpha
     * <li>CMYKA: Cyan, Magenta, Yellow, Key, Alpha
     * <li>XYZA: X, Y, Z, A
     * <li>YCbCrA: Y, Cb, Cr, Alpha
     * </ul>
     *
     * The byte array is a copy of the original node data. In Python, you can use bytes, bytearray
     * and the struct module to interpret the data and construct, for instance, a Pillow Image object.
     *
     * If you read the pixeldata of a mask, a filter or generator layer, you get the selection bytes,
     * which is one channel with values in the range from 0..255.
     *
     * If you want to change the pixels of a node you can write the pixels back after manipulation
     * with setPixelData(). This will only succeed on nodes with writable pixel data, e.g not on groups
     * or file layers.
     *
     * @param x x position from where to start reading
     * @param y y position from where to start reading
     * @param w row length to read
     * @param h number of rows to read
     * @return a QByteArray with the pixel data. The byte array may be empty.

     */
    QByteArray pixelData(int x, int y, int w, int h) const;

    /**
     * @brief pixelDataAtTime a basic function to get pixeldata from an animated node at a given time.
     * @param x the position from the left to start reading.
     * @param y the position from the top to start reader
     * @param w the row length to read
     * @param h the number of rows to read
     * @param time the frame number
     * @return a QByteArray with the pixel data. The byte array may be empty.
     */
    QByteArray pixelDataAtTime(int x, int y, int w, int h, int time) const;

    /**
     * @brief projectionPixelData reads the given rectangle from the Node's projection (that is, what the node
     * looks like after all sub-Nodes (like layers in a group or masks on a layer) have been applied,
     * and returns it as a byte array. The pixel data starts top-left, and is ordered row-first.
     *
     * The byte array can be interpreted as follows: 8 bits images have one byte per channel,
     * and as many bytes as there are channels. 16 bits integer images have two bytes per channel,
     * representing an unsigned short. 16 bits float images have two bytes per channel, representing
     * a half, or 16 bits float. 32 bits float images have four bytes per channel, representing a
     * float.
     *
     * You can read outside the node boundaries; those pixels will be transparent black.
     *
     * The order of channels is:
     *
     * <ul>
     * <li>Integer RGBA: Blue, Green, Red, Alpha
     * <li>Float RGBA: Red, Green, Blue, Alpha
     * <li>GrayA: Gray, Alpha
     * <li>Selection: selectedness
     * <li>LabA: L, a, b, Alpha
     * <li>CMYKA: Cyan, Magenta, Yellow, Key, Alpha
     * <li>XYZA: X, Y, Z, A
     * <li>YCbCrA: Y, Cb, Cr, Alpha
     * </ul>
     *
     * The byte array is a copy of the original node data. In Python, you can use bytes, bytearray
     * and the struct module to interpret the data and construct, for instance, a Pillow Image object.
     *
     * If you read the projection of a mask, you get the selection bytes, which is one channel with
     * values in the range from 0..255.
     *
     * If you want to change the pixels of a node you can write the pixels back after manipulation
     * with setPixelData(). This will only succeed on nodes with writable pixel data, e.g not on groups
     * or file layers.
     *
     * @param x x position from where to start reading
     * @param y y position from where to start reading
     * @param w row length to read
     * @param h number of rows to read
     * @return a QByteArray with the pixel data. The byte array may be empty.
     */
    QByteArray projectionPixelData(int x, int y, int w, int h) const;

    /**
     * @brief setPixelData writes the given bytes, of which there must be enough, into the
     * Node, if the Node has writable pixel data:
     *
     * <ul>
     * <li>paint layer: the layer's original pixels are overwritten
     * <li>filter layer, generator layer, any mask: the embedded selection's pixels are overwritten.
     * <b>Note:</b> for these
     * </ul>
     *
     * File layers, Group layers, Clone layers cannot be written to. Calling setPixelData on
     * those layer types will silently do nothing.
     *
     * @param value the byte array representing the pixels. There must be enough bytes available.
     * Krita will take the raw pointer from the QByteArray and start reading, not stopping before
     * (number of channels * size of channel * w * h) bytes are read.
     *
     * @param x the x position to start writing from
     * @param y the y position to start writing from
     * @param w the width of each row
     * @param h the number of rows to write
     * @return true if writing the pixeldata worked
     *
     * The written rect is marked dirty, so the image recomposites it (and what effects such as
     * a blur mask spread from it) in the background; call Document.waitForDone() before reading
     * the projection. Neither Document.refreshProjection() nor refreshProjection(rect) is
     * needed after it: either would composite the area a second time.
     */
    bool setPixelData(QByteArray value, int x, int y, int w, int h);

    /**
     * @brief bounds return the exact bounds of the node's paint device
     * @return the bounds, or an empty QRect if the node has no paint device or is empty.
     */
    QRect bounds() const;

    /**
     *  move the pixels to the given x, y location in the image coordinate space.
     *
     *  Krita Agent (krita-fork 5.3): one undo step ("Move"), or part of an open macro or agent move; it waits until
     *  the move is done, as the tool functions below do. Returns false, changing nothing, when the node is locked (or
     *  inside a locked group), is the root, or is not a layer or mask in its document. Body in NodeAgentTools.cpp.
     */
    bool move(int x, int y);

    /**
     * @brief position returns the position of the paint device of this node. The position is
     * always 0,0 unless the layer has been moved. If you want to know the topleft position of
     * the rectangle around the actual non-transparent pixels in the node, use bounds().
     * @return the top-left position of the node
     */
    QPoint position() const;

    // Krita Agent: Krita's painting tools as functions (krita-fork 5.3), bodies in NodeAgentTools.cpp.
    //
    // Each call works without a view and never reads the view's colours, brush, mirror or eraser mode. It is one
    // undo step, named as the tool names it unless options["name"] is given, or part of an open macro or agent move.
    // It never asks the artist's open strokes to end, and it waits for its own stroke only (never for the whole
    // image, and without running the event loop) until its pixels are on the layer. A stroke queued behind one the
    // artist is still drawing cannot start: after 60 s the call gives up, cancels its stroke and returns false.
    // It returns false, changing nothing, with a warning, when the node is locked (or inside a locked group), has no
    // pixels of its own (a group, a file or clone layer), is not in its document, or an argument or option is
    // unknown, not finite or out of range. Hidden layers can be painted. Colours are converted to the image's colour
    // space. The selection is read when the call's stroke runs, after the work queued before it.
    //
    // fill(), encloseAndFill() and gradient(): without a selection argument, the document's selection limits the
    // operation, as it limits the tool. smartPatch() changes only its area.

    /**
     * @brief fill fills from a point, as the Fill tool does with a click.
     * @param x, y the point, in image pixels
     * @param color the fill colour (converted to the image's colour space)
     * @param options any of:
     * <ul>
     * <li>"mode": "contiguous" (default: the region around the point), "similar" (every pixel of a similar colour)
     * or "selection" (all of the selection, or of the layer)</li>
     * <li>"sample": where regions are found: "layer" (default, this layer), "all" (all layers, as shown) or
     * "labels" (the layers with one of "labels", a list of colour label numbers 0 to 8)</li>
     * <li>"threshold" (1 to 100, default 8), "spread" (0 to 100, default 100), "closeGap" (0 to 32), "grow" (-400 to
     * 400 pixels), "feather" (0 to 400 pixels), "antialias" (bool), "stopGrowingAtDarkestPixel" (bool),
     * "useSelectionAsBoundary" (bool, default true, as the tool: regions end at the selection's edge)</li>
     * <li>"boundaryColor" (a colour): fill up to this colour instead of up to any different colour</li>
     * <li>"opacity" (0.0 to 1.0, default 1.0), "compositeOp" (a blending mode id, default "normal")</li>
     * <li>"name": the undo step's name (default "Flood Fill")</li>
     * </ul>
     * @param selection limits the fill instead of the document's selection (refused when it selects nothing)
     * @return true when the fill was made
     */
    bool fill(int x, int y, const QColor &color, const QVariantMap &options = QVariantMap(),
              Selection *selection = nullptr);

    /**
     * @brief encloseAndFill fills the regions inside an enclosing area, as the Enclose and Fill tool does with a
     * drawn shape.
     * @param enclosingArea the enclosing area (not empty)
     * @param color the fill colour
     * @param options "regions": which regions inside the area are filled: "all" (default), "color", "transparent",
     * "colorOrTransparent", "allExceptColor", "allExceptTransparent", "allExceptColorOrTransparent",
     * "surroundedByColor", "surroundedByTransparent" or "surroundedByColorOrTransparent", with "regionColor" (a
     * colour, required) for the ones naming a colour; "invert" (bool), "includeContourRegions" (bool, default false,
     * as the tool: regions touching the enclosing area's edge are left),
     * "includeSurroundingRegions" (bool, default false); and fill()'s "sample", "labels", "threshold", "spread",
     * "closeGap", "grow", "feather", "antialias", "stopGrowingAtDarkestPixel", "useSelectionAsBoundary", "opacity",
     * "compositeOp" and "name" (default "Enclose and Fill")
     * @param selection limits the fill instead of the document's selection
     */
    bool encloseAndFill(Selection *enclosingArea, const QColor &color, const QVariantMap &options = QVariantMap(),
                        Selection *selection = nullptr);

    /**
     * @brief gradient paints a gradient between two points, as the Gradient tool does with a drag.
     * @param start, end the gradient's ends, in image pixels: finite, within 1e6 of the origin, not the same point
     * @param options "colors": a list of two or more colours, spaced evenly from start to end; or "gradient": the
     * name of a gradient resource (its foreground and background stops take the first and second of "colors", else
     * black and white); "shape": "linear" (default), "bilinear", "radial", "square", "conical", "conicalSymmetric",
     * "spiral", "reverseSpiral" or "polygonal"; "repeat": "none" (default), "forwards" or "alternate"; "reverse"
     * (bool); "dither": false (default), true (blue noise), "blueNoise", "bayer2", "bayer4" or "bayer8";
     * "antiAliasThreshold" (0.0 to 1.0, default 0.2); "opacity", "compositeOp", and "name" (default "Gradient")
     * @param selection the area painted instead of the document's selection; with neither, the whole layer
     */
    bool gradient(const QPointF &start, const QPointF &end, const QVariantMap &options = QVariantMap(),
                  Selection *selection = nullptr);

    /**
     * @brief smartPatch fills an area from the paint around it (PatchMatch inpainting), as the Smart Patch tool does
     * with a painted mask. Only pixels inside the area change; where the area is partly selected (soft edges), the
     * patch is blended with the paint there. The document's selection is not used.
     * @param area the area to patch: not empty, and its bounding rectangle at most 512 x 512 pixels (262144; a
     * megapixel takes over 13 s, so larger areas are patched in pieces)
     * @param options "accuracy" (0 to 99, default 50: how much of the surroundings is searched), "patchRadius" (2 to
     * 8, default 4), "name" (default "Smart Patch")
     */
    bool smartPatch(Selection *area, const QVariantMap &options = QVariantMap());

    /**
     * @brief remove removes this node from its parent image.
     */
    bool remove();

    /**
     * @brief duplicate returns a full copy of the current node. The node is not inserted in the graphic
     * @return a valid Node object or 0 if the node couldn't be duplicated.
     */
    Node* duplicate();

    /**
     * @brief save exports the given node with this filename. The extension of the filename determines the filetype.
     * @param filename the filename including extension
     * @param xRes the horizontal resolution in pixels per pt (there are 72 pts in an inch)
     * @param yRes the horizontal resolution in pixels per pt (there are 72 pts in an inch)
     * @param exportConfiguration a configuration object appropriate to the file format.
     * @param exportRect the export bounds for saving a node as a QRect
     * If \p exportRect is empty, then save exactBounds() of the node. If you'd like to save the image-
     * aligned area of the node, just pass image->bounds() there.
     * See Document->exportImage for InfoObject details.
     * @return true if saving succeeded, false if it failed.
     */
    bool save(const QString &filename, double xRes, double yRes, const InfoObject &exportConfiguration, const QRect &exportRect = QRect());

    /**
     * @brief mergeDown merges the given node with the first visible node underneath this node in the layerstack.
     * This will drop all per-layer metadata.
     *
     * Protection (krita-fork 6.5): a merge leaves the composite as it is only when both layers use the Normal blending
     * mode and this layer is fully opaque. Otherwise it changes the lower layer's pixels under this one, and it is
     * refused (None, with a warning, the features named in Document.lastKeptOut()) when this layer's pixels reach a
     * protected feature. Document.setProtectionSuspended() allows it.
     */
    Node *mergeDown();

    /**
     * @brief scaleNode
     * @param origin the origin point
     * @param width the width
     * @param height the height
     * @param strategy the scaling strategy. There's several ones amongst these that aren't available in the regular UI.
     *
     * Protection (krita-fork 6.5): refused when the layer's pixels, now or after the change, reach a protected feature
     * (the call cannot be clipped to it). It returns false, warns, and Document.lastKeptOut() names the features.
     * Document.setProtectionSuspended() allows it. Returns false too for a node that is not a layer in a document.
     * <ul>
     * <li>Hermite</li>
     * <li>Bicubic - Adds pixels using the color of surrounding pixels. Produces smoother tonal gradations than Bilinear.</li>
     * <li>Box - Replicate pixels in the image. Preserves all the original detail, but can produce jagged effects.</li>
     * <li>Bilinear - Adds pixels averaging the color values of surrounding pixels. Produces medium quality results when the image is scaled from half to two times the original size.</li>
     * <li>Bell</li>
     * <li>BSpline</li>
     * <li>Lanczos3 - Offers similar results than Bicubic, but maybe a little bit sharper. Can produce light and dark halos along strong edges.</li>
     * <li>Mitchell</li>
     * </ul>
     */
    bool scaleNode(QPointF origin, int width, int height, QString strategy);

    /**
     * @brief rotateNode rotate this layer by the given radians.
     * @param radians amount the layer should be rotated in, in radians.
     *
     * Protection (krita-fork 6.5): refused when the layer's pixels, now or after the change, reach a protected feature
     * (the call cannot be clipped to it). It returns false, warns, and Document.lastKeptOut() names the features.
     * Document.setProtectionSuspended() allows it. Returns false too for a node that is not a layer in a document.
     */
    bool rotateNode(double radians);

    /**
     * @brief cropNode crop this layer.
     * @param x the left edge of the cropping rectangle.
     * @param y the top edge of the cropping rectangle
     * @param w the right edge of the cropping rectangle
     * @param h the bottom edge of the cropping rectangle
     *
     * Protection (krita-fork 6.5): refused when the layer's pixels, now or after the change, reach a protected feature
     * (the call cannot be clipped to it). It returns false, warns, and Document.lastKeptOut() names the features.
     * Document.setProtectionSuspended() allows it. Returns false too for a node that is not a layer in a document.
     */
    bool cropNode(int x, int y, int w, int h);

    /**
     * @brief shearNode perform a shear operation on this node.
     * @param angleX the X-angle in degrees to shear by
     * @param angleY the Y-angle in degrees to shear by
     *
     * Protection (krita-fork 6.5): refused when the layer's pixels, now or after the change, reach a protected feature
     * (the call cannot be clipped to it). It returns false, warns, and Document.lastKeptOut() names the features.
     * Document.setProtectionSuspended() allows it. Returns false too for a node that is not a layer in a document.
     */
    bool shearNode(double angleX, double angleY);

    /**
     * @brief thumbnail create a thumbnail of the given dimensions. The thumbnail is sized according
     * to the layer dimensions, not the image dimensions. If the requested size is too big a null
     * QImage is created. If the current node cannot generate a thumbnail, a transparent QImage of the
     * requested size is generated.
     * @return a QImage representing the layer contents.
     */
    QImage thumbnail(int w, int h);

    /**
     * @brief layerStyleToAsl retrieve the current layer's style in ASL format.
     * @return a QString in ASL format representing the layer style.
     */
    QString layerStyleToAsl();

    /**
     * @brief setLayerStyleFromAsl set a new layer style for this node.
     * @param aslContent a string formatted in ASL format containing the layer style
     * @return true if layer style was set, false if failed.
     */
    bool setLayerStyleFromAsl(const QString &asl);

    /**
     * @brief index the index of the node inside the parent
     * @return an integer representing the node's index inside the parent
     */
    int index() const;

    /**
     * @brief uniqueId uniqueId of the node
     * @return a QUuid representing a unique id to identify the node
     */
    QUuid uniqueId() const;

    /**
     * @brief paint a line on the canvas. Uses current brush preset
     * @param pointOne starting point
     * @param pointTwo end point
     * @param pressureOne starting pressure
     * @param pressureTwo end pressure
     * @param strokeStyle appearance of the outline, one of:
     * <ul>
     * <li>None - will use Foreground Color, since line would be invisible otherwise
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * </ul>
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintLine(const QPointF pointOne,
                   const QPointF pointTwo,
                   double pressureOne = 1.0,
                   double pressureTwo = 1.0,
                   const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                   const QString &name = QString());

    /**
     * @brief paintPolylineStroke paint one continuous brush stroke with complete input
     * information for every supplied point. Uses the current brush preset.
     *
     * The stroke is submitted as one undoable freehand stroke, so brush
     * spacing, randomness, and distance-based sensors are continuous across
     * all segments. A single point paints one dab.
     *
     * @param points input samples in image coordinates. Time is elapsed
     * milliseconds from the beginning of the stroke; speed is normalized.
     * @param strokeStyle appearance of the outline; see paintLine().
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintPolylineStroke(const QList<StrokePoint> &points,
                     const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                     const QString &name = QString());

    /**
     * @brief paintStrokes paint brush strokes in the background, with full pen input, and return the job painting
     * them (Krita Agent; defined in NodeStrokeJobs.cpp). The call returns at once and never blocks the window, and
     * it needs no active view: the brush comes from the job's options, never from the view's state.
     *
     * Each stroke is a map, painted as one freehand stroke (spacing, randomness and distance sensors continuous
     * along it), in image pixels:
     * <ul>
     * <li>"points": [[x, y, pen...], ...], straight lines between them (one point paints one dab); or</li>
     * <li>"start": [x, y, pen...] and "segments": [[c1x, c1y, c2x, c2y, x, y, pen...], ...], cubic curves;</li>
     * <li>"color" ("#rrggbb", "#aarrggbb" or a colour name; black when not given), "size" (the brush diameter in
     *     pixels), "opacity" and "flow" (0 to 1); the preset's own size, opacity and flow when not given.</li>
     * </ul>
     * Pen input per point, in the units Krita's tablet input gives its brush engine, inline after x and y in this
     * order, or as per-point lists in the stroke (one value per point: the start, then each segment's end):
     * "pressure" (0 to 1), "tilt" ([x, y] in degrees, -60 to 60), "rotation" (degrees, -180 to 180), "speed" (0 to 1:
     * Krita's view pixels per millisecond over 30) and "time_ms" (milliseconds since the stroke began). A value not
     * given is a mouse's: pressure 1, everything else 0. Values out of range are clamped, rotation wrapped.
     *
     * Points and control points must lie inside the image grown by one brush size (the stroke's, else the
     * preset's); a job takes at most 10000 strokes of at most 10000 points. A stroke of only a start, or of one
     * point, paints one dab.
     *
     * The strokes are queued in windows of 32, the next when the last has painted, so the artist's own strokes run
     * between windows instead of after the whole job. Job strokes never ask the artist's strokes to end, and Esc
     * does not cancel them; the artist's Undo during a job stops it (keeping its first strokes) and then undoes.
     * Must be called on the GUI thread.
     *
     * @param strokes the strokes, painted in order.
     * @param options a map of:
     * <ul>
     * <li>"preset": the name of a brush preset in the resource database; when not given, a copy of the active
     *     view's current preset (refused without one);</li>
     * <li>"compositeOp": the blending mode id (for example "normal", "multiply"); the preset's own when not
     *     given. Erasing is "erase": the view's eraser mode never applies;</li>
     * <li>"name": the undo step's name ("Scripted Brush Strokes" when not given);</li>
     * <li>"color", "size", "opacity", "flow": defaults for strokes that do not give their own.</li>
     * </ul>
     * Mirror painting is always off, and neither the view's eraser mode nor its alpha lock applies.
     * @param selection the selection the strokes are clipped to; none (null) paints everywhere, whatever the
     * document's or the layer's selection.
     * @return the job, owned by the caller. A job refused (no document, no paintable pixels, a locked node, no
     * preset, a malformed stroke) is returned in state "failed" with nothing queued.
     *
     * Undo: the job is one undo step, named by "name", landing when its last stroke has ended; inside an open agent
     * move or undo macro it joins that step (which then lands only after the job, even if the script ends it first).
     */
    StrokeJob *paintStrokes(const QVariantList &strokes,
                            const QVariantMap &options = QVariantMap(),
                            Selection *selection = nullptr);

    /**
     * @brief paint a rectangle on the canvas. Uses current brush preset
     * @param rect QRect with x, y, width, and height
     * @param strokeStyle appearance of the outline, one of:
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * </ul>
     * Default is ForegroundColor.
     * @param fillStyle appearance of the fill, one of:
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * <li>Pattern</li>
     * </ul>
     * Default is None.
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintRectangle(const QRectF &rect,
                        const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                        const QString fillStyle = PaintingResources::defaultFillStyle,
                        const QString &name = QString());
 
    /**
     * @brief paint a polygon on the canvas. Uses current brush preset
     * @param list of Qpoints
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * </ul>
     * Default is ForegroundColor.
     * @param fillStyle appearance of the fill, one of:
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * <li>Pattern</li>
     * </ul>
     * Default is None.
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintPolygon(const QList<QPointF> points,
                      const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                      const QString fillStyle = PaintingResources::defaultFillStyle,
                      const QString &name = QString());
    /**
     * @brief paint an ellipse on the canvas. Uses current brush preset
     * @param rect QRect with x, y, width, and height
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * </ul>
     * Default is ForegroundColor.
     * @param fillStyle appearance of the fill, one of:
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * <li>Pattern</li>
     * </ul>
     * Default is None.
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintEllipse(const QRectF &rect,
                      const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                      const QString fillStyle = PaintingResources::defaultFillStyle,
                      const QString &name = QString());
    /**
     * @brief paint a custom path on the canvas. Uses current brush preset
     * @param  path QPainterPath to determine path
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * </ul>
     * Default is ForegroundColor.
     * @param fillStyle appearance of the fill, one of:
     * <ul>
     * <li>None
     * <li>ForegroundColor</li>
     * <li>BackgroundColor</li>
     * <li>Pattern</li>
     * </ul>
     * Default is None.
     * @param name the name of the undo step; empty for the open agent move's name, or else
     * "Scripted Brush Stroke"
     */
    void paintPath(const QPainterPath &path,
                   const QString strokeStyle = PaintingResources::defaultStrokeStyle,
                   const QString fillStyle = PaintingResources::defaultFillStyle,
                   const QString &name = QString());
    /**
     * @brief paintAbility can be used to determine whether this node can be painted on with the current brush preset.
     * @return QString, one of the following:
     * <ul>
     * <li>VECTOR - This node is vector-based.</li>
     * <li>CLONE - This node is a Clone Layer.</li>
     * <li>PAINT - This node is paintable by the current brush preset.</li>
     * <li>UNPAINTABLE - This node is not paintable, or a null preset is somehow selected./li>
     * <li>MYPAINTBRUSH_UNPAINTABLE - This node's non-RGBA colorspace cannot be painted on by the currently selected MyPaint brush.</li>
     * </ul>
     */
    QString paintAbility();

private:

    friend class Filter;
    friend class Document;
    friend class Selection;
    friend class GroupLayer;
    friend class FileLayer;
    friend class FilterLayer;
    friend class FillLayer;
    friend class VectorLayer;
    friend class FilterMask;
    friend class SelectionMask;
    friend class TransparencyMask;
    friend class TransformMask;
    friend class ColorizeMask;
    friend class CloneLayer;

    explicit Node(KisImageSP image, KisNodeSP node, QObject *parent = 0);

    /**
     * @brief paintDevice gives access to the internal paint device of this Node
     * @return the paintdevice or 0 if the node does not have an editable paint device.
     */
    KisPaintDeviceSP paintDevice() const;
    KisImageSP image() const;
    KisNodeSP node() const;

    struct Private;
    Private *const d;

};

typedef QSharedPointer<Node> NodeSP;

#endif // LIBKIS_NODE_H
