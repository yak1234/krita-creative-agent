/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATURELIST_H
#define KISFEATURELIST_H

#include <QList>
#include <QObject>
#include <QPoint>
#include <QRect>
#include <QScopedPointer>
#include <QUuid>

#include "KisFeature.h"
#include "kis_default_bounds_base.h"
#include "kritaimage_export.h"

/**
 * The features of a document (the feature map: krita-fork, capability canvas-features), owned by its KisImage
 * (KisImage::featureList()) and copied with it, so a document cloned for saving saves them. KisKraSaver and
 * KisKraLoader keep them in the .kra: a <features version="1"> element in maindoc.xml and one mask per feature,
 * written by Krita's paint-device writer.
 *
 * The list keeps its features in order and indexes their bounds in an R-tree (boost::geometry::index::rtree), so
 * "which features are near here" never scans masks; exact answers then read the masks (queries: task 6.4).
 *
 * insertFeature(), removeFeature() and the features' own setters change the list at once, with no undo. Scripts and
 * tools change it through the undo commands in KisFeatureCommands.h instead, one undo step each.
 *
 * Thread safety: every method locks the list, so it can be read from the GUI thread while a stroke job changes it.
 * The signals are emitted from the thread that made the change, often a stroke job. sigFeatureChanged() is emitted
 * while the feature holds the list's notification guard (KisFeatureOwnerGuard), so a slot connected directly must
 * not wait for strokes or the image (waitForDone(), barrierLock()): the stroke it waits for may be the one emitting.
 * Connect queued, or only record the change.
 */
class KRITAIMAGE_EXPORT KisFeatureList : public QObject
{
    Q_OBJECT
public:
    /**
     * @param defaultBounds the bounds a feature's mask takes when it is added (the image's bounds, so "select all"
     *        and "invert" on a mask mean the whole document); null leaves masks as they are
     */
    explicit KisFeatureList(KisDefaultBoundsBaseSP defaultBounds = KisDefaultBoundsBaseSP(), QObject *parent = nullptr);
    ~KisFeatureList() override;

    /// Replaces this list's features with copies of \p rhs's (same ids, masks sharing tiles until changed).
    void copyFrom(const KisFeatureList &rhs);

    KisDefaultBoundsBaseSP defaultBounds() const;

    /**
     * The version of the .kra <features> element the list was loaded from (KisKraFeatures::Version for a new list).
     * Saving writes that version: a later one loses what this build does not understand, and the saver says so.
     * Copied by copyFrom(), so the clone that is saved carries it.
     */
    int sourceVersion() const;
    void setSourceVersion(int version);

    /**
     * Whether a feature has ever been in this list, or an add command made for it (KisAddFeatureCommand marks it
     * when it is made, before its stroke runs). False means no queued undo, redo or add can bring a feature in, so an
     * image operation can run exactly as upstream (KisFeatureImageCommand::endApplicator()). Never goes back to
     * false; copied by copyFrom().
     */
    bool mayHaveFeatures() const;
    void setMayHaveFeatures();

    QList<KisFeatureSP> features() const;
    int count() const;
    bool isEmpty() const;

    KisFeatureSP feature(const QUuid &id) const;
    /// The first feature with this exact name, or null.
    KisFeatureSP featureByName(const QString &name) const;
    /// The position of the feature with \p id, or -1.
    int indexOf(const QUuid &id) const;

    /**
     * Adds \p feature at \p index (at the end when out of range), with no undo.
     * @return false if the feature is null or a feature with its id is already in the list
     */
    bool insertFeature(KisFeatureSP feature, int index = -1);

    /// Removes the feature with \p id, with no undo. @return the feature removed, or null
    KisFeatureSP removeFeature(const QUuid &id);

    /// Removes every feature, with no undo.
    void clear();

    /**
     * The spatial index, at the level of bounds: the features whose bounds intersect \p rect, in list order. Some
     * may not touch \p rect with any pixel of their mask; the exact queries of task 6.4 read the masks.
     */
    QList<KisFeatureSP> featuresWithBoundsIntersecting(const QRect &rect) const;

    /// The features whose bounds contain \p point, in list order (bounds level, as above).
    QList<KisFeatureSP> featuresWithBoundsContaining(const QPoint &point) const;

Q_SIGNALS:
    void sigFeatureAdded(const QUuid &id);
    void sigFeatureRemoved(const QUuid &id);
    /// A feature's name, kind, author, state, protection, mask or properties changed.
    void sigFeatureChanged(const QUuid &id);

private:
    friend class KisFeature;
    /// Called by a feature of this list after it changed (outside the feature's lock).
    void featureChanged(KisFeature *feature, bool boundsChanged);

    struct Private;
    QScopedPointer<Private> m_d;
};

#endif // KISFEATURELIST_H
