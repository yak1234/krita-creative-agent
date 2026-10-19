/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#ifndef LIBKIS_KRITA_H
#define LIBKIS_KRITA_H

#include <QObject>
#include <QAction>

#include "kritalibkis_export.h"
#include "libkis.h"

#include "Extension.h"
#include "Document.h"
#include "Window.h"
#include "View.h"
#include "Notifier.h"


/**
 * Krita is a singleton class that offers the root access to the Krita object hierarchy.
 *
 * The Krita.instance() is aliased as two builtins: Scripter and Application.
 */
class KRITALIBKIS_EXPORT Krita : public QObject
{
    Q_OBJECT

public:
    explicit Krita(QObject *parent = 0);
    ~Krita() override;

public Q_SLOTS:


    /**
     * @return the currently active document, if there is one.
     */
    Document* activeDocument() const;

    /**
     * @brief setActiveDocument activates the first view that shows the given document
     * @param value the document we want to activate
     */
    void setActiveDocument(Document* value);

    /**
     * @brief batchmode determines whether the script is run in batch mode. If batchmode
     * is true, scripts should now show messageboxes or dialog boxes.
     *
     * Note that this separate from Document.setBatchmode(), which determines whether
     * export/save option dialogs are shown.
     *
     * @return true if the script is run in batchmode
     */
    bool batchmode() const;

    /**
     * @brief setBatchmode sets the batchmode to @param value; if true, scripts should
     * not show dialogs or messageboxes.
     */
    void setBatchmode(bool value);

    /**
     * @return return a list of all actions for the currently active mainWindow.
     */
    QList<QAction*> actions() const;

    /**
     * @return the action that has been registered under the given name, or 0 if no such action exists.
     */
    QAction *action(const QString &name) const;

    /**
     * @return a list of all open Documents
     */
    QList<Document*> documents() const;

    /**
     * @return a list of all the dockers
     */
    QList<QDockWidget*> dockers() const;

    /**
     * @brief Filters are identified by an internal name. This function returns a list
     * of all existing registered filters.
     * @return a list of all registered filters
     */
    QStringList filters() const;

    /**
     * @brief filter construct a Filter object with a default configuration.
     * @param name the name of the filter. Use Krita.instance().filters() to get
     * a list of all possible filters.
     * @return the filter or None if there is no such filter.
     */
    Filter *filter(const QString &name) const;

    /**
     * @brief colorModels creates a list with all color models id's registered.
     * @return a list of all color models or a empty list if there is no such color models.
     */
    QStringList colorModels() const;

    /**
     * @brief colorDepths creates a list with the names of all color depths
     * compatible with the given color model.
     * @param colorModel the id of a color model.
     * @return a list of all color depths or a empty list if there is no such
     * color depths.
     */
    QStringList colorDepths(const QString &colorModel) const;

    /**
     * @brief filterStrategies Retrieves all installed filter strategies. A filter
     * strategy is used when transforming (scaling, shearing, rotating) an image to
     * calculate the value of the new pixels. You can use th
     * @return the id's of all available filters.
     */
    QStringList filterStrategies() const;

    /**
     * @brief profiles creates a list with the names of all color profiles compatible
     * with the given color model and color depth.
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
     * @return a list with valid names
     */
    QStringList profiles(const QString &colorModel, const QString &colorDepth) const;

    /**
     * @brief addProfile load the given profile into the profile registry.
     * @param profilePath the path to the profile.
     * @return true if adding the profile succeeded.
     */
    bool addProfile(const QString &profilePath);

    /**
     * @brief notifier the Notifier singleton emits signals when documents are opened and
     * closed, the configuration changes, views are opened and closed or windows are opened.
     * @return the notifier object
     */
    Notifier *notifier() const;

    /**
     * @brief version Determine the version of Krita
     *
     * Usage: print(Application.version ())
     *
     * @return the version string including git sha1 if Krita was built from git
     */
    QString version() const;

    /**
     * @return a list of all views. A Document can be shown in more than one view.
     */
    QList<View*> views() const;

    /**
     * @return the currently active window or None if there is no window
     */
    Window *activeWindow() const;

    /**
     * @return a list of all windows
     */
    QList<Window *> windows() const;

    /**
     * @brief resources returns a list of Resource objects of the given type
     * @param type Valid types are:
     *
     * <ul>
     * <li>pattern</li>
     * <li>gradient</li>
     * <li>brush</li>
     * <li>preset</li>
     * <li>palette</li>
     * <li>workspace</li>
     * </ul>
     */
    QMap<QString, Resource*> resources(QString &type) const;

    // Krita Agent: brush tips and presets made by scripts (krita-fork 5.1; implemented in KritaAgentResources.cpp).

    /**
     * @brief createBrushTip makes a brush tip from \p image, as the Custom Brush dialog's "Stamp" does, and adds it
     * to the resource database: it is listed and usable at once, without a restart, and tagged "Agent".
     *
     * A tip with the name of one made here earlier replaces it (a new version of that resource, as saving a
     * resource of the same name in Krita does). Replacing a tip changes every preset that uses it, the agent's and
     * the artist's alike: a preset finds its tip through the resource, which now holds the new pixels. To change one
     * preset only, make a tip with a new name and a preset with it.
     *
     * Only the agent's own tips are replaced: those tagged "Agent" in the resource folder, saved in the same format.
     * When the name belongs to any other resource (one of Krita's, the artist's, a bundle's or a document's), it is
     * left alone and the new tip is named "name (2)" (or the next free number); the returned resource has that name.
     *
     * How the tip is applied ("image" or "lightness", see below) is kept in the resource database, not in the tip's
     * .gbr file, which has no place for it. Presets made with the tip keep it in their own file. If the database
     * loses it (rebuilt from the files), a later createPreset() uses an "image" tip as a lightness map.
     *
     * @code
     * tip = Application.createBrushTip(QImage("/path/cloud.png"), "Cloud tip")
     * preset = Application.createPreset(basePreset, tip, "Cloud")
     * @endcode
     *
     * @param image the tip's pixels; its size is the tip's size at brush size 100%
     * @param name the resource's name (its file is named after it, with the characters a file name cannot take
     * replaced)
     * @param application how the brush engine uses the tip:
     * <ul>
     * <li>"alpha" (the default): the image's alpha is the tip's coverage, painted in the current colour;</li>
     * <li>"mask": coverage from the image's darkness and alpha, painted in the current colour (the dialog's
     * "Create mask from color");</li>
     * <li>"image": stamps the image's own colours;</li>
     * <li>"lightness": the image's lightness on the current colour.</li>
     * </ul>
     * @return the new brush tip resource (type "brush"; its name() is the name it was given), or 0 for a null or
     * empty image, an empty name or an unknown application
     */
    Resource *createBrushTip(const QImage &image, const QString &name, const QString &application = QString("alpha"));

    /**
     * @brief createBrushTip makes a brush tip from an area of \p document's rendered image (its projection), as the
     * Custom Brush dialog does from the image. See createBrushTip(QImage, ...).
     *
     * @param document the document to read
     * @param rect the area in image pixels; an empty rect takes the whole image
     * @param name the resource's name
     * @param application "alpha", "mask", "image" or "lightness", as for createBrushTip(QImage, ...)
     * @return the new brush tip resource, or 0
     */
    Resource *createBrushTip(Document *document, const QRect &rect, const QString &name,
                             const QString &application = QString("alpha"));

    /**
     * @brief createPreset makes a brush preset from \p basePreset with \p brushTip as its tip, and adds it to the
     * resource database: listed and usable at once (View.setCurrentBrushPreset()), without a restart, and tagged
     * "Agent". The base preset itself does not change.
     *
     * The base must be a preset whose engine uses brush tips (the pixel brush, colour smudge, and so on). The new
     * preset takes the tip at its own size (scale 100%), its spacing and its application; everything else (size
     * curves, opacity, flow, blending mode) comes from the base. A preset with the name of one made here earlier
     * replaces it; a name that belongs to any other preset (Krita's own, the artist's) is left alone and the new
     * preset is named "name (2)" (or the next free number), as for createBrushTip().
     *
     * @param basePreset a resource of type "preset"
     * @param brushTip a resource of type "brush", from createBrushTip() or Krita's own
     * @param name the new preset's name
     * @return the new preset (type "preset"), or 0 when an argument is missing or of the wrong type, or the base's
     * engine has no brush tip
     */
    Resource *createPreset(Resource *basePreset, Resource *brushTip, const QString &name);

    /**
     * @brief createPreset makes a brush preset from a preset's XML (as Preset.toXML() gives) with \p brushTip as
     * its tip. See createPreset(Resource, ...).
     */
    Resource *createPreset(const QString &baseXml, Resource *brushTip, const QString &name);


    /**
     * @brief return all recent documents registered in the RecentFiles group of the kritarc
     */
    QStringList recentDocuments() const;


    /**
     * @brief createDocument creates a new document and image and registers
     * the document with the Krita application.
     *
     * Unless you explicitly call Document::close() the document will remain
     * known to the Krita document registry. The document and its image will
     * only be deleted when Krita exits.
     *
     * The document will have one transparent layer.
     *
     * To create a new document and show it, do something like:
@code
from Krita import *

def add_document_to_window():
    d = Application.createDocument(100, 100, "Test", "RGBA", "U8", "", 120.0)
    Application.activeWindow().addView(d)

add_document_to_window()
@endcode
     *
     * @param width the width in pixels
     * @param height the height in pixels
     * @param name the name of the image (not the filename of the document)
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
     * @param profile The name of an icc profile that is known to Krita. If an empty string is passed, the default is
     * taken.
     * @param resolution the resolution in points per inch.
     * @return the created document.
     */
    Document *createDocument(int width, int height, const QString &name, const QString &colorModel, const QString &colorDepth, const QString &profile, double resolution);

    /**
     * @brief openDocument creates a new Document, registers it with the Krita application and loads the given file.
     * @param filename the file to open in the document
     * @return the document
     */
    Document *openDocument(const QString &filename);

    /**
     * @brief openWindow create a new main window. The window is not shown by default.
     */
    Window *openWindow();

    /**
     * @brief addExtension add the given plugin to Krita. There will be a single instance of each Extension in the Krita process.
     * @param extension the extension to add.
     */
    void addExtension(Extension* extension);

    /**
     * return a list with all registered extension objects.
     */
    QList<Extension*> extensions();

    /**
     * @brief addDockWidgetFactory Add the given docker factory to the application. For scripts
     * loaded on startup, this means that every window will have one of the dockers created by the
     * factory.
     * @param factory The factory object.
     */
    void addDockWidgetFactory(DockWidgetFactoryBase* factory );

    /**
     * @brief writeSetting write the given setting under the given name to the kritarc file in
     * the given settings group.
     * @param group The group the setting belongs to. If empty, then the setting is written in the
     * general section
     * @param name The name of the setting
     * @param value The value of the setting. Script settings are always written as strings.
     */
    void writeSetting(const QString &group, const QString &name, const QString &value);

    /**
     * @brief readSetting read the given setting value from the kritarc file.
     * @param group The group the setting is part of. If empty, then the setting is read from
     * the general group.
     * @param name The name of the setting
     * @param defaultValue The default value of the setting
     * @return a string representing the setting.
     */
    QString readSetting(const QString &group, const QString &name, const QString &defaultValue);

    /**
     * @brief icon
     * This allows you to get icons from Krita's internal icons.
     * @param iconName name of the icon.
     * @return the icon related to this name.
     */
    QIcon icon(QString &iconName) const;

    /**
     * @brief instance retrieve the singleton instance of the Application object.
     */
    static Krita* instance();

    // Internal only: for use with mikro.py
    static QObject *fromVariant(const QVariant& v);

    static QString krita_i18n(const QString &text);
    static QString krita_i18nc(const QString &context, const QString &text);


    static QString getAppDataLocation();

private Q_SLOTS:

    /// This is called from the constructor of the window, before the xmlgui file is loaded
    void mainWindowIsBeingCreated(KisMainWindow *window);


private:
    struct Private;
    Private *const d;
    static Krita* s_instance;

};

Q_DECLARE_METATYPE(Notifier*);

#endif // LIBKIS_KRITA_H
