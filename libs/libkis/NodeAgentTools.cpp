/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
// Krita Agent: Krita's painting tools as functions on a Node (krita-fork 5.3).
//
// Node::fill(), encloseAndFill(), gradient(), smartPatch() and move() read a script's arguments and options, and run
// KisToolFunctions (libs/ui), which build the same stroke as the tool. Each is one undo step, or joins the script's
// open macro or agent move (DocumentHistory::scriptUndoFacade), and waits until its pixels are on the layer.
#include "Node.h"

#include <QMetaType>
#include <functional>
#include <QStringList>

#include <KisResourceModel.h>
#include <KisResourceTypes.h>
#include <KoAbstractGradient.h>
#include <KoCanvasResourcesIds.h>
#include <KoColor.h>
#include <KoColorSpace.h>
#include <KoLocalStrokeCanvasResources.h>
#include <KoStopGradient.h>
#include <kis_debug.h>
#include <kis_default_bounds.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <kis_pointer_utils.h>
#include <kis_selection.h>
#include <KisImageResolutionProxy.h>
#include <processing/KisToolFunctions.h>

#include "DocumentHistory.h"
#include "ScriptWaits.h"
#include "Selection.h"

namespace
{

/// Reads a script's options, refusing unknown keys and values of the wrong kind or out of range.
class Options
{
public:
    Options(const QVariantMap &options, const QStringList &known)
        : m_options(options)
    {
        for (auto it = options.constBegin(); it != options.constEnd(); ++it) {
            if (!known.contains(it.key())) fail(QString("unknown option \"%1\"").arg(it.key()));
        }
    }

    bool ok() const { return m_error.isEmpty(); }
    QString error() const { return m_error; }
    bool has(const QString &key) const { return m_options.contains(key); }

    void readInt(const QString &key, int &out, int min, int max)
    {
        if (!has(key)) return;
        double value = 0;
        if (!number(m_options.value(key), value) || value != qRound64(value) || value < min || value > max) {
            fail(QString("\"%1\" must be a whole number from %2 to %3").arg(key).arg(min).arg(max));
            return;
        }
        out = int(value);
    }

    void readDouble(const QString &key, double &out, double min, double max)
    {
        if (!has(key)) return;
        double value = 0;
        if (!number(m_options.value(key), value) || value < min || value > max) {
            fail(QString("\"%1\" must be a number from %2 to %3").arg(key).arg(min).arg(max));
            return;
        }
        out = value;
    }

    void readBool(const QString &key, bool &out)
    {
        if (!has(key)) return;
        const QVariant value = m_options.value(key);
        if (value.typeId() != QMetaType::Bool) {
            fail(QString("\"%1\" must be true or false").arg(key));
            return;
        }
        out = value.toBool();
    }

    void readString(const QString &key, QString &out)
    {
        if (!has(key)) return;
        const QVariant value = m_options.value(key);
        if (value.typeId() != QMetaType::QString) {
            fail(QString("\"%1\" must be a string").arg(key));
            return;
        }
        out = value.toString();
    }

    /// One of \p choices, as the index of the string in it.
    void readChoice(const QString &key, int &out, const QStringList &choices)
    {
        if (!has(key)) return;
        QString value;
        readString(key, value);
        if (!ok()) return;
        const int index = choices.indexOf(value);
        if (index < 0) {
            fail(QString("\"%1\" must be one of %2").arg(key, choices.join(", ")));
            return;
        }
        out = index;
    }

    void readColor(const QString &key, QColor &out)
    {
        if (!has(key)) return;
        if (!color(m_options.value(key), out)) fail(QString("\"%1\" must be a colour").arg(key));
    }

    void readColors(const QString &key, QList<QColor> &out)
    {
        if (!has(key)) return;
        const QVariant value = m_options.value(key);
        if (value.typeId() != QMetaType::QVariantList) {
            fail(QString("\"%1\" must be a list of colours").arg(key));
            return;
        }
        for (const QVariant &item : value.toList()) {
            QColor c;
            if (!color(item, c)) {
                fail(QString("\"%1\" must be a list of colours").arg(key));
                return;
            }
            out << c;
        }
    }

    void readInts(const QString &key, QList<int> &out, int min, int max)
    {
        if (!has(key)) return;
        const QVariant value = m_options.value(key);
        if (value.typeId() != QMetaType::QVariantList) {
            fail(QString("\"%1\" must be a list of whole numbers").arg(key));
            return;
        }
        for (const QVariant &item : value.toList()) {
            double n = 0;
            if (!number(item, n) || n != qRound64(n) || n < min || n > max) {
                fail(QString("\"%1\" must be a list of whole numbers from %2 to %3").arg(key).arg(min).arg(max));
                return;
            }
            out << int(n);
        }
    }

    void fail(const QString &error)
    {
        if (m_error.isEmpty()) m_error = error;
    }

private:
    static bool number(const QVariant &value, double &out)
    {
        switch (value.typeId()) {
        case QMetaType::Int:
        case QMetaType::UInt:
        case QMetaType::LongLong:
        case QMetaType::ULongLong:
        case QMetaType::Double:
        case QMetaType::Float:
            out = value.toDouble();
            return qIsFinite(out); // NaN and infinities never compare out of range: refuse them here
        default:
            return false;
        }
    }

    static bool color(const QVariant &value, QColor &out)
    {
        if (value.typeId() == QMetaType::QColor) {
            out = value.value<QColor>();
        } else if (value.typeId() == QMetaType::QString) {
            out = QColor::fromString(value.toString());
        } else {
            return false;
        }
        return out.isValid();
    }

    const QVariantMap &m_options;
    QString m_error;
};

const QStringList fillKeys = {"sample", "labels", "threshold", "spread", "closeGap", "grow", "feather", "antialias",
                              "stopGrowingAtDarkestPixel", "useSelectionAsBoundary", "opacity", "compositeOp", "name"};

/// fill()'s options shared with encloseAndFill(); \p device checks the blending mode.
void readFillOptions(Options &options, KisToolFunctions::FillOptions &fill, KisPaintDeviceSP device)
{
    int sample = 0;
    options.readChoice("sample", sample, {"layer", "all", "labels"});
    fill.reference = KisToolFunctions::FillOptions::Reference(sample);
    options.readInts("labels", fill.referenceLabels, 0, 8);
    if (options.ok() && options.has("labels") != (fill.reference == KisToolFunctions::FillOptions::ColorLabeledLayers)) {
        options.fail("\"labels\" go with \"sample\": \"labels\", and it needs them");
    }
    if (options.ok() && options.has("labels") && fill.referenceLabels.isEmpty()) {
        options.fail("\"labels\" must name at least one colour label");
    }
    options.readInt("threshold", fill.threshold, 1, 100);
    options.readInt("spread", fill.opacitySpread, 0, 100);
    options.readInt("closeGap", fill.closeGap, 0, 32);
    options.readInt("grow", fill.grow, -400, 400);
    options.readInt("feather", fill.feather, 0, 400);
    options.readBool("antialias", fill.antiAlias);
    options.readBool("stopGrowingAtDarkestPixel", fill.stopGrowingAtDarkestPixel);
    options.readBool("useSelectionAsBoundary", fill.useSelectionAsBoundary);
    double opacity = fill.opacity;
    options.readDouble("opacity", opacity, 0.0, 1.0);
    fill.opacity = opacity;
    options.readString("compositeOp", fill.compositeOp);
    if (options.ok() && device && !device->colorSpace()->hasCompositeOp(fill.compositeOp)) {
        options.fail(QString("unknown blending mode \"%1\"").arg(fill.compositeOp));
    }
}

/// \p selection's pixels on \p image's bounds, or null for none.
KisSelectionSP selectionOn(KisSelectionSP selection, KisImageSP image)
{
    if (!selection || !image) return nullptr;
    KisSelectionSP result = new KisSelection(new KisDefaultBounds(image), toQShared(new KisImageResolutionProxy(image)));
    result->pixelSelection()->applySelection(selection->projection(), SELECTION_REPLACE);
    return result;
}

/// A gradient from \p colors, evenly spaced.
KoAbstractGradientSP gradientFrom(const QList<QColor> &colors, const KoColorSpace *colorSpace)
{
    QList<KoGradientStop> stops;
    for (int i = 0; i < colors.size(); i++) {
        stops << KoGradientStop(qreal(i) / (colors.size() - 1), KoColor(colors[i], colorSpace), COLORSTOP);
    }
    KoStopGradientSP gradient(new KoStopGradient());
    gradient->setStops(stops);
    gradient->setValid(true);
    return gradient;
}

/// The gradient resource called \p name, with its foreground and background stops in \p foreground and
/// \p background; null when there is none.
KoAbstractGradientSP gradientResource(const QString &name, const KoColor &foreground, const KoColor &background)
{
    KisResourceModel model(ResourceType::Gradients);
    KoAbstractGradientSP found;
    for (KoResourceSP resource : model.resourcesForName(name)) {
        found = resource.dynamicCast<KoAbstractGradient>();
        if (found) break;
    }
    if (!found) return nullptr;
    QSharedPointer<KoLocalStrokeCanvasResources> colors(new KoLocalStrokeCanvasResources());
    colors->storeResource(KoCanvasResource::ForegroundColor, QVariant::fromValue(foreground));
    colors->storeResource(KoCanvasResource::BackgroundColor, QVariant::fromValue(background));
    return found->cloneAndBakeVariableColors(colors);
}

bool refused(const char *call, const QString &reason)
{
    warnScript << call << "refused," << reason;
    return false;
}

} // namespace

/**
 * Waits for one call's stroke only, never for the whole image (ScriptWaits: bounded by KisToolFunctions::waitLimit(),
 * handling events meanwhile so a held pen can lift). Past the limit the stroke is cancelled and the call refused.
 */
static bool waitForStroke(KisToolFunctions::CompletionSP completion, const char *call)
{
    return ScriptWaits::waitForStroke(completion, call);
}

/// A target for the tool functions: this node, \p selection, and the open macro's or move's undo, if any. Taken only
/// once a call is going ahead, since it counts as script work in the open move.
static KisToolFunctions::Target toolTarget(KisImageSP image, KisNodeSP node, KisSelectionSP selection,
                                           bool overrideSelection, const QString &name)
{
    KisToolFunctions::Target target;
    target.image = image;
    target.node = node;
    target.selection = selection;
    target.overrideSelection = overrideSelection;
    target.name = name.isEmpty() ? KUndo2MagicString() : kundo2_noi18n(name);
    return target;
}

static bool runTool(KisToolFunctions::Target target, const char *call,
                    const std::function<bool(const KisToolFunctions::Target &, QString *)> &run)
{
    QString reason;
    if (!KisToolFunctions::canPaint(target, &reason)) return refused(call, reason);
    // A locked image (Document.lock()) runs no stroke until it is unlocked: refuse instead of waiting out the limit.
    if (target.image->locked()) return refused(call, "the document is locked (Document.lock()); unlock it first");
    target.undoFacade = DocumentHistory::scriptUndoFacade(target.image, target.node->paintDevice());
    target.completion.reset(new KisToolFunctions::Completion());
    if (!run(target, &reason)) return refused(call, reason);
    return waitForStroke(target.completion, call);
}

bool Node::fill(int x, int y, const QColor &color, const QVariantMap &options, Selection *selection)
{
    const char *call = "Node.fill():";
    if (!this->image() || !this->node()) return refused(call, "the node is not in a document");
    if (!color.isValid()) return refused(call, "the colour is not valid");
    KisNodeSP node = this->node();
    Options read(options, QStringList(fillKeys) << "mode" << "boundaryColor");
    KisToolFunctions::FillOptions fill;
    int mode = 0;
    read.readChoice("mode", mode, {"contiguous", "similar", "selection"});
    fill.area = KisToolFunctions::FillOptions::Area(mode);
    readFillOptions(read, fill, node ? node->paintDevice() : nullptr);
    QColor boundary;
    read.readColor("boundaryColor", boundary);
    QString name;
    read.readString("name", name);
    if (!read.ok()) return refused(call, read.error());
    KisImageSP image = this->image();
    if (boundary.isValid() && image) {
        fill.useBoundaryColor = true;
        fill.boundaryColor = KoColor(boundary, image->colorSpace());
    }
    if (selection && !selection->selection()) return refused(call, "the selection is not valid");

    const KisSelectionSP limit = selectionOn(selection ? selection->selection() : nullptr, image);
    if (selection && (!limit || limit->selectedExactRect().isEmpty())) {
        return refused(call, "the limiting selection selects nothing");
    }
    const KisToolFunctions::Target target = toolTarget(image, node, limit, selection != nullptr, name);
    const KoColor fillColor(color, image ? image->colorSpace() : nullptr);
    return runTool(target, call, [&](const KisToolFunctions::Target &t, QString *reason) {
        return KisToolFunctions::fill(t, QPoint(x, y), fillColor, fill, reason);
    });
}

bool Node::encloseAndFill(Selection *enclosingArea, const QColor &color, const QVariantMap &options,
                          Selection *selection)
{
    const char *call = "Node.encloseAndFill():";
    if (!this->image() || !this->node()) return refused(call, "the node is not in a document");
    if (!color.isValid()) return refused(call, "the colour is not valid");
    if (!enclosingArea || !enclosingArea->selection()) return refused(call, "there is no enclosing area");
    KisNodeSP node = this->node();
    KisImageSP image = this->image();
    Options read(options, QStringList(fillKeys) << "regions" << "regionColor" << "invert" << "includeContourRegions"
                                                << "includeSurroundingRegions");
    KisToolFunctions::EncloseAndFillOptions enclose;
    int regions = 0;
    read.readChoice("regions", regions,
                    {"all", "color", "transparent", "colorOrTransparent", "allExceptColor", "allExceptTransparent",
                     "allExceptColorOrTransparent", "surroundedByColor", "surroundedByTransparent",
                     "surroundedByColorOrTransparent"});
    enclose.regions = KisEncloseAndFillPainter::RegionSelectionMethod(regions);
    QColor regionColor;
    read.readColor("regionColor", regionColor);
    const QList<int> namingAColor = {1, 3, 4, 6, 7, 9}; // the "color" methods
    if (read.ok() && namingAColor.contains(regions) && !regionColor.isValid()) {
        read.fail("this \"regions\" method needs \"regionColor\"");
    }
    read.readBool("invert", enclose.invertRegions);
    read.readBool("includeContourRegions", enclose.includeContourRegions);
    read.readBool("includeSurroundingRegions", enclose.includeSurroundingRegions);
    readFillOptions(read, enclose.fill, node ? node->paintDevice() : nullptr);
    QString name;
    read.readString("name", name);
    if (!read.ok()) return refused(call, read.error());
    if (image) enclose.regionColor = KoColor(regionColor.isValid() ? regionColor : QColor(Qt::black), image->colorSpace());
    if (selection && !selection->selection()) return refused(call, "the selection is not valid");

    KisSelectionSP area = selectionOn(enclosingArea ? enclosingArea->selection() : nullptr, image);
    const KisSelectionSP limit = selectionOn(selection ? selection->selection() : nullptr, image);
    if (selection && (!limit || limit->selectedExactRect().isEmpty())) {
        return refused(call, "the limiting selection selects nothing");
    }
    const KisToolFunctions::Target target = toolTarget(image, node, limit, selection != nullptr, name);
    const KoColor fillColor(color, image ? image->colorSpace() : nullptr);
    return runTool(target, call, [&](const KisToolFunctions::Target &t, QString *reason) {
        return KisToolFunctions::encloseAndFill(t, area ? area->pixelSelection() : nullptr, fillColor, enclose, reason);
    });
}

bool Node::gradient(const QPointF &start, const QPointF &end, const QVariantMap &options, Selection *selection)
{
    const char *call = "Node.gradient():";
    if (!this->image() || !this->node()) return refused(call, "the node is not in a document");
    KisNodeSP node = this->node();
    KisImageSP image = this->image();
    Options read(options, {"colors", "gradient", "shape", "repeat", "reverse", "dither", "antiAliasThreshold",
                           "opacity", "compositeOp", "name"});
    KisToolFunctions::GradientOptions gradient;
    QList<QColor> colors;
    read.readColors("colors", colors);
    QString resourceName;
    read.readString("gradient", resourceName);
    int shape = 0;
    read.readChoice("shape", shape, {"linear", "bilinear", "radial", "square", "conical", "conicalSymmetric", "spiral",
                                     "reverseSpiral", "polygonal"});
    gradient.shape = KisGradientPainter::enumGradientShape(shape);
    int repeat = 0;
    read.readChoice("repeat", repeat, {"none", "forwards", "alternate"});
    gradient.repeat = KisGradientPainter::enumGradientRepeat(repeat);
    read.readBool("reverse", gradient.reverse);
    if (read.has("dither")) {
        if (options.value("dither").typeId() == QMetaType::Bool) {
            bool dither = false;
            read.readBool("dither", dither);
            gradient.dither = dither ? KisGradientPainter::DitherBlueNoise : KisGradientPainter::DitherNone;
        } else {
            int dither = 0;
            read.readChoice("dither", dither, {"none", "blueNoise", "bayer2", "bayer4", "bayer8"});
            gradient.dither = KisGradientPainter::enumDither(dither);
        }
    }
    read.readDouble("antiAliasThreshold", gradient.antiAliasThreshold, 0.0, 1.0);
    double opacity = gradient.opacity;
    read.readDouble("opacity", opacity, 0.0, 1.0);
    gradient.opacity = opacity;
    read.readString("compositeOp", gradient.compositeOp);
    QString name;
    read.readString("name", name);
    if (read.ok() && node && node->paintDevice() && !node->paintDevice()->colorSpace()->hasCompositeOp(gradient.compositeOp)) {
        read.fail(QString("unknown blending mode \"%1\"").arg(gradient.compositeOp));
    }
    if (read.ok() && resourceName.isEmpty() && colors.size() < 2) {
        read.fail("a gradient needs \"colors\" (two or more) or \"gradient\" (a resource name)");
    }
    if (!read.ok()) return refused(call, read.error());
    if (selection && !selection->selection()) return refused(call, "the selection is not valid");

    const KisSelectionSP limit = selectionOn(selection ? selection->selection() : nullptr, image);
    if (selection && (!limit || limit->selectedExactRect().isEmpty())) {
        return refused(call, "the limiting selection selects nothing");
    }
    const KisToolFunctions::Target target = toolTarget(image, node, limit, selection != nullptr, name);
    QString reason;
    if (!KisToolFunctions::canPaint(target, &reason)) return refused(call, reason);
    KoAbstractGradientSP resource;
    if (resourceName.isEmpty()) {
        resource = gradientFrom(colors, image->colorSpace());
    } else {
        const KoColor foreground(colors.size() > 0 ? colors[0] : QColor(Qt::black), image->colorSpace());
        const KoColor background(colors.size() > 1 ? colors[1] : QColor(Qt::white), image->colorSpace());
        resource = gradientResource(resourceName, foreground, background);
        if (!resource) return refused(call, QString("there is no gradient called \"%1\"").arg(resourceName));
    }
    return runTool(target, call, [&](const KisToolFunctions::Target &t, QString *why) {
        return KisToolFunctions::gradient(t, start, end, resource, gradient, why);
    });
}

bool Node::smartPatch(Selection *area, const QVariantMap &options)
{
    const char *call = "Node.smartPatch():";
    if (!area || !area->selection()) return refused(call, "there is no area to patch");
    Options read(options, {"accuracy", "patchRadius", "name"});
    int accuracy = 50;
    int patchRadius = 4;
    read.readInt("accuracy", accuracy, 0, 99);
    read.readInt("patchRadius", patchRadius, 2, 8);
    QString name;
    read.readString("name", name);
    if (!read.ok()) return refused(call, read.error());

    KisImageSP image = this->image();
    KisSelectionSP mask = selectionOn(area ? area->selection() : nullptr, image);
    const KisToolFunctions::Target target = toolTarget(image, node(), nullptr, true, name);
    return runTool(target, call, [&](const KisToolFunctions::Target &t, QString *reason) {
        return KisToolFunctions::smartPatch(t, mask ? mask->pixelSelection() : nullptr, accuracy, patchRadius, reason);
    });
}

bool Node::move(int x, int y)
{
    const char *call = "Node.move():";
    KisNodeSP node = this->node();
    KisImageSP image = this->image();
    if (!node || !image) return refused(call, "the node is not in a document");

    KisToolFunctions::Target target = toolTarget(image, node, nullptr, false, QString());
    QString reason;
    if (QPoint(node->x(), node->y()) == QPoint(x, y)) {
        // Nothing to move: no step, but the same refusals.
        return KisToolFunctions::moveNode(target, QPoint(x, y), &reason) ? true : refused(call, reason);
    }
    if (image->locked()) return refused(call, "the document is locked (Document.lock()); unlock it first");
    target.undoFacade = DocumentHistory::scriptUndoFacade(image, node->paintDevice());
    target.completion.reset(new KisToolFunctions::Completion());
    if (!KisToolFunctions::moveNode(target, QPoint(x, y), &reason)) return refused(call, reason);
    return waitForStroke(target.completion, call);
}
