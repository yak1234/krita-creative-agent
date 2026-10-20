/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_FEATURE_H
#define LIBKIS_FEATURE_H

#include <QColor>
#include <QObject>
#include <QRect>
#include <QString>

#include "kritalibkis_export.h"
#include "libkis.h"

#include <KisFeature.h>
#include <kis_types.h>

class Selection;

/**
 * Feature is a named region of the painting, such as "Sky", "Moon" or "Tower 3": a mask at document size with a
 * name, a kind, who made it and whether it counts yet. A feature describes the painting and never holds its pixels:
 * it can span layers, and adding, renaming or removing one changes no pixel. Features are saved in the .kra; stock
 * Krita opens the file and ignores them.
 *
 * Get them from Document.features() and Document.feature(name), and change the list with Document.addFeature(),
 * Document.renameFeature() and Document.removeFeature(), each one undo step.
 *
 * A Feature object follows the feature in its document: after a rename, name() gives the new name. The measured
 * properties (bounds, area, mean colour) were taken when its mask was set.
 *
 * @code
 * doc = Krita.instance().activeDocument()
 * sel = Selection()
 * sel.select(0, 0, doc.width(), 1800, 255)
 * sky = doc.addFeature("Sky", "sky", sel, "artist", "kept")
 * print(sky.bounds(), sky.area(), sky.meanColor().name())
 * for f in doc.features():
 *     print(f.name(), f.kind(), f.author(), f.state())
 * @endcode
 */
class KRITALIBKIS_EXPORT Feature : public QObject
{
    Q_OBJECT
    Q_DISABLE_COPY(Feature)

public:
    /// Wraps \p feature of \p image. Scripts get Feature objects from Document.
    explicit Feature(KisImageSP image, KisFeatureSP feature, QObject *parent = 0);
    ~Feature() override;

    /// Two Feature objects are equal when they stand for the same feature.
    bool operator==(const Feature &other) const;
    bool operator!=(const Feature &other) const;

public Q_SLOTS:
    /**
     * @return the feature's identity, which stays the same through renames and saving, as a string such as
     * "{6f1c...}"
     */
    QString id() const;

    /// @return the feature's name, unique in its document
    QString name() const;

    /// @return what the feature is: "sky", "building", "figure", "seam", ... (free text)
    QString kind() const;

    /// @return who made it: "artist" or "agent"
    QString author() const;

    /// @return "proposed" (an agent's proposal, which does not count until the artist keeps it) or "kept"
    QString state() const;

    /**
     * @return true if the feature is protected: Krita keeps the agent's writes out of it (see Feature.setProtected()).
     */
    bool isProtected() const;

    /**
     * @brief setProtected protects the feature, or lifts its protection, as one undo step (inside an open agent move
     * or macro, part of its step). No pixel changes, and the protection is saved in the .kra.
     *
     * While a feature is protected, Krita keeps the agent's writes out of it:
     * <ul>
     * <li>clipped: Node.paintStrokes() jobs, the tool functions Node.fill(), encloseAndFill(), gradient() and
     * smartPatch(); and, while the agent works (an agent move or job is open, or Document.setAgentActive(True)), the raw
     * writes Node.setPixelData(), Channel.setPixelData(), Filter.apply(), Filter.startFilter(), Selection.cut() and
     * paste();</li>
     * <li>refused whole (the call cannot be clipped; it returns false or None, warns, and Document.lastKeptOut() names
     * the features): Node.move(), rotateNode(), scaleNode(), shearNode(), cropNode(), setColorSpace(), setColorProfile()
     * of a layer whose pixels reach a protected feature, a mergeDown() that is not Normal-blend and fully opaque, and any
     * write to a layer under a transform mask or shown by a clone layer;</li>
     * <li>not covered: layer creation, opacity, visibility and blending-mode edits, layer styles, and spreading effects
     * (blur or offset filter layers, filter masks, colorize mask key strokes). They are not pixel writes of the agent
     * into the feature, but they can change how a protected feature looks; Document.protectedSelection() gives a
     * selection to limit such a layer with. Krita.action(...) and the tool actions use the artist's selection and are
     * not protected either.</li>
     * </ul>
     * The writes happen as asked everywhere else, and the call names what it was kept out of (see
     * Document.lastKeptOut()). The artist's own tools are never restricted. Protection does not depend on the script
     * that set it: it stays on until someone lifts it. A deliberate edit inside a protected feature passes the option
     * "allowProtected" to the call, or lifts the protection with Document.setProtectionSuspended() inside an agent move.
     * Unprotecting (setProtected(False)), removing the feature and undoing the step that protected it also lift it: they
     * are ordinary calls, so a bridge that must not let a model do that does not forward them.
     *
     * A job already running honours a feature protected meanwhile from its next window of strokes on (at most 32
     * strokes later); the tool functions read protection when their stroke runs.
     *
     * @return true if it was set (or already was); false if the feature is no longer in its document, or the call was
     * held back past the wait limit
     */
    bool setProtected(bool value);

    /// @return the exact bounds of the mask's non-zero pixels; an empty rect for an empty mask
    QRect bounds() const;

    /// @return the number of pixels the mask selects at all (non-zero)
    qint64 area() const;

    /**
     * @return the mean colour of the painting under the mask, weighted by the mask's value, measured when the mask
     * was set; an invalid QColor when there is none
     */
    QColor meanColor() const;

    /**
     * @return a copy of the feature's mask as a Selection (255 inside, 0 outside, in between at soft edges). Changing
     * the copy does not change the feature.
     */
    Selection *mask() const;

    /// @return true while the feature is in its document (false after it was removed)
    bool isInDocument() const;

private:
    friend class Document;
    KisFeatureSP feature() const;

    struct Private;
    Private *const d;
};

#endif // LIBKIS_FEATURE_H
