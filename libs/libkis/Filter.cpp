/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "Filter.h"

#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include <kis_debug.h>
#include "DocumentHistory.h"
#include "ScriptWaits.h"
#include <kis_painter.h>
#include <kis_selection.h>
#include <kis_transaction.h>
#include <kis_processing_applicator.h>
#include <kis_resources_snapshot.h>

#include <KoCanvasResourceProvider.h>

#include <kis_canvas_resource_provider.h>
#include <kis_filter.h>
#include <kis_properties_configuration.h>
#include <kis_filter_configuration.h>
#include <kis_filter_manager.h>
#include <kis_filter_registry.h>
#include <KisDocument.h>
#include <kis_paint_device.h>
#include <kis_paint_device_frames_interface.h>
#include <KisPart.h>
#include <KisView.h>

#include <strokes/kis_filter_stroke_strategy.h>
#include <krita_utils.h>
#include <KisGlobalResourcesInterface.h>

#include "Krita.h"
#include "Document.h"
#include "InfoObject.h"
#include "Node.h"

struct Filter::Private {
    Private() {}
    QString name;
    InfoObject *configuration {0};
};

Filter::Filter()
    : QObject(0)
    , d(new Private)
{
}

Filter::~Filter()
{
    delete d->configuration;
    delete d;
}

bool Filter::operator==(const Filter &other) const
{
    return (d->name == other.d->name
            && d->configuration == other.d->configuration);
}

bool Filter::operator!=(const Filter &other) const
{
    return !(operator==(other));
}


QString Filter::name() const
{
    return d->name;
}

void Filter::setName(const QString &name)
{
    d->name = name;
    delete d->configuration;

    KisFilterSP filter = KisFilterRegistry::instance()->value(d->name);
    d->configuration = new InfoObject(filter->defaultConfiguration(KisGlobalResourcesInterface::instance()));
}

InfoObject* Filter::configuration() const
{
    return d->configuration;
}

void Filter::setConfiguration(InfoObject* value)
{
    d->configuration = value;
}

namespace
{
/// Applies a filter to a rectangle of a node's paint device, within a selection, keeping the transaction to undo and
/// redo it (Krita Agent: Filter.apply is an undo step, selection-aware, and runs as a stroke, off the caller).
class FilterApplyCommand : public KUndo2Command
{
public:
    /// \p protectedBy: the image whose protected features the write keeps out of (krita-fork 6.5), or null.
    FilterApplyCommand(KisFilterSP filter, KisFilterConfigurationSP config, KisNodeSP node, const QRect &rect,
                       KisSelectionSP selection, KisImageSP protectedBy)
        : KUndo2Command(kundo2_noi18n(QString("Filter \"%1\"").arg(filter->name())))
        , m_filter(filter)
        , m_config(config)
        , m_node(node)
        , m_rect(rect)
        , m_selection(selection)
        , m_protectedBy(protectedBy)
    {
    }

    void redo() override
    {
        if (m_transaction) {
            m_transaction->redo();
            return;
        }
        KisPaintDeviceSP device = m_node->paintDevice();
        if (!device || m_rect.isEmpty()) {
            return;
        }
        // The filter works on a copy (it shares the tiles until one side changes); only the selected part of the
        // result reaches the layer.
        KisPaintDeviceSP filtered = new KisPaintDevice(*device);
        m_filter->process(filtered, m_rect, m_config);
        KisSelectionSP selection = m_selection;
        if (m_protectedBy) {
            // Read when the filter runs. A filter changes what it is given, so it is kept out of every protected
            // feature within the rectangle it was asked to filter (and the selection).
            m_protectedBy->featureList()->recordKeptOut(KisFeatureProtection::keptOutOf(m_protectedBy, m_rect, m_selection));
            selection = KisFeatureProtection::guardSelection(m_protectedBy, m_selection);
            m_protectedBy.clear();
        }
        KisTransaction transaction(device);
        KisPainter::copyAreaOptimized(m_rect.topLeft(), filtered, device, m_rect, selection);
        m_transaction.reset(transaction.endAndTake());
        m_transaction->redo(); // a transaction's first redo only marks it done: the change is already in
        m_node->setDirty(m_rect);
    }

    void undo() override
    {
        if (m_transaction) {
            m_transaction->undo();
        }
    }

private:
    KisFilterSP m_filter;
    KisFilterConfigurationSP m_config;
    KisNodeSP m_node;
    QRect m_rect;
    KisSelectionSP m_selection;
    KisImageSP m_protectedBy;
    QScopedPointer<KUndo2Command> m_transaction;
};
}

bool Filter::apply(Node *node, int x, int y, int w, int h)
{
    if (!node || !node->node()) return false;
    if (node->locked()) return false;

    KisFilterSP filter = KisFilterRegistry::instance()->value(d->name);
    if (!filter) return false;
    if (!d->configuration) return false;

    KisPaintDeviceSP dev = node->paintDevice();
    if (!dev) return false;

    KisImageSP image = node->image();
    QRect applyRect = QRect(x, y, w, h).normalized();
    KisFilterConfigurationSP config = static_cast<KisFilterConfiguration*>(d->configuration->configuration().data());
    KisFilterConfigurationSP snapshot = config->cloneWithResourcesSnapshot();

    if (!image || !node->node()->parent()) {
        // A node outside a document's tree: the old direct way, nothing to undo.
        filter->process(dev, applyRect, snapshot);
        return true;
    }

    // The selection that limits the node's tools (its own, else the image's), as the filter dialog uses it.
    KisSelectionSP selection;
    {
        KisResourcesSnapshotSP resources = new KisResourcesSnapshot(image, node->node());
        if (KisSelectionSP active = resources->activeSelection()) {
            selection = new KisSelection(*active);
            applyRect &= selection->selectedExactRect();
        }
    }
    if (applyRect.isEmpty()) return true; // nothing selected there: nothing to filter
    KisImageSP protectedBy = DocumentHistory::protectionFor(image);
    if (protectedBy) {
        const QString why = KisFeatureProtection::whyNotCanvasAligned(image, node->node());
        if (!why.isEmpty()) {
            warnScript << "Filter.apply() refused," << why;
            return false;
        }
    }

    // An undo step of its own, or part of the open macro or agent move; waits for this stroke only.
    DocumentHistory::scriptUndoAdapter(image, dev); // orders the step's work on this layer, if one is open
    // (On a locked image it is run at once and recorded, so a script inside a lock block sees the result.)
    return DocumentHistory::runPropertyCommand(image, new FilterApplyCommand(filter, snapshot, node->node(), applyRect, selection, protectedBy),
                                               "Filter.apply()", true);
}

bool Filter::startFilter(Node *node, int x, int y, int w, int h)
{
    if (node->locked()) return false;

    KisFilterSP filter = KisFilterRegistry::instance()->value(d->name);
    if (!filter) return false;

    KisImageSP image = node->image();
    if (!image) return false;

    KisFilterConfigurationSP filterConfig = static_cast<KisFilterConfiguration*>(d->configuration->configuration().data());

    // Krita Agent: its own resources, never the active view's.
    KisResourcesSnapshotSP resources = new KisResourcesSnapshot(image, node->node());

    // Krita Agent: a filter started in a macro or agent move joins its step.
    resources->setPostExecutionUndoAdapterOverride(DocumentHistory::scriptUndoAdapter(image, node->paintDevice()));

    // Krita Agent (krita-fork 6.5): an agent's filter is kept out of the protected features, as they are when it is
    // started (unlike Filter.apply(), which reads them when it runs).
    if (DocumentHistory::protectionFor(image)) {
        const QString why = KisFeatureProtection::whyNotCanvasAligned(image, node->node());
        if (!why.isEmpty()) {
            warnScript << "Filter.startFilter() refused," << why;
            return false;
        }
        KisSelectionSP active = resources->activeSelection();
        const QRect area = active ? active->selectedExactRect() & image->bounds() : image->bounds();
        image->featureList()->recordKeptOut(KisFeatureProtection::keptOutOf(image, area, active));
        resources->setSelectionOverride(KisFeatureProtection::guardSelection(image, active));
    }

    // Krita Agent: the artist's open strokes are not asked to end, and only this stroke is waited for (a stroke held
    // back past the wait limit is cancelled).
    return ScriptWaits::run(image, "Filter.startFilter()", [&]() {
        KisStrokeId currentStrokeId = image->startStroke(new KisFilterStrokeStrategy(filter,
                                                                                     KisFilterConfigurationSP(filterConfig),
                                                                                     resources));
        image->addJob(currentStrokeId, new KisFilterStrokeStrategy::FilterJobData());
        image->endStroke(currentStrokeId);
    });
}

KisFilterConfigurationSP Filter::filterConfig()
{
    KisFilterConfigurationSP config = KisFilterRegistry::instance()->get(d->name)->factoryConfiguration(KisGlobalResourcesInterface::instance());
    Q_FOREACH(const QString property, d->configuration->properties().keys()) {
        config->setProperty(property, d->configuration->property(property));
    }
    return config;
}
