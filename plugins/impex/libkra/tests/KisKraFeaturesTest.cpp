/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "KisKraFeaturesTest.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDomDocument>
#include <QFile>
#include <QMap>
#include <QRegularExpression>

#include <functional>
#include <zlib.h>
#include <QScopedPointer>
#include <QTemporaryDir>

#include <quazip.h>
#include <quazipfile.h>
#include <quazipnewinfo.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <KoDocumentInfo.h>
#include <KoStore.h>

#include <KisFeature.h>
#include <KisFeatureList.h>
#include <kis_fill_painter.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kis_pixel_selection.h>
#include <kis_undo_stores.h>

#include "KisKraFeatures.h"

namespace {

const QRect imageRect(0, 0, 300, 200);

/// A painting with a blue sky over grey ground, a yellow moon, and three features: "Sky" (the artist's, kept and
/// protected), "Moon" (a soft mask, the agent's proposal) and "Tower 3" (two separate parts).
struct FeatureDocument {
    QScopedPointer<KisDocument> doc;
    KisImageSP image;
    KisNodeSP layer;

    FeatureDocument(bool withFeatures = true)
        : doc(KisPart::instance()->createDocument())
    {
        doc->setFileBatchMode(true); // never a dialog in a test
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(new KisSurrogateUndoStore(), imageRect.width(), imageRect.height(), cs, "features");
        layer = new KisPaintLayer(image, "painting", OPACITY_OPAQUE_U8);
        KisPaintDeviceSP dev = layer->paintDevice();
        dev->fill(QRect(0, 0, 300, 100), KoColor(QColor(40, 80, 200), cs));
        dev->fill(QRect(0, 100, 300, 100), KoColor(QColor(120, 120, 120), cs));
        dev->fill(QRect(220, 20, 30, 30), KoColor(QColor(250, 230, 90), cs));
        image->addNode(layer);
        doc->setCurrentImage(image);
        doc->documentInfo()->setAboutInfo("title", "features");
        image->initialRefreshGraph();
        image->waitForDone();

        if (!withFeatures) return;

        KisPixelSelectionSP sky = new KisPixelSelection();
        sky->select(QRect(0, 0, 300, 100));
        add(new KisFeature("Sky", "sky", sky, KisFeature::Artist, KisFeature::Kept, true));

        // Soft edges: every value from 1 to 255 appears, so a lossy write would show.
        KisPixelSelectionSP moon = new KisPixelSelection();
        for (int y = 0; y < 30; y++) {
            for (int x = 0; x < 30; x++) {
                moon->select(QRect(220 + x, 20 + y, 1, 1), quint8(1 + (x * 30 + y * 7) % 255));
            }
        }
        add(new KisFeature("Moon", "moon", moon, KisFeature::Agent, KisFeature::Proposed, false));

        KisPixelSelectionSP tower = new KisPixelSelection();
        tower->select(QRect(50, 80, 20, 120));
        tower->select(QRect(90, 120, 15, 80));
        add(new KisFeature("Tower 3", "building", tower, KisFeature::Agent, KisFeature::Kept, false));
    }

    void add(KisFeatureSP feature)
    {
        feature->measure(image->projection());
        QVERIFY(image->featureList()->insertFeature(feature));
    }

    QString save(const QTemporaryDir &dir, const QString &name = "features.kra")
    {
        const QString path = dir.filePath(name);
        if (!doc->exportDocumentSync(path, doc->nativeFormatMimeType())) {
            qWarning() << "saving failed:" << doc->errorMessage() << path;
            return QString();
        }
        return path;
    }
};

QByteArray maskBytes(KisPixelSelectionSP mask)
{
    QByteArray bytes(imageRect.width() * imageRect.height(), 0);
    mask->readBytes(reinterpret_cast<quint8 *>(bytes.data()), imageRect);
    return bytes;
}

QDomDocument readMaindoc(const QString &path)
{
    QDomDocument dom;
    QScopedPointer<KoStore> store(KoStore::createStore(path, KoStore::Read));
    if (store && !store->bad() && store->open("maindoc.xml")) {
        dom.setContent(store->device());
        store->close();
    }
    return dom;
}

/// Copies the zip at \p from to \p to with maindoc.xml changed by \p editMaindoc and the files in \p extra added.
bool rewriteKra(const QString &from,
                const QString &to,
                std::function<void(QDomDocument &)> editMaindoc,
                const QMap<QString, QByteArray> &extra = {},
                const QStringList &drop = {})
{
    QuaZip in(from);
    if (!in.open(QuaZip::mdUnzip)) return false;
    QuaZip out(to);
    if (!out.open(QuaZip::mdCreate)) return false;

    auto write = [&out](const QString &name, const QByteArray &data) {
        QuaZipFile file(&out);
        // The mimetype entry stays first and uncompressed, as Krita writes it.
        const bool stored = name == QLatin1String("mimetype");
        if (!file.open(QIODevice::WriteOnly, QuaZipNewInfo(name), nullptr, 0, stored ? 0 : Z_DEFLATED,
                       stored ? 0 : Z_DEFAULT_COMPRESSION)) {
            return false;
        }
        file.write(data);
        file.close();
        return file.getZipError() == UNZ_OK;
    };

    for (bool more = in.goToFirstFile(); more; more = in.goToNextFile()) {
        const QString name = in.getCurrentFileName();
        QuaZipFile file(&in);
        if (!file.open(QIODevice::ReadOnly)) return false;
        QByteArray data = file.readAll();
        file.close();
        if (drop.contains(name)) continue;
        if (name == QLatin1String("maindoc.xml")) {
            QDomDocument dom;
            if (!dom.setContent(data)) return false;
            editMaindoc(dom);
            data = dom.toByteArray();
        }
        if (!write(name, data)) return false;
    }
    for (auto it = extra.constBegin(); it != extra.constEnd(); ++it) {
        if (!write(it.key(), it.value())) return false;
    }
    out.close();
    return out.getZipError() == UNZ_OK;
}

QDomElement featuresElementOf(QDomDocument &dom)
{
    return dom.documentElement().firstChildElement("IMAGE").firstChildElement(KisKraFeatures::ElementName);
}

QByteArray layerBytes(KisImageSP image)
{
    KisPaintDeviceSP dev = image->root()->firstChild()->paintDevice();
    QByteArray bytes(imageRect.width() * imageRect.height() * 4, 0);
    dev->readBytes(reinterpret_cast<quint8 *>(bytes.data()), imageRect);
    return bytes;
}

} // namespace

void KisKraFeaturesTest::testRoundTrip()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    FeatureDocument source;
    const QList<KisFeatureSP> saved = source.image->featureList()->features();
    QCOMPARE(saved.size(), 3);
    QVERIFY(saved[1]->properties().hasMeanColor);

    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    // For opening the file in another Krita (stock Krita's compatibility check): a copy where the variable says.
    const QString keep = QString::fromLocal8Bit(qgetenv("KIS_FEATURES_TEST_KEEP_KRA"));
    if (!keep.isEmpty()) {
        QFile::remove(keep);
        QVERIFY(QFile::copy(path, keep));
    }

    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY2(loaded->loadNativeFormat(path), qPrintable(loaded->errorMessage()));
    loaded->image()->waitForDone();
    QVERIFY2(loaded->warningMessage().isEmpty(), qPrintable(loaded->warningMessage()));

    const QList<KisFeatureSP> features = loaded->image()->featureList()->features();
    QCOMPARE(features.size(), saved.size());
    for (int i = 0; i < saved.size(); i++) {
        const KisFeatureSP a = saved[i];
        const KisFeatureSP b = features[i];
        QCOMPARE(b->id(), a->id());
        QCOMPARE(b->name(), a->name());
        QCOMPARE(b->kind(), a->kind());
        QCOMPARE(b->author(), a->author());
        QCOMPARE(b->state(), a->state());
        QCOMPARE(b->isProtected(), a->isProtected());
        QCOMPARE(b->bounds(), a->bounds());
        QCOMPARE(b->area(), a->area());
        QCOMPARE(b->properties().hasMeanColor, a->properties().hasMeanColor);
        QVERIFY(b->meanColor() == a->meanColor());
        QVERIFY(b->properties() == a->properties());
        // Pixel-exact masks, default pixel included.
        QCOMPARE(maskBytes(b->mask()), maskBytes(a->mask()));
        QVERIFY(b->mask()->defaultPixel() == a->mask()->defaultPixel());
        QCOMPARE(b->mask()->selectedExactRect(), a->mask()->selectedExactRect());
        // Measured again on the reopened painting, the properties are the same.
        QVERIFY(KisFeature::measureMask(b->mask(), loaded->image()->projection()) == a->properties());
    }

    QCOMPARE(features[0]->name(), QString("Sky"));
    QCOMPARE(features[0]->author(), KisFeature::Artist);
    QCOMPARE(features[0]->state(), KisFeature::Kept);
    QVERIFY(features[0]->isProtected());
    QCOMPARE(features[1]->name(), QString("Moon"));
    QCOMPARE(features[1]->author(), KisFeature::Agent);
    QCOMPARE(features[1]->state(), KisFeature::Proposed);
    QCOMPARE(features[2]->name(), QString("Tower 3"));
    QCOMPARE(features[2]->area(), qint64(20 * 120 + 15 * 80));
    QCOMPARE(features[2]->bounds(), QRect(50, 80, 55, 120));

    // The masks take the reopened image's bounds; the index answers on the loaded list.
    QCOMPARE(features[0]->mask()->defaultBounds()->bounds(), loaded->image()->bounds());
    QCOMPARE(loaded->image()->featureList()->featuresWithBoundsContaining(QPoint(60, 90)).size(), 2);

    // The painting itself is untouched.
    QCOMPARE(layerBytes(loaded->image()), layerBytes(source.image));
}

void KisKraFeaturesTest::testMaindocXmlLayout()
{
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());

    QDomDocument dom = readMaindoc(path);
    const QDomElement image = dom.documentElement().firstChildElement("IMAGE");
    QVERIFY(!image.isNull());
    // Stock Krita reads the layers from <IMAGE>'s first child: the features never come first.
    QCOMPARE(image.firstChildElement().tagName(), QString("layers"));

    const QDomElement features = image.firstChildElement("features");
    QVERIFY(!features.isNull());
    QCOMPARE(features.attribute("version"), QString("1"));
    QCOMPARE(features.elementsByTagName("feature").size(), 3);

    const QDomElement sky = features.firstChildElement("feature");
    QCOMPARE(sky.attribute("name"), QString("Sky"));
    QCOMPARE(sky.attribute("kind"), QString("sky"));
    QCOMPARE(sky.attribute("author"), QString("artist"));
    QCOMPARE(sky.attribute("state"), QString("kept"));
    QCOMPARE(sky.attribute("protected"), QString("true"));
    QCOMPARE(sky.attribute("area"), QString::number(300 * 100));
    QCOMPARE(sky.firstChildElement("bounds").attribute("width"), QString("300"));
    QVERIFY(!sky.firstChildElement("meanColor").isNull());

    // One mask file and its default pixel per feature, inside the image's folder of the zip.
    QScopedPointer<KoStore> store(KoStore::createStore(path, KoStore::Read));
    for (QDomElement f = features.firstChildElement("feature"); !f.isNull(); f = f.nextSiblingElement("feature")) {
        const QString location = image.attribute("name") + "/features/" + f.attribute("mask");
        QVERIFY2(store->hasFile(location), qPrintable(location));
        QVERIFY2(store->hasFile(location + ".defaultpixel"), qPrintable(location));
    }
}

void KisKraFeaturesTest::testNoFeaturesWritesNothing()
{
    QTemporaryDir dir;
    FeatureDocument source(false);
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    QDomDocument dom = readMaindoc(path);
    QVERIFY(!dom.documentElement().isNull());
    QVERIFY(featuresElementOf(dom).isNull());

    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY2(loaded->loadNativeFormat(path), qPrintable(loaded->errorMessage()));
    QVERIFY(loaded->image()->featureList()->isEmpty());
}

namespace {
KisDocument *loadKra(const QString &path)
{
    KisDocument *loaded = KisPart::instance()->createDocument();
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    if (!loaded->loadNativeFormat(path)) {
        qWarning() << "loading failed:" << loaded->errorMessage() << path;
    }
    if (loaded->image()) {
        loaded->image()->waitForDone();
    }
    return loaded;
}

QStringList featureNames(KisImageSP image)
{
    QStringList names;
    Q_FOREACH (KisFeatureSP f, image->featureList()->features()) {
        names << f->name();
    }
    return names;
}
} // namespace

void KisKraFeaturesTest::testNewerVersionLoadsWhatItKnows()
{
    // A later Krita may add attributes and elements; this one reads what it knows and ignores the rest.
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    const QString newer = dir.filePath("newer.kra");
    QVERIFY(rewriteKra(path, newer, [](QDomDocument &dom) {
        QDomElement features = featuresElementOf(dom);
        features.setAttribute("version", "2");
        features.setAttribute("index", "quadtree");
        features.insertBefore(dom.createElement("groups"), features.firstChild());
        for (QDomElement e = features.firstChildElement("feature"); !e.isNull(); e = e.nextSiblingElement("feature")) {
            e.setAttribute("confidence", "0.9");
            QDomElement outline = dom.createElement("outline");
            outline.setAttribute("points", "0,0 1,1");
            e.appendChild(outline);
        }
    }));

    QScopedPointer<KisDocument> loaded(loadKra(newer));
    QVERIFY(loaded->image());
    QCOMPARE(featureNames(loaded->image()), QStringList({"Sky", "Moon", "Tower 3"}));
    KisFeatureSP moon = loaded->image()->featureList()->featureByName("Moon");
    QVERIFY(moon);
    QVERIFY(source.image->featureList()->featureByName("Moon"));
    QCOMPARE(maskBytes(moon->mask()), maskBytes(source.image->featureList()->featureByName("Moon")->mask()));
    QCOMPARE(moon->properties(), source.image->featureList()->featureByName("Moon")->properties());
    QCOMPARE(layerBytes(loaded->image()), layerBytes(source.image));
}

void KisKraFeaturesTest::testUnreadableVersionIsSkipped()
{
    for (const QString &version : {QString("0"), QString("x"), QString()}) {
        QTemporaryDir dir;
        FeatureDocument source;
        const QString path = source.save(dir);
        QVERIFY(!path.isEmpty());
        const QString bad = dir.filePath("bad.kra");
        QVERIFY(rewriteKra(path, bad, [version](QDomDocument &dom) {
            featuresElementOf(dom).setAttribute("version", version);
        }));

        QScopedPointer<KisDocument> loaded(loadKra(bad));
        QVERIFY(loaded->image());
        QVERIFY(loaded->image()->featureList()->isEmpty());
        QVERIFY2(loaded->warningMessage().contains("version"), qPrintable(loaded->warningMessage()));
        QCOMPARE(layerBytes(loaded->image()), layerBytes(source.image));
    }
}

void KisKraFeaturesTest::testLoadMeasuresBoundsAndAreaKeepsMeanColor()
{
    // Bounds and area are measured from the mask on load; the mean colour is the saved one (the painting is not
    // composited yet when features load).
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    const QString edited = dir.filePath("edited.kra");
    const quint8 bgra[4] = {1, 2, 3, 255};
    const QString savedColor = QString::fromLatin1(QByteArray(reinterpret_cast<const char *>(bgra), 4).toBase64());
    QVERIFY(rewriteKra(path, edited, [savedColor](QDomDocument &dom) {
        for (QDomElement e = featuresElementOf(dom).firstChildElement("feature"); !e.isNull();
             e = e.nextSiblingElement("feature")) {
            e.setAttribute("area", "7");
            QDomElement bounds = e.firstChildElement("bounds");
            bounds.setAttribute("x", "1");
            bounds.setAttribute("y", "2");
            bounds.setAttribute("width", "3");
            bounds.setAttribute("height", "4");
            e.firstChildElement("meanColor").setAttribute("data", savedColor);
        }
    }));

    QScopedPointer<KisDocument> loaded(loadKra(edited));
    QVERIFY(loaded->image());
    QCOMPARE(featureNames(loaded->image()), QStringList({"Sky", "Moon", "Tower 3"}));
    Q_FOREACH (KisFeatureSP f, loaded->image()->featureList()->features()) {
        KisFeatureSP original = source.image->featureList()->featureByName(f->name());
        QVERIFY(original);
        QCOMPARE(f->bounds(), original->bounds());
        QCOMPARE(f->area(), original->area());
        QVERIFY(f->properties().hasMeanColor);
        QCOMPARE(QByteArray(reinterpret_cast<const char *>(f->meanColor().data()), 4),
                 QByteArray(reinterpret_cast<const char *>(bgra), 4));
    }
    // The spatial index uses the measured bounds.
    QCOMPARE(loaded->image()->featureList()->featuresWithBoundsContaining(QPoint(230, 30)).size(), 2);
}

void KisKraFeaturesTest::testDuplicateNamesAreRenamedOnLoad()
{
    // Names are unique in a document; a file with two features of one name (written by hand, or by another tool)
    // keeps both, the later one renamed, with a warning.
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    const QString edited = dir.filePath("duplicates.kra");
    QVERIFY(rewriteKra(path, edited, [](QDomDocument &dom) {
        for (QDomElement e = featuresElementOf(dom).firstChildElement("feature"); !e.isNull();
             e = e.nextSiblingElement("feature")) {
            e.setAttribute("name", "Sky");
        }
    }));

    QScopedPointer<KisDocument> loaded(loadKra(edited));
    QVERIFY(loaded->image());
    QCOMPARE(featureNames(loaded->image()), QStringList({"Sky", "Sky (2)", "Sky (3)"}));
    QVERIFY2(loaded->warningMessage().contains("Sky (2)"), qPrintable(loaded->warningMessage()));
    // Each kept its own mask.
    KisFeatureSP second = loaded->image()->featureList()->featureByName("Sky (2)");
    QVERIFY(second);
    QCOMPARE(second->bounds(), QRect(220, 20, 30, 30));
}

void KisKraFeaturesTest::testMissingMaskIsSkipped()
{
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    const QString moonMask = "features/features/feature-"
        + source.image->featureList()->featureByName("Moon")->id().toString(QUuid::WithoutBraces);
    const QString broken = dir.filePath("broken.kra");
    QVERIFY(rewriteKra(path, broken, [](QDomDocument &) {}, {}, {moonMask}));

    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY(loaded->loadNativeFormat(broken));
    QStringList names;
    Q_FOREACH (KisFeatureSP f, loaded->image()->featureList()->features()) {
        names << f->name();
    }
    QCOMPARE(names, QStringList({"Sky", "Tower 3"}));
    QVERIFY(loaded->warningMessage().contains("Moon"));
}

void KisKraFeaturesTest::testUnknownElementAndFilesAreIgnored()
{
    // What stock Krita sees in our file: an <IMAGE> child it has no branch for, and files it never opens. The loops of
    // KisKraLoader::loadXML() that skip such an element, and KraConverter's loading by file name, are upstream code
    // this fork does not change; here they meet an element and files this build does not know either.
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    const QString foreign = dir.filePath("foreign.kra");
    QVERIFY(rewriteKra(path, foreign, [](QDomDocument &dom) {
        QDomElement features = featuresElementOf(dom);
        features.setTagName("features-of-a-later-krita");
        QDomElement more = dom.createElement("unknown-thing");
        more.setAttribute("version", "7");
        more.appendChild(dom.createElement("child"));
        dom.documentElement().firstChildElement("IMAGE").appendChild(more);
    }, {{"features/unknown/data.bin", QByteArray(1000, 'x')}, {"unknown-top-level.json", QByteArray("{}")}}));

    QScopedPointer<KisDocument> loaded(KisPart::instance()->createDocument());
    loaded->setFileBatchMode(true); // never a dialog in a test
    // A temporary home has no mime database to recognise .kra by: say what it is.
    loaded->setMimeType(KisDocument::nativeFormatMimeType());
    QVERIFY(loaded->loadNativeFormat(foreign));
    loaded->image()->waitForDone();
    QVERIFY2(loaded->errorMessage().isEmpty(), qPrintable(loaded->errorMessage()));
    QVERIFY2(loaded->warningMessage().isEmpty(), qPrintable(loaded->warningMessage()));
    QVERIFY(loaded->image()->featureList()->isEmpty());
    QCOMPARE(loaded->image()->root()->childCount(), 1u);
    QCOMPARE(layerBytes(loaded->image()), layerBytes(source.image));
}

void KisKraFeaturesTest::testBlankAndPaddedNamesOnLoad()
{
    // The rules addFeature applies: outer spaces go, and a name of nothing but spaces becomes "Feature".
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    const QString edited = dir.filePath("names.kra");
    QVERIFY(rewriteKra(path, edited, [](QDomDocument &dom) {
        for (QDomElement e = featuresElementOf(dom).firstChildElement("feature"); !e.isNull();
             e = e.nextSiblingElement("feature")) {
            if (e.attribute("name") == "Sky") e.setAttribute("name", "   ");
            if (e.attribute("name") == "Moon") e.setAttribute("name", " Moon  ");
        }
    }));

    QScopedPointer<KisDocument> loaded(loadKra(edited));
    QVERIFY(loaded->image());
    QCOMPARE(featureNames(loaded->image()), QStringList({"Feature", "Moon", "Tower 3"}));
    QVERIFY2(loaded->warningMessage().contains("Feature"), qPrintable(loaded->warningMessage()));
}

void KisKraFeaturesTest::testSelectedDefaultPixelIsBoundedOnLoad()
{
    // A mask whose default pixel is selected (an inverted selection, kept by a tool that skipped addFeature) loads
    // as the document's part of it, with an unselected default.
    QTemporaryDir dir;
    FeatureDocument source(false);
    KisPixelSelectionSP inverted = new KisPixelSelection();
    inverted->select(QRect(0, 0, 300, 100));
    inverted->invert();
    QVERIFY(inverted->defaultPixel().data()[0] != 0);
    KisFeatureSP ground = new KisFeature("Ground", "ground", inverted);
    // Inserted first: in the list, the mask's default bounds are the image's, so measuring it ends.
    QVERIFY(source.image->featureList()->insertFeature(ground));
    ground->measure(source.image->projection());
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());

    QScopedPointer<KisDocument> loaded(loadKra(path));
    QVERIFY(loaded->image());
    KisFeatureSP feature = loaded->image()->featureList()->featureByName("Ground");
    QVERIFY(feature);
    QCOMPARE(int(feature->mask()->defaultPixel().data()[0]), 0);
    QCOMPARE(maskBytes(feature->mask()), maskBytes(inverted));
    QCOMPARE(feature->bounds(), QRect(0, 100, 300, 100));
    QCOMPARE(feature->area(), qint64(300 * 100));
}

void KisKraFeaturesTest::testResavingANewerVersionWarns()
{
    // Saving writes version 1 and drops what a later version added: the save says so in the log.
    QTemporaryDir dir;
    FeatureDocument source;
    const QString path = source.save(dir);
    QVERIFY(!path.isEmpty());
    const QString newer = dir.filePath("newer.kra");
    QVERIFY(rewriteKra(path, newer, [](QDomDocument &dom) {
        featuresElementOf(dom).setAttribute("version", "2");
    }));
    QScopedPointer<KisDocument> loaded(loadKra(newer));
    QVERIFY(loaded->image());
    QCOMPARE(loaded->image()->featureList()->sourceVersion(), 2);

    QTest::ignoreMessage(QtWarningMsg, QRegularExpression("features.*version 2.*version 1"));
    QVERIFY(loaded->exportDocumentSync(dir.filePath("resaved.kra"), loaded->nativeFormatMimeType()));

    // A file of this version saves without a word.
    QScopedPointer<KisDocument> current(loadKra(path));
    QVERIFY(current->image());
    QCOMPARE(current->image()->featureList()->sourceVersion(), 1);
    QVERIFY(current->exportDocumentSync(dir.filePath("resaved-current.kra"), current->nativeFormatMimeType()));
}

KISTEST_TEMPORARY_HOME_MAIN(KisKraFeaturesTest)
