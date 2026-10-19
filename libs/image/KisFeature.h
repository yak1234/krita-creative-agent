/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef KISFEATURE_H
#define KISFEATURE_H

#include <QMutex>
#include <QRecursiveMutex>
#include <QRect>
#include <QSharedPointer>
#include <QString>
#include <QUuid>

#include <KoColor.h>

#include "kis_shared.h"
#include "kis_shared_ptr.h"
#include "kis_types.h"
#include "kritaimage_export.h"

class KisFeature;
class KisFeatureList;
typedef KisSharedPtr<KisFeature> KisFeatureSP;

/**
 * The link from the features of a list to the list. The list clears it before it is destroyed, under \p mutex, which
 * a feature holds while it notifies the list (KisFeature::notifyOwner()): a feature never calls a list that is gone,
 * even when one thread changes the feature while another destroys the list. Recursive, so a slot that destroys the
 * list during a notification does not wait for itself.
 */
struct KisFeatureOwnerGuard {
    QRecursiveMutex mutex;
    KisFeatureList *list {nullptr};
};

/**
 * A feature of the painting: a named region ("Sky", "Moon", "Tower 3") with an 8-bit mask at document size. It
 * describes the painting and never holds its pixels, so it can span layers, and adding, changing or removing it
 * changes no pixel. A document keeps its features in a KisFeatureList owned by its KisImage.
 *
 * The mask is a tiled KisPixelSelection: empty and full tiles cost almost nothing, so a feature that covers a small
 * part of a large image stays small. Never copy it into a dense buffer.
 *
 * The measured properties (bounds, area, mean colour) are a snapshot taken when the mask was set or measured:
 * setMask() and measure() update them, and so do the image's crop, canvas resize, scale, rotate, shear, mirror and
 * colour-space conversion, which also move the mask (KisFeatureImageCommand); painting does not. The mean colour is
 * saved with the feature, so a reopened document has it without compositing; bounds and area are measured on load.
 *
 * Thread safety: every accessor locks the feature, so its fields can be read from the GUI thread while a stroke job
 * changes them. Change a feature that is in a list through undo commands (KisFeatureCommands.h) or through the
 * setters here; both keep the list's spatial index current.
 */
class KRITAIMAGE_EXPORT KisFeature : public KisShared
{
public:
    /// Who made the feature.
    enum Author {
        Artist,
        Agent
    };

    /// A proposed feature (usually the agent's) does not count until the artist keeps it.
    enum State {
        Proposed,
        Kept
    };

    /// What a feature measured from its mask and the painting under it.
    struct Properties {
        /// The exact bounds of the mask's non-zero pixels, in image coordinates; empty for an empty mask.
        QRect bounds;
        /// The number of pixels where the mask is not zero.
        qint64 area {0};
        /// The mean colour of the painting under the mask, weighted by the mask's value (Krita's alpha-weighted
        /// colour mixing), in the colour space of the device it was measured on. Without a colour space (no
        /// colour source, or an empty mask) there is no mean colour.
        KoColor meanColor;
        /// False when there is no mean colour: \p meanColor is then meaningless.
        bool hasMeanColor {false};

        bool operator==(const Properties &rhs) const;
        bool operator!=(const Properties &rhs) const { return !(*this == rhs); }
    };

    /**
     * @param name the feature's name
     * @param kind what it is: "sky", "building", "figure", "seam", ... (free text)
     * @param mask the feature's mask, held as it is (not copied); a null mask becomes an empty one
     * @param id the feature's identity; a null id gets a new one
     */
    KisFeature(const QString &name,
               const QString &kind,
               KisPixelSelectionSP mask,
               Author author = Agent,
               State state = Proposed,
               bool isProtected = false,
               const QUuid &id = QUuid());

    /// A copy with the same id and properties, its mask copied (Krita shares the tiles until one side changes them),
    /// in no list.
    KisFeature(const KisFeature &rhs);
    ~KisFeature();

    KisFeature &operator=(const KisFeature &rhs) = delete;

    QUuid id() const;

    QString name() const;
    void setName(const QString &name);

    QString kind() const;
    void setKind(const QString &kind);

    Author author() const;
    void setAuthor(Author author);

    State state() const;
    void setState(State state);

    /// Protection is stored here; enforcing it belongs to the code that writes pixels (krita-fork task 6.5).
    bool isProtected() const;
    void setProtected(bool value);

    /// The mask itself, not a copy. Who changes its pixels in place calls measure() afterwards.
    KisPixelSelectionSP mask() const;

    /**
     * Replaces the mask and measures it again.
     * @param colorSource the painting to take the mean colour from (usually the image's projection); without one
     *        the feature has no mean colour
     */
    void setMask(KisPixelSelectionSP mask, KisPaintDeviceSP colorSource = KisPaintDeviceSP());

    /// Measures the current mask again (after its pixels changed in place, or the painting under it changed).
    void measure(KisPaintDeviceSP colorSource = KisPaintDeviceSP());

    Properties properties() const;
    QRect bounds() const;
    qint64 area() const;
    KoColor meanColor() const;

    /// Sets properties measured earlier, without measuring (the .kra loader restores the saved ones).
    void setProperties(const Properties &properties);

    /// Replaces the mask and its properties at once, without measuring: undo and redo of a command that changed
    /// both (KisFeatureImageCommand) put back what was measured before.
    void setMaskAndProperties(KisPixelSelectionSP mask, const Properties &properties);

    /// Measures \p mask: its exact bounds, area and, with a colour source, mean colour. Reads only the mask's
    /// non-default tiles inside its exact bounds, row by row, never a dense copy.
    static Properties measureMask(KisPixelSelectionSP mask, KisPaintDeviceSP colorSource);

    /**
     * A copy of \p mask cut to \p bounds (the document), with an unselected default pixel. An inverted selection
     * selects everything outside its holes, out to infinity (its default pixel is selected): as a feature's mask it
     * would select new canvas borders and the corners of a rotation. Masks of features are always made this way
     * (libkis addFeature, the .kra loader). The copy shares the tiles of \p mask until one side changes them.
     */
    static KisPixelSelectionSP boundedMask(KisPixelSelectionSP mask, const QRect &bounds);

    static QString authorToString(Author author);
    /// "artist" or "agent"; anything else gives \p fallback.
    static Author authorFromString(const QString &value, Author fallback = Agent);
    static QString stateToString(State state);
    /// "proposed" or "kept"; anything else gives \p fallback.
    static State stateFromString(const QString &value, State fallback = Proposed);

private:
    friend class KisFeatureList;
    /// Set by the list that holds the feature, so a change of bounds updates its spatial index.
    void setOwner(QSharedPointer<KisFeatureOwnerGuard> guard);
    QSharedPointer<KisFeatureOwnerGuard> owner() const;
    void notifyOwner(bool boundsChanged);

    mutable QMutex m_mutex;
    const QUuid m_id;
    QString m_name;
    QString m_kind;
    Author m_author;
    State m_state;
    bool m_protected;
    KisPixelSelectionSP m_mask;
    Properties m_properties;
    QSharedPointer<KisFeatureOwnerGuard> m_owner;
};

#endif // KISFEATURE_H
