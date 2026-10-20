/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include <QUrl>
#include <QScopedPointer>
#include <QUuid>

#include <iterator>

#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorTransformation.h>

#include <KisDocument.h>
#include <KisMimeDatabase.h>
#include <KisPart.h>
#include <kis_image.h>
#include <kis_types.h>
#include <kis_node.h>
#include <kis_paint_layer.h>
#include <kis_group_layer.h>
#include <kis_file_layer.h>
#include <kis_adjustment_layer.h>
#include <kis_generator_layer.h>
#include <kis_clone_layer.h>
#include <kis_shape_layer.h>
#include <KisReferenceImagesLayer.h>
#include <kis_transparency_mask.h>
#include <kis_filter_mask.h>
#include <kis_transform_mask.h>
#include <kis_selection_mask.h>
#include <lazybrush/kis_colorize_mask.h>
#include <kis_layer.h>
#include <kis_meta_data_merge_strategy.h>
#include <kis_meta_data_merge_strategy_registry.h>
#include <kis_filter_strategy.h>
#include <commands/kis_node_compositeop_command.h>
#include <commands/kis_node_opacity_command.h>
#include <commands/KisNodeRenameCommand.h>
#include <commands/kis_image_layer_add_command.h>
#include <commands/kis_image_layer_remove_command.h>
#include <commands_new/kis_set_layer_style_command.h>
#include <kis_processing_applicator.h>
#include <kis_asl_layer_style_serializer.h>

#include <kis_raster_keyframe_channel.h>
#include <kis_keyframe.h>
#include "ScriptWaits.h"
#include "kis_selection.h"

#include "InfoObject.h"
#include "Krita.h"
#include "Node.h"
#include "Channel.h"
#include "Filter.h"
#include "Selection.h"

#include "GroupLayer.h"
#include "CloneLayer.h"
#include "FilterLayer.h"
#include "FillLayer.h"
#include "FileLayer.h"
#include "VectorLayer.h"
#include "FilterMask.h"
#include "SelectionMask.h"
#include "TransparencyMask.h"
#include "TransformMask.h"
#include "ColorizeMask.h"

#include "LibKisUtils.h"
#include <kis_layer_utils.h>

#include "PaintingResources.h"
#include "DocumentHistory.h"
#include "KisMainWindow.h"
#include "kis_canvas2.h"
#include "KoCanvasResourceProvider.h"
#include <brushengine/kis_paint_information.h>
#include <brushengine/kis_paintop_preset.h>


#include <cmath>

#include <KoCompositeOpRegistry.h>
#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include <kis_debug.h>

namespace {
/**
 * Krita Agent (krita-fork 6.5): whether a whole-layer rewrite (a transform, a crop, a colour conversion, a merge)
 * must be refused because the pixels it rewrites, where they are now or where they would be, touch a protected
 * feature. Such a call cannot be clipped to the feature, so as for Node.move() it is refused, with a warning, and the
 * features are named in Document.lastKeptOut(). Document.setProtectionSuspended() is the way out. Nothing is refused
 * when no feature is protected.
 */
bool refusedByProtection(KisImageSP image, const QList<QRect> &areas, const char *call)
{
    if (!KisFeatureProtection::isActive(image)) return false;
    QStringList names;
    for (const QRect &area : areas) {
        for (const QString &name : KisFeatureProtection::keptOutOf(image, area)) {
            if (!names.contains(name)) names << name;
        }
    }
    if (names.isEmpty()) return false;
    image->featureList()->recordKeptOut(names);
    warnScript << call << "refused: it would rewrite pixels inside the protected features" << names.join(", ")
               << "(Document.setProtectionSuspended(True) lifts protection for a deliberate edit)";
    return true;
}

/// The bounds of \p rect after \p transform, with a margin, or an empty rect when the numbers are not usable.
QRect transformedBounds(const QTransform &transform, const QRect &rect)
{
    const QRectF mapped = transform.mapRect(QRectF(rect));
    if (!std::isfinite(mapped.x()) || !std::isfinite(mapped.y()) || !std::isfinite(mapped.width()) || !std::isfinite(mapped.height())
        || std::abs(mapped.x()) > 1e9 || std::abs(mapped.y()) > 1e9 || mapped.width() > 1e9 || mapped.height() > 1e9) {
        return QRect(INT_MIN / 2, INT_MIN / 2, INT_MAX, INT_MAX); // unusable numbers: as if it reached everywhere
    }
    return mapped.toAlignedRect().adjusted(-2, -2, 2, 2);
}
}

namespace {
/// Krita Agent: sets a node's visibility, undoably (KisImageChangeVisibilityCommand is not exported).
class NodeVisibilityCommand : public KUndo2Command
{
public:
    NodeVisibilityCommand(KisNodeSP node, bool visible)
        : KUndo2Command(kundo2_i18n("Change Visibility"))
        , m_node(node)
        , m_visible(visible)
        , m_oldVisible(node->visible())
    {
    }
    void redo() override { m_node->setVisible(m_visible); }
    void undo() override { m_node->setVisible(m_oldVisible); }

private:
    KisNodeSP m_node;
    bool m_visible;
    bool m_oldVisible;
};
}

struct Node::Private {
    Private() {}
    KisImageWSP image;
    KisNodeSP node;
};

Node::Node(KisImageSP image, KisNodeSP node, QObject *parent)
    : QObject(parent)
    , d(new Private)
{
    d->image = image;
    d->node = node;
}

Node *Node::createNode(KisImageSP image, KisNodeSP node, QObject *parent)
{
    if (node.isNull()) {
        return 0;
    }
    if (node->inherits("KisGroupLayer")) {
        return new GroupLayer(dynamic_cast<KisGroupLayer*>(node.data()));
    }
    else if (node->inherits("KisCloneLayer")) {
        return new CloneLayer(dynamic_cast<KisCloneLayer*>(node.data()));
    }
    else if (node->inherits("KisFileLayer")) {
        return new FileLayer(dynamic_cast<KisFileLayer*>(node.data()));
    }
    else if (node->inherits("KisAdjustmentLayer")) {
        return new FilterLayer(dynamic_cast<KisAdjustmentLayer*>(node.data()));
    }
    else if (node->inherits("KisGeneratorLayer")) {
        return new FillLayer(dynamic_cast<KisGeneratorLayer*>(node.data()));
    }
    else if (node->inherits("KisShapeLayer")) {
        return new VectorLayer(dynamic_cast<KisShapeLayer*>(node.data()));
    }
    else if (node->inherits("KisFilterMask")) {
        return new FilterMask(image, dynamic_cast<KisFilterMask*>(node.data()));
    }
    else if (node->inherits("KisSelectionMask")) {
        return new SelectionMask(image, dynamic_cast<KisSelectionMask*>(node.data()));
    }
    else if (node->inherits("KisTransparencyMask")) {
        return new TransparencyMask(image, dynamic_cast<KisTransparencyMask*>(node.data()));
    }
    else if (node->inherits("KisTransformMask")) {
        return new TransformMask(image, dynamic_cast<KisTransformMask*>(node.data()));
    }
    else if (node->inherits("KisColorizeMask")) {
        return new ColorizeMask(image, dynamic_cast<KisColorizeMask*>(node.data()));
    }
    else {
        return new Node(image, node, parent);
    }
}

Node::~Node()
{
    delete d;
}

bool Node::operator==(const Node &other) const
{
    return (d->node == other.d->node
            && d->image == other.d->image);
}

bool Node::operator!=(const Node &other) const
{
    return !(operator==(other));
}

Node *Node::clone() const
{
    KisNodeSP clone = d->node->clone();
    Node *node = Node::createNode(0, clone);
    return node;
}


bool Node::alphaLocked() const
{
    if (!d->node) return false;
    KisPaintLayerSP paintLayer = qobject_cast<KisPaintLayer*>(d->node.data());
    if (paintLayer) {
        return paintLayer->alphaLocked();
    }
    return false;
}

void Node::setAlphaLocked(bool value)
{
    if (!d->node) return;
    KisPaintLayerSP paintLayer = qobject_cast<KisPaintLayer*>(d->node.data());
    if (paintLayer) {
        paintLayer->setAlphaLocked(value);
    }
}


QString Node::blendingMode() const
{
    if (!d->node) return QString();

    return d->node->compositeOpId();
}

void Node::setBlendingMode(QString value)
{
    if (!d->node) return;

    KUndo2Command *cmd = new KisNodeCompositeOpCommand(d->node,
                                                       value);

    // Krita Agent: joins an open macro or agent move, waits for its own stroke only
    DocumentHistory::runCommandStrokeAndWait(d->image, cmd, "Node.setBlendingMode()");
}


QList<Channel*> Node::channels() const
{
    QList<Channel*> channels;

    if (!d->node) return channels;
    if (!d->node->inherits("KisLayer")) return channels;

    Q_FOREACH(KoChannelInfo *info, d->node->colorSpace()->channels()) {
        Channel *channel = new Channel(d->node, info);
        channels << channel;
    }

    return channels;
}

QList<Node*> Node::childNodes() const
{
    QList<Node*> nodes;
    if (d->node) {
        KisNodeList nodeList;
        int childCount = d->node->childCount();
        for (int i = 0; i < childCount; ++i) {
            nodeList << d->node->at(i);
        }
        nodes = LibKisUtils::createNodeList(nodeList, d->image);
    }
    return nodes;
}

QList<Node*> Node::findChildNodes(const QString &name, bool recursive, bool partialMatch, const QString &type, int colorLabelIndex) const
{
    if (!d->node) return {};

    QList<Node*> nodes;
    KisNodeList nodeList = KisLayerUtils::findNodesByName(d->node, name, recursive, partialMatch);

    if (!type.isEmpty()) {
        for (int i = nodeList.size() - 1; i >= 0; i--) {
            if ((type == "paintlayer" && !qobject_cast<const KisPaintLayer*>(nodeList.at(i))) ||
                (type == "vectorlayer" && !qobject_cast<const KisShapeLayer*>(nodeList.at(i))) ||
                (type == "grouplayer" && !qobject_cast<const KisGroupLayer*>(nodeList.at(i))) ||
                (type == "filelayer" && !qobject_cast<const KisFileLayer*>(nodeList.at(i))) ||
                (type == "filterlayer" && !qobject_cast<const KisAdjustmentLayer*>(nodeList.at(i))) ||
                (type == "filllayer" && !qobject_cast<const KisGeneratorLayer*>(nodeList.at(i))) ||
                (type == "clonelayer" && !qobject_cast<const KisCloneLayer*>(nodeList.at(i))) ||
                (type == "transformmask" && !qobject_cast<const KisTransformMask*>(nodeList.at(i))) ||
                (type == "referenceimageslayer" && !qobject_cast<const KisReferenceImagesLayer*>(nodeList.at(i))) ||
                (type == "transparencymask" && !qobject_cast<const KisTransformMask*>(nodeList.at(i))) ||
                (type == "filtermask" && !qobject_cast<const KisFilterMask*>(nodeList.at(i))) ||
                (type == "selectionmask" && !qobject_cast<const KisSelectionMask*>(nodeList.at(i))) ||
                (type == "colorizemask" && !qobject_cast<const KisColorizeMask*>(nodeList.at(i)))
            ) {
                nodeList.removeAt(i);
            }
        }
    }

    if (colorLabelIndex > 0) {
        for (int i = nodeList.size() - 1; i >= 0; i--) {
            if (nodeList.at(i)->colorLabelIndex() != colorLabelIndex) {
                nodeList.removeAt(i);
            }
        }
    }

    return LibKisUtils::createNodeList(nodeList, d->image);
}

bool Node::addChildNode(Node *child, Node *above)
{
    if (!d->node) return false;

    KUndo2Command *cmd = 0;

    if (above) {
        cmd = new KisImageLayerAddCommand(d->image, child->node(), d->node, above->node());
    } else {
        cmd = new KisImageLayerAddCommand(d->image, child->node(), d->node, d->node->childCount());
    }

    // Krita Agent: joins an open macro or agent move, waits for its own stroke only
    return DocumentHistory::runCommandStrokeAndWait(d->image, cmd, "Node.addChildNode()");
}

bool Node::removeChildNode(Node *child)
{
    if (!d->node) return false;
    return child->remove();
}

void Node::setChildNodes(QList<Node*> nodes)
{
    if (!d->node) return;
    while (d->node->firstChild()) {
        d->image->removeNode(d->node->firstChild());
    }
    Q_FOREACH(Node *node, nodes) {
        d->image->addNode(node->node(), d->node);
    }
}

int Node::colorLabel() const
{
    if (!d->node) return 0;
    return d->node->colorLabelIndex();
}

void Node::setColorLabel(int index)
{
    if (!d->node) return;
    d->node->setColorLabelIndex(index);
}

QString Node::colorDepth() const
{
    if (!d->node) return "";
    if (!d->node->projection()) return d->node->colorSpace()->colorDepthId().id();
    return d->node->projection()->colorSpace()->colorDepthId().id();
}

QString Node::colorModel() const
{
    if (!d->node) return "";
    if (!d->node->projection()) return d->node->colorSpace()->colorModelId().id();
    return d->node->projection()->colorSpace()->colorModelId().id();
}


QString Node::colorProfile() const
{
    if (!d->node) return "";
    if (!d->node->projection()) return d->node->colorSpace()->profile()->name();
    return d->node->projection()->colorSpace()->profile()->name();
}

bool Node::setColorProfile(const QString &colorProfile)
{
    if (!d->node) return false;
    if (!d->node->inherits("KisLayer")) return false;
    KisLayer *layer = qobject_cast<KisLayer*>(d->node.data());
    // Assigning a profile changes how every pixel of the layer reads.
    if (refusedByProtection(d->image, {QRect(d->node->exactBounds())}, "Node.setColorProfile()")) return false;
    const KoColorProfile *profile = KoColorSpaceRegistry::instance()->profileByName(colorProfile);
    bool result = false;
    const bool done = ScriptWaits::run(d->image, "Node.setColorProfile()", [&]() {
        result = d->image->assignLayerProfile(layer, profile);
    });
    return result && done;
}

bool Node::setColorSpace(const QString &colorModel, const QString &colorDepth, const QString &colorProfile)
{
    if (!d->node) return false;
    if (!d->node->inherits("KisLayer")) return false;
    const KoColorProfile *profile = KoColorSpaceRegistry::instance()->profileByName(colorProfile);
    if (!profile) return false;
    // A conversion rewrites every pixel of the layer.
    if (refusedByProtection(d->image, {QRect(d->node->exactBounds())}, "Node.setColorSpace()")) return false;
    const KoColorSpace *dstCs = KoColorSpaceRegistry::instance()->colorSpace(colorModel,
                                                                             colorDepth,
                                                                             profile);
    return ScriptWaits::run(d->image, "Node.setColorSpace()", [&]() {
        d->image->convertLayerColorSpace(d->node, dstCs, KoColorConversionTransformation::internalRenderingIntent(), KoColorConversionTransformation::internalConversionFlags());
    });
}

bool Node::animated() const
{
    if (!d->node) return false;
    return d->node->isAnimated();
}

void Node::enableAnimation() const
{
    if (!d->node) return;
    d->node->enableAnimation();
}

void Node::setPinnedToTimeline(bool pinned) const
{
    if (!d->node) return;
    d->node->setPinnedToTimeline(pinned);
}

bool Node::isPinnedToTimeline() const
{
    if (!d->node) return false;
    return d->node->isPinnedToTimeline();
}

bool Node::collapsed() const
{
    if (!d->node) return false;
    return d->node->collapsed();
}

void Node::setCollapsed(bool collapsed)
{
    if (!d->node) return;
    d->node->setCollapsed(collapsed);
}

bool Node::inheritAlpha() const
{
    if (!d->node) return false;
    if (!d->node->inherits("KisLayer")) return false;
    return qobject_cast<const KisLayer*>(d->node)->alphaChannelDisabled();
}

void Node::setInheritAlpha(bool value)
{
    if (!d->node) return;
    if (!d->node->inherits("KisLayer")) return;
    const_cast<KisLayer*>(qobject_cast<const KisLayer*>(d->node))->disableAlphaChannel(value);
}

bool Node::locked() const
{
    if (!d->node) return false;
    return d->node->userLocked();
}

void Node::setLocked(bool value)
{
    if (!d->node) return;
    d->node->setUserLocked(value);
}

bool Node::hasExtents()
{
    return !d->node->extent().isEmpty();
}

QString Node::name() const
{
    if (!d->node) return QString();
    return d->node->name();
}

void Node::setName(QString name)
{
    if (!d->node) return;
    if (!d->image || !d->node->parent() || d->node->name() == name) {
        d->node->setName(name);
        return;
    }
    // Krita Agent: an undo step (or part of the open agent move)
    DocumentHistory::runPropertyCommand(d->image, new KisNodeRenameCommand(d->node, d->node->name(), name), "Node.setName()");
}


int Node::opacity() const
{
    if (!d->node) return 0;
    return d->node->opacity();
}

void Node::setOpacity(int value)
{
    if (!d->node) return;
    if (value < 0) value = 0;
    if (value > 255) value = 255;
    if (!d->image || !d->node->parent() || d->node->opacity() == value) {
        d->node->setOpacity(value);
        return;
    }
    // Krita Agent: an undo step (or part of the open agent move), like setBlendingMode()
    DocumentHistory::runPropertyCommand(d->image, new KisNodeOpacityCommand(d->node, value), "Node.setOpacity()");
}


Node* Node::parentNode() const
{
    if (!d->node) return 0;
    if (!d->node->parent()) return 0;
    return Node::createNode(d->image, d->node->parent());
}

QString Node::type() const
{
    if (!d->node) return QString();
    if (qobject_cast<const KisPaintLayer*>(d->node)) {
        return "paintlayer";
    }
    else if (qobject_cast<const KisGroupLayer*>(d->node)) {
        return "grouplayer";
    }
    if (qobject_cast<const KisFileLayer*>(d->node)) {
        return "filelayer";
    }
    if (qobject_cast<const KisAdjustmentLayer*>(d->node)) {
        return "filterlayer";
    }
    if (qobject_cast<const KisGeneratorLayer*>(d->node)) {
        return "filllayer";
    }
    if (qobject_cast<const KisCloneLayer*>(d->node)) {
        return "clonelayer";
    }
    if (qobject_cast<const KisReferenceImagesLayer*>(d->node)) {
        return "referenceimageslayer";
    }
    if (qobject_cast<const KisShapeLayer*>(d->node)) {
        return "vectorlayer";
    }
    if (qobject_cast<const KisTransparencyMask*>(d->node)) {
        return "transparencymask";
    }
    if (qobject_cast<const KisFilterMask*>(d->node)) {
        return "filtermask";
    }
    if (qobject_cast<const KisTransformMask*>(d->node)) {
        return "transformmask";
    }
    if (qobject_cast<const KisSelectionMask*>(d->node)) {
        return "selectionmask";
    }
    if (qobject_cast<const KisColorizeMask*>(d->node)) {
        return "colorizemask";
    }
    return QString();
}

QIcon Node::icon() const
{
    QIcon icon;
    if (d->node) {
        icon = d->node->icon();
    }
    return icon;
}

bool Node::visible() const
{
    if (!d->node) return false;
    return d->node->visible();
}

bool Node::hasKeyframeAtTime(int frameNumber)
{
    if (!d->node || !d->node->isAnimated()) return false;

    KisRasterKeyframeChannel *rkc = dynamic_cast<KisRasterKeyframeChannel*>(d->node->getKeyframeChannel(KisKeyframeChannel::Raster.id()));
    if (!rkc) return false;

    KisKeyframeSP currentKeyframe = rkc->keyframeAt(frameNumber);

    if (!currentKeyframe) {
        return false;
    }

    return true;
}

void Node::setVisible(bool visible)
{
    if (!d->node) return;
    if (!d->image || !d->node->parent() || d->node->visible() == visible) {
        d->node->setVisible(visible);
        return;
    }
    // Krita Agent: an undo step (or part of the open agent move)
    DocumentHistory::runPropertyCommand(d->image, new NodeVisibilityCommand(d->node, visible), "Node.setVisible()");
}


QByteArray Node::pixelData(int x, int y, int w, int h) const
{
    QByteArray ba;

    if (!d->node) return ba;

    KisPaintDeviceSP dev = d->node->paintDevice();
    if (!dev) return ba;

    ba.resize(w * h * dev->pixelSize());
    dev->readBytes(reinterpret_cast<quint8*>(ba.data()), x, y, w, h);
    return ba;
}

QByteArray Node::pixelDataAtTime(int x, int y, int w, int h, int time) const
{
    QByteArray ba;

    if (!d->node || !d->node->isAnimated()) return ba;

    //
    KisRasterKeyframeChannel *rkc = dynamic_cast<KisRasterKeyframeChannel*>(d->node->getKeyframeChannel(KisKeyframeChannel::Raster.id()));
    if (!rkc) return ba;
    KisRasterKeyframeSP frame = rkc->keyframeAt<KisRasterKeyframe>(time);
    if (!frame) return ba;
    KisPaintDeviceSP dev = new KisPaintDevice(*d->node->paintDevice(), KritaUtils::DeviceCopyMode::CopySnapshot);
    if (!dev) return ba;

    frame->writeFrameToDevice(dev);

    ba.resize(w * h * dev->pixelSize());
    dev->readBytes(reinterpret_cast<quint8*>(ba.data()), x, y, w, h);
    return ba;
}


QByteArray Node::projectionPixelData(int x, int y, int w, int h) const
{
    QByteArray ba;

    if (!d->node) return ba;

    KisPaintDeviceSP dev;
    if (const KisColorizeMask *mask = qobject_cast<const KisColorizeMask*>(d->node)) {

        dev = mask->coloringProjection();
    } else {
        dev = d->node->projection();
    }
    if (!dev) return ba;

    ba.resize(w * h * dev->pixelSize());
    dev->readBytes(reinterpret_cast<quint8*>(ba.data()), x, y, w, h);
    return ba;
}

bool Node::setPixelData(QByteArray value, int x, int y, int w, int h)
{
    if (!d->node) return false;
    KisPaintDeviceSP dev = d->node->paintDevice();
    if (!dev) return false;
    if (value.length() <  w * h * (int)dev->colorSpace()->pixelSize()) {
        qWarning() << "Node::setPixelData: not enough data to write to the paint device";
        return false;
    }
    // Krita Agent: an undo step of its own, or part of the open macro or agent move (queued after its earlier
    // strokes). The write marks only its own rect dirty (the command does).
    // A node outside the image's tree has no history to join: the write is direct. (On a locked image the write is
    // direct too, and recorded.)
    if (!d->image || !d->node->parent()) {
        dev->writeBytes((const quint8*)value.constData(), x, y, w, h);
        d->node->setDirty(QRect(x, y, w, h));
        return true;
    }
    return DocumentHistory::writePixelData(d->image, d->node, value, QRect(x, y, w, h));
}

QRect Node::bounds() const
{
    if (!d->node) return QRect();
    return d->node->exactBounds();
}

// Krita Agent: Node::move() is in NodeAgentTools.cpp, as an undo step (krita-fork 5.3).

QPoint Node::position() const
{
    if (!d->node) return QPoint();
    return QPoint(d->node->x(), d->node->y());
}

bool Node::remove()
{
    if (!d->node) return false;
    if (!d->node->parent()) return false;

    KUndo2Command *cmd = new KisImageLayerRemoveCommand(d->image, d->node);

    // Krita Agent: joins an open macro or agent move, waits for its own stroke only
    return DocumentHistory::runCommandStrokeAndWait(d->image, cmd, "Node.remove()");
}

Node* Node::duplicate()
{
    if (!d->node) return 0;
    return Node::createNode(d->image, d->node->clone());
}

bool Node::save(const QString &filename, double xRes, double yRes, const InfoObject &exportConfiguration, const QRect &exportRect)
{
    if (!d->node) return false;
    if (filename.isEmpty()) return false;

    KisPaintDeviceSP projection = d->node->projection();
    QRect bounds = (exportRect.isEmpty())? d->node->exactBounds() : exportRect;

    QString mimeType = KisMimeDatabase::mimeTypeForFile(filename, false);
    QScopedPointer<KisDocument> doc(KisPart::instance()->createDocument());

    KisImageSP dst = new KisImage(doc->createUndoStore(),
                                  bounds.right(),
                                  bounds.bottom(),
                                  projection->compositionSourceColorSpace(),
                                  d->node->name());
    dst->setResolution(xRes, yRes);
    doc->setFileBatchMode(Krita::instance()->batchmode());
    doc->setCurrentImage(dst);
    KisPaintLayer* paintLayer = new KisPaintLayer(dst, "paint device", d->node->opacity());
    paintLayer->paintDevice()->makeCloneFrom(projection, bounds);
    dst->addNode(paintLayer, dst->rootLayer(), KisLayerSP(0));
    dst->cropImage(bounds);
    dst->initialRefreshGraph();

    bool r = doc->exportDocumentSync(filename, mimeType.toLatin1(), exportConfiguration.configuration());
    if (!r) {
        qWarning() << doc->errorMessage();
    }
    return r;
}

Node* Node::mergeDown()
{
    if (!d->node) return 0;
    if (!qobject_cast<KisLayer*>(d->node.data())) return 0;
    if (!d->node->prevSibling()) return 0;

    // A merge is the composite unchanged only for a fully opaque upper layer with the Normal blending mode; any other
    // merge changes the lower layer's pixels under the upper one, so it is refused where that reaches a protected feature.
    if (KisFeatureProtection::isActive(d->image)) {
        KisLayer *upper = qobject_cast<KisLayer*>(d->node.data());
        KisLayer *lower = qobject_cast<KisLayer*>(d->node->prevSibling().data());
        const bool plain = upper && lower && upper->compositeOpId() == COMPOSITE_OVER && lower->compositeOpId() == COMPOSITE_OVER
            && upper->opacity() == OPACITY_OPAQUE_U8;
        if (!plain && refusedByProtection(d->image, {QRect(d->node->exactBounds())}, "Node.mergeDown()")) return 0;
    }

    // The layer below receives the merge. A merge that was held back past the wait limit is cancelled: null then,
    // never the layer below as if it were the result.
    KisNodeSP below = d->node->prevSibling();
    const bool done = ScriptWaits::run(d->image, "Node.mergeDown()", [&]() {
        d->image->mergeDown(qobject_cast<KisLayer*>(d->node.data()), KisMetaData::MergeStrategyRegistry::instance()->get("Drop"));
    });
    if (!done) return 0;
    return Node::createNode(d->image, d->node->prevSibling() ? d->node->prevSibling() : below);
}

bool Node::scaleNode(QPointF origin, int width, int height, QString strategy)
{
    if (!d->node) return false;
    if (!qobject_cast<KisLayer*>(d->node.data())) return false;
    if (!d->node->parent()) return false;

    KisFilterStrategy *actualStrategy = KisFilterStrategyRegistry::instance()->get(strategy);
    if (!actualStrategy) actualStrategy = KisFilterStrategyRegistry::instance()->get("Bicubic");

    const QRect bounds(d->node->exactBounds());
    if (KisFeatureProtection::isActive(d->image)) {
        QTransform t;
        t.translate(origin.x(), origin.y());
        t.scale(qreal(width) / qMax(1, bounds.width()), qreal(height) / qMax(1, bounds.height()));
        t.translate(-origin.x(), -origin.y());
        if (refusedByProtection(d->image, {bounds, transformedBounds(t, bounds)}, "Node.scaleNode()")) return false;
    }

    return ScriptWaits::run(d->image, "Node.scaleNode()", [&]() {
        d->image->scaleNode(d->node,
                            origin,
                            qreal(width) / bounds.width(),
                            qreal(height) / bounds.height(),
                            actualStrategy, 0);
    });
}

bool Node::rotateNode(double radians)
{
    if (!d->node) return false;
    if (!qobject_cast<KisLayer*>(d->node.data())) return false;
    if (!d->node->parent()) return false;

    if (KisFeatureProtection::isActive(d->image)) {
        const QRect bounds(d->node->exactBounds());
        QTransform t;
        t.translate(bounds.center().x(), bounds.center().y());
        t.rotateRadians(radians);
        t.translate(-bounds.center().x(), -bounds.center().y());
        if (refusedByProtection(d->image, {bounds, transformedBounds(t, bounds)}, "Node.rotateNode()")) return false;
    }

    return ScriptWaits::run(d->image, "Node.rotateNode()", [&]() {
        d->image->rotateNode(d->node, radians, 0);
    });
}

bool Node::cropNode(int x, int y, int w, int h)
{
    if (!d->node) return false;
    if (!qobject_cast<KisLayer*>(d->node.data())) return false;
    if (!d->node->parent()) return false;

    // A crop deletes what lies outside the rectangle: the layer's pixels are rewritten wherever it reaches.
    if (refusedByProtection(d->image, {QRect(d->node->exactBounds())}, "Node.cropNode()")) return false;

    QRect rect = QRect(x, y, w, h);
    return ScriptWaits::run(d->image, "Node.cropNode()", [&]() {
        d->image->cropNode(d->node, rect);
    });
}

bool Node::shearNode(double angleX, double angleY)
{
    if (!d->node) return false;
    if (!qobject_cast<KisLayer*>(d->node.data())) return false;
    if (!d->node->parent()) return false;

    if (KisFeatureProtection::isActive(d->image)) {
        const QRect bounds(d->node->exactBounds());
        QTransform t;
        t.translate(bounds.center().x(), bounds.center().y());
        t.shear(std::tan(qDegreesToRadians(angleX)), std::tan(qDegreesToRadians(angleY)));
        t.translate(-bounds.center().x(), -bounds.center().y());
        if (refusedByProtection(d->image, {bounds, transformedBounds(t, bounds)}, "Node.shearNode()")) return false;
    }

    return ScriptWaits::run(d->image, "Node.shearNode()", [&]() {
        d->image->shearNode(d->node, angleX, angleY, 0);
    });
}

QImage Node::thumbnail(int w, int h)
{
    if (!d->node) return QImage();
    return d->node->createThumbnail(w, h);
}

QString Node::layerStyleToAsl()
{
    if (!d->node) return QString();

    KisLayer *layer = qobject_cast<KisLayer*>(d->node.data());

    if (!layer) return QString();

    KisPSDLayerStyleSP layerStyle = layer->layerStyle();

    if (!layerStyle) return QString();

    KisAslLayerStyleSerializer serializer;

    serializer.setStyles(QVector<KisPSDLayerStyleSP>() << layerStyle);

    return serializer.formPsdXmlDocument().toString();
}

bool Node::setLayerStyleFromAsl(const QString &asl)
{
    if (!d->node) return false;

    KisLayer *layer = qobject_cast<KisLayer*>(d->node.data());

    if (!layer) return false;

    QDomDocument aslDoc;

    if (!aslDoc.setContent(asl)) {
        qWarning() << "ASL string format is invalid!";
        return false;
    }

    KisAslLayerStyleSerializer serializer;

    serializer.registerPSDPattern(aslDoc);
    serializer.readFromPSDXML(aslDoc);

    if (serializer.styles().size() != 1) return false;

    KisPSDLayerStyleSP newStyle = serializer.styles().first();
    KUndo2Command *cmd = new KisSetLayerStyleCommand(layer, layer->layerStyle(), newStyle);

    // Krita Agent: joins an open macro or agent move, waits for its own stroke only
    return DocumentHistory::runCommandStrokeAndWait(d->image, cmd, "Node.setLayerStyleFromAsl()");
}

int Node::index() const
{
    if (!d->node) return -1;
    if (!d->node->parent()) return -1;

    return d->node->parent()->index(d->node);
}

QUuid Node::uniqueId() const
{
    if (!d->node) return QUuid();
    return d->node->uuid();
}

KisPaintDeviceSP Node::paintDevice() const
{
    return d->node->paintDevice();
}

KisImageSP Node::image() const
{
    return d->image;
}

KisNodeSP Node::node() const
{
    return d->node;
}

QString Node::paintAbility()
{
    // Taken from KisTool:nodePaintAbility().
    // Krita Agent: no active view means nothing to take the brush from: refused, not dereferenced.
    KoCanvasResourceProvider *resourceManager = PaintingResources::viewResources();
    if (!resourceManager) {
        return "UNPAINTABLE";
    }
    if (resourceManager->resource(KoCanvasResource::CurrentPaintOpPreset).isNull()) {
        return "UNPAINTABLE";
    }

    if (!d->node) {
        return "UNPAINTABLE";
    }

    if (d->node->inherits("KisShapeLayer")) {
        return "VECTOR";
    }
    if (d->node->inherits("KisCloneLayer")) {
        return "CLONE";
    }
    if (d->node->paintDevice()) {

        KisPaintOpPresetSP currentPaintOpPreset = resourceManager->resource(KoCanvasResource::CurrentPaintOpPreset).value<KisPaintOpPresetSP>();
        if (currentPaintOpPreset->paintOp().id() == "mypaintbrush") {
            const KoColorSpace *colorSpace = d->node->paintDevice()->colorSpace();
            if (colorSpace->colorModelId() != RGBAColorModelID) {
                return "MYPAINTBRUSH_UNPAINTABLE";
            }
        }

        return "PAINT";
    }

    return "UNPAINTABLE";
}

void Node::paintLine(const QPointF pointOne, const QPointF pointTwo, double pressureOne, double pressureTwo, const QString strokeStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintLine() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    KisPaintInformation pointOneInfo;
    pointOneInfo.setPressure(pressureOne);
    pointOneInfo.setPos(pointOne);

    KisPaintInformation pointTwoInfo;
    pointTwoInfo.setPressure(pressureTwo);
    pointTwoInfo.setPos(pointTwo);

    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, PaintingResources::defaultFillStyle, name);
    helper.paintLine(pointOneInfo, pointTwoInfo);
}

void Node::paintPolylineStroke(const QList<StrokePoint> &points, const QString strokeStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintPolylineStroke() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    if (points.isEmpty()) {
        return;
    }

    auto paintInformation = [] (const StrokePoint &point) {
        return KisPaintInformation(point.position(),
                                   point.pressure(),
                                   point.xTilt(),
                                   point.yTilt(),
                                   point.rotation(),
                                   point.tangentialPressure(),
                                   1.0,
                                   point.time(),
                                   point.speed());
    };

    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, PaintingResources::defaultFillStyle, name);

    KisPaintInformation previous = paintInformation(points.first());
    if (points.size() == 1) {
        helper.paintLine(previous, previous);
        return;
    }

    for (auto it = std::next(points.cbegin()); it != points.cend(); ++it) {
        KisPaintInformation current = paintInformation(*it);
        helper.paintLine(previous, current);
        previous = current;
    }
}


void Node::paintRectangle(const QRectF &rect, const QString strokeStyle, const QString fillStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintRectangle() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    // reference class where this stuff is being done. Maybe can use the "facade" like that does for setup?
    // void KisFigurePaintingToolHelper::paintRect(const QRectF &rect)

    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, fillStyle, name);
    helper.paintRect(rect);
}


void Node::paintPolygon(const QList<QPointF> listPoint, const QString strokeStyle, const QString fillStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintPolygon() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    // strategy needs points in vPointF format
    QVector<QPointF> points = points.fromList(listPoint);
    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, fillStyle, name);
    helper.paintPolygon(points);
}


void Node::paintEllipse(const QRectF &rect, const QString strokeStyle, const QString fillStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintEllipse() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, fillStyle, name);
    helper.paintEllipse(rect);
}


void Node::paintPath(const QPainterPath &path, const QString strokeStyle, const QString fillStyle, const QString &name)
{
    if (paintAbility() != "PAINT") {
        warnScript << "Node::paintPath() refused: the node cannot be painted, or there is no active view to take the brush from.";
        return;
    }

    KisFigurePaintingToolHelper helper = PaintingResources::createHelper(d->image, node(), strokeStyle, fillStyle, name);
    helper.paintPainterPath(path);
}
