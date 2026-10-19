/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen
 *  SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AGENT_ACCEL_H
#define AGENT_ACCEL_H

#include <QByteArray>
#include <QHash>
#include <QObject>
#include <QSharedPointer>
#include <QString>
#include <QVariant>
#include <KisActionPlugin.h>

/**
 * Loaded once per Krita window like any view plugin; the first one creates the service below. It adds no actions.
 */
class AgentAccelPlugin : public KisActionPlugin
{
    Q_OBJECT
public:
    AgentAccelPlugin(QObject *parent, const QVariantList &);
    ~AgentAccelPlugin() override;
};

/**
 * What the Creative Agent's Python plugin calls (kritamcp/agent_accel.py): one object on the application, found by its
 * name, with invokable methods taking plain values. Every method runs on Krita's main thread, as the plugin's do.
 */
class AgentAccelService : public QObject
{
    Q_OBJECT
public:
    static constexpr const char *OBJECT_NAME = "creative-agent-accel";
    static void ensure();

    /// The helper's protocol version; the Python side refuses a version it does not know.
    Q_INVOKABLE int version() const;
    /// Recomposite the part of the document at `path` (empty: the active one) that changes when pixels changed inside
    /// [x, y, w, h], and wait for it, where the Python API can only recomposite the whole image. The rect is grown by
    /// every effect that spreads a change outside it (region_refresh.h): filter masks, adjustment layers, layer styles,
    /// transform masks, clones, through pass-through groups; before protocol 7 it was exactly the rect, which left a
    /// stale halo. Returns the milliseconds it took, or -1 when there is no such document.
    Q_INVOKABLE int refreshRect(const QString &path, int x, int y, int w, int h);
    /// refreshRect, answering {"ms", "rect": [x, y, w, h] (what was recomposited, cut to the image; [0, 0, 0, 0] when
    /// nothing of the rect is inside it), "requested": [x, y, w, h]} as JSON, or {"error"} (protocol 7).
    Q_INVOKABLE QString refreshRegion(const QString &path, int x, int y, int w, int h);
    /// Paint a chunk of strokes on the layer `layerId` (its uniqueId) of the document at `path`, with the brush preset
    /// the view has now. `strokesJson` is {"strokes": [{"start": [x, y, pen...], "segments": [[c1x, c1y, c2x, c2y,
    /// x, y, pen...], ...], "size", "opacity", "flow", "color": "#rrggbb"}]}, where pen is pressure?, xTilt?, yTilt?,
    /// rotation?, speed?, timeMs? (stroke_points.h: Krita's tablet units, defaults a mouse's). The Python API makes one
    /// stroke job, undo step and view brush update per stroke and paints with a mouse at full pressure; here consecutive
    /// strokes that share size, opacity, flow and colour are one stroke job, the brush is never pushed to the view, and
    /// every point carries its pen values to the brush's sensors. Queues the jobs and returns {"status", "strokes",
    /// "jobs", "ms"} as JSON, or {"error"};
    /// the caller waits for them as it does today (Document.waitForDone).
    Q_INVOKABLE QString paintStrokes(const QString &path, const QString &layerId, const QString &strokesJson);

    /*
     * Selection builders on the visible image (the projection) of the document at `path`, as the plugin's `select`
     * steps mean them (region_craft.py colour_mask and connected_mask): a pixel matches when each of its 8-bit R, G and
     * B is within `tolerance` (0-255) of the wanted colour's and it is not fully transparent. The search stays inside
     * [bx, by, bw, bh] (the step's bounds, or the whole canvas). Krita's own similar-colour test (KoColorSpace::
     * differenceA, used by KisFillPainter) measures colour another way and would select other pixels, so the test is
     * the plugin's; the joining is Krita's scanline fill (KisScanlineFill), as the contiguous selection tool's.
     *
     * The answer is a 16-byte header, x, y, w, h as little-endian int32: the bounding rect of the selected pixels,
     * then w*h mask bytes (255 selected, 0 not), row by row. Nothing selected is w = h = 0 and no bytes. An empty
     * QByteArray is a failure (no such document, not 8-bit RGBA, a seed outside the bounds): the caller then uses
     * its Python path.
     */
    /// The pixels matching the seed's colour that join the seed through edge neighbours (a magic wand).
    Q_INVOKABLE QByteArray selectContiguous(const QString &path, int x, int y, int tolerance, int bx, int by, int bw, int bh);
    /// Every pixel matching `colour` ("#rrggbb"), joined or not (a colour range).
    Q_INVOKABLE QByteArray selectSimilar(const QString &path, const QString &colour, int tolerance, int bx, int by, int bw, int bh);
    /// The outline of a mask in the builders' format, from KisPixelSelection::outline(): {"polygons": [[[x, y], ...],
    /// ...]} in canvas pixel corners, or {"error"}.
    Q_INVOKABLE QString selectionOutline(const QByteArray &headerAndMask);

    /// A whole select's seed and colour steps in one call, where the plugin made a selection per step and merged them in
    /// Python (about 0.5 s a step at 6000x4500, nearly all of it moving and merging masks). `stepsJson` is the plugin's
    /// steps without their refinements, [{"seed": [x, y] | "color": "#rrggbb", "tolerance"?, "bounds"?: [x, y, w, h],
    /// "mode"?}], with region_craft's defaults (tolerance 24, the whole canvas, replace first and add after). The
    /// projection is read once, every step searched in it as selectContiguous and selectSimilar search, and the steps
    /// combined on byte masks as KisPixelSelection::applySelection combines them. Answers one mask in the builders'
    /// format, cropped to the final selected pixels; an empty QByteArray for a failure or a step it refuses (the plugin
    /// then builds step by step).
    Q_INVOKABLE QByteArray buildSelection(const QString &path, const QString &stepsJson);
    /// The last buildSelection's phases in milliseconds, as JSON: {"steps", "area": [x, y, w, h], "wait" (for Krita to
    /// settle), "parse", "read" (the projection), "fill" (every step's search), "combine", "pack", "total"}, or {"error"} when it failed. "{}" before any.
    Q_INVOKABLE QString buildTimings() const;

    /*
     * Background save (protocol 6), where libkis's Document.save() holds Krita's main thread for the whole write (5-6.5
     * s at 6000x4500). Krita's own background path (KisDocument::exportDocument -> initiateSavingInBackground) copies
     * the image on the main thread and writes the copy on a worker thread; the document stays usable meanwhile.
     *
     * The copy is written beside the painting (background_save.h) and renamed over it only once Krita reports it
     * written and verified, so a failed save leaves the previous file as it was: Krita's own save on macOS deletes the
     * painting before copying the new file in. The document is marked unmodified when nothing changed it while it
     * saved, as Krita's own save does. No dialog is shown (batch mode while it starts and finishes); Krita shows its
     * usual progress in the status bar.
     *
     * One save per document at a time: a request while this helper's or Krita's own save of it runs (autosave, the
     * artist's save) is refused, never queued: its job fails at once with that reason, and the caller tries later.
     * A document closed mid-save: Krita waits for the save while it closes, so the job still ends done or failed.
     */
    /// Start saving the open document whose file is `path` (empty: the active one) to that file. Returns the job id
    /// (from 1), or -1 when there is no such document.
    Q_INVOKABLE int saveInBackground(const QString &path);
    /// The job as JSON: {"job", "state": "running" | "done" | "failed", "ms" (request to end, or so far), "startMs"
    /// (the main thread's share: waiting, copying, starting), "error", "file", "clean" (the document was marked
    /// unmodified)}. An unknown job is failed with an error, never done.
    Q_INVOKABLE QString saveStatus(int jobId) const;

private:
    explicit AgentAccelService(QObject *parent);
    struct SaveJob;
    void finishSave(int id, bool exported, const QString &exportError);
    QString m_buildTimings = QStringLiteral("{}");
    QHash<int, QSharedPointer<SaveJob>> m_saveJobs;
    int m_lastSaveJob = 0;
};

#endif
