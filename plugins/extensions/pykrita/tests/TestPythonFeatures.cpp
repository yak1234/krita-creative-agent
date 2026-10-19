/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// The feature map from Python (krita-fork 6.2): Document.addFeature(), features(), feature(), renameFeature(),
// removeFeature() and the Feature class, through the built krita module.

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonFeatures.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>

#include <Document.h>
#include <kundo2stack.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_paint_device.h>
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

} // namespace

void TestPythonFeatures::initTestCase()
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

void TestPythonFeatures::testFeaturesFromPython()
{
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    kisdoc->setFileBatchMode(true); // never a dialog in a test
    KisImageSP image = new KisImage(kisdoc->createUndoStore(), 64, 48, KoColorSpaceRegistry::instance()->rgb8(), "test");
    KisNodeSP layer = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
    layer->paintDevice()->fill(image->bounds(), KoColor(QColor(10, 20, 200), layer->colorSpace()));
    image->addNode(layer);
    image->addNode(new KisPaintLayer(image, "empty", OPACITY_OPAQUE_U8));
    kisdoc->setCurrentImage(image);
    image->refreshGraphAsync();
    settle(image);
    QScopedPointer<Document> doc(new Document(kisdoc.data(), false));
    const int steps = kisdoc->undoStack()->count();

    const QString out = runPython(QString(
        "doc = sip.wrapinstance(%1, krita.Document)\n"
        "sel = krita.Selection()\n"
        "sel.select(0, 0, 64, 20, 255)\n"
        "f = doc.addFeature('Sky', 'sky', sel, 'artist', 'kept', True)\n"
        "proposal = doc.addFeature('Ground', 'ground', sel)\n"
        "parts = [type(f).__name__, f.name(), f.kind(), f.author(), f.state(), str(f.isProtected()),\n"
        "         '%d,%d,%d,%d' % (f.bounds().x(), f.bounds().y(), f.bounds().width(), f.bounds().height()),\n"
        "         str(f.area()), f.meanColor().name(), proposal.author(), proposal.state(),\n"
        "         ','.join(x.name() for x in doc.features()),\n"
        "         str(doc.addFeature('Sky', 'sky', sel) is None), str(doc.feature('Moon') is None),\n"
        "         str(doc.renameFeature('Sky', 'Evening sky')), f.name(), str(doc.feature('Evening sky') == f),\n"
        "         str(bytes(f.mask().pixelData(0, 19, 2, 2))), str(doc.removeFeature('Ground')),\n"
        "         str(proposal.isInDocument()), str(len(doc.features()))]\n"
        "result = '|'.join(parts)").arg(quintptr(doc.data())));

    QCOMPARE(out, QString("Feature|Sky|sky|artist|kept|True|0,0,64,20|1280|#0a14c8|agent|proposed|Sky,Ground|True|True"
                          "|True|Evening sky|True|b'\\xff\\xff\\x00\\x00'|True|False|1"));
    // add, add, rename, remove: one undo step each
    QCOMPARE(kisdoc->undoStack()->count(), steps + 4);
    runPython("del doc, sel, f, proposal\nresult = None");
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonFeatures)
