/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// The feature builders from Python (krita-fork 6.3): Document.maskContiguous(), maskSimilarColor(), maskSnapOutline(),
// maskSegments() and maskFromSelection() through the built krita module, with Python lists, dicts, QPointF and QColor.

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonFeatureBuilders.h"

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

void TestPythonFeatureBuilders::initTestCase()
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

void TestPythonFeatureBuilders::testBuildersFromPython()
{
    // Blue, with red on the left half and a red island on the right.
    QScopedPointer<KisDocument> kisdoc(KisPart::instance()->createDocument());
    kisdoc->setFileBatchMode(true); // never a dialog in a test
    KisImageSP image = new KisImage(kisdoc->createUndoStore(), 64, 48, KoColorSpaceRegistry::instance()->rgb8(), "test");
    KisNodeSP layer = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
    const KoColorSpace *cs = layer->colorSpace();
    layer->paintDevice()->fill(image->bounds(), KoColor(QColor(40, 40, 200), cs));
    layer->paintDevice()->fill(QRect(0, 0, 32, 48), KoColor(QColor(200, 40, 40), cs));
    layer->paintDevice()->fill(QRect(48, 20, 8, 8), KoColor(QColor(200, 40, 40), cs));
    image->addNode(layer);
    kisdoc->setCurrentImage(image);
    image->refreshGraphAsync();
    settle(image);
    QScopedPointer<Document> doc(new Document(kisdoc.data(), false));
    const int steps = kisdoc->undoStack()->count();

    const QString out = runPython(QString(
        "from PyQt6.QtCore import QPointF\n"
        "from PyQt6.QtGui import QColor\n"
        "doc = sip.wrapinstance(%1, krita.Document)\n"
        "def area(sel):\n"
        "    return sum(1 for b in bytes(sel.pixelData(0, 0, 64, 48)) if b >= 128)\n"
        "left = doc.maskContiguous([QPointF(2, 2)], {'threshold': 10})\n"
        "reds = doc.maskSimilarColor([QColor(200, 40, 40)])\n"
        "fromPoint = doc.maskSimilarColor([], {'points': [QPointF(50, 22)]})\n"
        "box = krita.Selection()\n"
        "box.select(0, 0, 16, 48, 255)\n"
        "inBox = doc.maskContiguous([QPointF(2, 2)], {'within': box, 'antiAlias': False})\n"
        "outline = doc.maskSnapOutline([QPointF(0, 0), QPointF(32, 0), QPointF(32, 48), QPointF(0, 48)], {'searchRadius': 8})\n"
        "hintLeft = krita.Selection()\n"
        "hintLeft.select(4, 20, 6, 6, 255)\n"
        "hintRight = krita.Selection()\n"
        "hintRight.select(40, 4, 6, 6, 255)\n"
        "regions = doc.maskSegments([hintLeft, hintRight], {'rect': [0, 0, 64, 48], 'edgeSize': 2.0})\n"
        "box.select(0, 0, 64, 48, 255)\n"
        "doc.setSelection(box)\n"
        "whole = doc.maskFromSelection()\n"
        "bad = doc.maskContiguous([QPointF(2, 2)], {'treshold': 3})\n"
        "noTime = doc.maskContiguous([QPointF(2, 2)], {'timeoutMs': 0})\n"
        "tooMany = doc.maskContiguous([QPointF(2, 2)] * 300)\n"
        "feature = doc.addFeature('Left', 'wall', doc.maskContiguous([QPointF(2, 2)]))\n"
        "parts = [type(left).__name__, str(area(left)), str(area(reds)), str(area(fromPoint)), str(area(inBox)),\n"
        "         str(abs(area(outline) - 32 * 48) <= 2 * 48), str(len(regions)), str(sum(area(r) for r in regions)),\n"
        "         str(area(whole)), str(bad is None), feature.name(), str(feature.area()), str(noTime is None), str(tooMany is None)]\n"
        "result = '|'.join(parts)").arg(quintptr(doc.data())));

    QCOMPARE(out, QString("Selection|1536|1600|1600|768|True|2|3072|3072|True|Left|1536|True|True"));
    // Only the selection and the feature are undo steps: the builders add none.
    QCOMPARE(kisdoc->undoStack()->count(), steps + 2);
    runPython("del doc, left, reds, fromPoint, box, inBox, outline, hintLeft, hintRight, regions, whole, feature\nresult = None");
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonFeatureBuilders)
