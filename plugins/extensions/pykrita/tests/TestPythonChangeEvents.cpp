/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonChangeEvents.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>

#include <Notifier.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColorSpaceRegistry.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_paint_layer.h>

namespace {

void settle(KisImageSP image)
{
    image->waitForDone();
    for (int i = 0; i < 5; i++) {
        QCoreApplication::sendPostedEvents();
        QCoreApplication::processEvents();
    }
}

/// Runs \p code in the test's Python globals; returns str(result), or the Python error.
QString runPython(const QString &code)
{
    PyObject *main = PyImport_AddModule("__main__");
    PyObject *globals = PyModule_GetDict(main);
    PyObject *value = PyRun_String(code.toUtf8().constData(), Py_file_input, globals, globals);
    if (!value) {
        PyObject *type, *error, *traceback;
        PyErr_Fetch(&type, &error, &traceback);
        PyObject *text = error ? PyObject_Str(error) : nullptr;
        const QString message = QString("python error: %1").arg(text ? QString::fromUtf8(PyUnicode_AsUTF8(text)) : "?");
        Py_XDECREF(text);
        Py_XDECREF(type);
        Py_XDECREF(error);
        Py_XDECREF(traceback);
        return message;
    }
    Py_DECREF(value);
    PyObject *result = PyDict_GetItemString(globals, "result");
    if (!result) return QString();
    PyObject *text = PyObject_Str(result);
    const QString out = QString::fromUtf8(PyUnicode_AsUTF8(text));
    Py_DECREF(text);
    return out;
}

/// A document with a paint layer, added to KisPart with a notification.
struct PlainDocument {
    QScopedPointer<KisDocument> kisdoc {KisPart::instance()->createDocument()};
    KisImageSP image;

    PlainDocument()
    {
        image = new KisImage(0, 64, 64, KoColorSpaceRegistry::instance()->rgb8(), "test");
        image->addNode(new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data());
        settle(image);
    }

    ~PlainDocument()
    {
        if (kisdoc) KisPart::instance()->removeDocument(kisdoc.data(), false);
    }
};

} // namespace

void TestPythonChangeEvents::initTestCase()
{
    // The built module, imported as PyKrita.krita from a package in the temporary home.
    const QString root = QDir::homePath() + "/python";
    QVERIFY(QDir().mkpath(root + "/PyKrita"));
    QFile init(root + "/PyKrita/__init__.py");
    QVERIFY(init.open(QIODevice::WriteOnly));
    init.close();
    QVERIFY2(QFile::copy(PYKRITA_TEST_MODULE, root + "/PyKrita/krita.so"), PYKRITA_TEST_MODULE);
    qputenv("PYTHONPATH", QFile::encodeName(root + ":" + PYKRITA_TEST_PYQT_DIR));
    qputenv("PYTHONDONTWRITEBYTECODE", "1");
    Py_Initialize();
    QCOMPARE(runPython("from PyQt6 import sip\nfrom PyKrita import krita\nresult = 'ok'"), QString("ok"));
}

void TestPythonChangeEvents::cleanupTestCase()
{
    // The interpreter stays: finalizing it with PyQt's wrappers of live Qt objects is not worth the risk in a test.
}

void TestPythonChangeEvents::testKeptNodeReferencesAreSafe()
{
    PlainDocument d;
    Notifier notifier;
    QString out = runPython(QString(
        "notifier = sip.wrapinstance(%1, krita.Notifier)\n"
        "kept = []\n"
        "seen = []\n"
        "def removed(document, node):\n"
        "    kept.append((document, node))\n"
        "    seen.append(node.name())\n"
        "notifier.nodeRemoved.connect(removed)\n"
        "result = 'connected'").arg(quintptr(&notifier)));
    QCOMPARE(out, QString("connected"));

    QList<KisNodeSP> layers;
    for (int i = 0; i < 20; i++) {
        KisNodeSP layer = new KisPaintLayer(d.image, QString("layer %1").arg(i), OPACITY_OPAQUE_U8);
        d.image->addNode(layer);
        layers << layer;
    }
    settle(d.image);
    for (const KisNodeSP &layer : layers) {
        d.image->removeNode(layer);
        settle(d.image);
    }
    layers.clear();
    settle(d.image);

    // During the slot each object was valid.
    out = runPython("result = ','.join(seen)");
    QStringList expected;
    for (int i = 0; i < 20; i++) expected << QString("layer %1").arg(i);
    QCOMPARE(out, expected.join(","));

    // Afterwards, every kept object either still works or raises; it never crashes or reads freed memory.
    out = runPython(
        "def probe(obj, read):\n"
        "    try:\n"
        "        return read(obj)\n"
        "    except RuntimeError:\n"
        "        return 'deleted'\n"
        "names = [probe(node, lambda n: n.name()) for document, node in kept]\n"
        "widths = [probe(document, lambda doc: str(doc.width())) for document, node in kept]\n"
        "ok = all(name in ('deleted', 'layer %d' % i) for i, name in enumerate(names))\n"
        "ok = ok and all(width in ('deleted', '64') for width in widths)\n"
        "result = 'safe' if ok and len(names) == 20 else 'unsafe: %r %r' % (names, widths)");
    QCOMPARE(out, QString("safe"));
    qInfo("kept node objects afterwards: %s", qPrintable(runPython("result = names")));
    runPython("notifier.nodeRemoved.disconnect(removed)\nkept.clear()\nresult = None");
}

void TestPythonChangeEvents::testNodesCompareAcrossEvents()
{
    PlainDocument d;
    Notifier notifier;
    QString out = runPython(QString(
        "notifier = sip.wrapinstance(%1, krita.Notifier)\n"
        "added = []\n"
        "removed = []\n"
        "def on_added(document, node):\n"
        "    added.append(node.uniqueId().toString())\n"
        "def on_removed(document, node):\n"
        "    removed.append(node.uniqueId().toString())\n"
        "notifier.nodeAdded.connect(on_added)\n"
        "notifier.nodeRemoved.connect(on_removed)\n"
        "result = 'connected'").arg(quintptr(&notifier)));
    QCOMPARE(out, QString("connected"));

    KisNodeSP layer = new KisPaintLayer(d.image, "same", OPACITY_OPAQUE_U8);
    d.image->addNode(layer);
    settle(d.image);
    d.image->removeNode(layer);
    settle(d.image);

    out = runPython("result = 'same' if added == removed and len(added) == 1 else 'differs: %r %r' % (added, removed)");
    QCOMPARE(out, QString("same"));
    runPython("notifier.nodeAdded.disconnect(on_added)\nnotifier.nodeRemoved.disconnect(on_removed)\nresult = None");
}

void TestPythonChangeEvents::testKeptDocumentReferenceAfterClose()
{
    QScopedPointer<PlainDocument> d(new PlainDocument);
    Notifier notifier;
    QString out = runPython(QString(
        "notifier = sip.wrapinstance(%1, krita.Notifier)\n"
        "documents = []\n"
        "def on_added(document, node):\n"
        "    documents.append(document)\n"
        "notifier.nodeAdded.connect(on_added)\n"
        "result = 'connected'").arg(quintptr(&notifier)));
    QCOMPARE(out, QString("connected"));
    d->image->addNode(new KisPaintLayer(d->image, "x", OPACITY_OPAQUE_U8));
    settle(d->image);
    KisImageSP image = d->image;
    d.reset(); // closes the document
    image.clear();
    for (int i = 0; i < 5; i++) {
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        QCoreApplication::processEvents();
    }
    out = runPython(
        "def probe(document):\n"
        "    try:\n"
        "        return str(document.width())\n"
        "    except RuntimeError:\n"
        "        return 'deleted'\n"
        "values = [probe(document) for document in documents]\n"
        "result = 'safe' if len(values) == 1 and values[0] in ('deleted', '0', '64') else 'unsafe: %r' % values");
    QCOMPARE(out, QString("safe"));
    runPython("notifier.nodeAdded.disconnect(on_added)\ndocuments.clear()\nresult = None");
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonChangeEvents)
