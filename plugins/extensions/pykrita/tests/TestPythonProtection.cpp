/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonProtection.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>

#include <Document.h>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <KoResource.h>
#include <kis_image.h>
#include <kis_paint_device.h>
#include <kis_paint_layer.h>
#include <kundo2stack.h>

namespace {

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

/// The database name of Krita's preset "b) Basic-5 Size" (the bundle's files use underscores), or empty.
QString pressurePreset()
{
    for (const QString &name : {QString("b) Basic-5 Size"), QString("b)_Basic-5_Size")}) {
        KoResourceSP found = KisGlobalResourcesInterface::instance()->source(ResourceType::PaintOpPresets)
                                 .bestMatch(QString(), QString(), name);
        if (found && found->valid()) return name;
    }
    return QString();
}

/// A document of 300x200 with a paint layer "base" holding grey where two "buildings" stand, registered with KisPart, as
/// `doc` and `layer` in Python.
struct PythonDocument {
    QScopedPointer<KisDocument> kisdoc {KisPart::instance()->createDocument()};
    KisImageSP image;
    QScopedPointer<Document> doc;

    PythonDocument()
    {
        kisdoc->setFileBatchMode(true);
        image = new KisImage(kisdoc->createUndoStore(), 300, 200, KoColorSpaceRegistry::instance()->rgb8(), "test");
        KisPaintLayerSP base = new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8);
        base->paintDevice()->fill(QRect(20, 60, 40, 120), KoColor(Qt::gray, base->paintDevice()->colorSpace()));
        base->paintDevice()->fill(QRect(150, 60, 50, 120), KoColor(Qt::gray, base->paintDevice()->colorSpace()));
        image->addNode(base);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data(), false);
        image->waitForDone();
        kisdoc->undoStack()->clear();
        doc.reset(new Document(kisdoc.data(), false));
        runPython(QString("doc = sip.wrapinstance(%1, krita.Document)\n"
                          "layer = doc.nodeByName('base')\n"
                          "def rect(name, x, y, w, h, protect=False):\n"
                          "    sel = krita.Selection()\n"
                          "    sel.select(x, y, w, h, 255)\n"
                          "    return doc.addFeature(name, 'building', sel, 'artist', 'kept', protect)\n"
                          "def inside(x, y, w, h):\n"
                          "    return bytes(layer.pixelData(x, y, w, h))\n"
                          "result = None").arg(quintptr(doc.data())));
    }

    ~PythonDocument()
    {
        runPython("job = None\nlayer = None\nsel = None\nfeatures = None\ndoc = None\nresult = None");
        doc.reset();
        image->waitForDone();
        QCoreApplication::processEvents();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }
};

} // namespace

void TestPythonProtection::initTestCase()
{
    const QString root = QDir::homePath() + "/python";
    QVERIFY(QDir().mkpath(root + "/PyKrita"));
    QFile init(root + "/PyKrita/__init__.py");
    QVERIFY(init.open(QIODevice::WriteOnly));
    init.close();
    QVERIFY2(QFile::copy(PYKRITA_TEST_MODULE, root + "/PyKrita/krita.so"), PYKRITA_TEST_MODULE);
    QVERIFY2(QFile::copy(PYKRITA_TEST_AGENTMOVE, root + "/agentmove.py"), PYKRITA_TEST_AGENTMOVE);
    qputenv("PYTHONPATH", QFile::encodeName(root + ":" + PYKRITA_TEST_PYQT_DIR));
    qputenv("PYTHONDONTWRITEBYTECODE", "1");
    Py_Initialize();
    QCOMPARE(runPython("from PyQt6 import sip\n"
                       "from PyQt6.QtCore import QCoreApplication, QRect\n"
                       "from PyKrita import krita\n"
                       "import agentmove\n"
                       "agentmove.install(krita.Document)\n"
                       "def settle(job, ms=20000):\n"
                       "    waited = 0\n"
                       "    while not job.wait(10) and waited < ms:\n"
                       "        QCoreApplication.processEvents()\n"
                       "        waited += 10\n"
                       "    QCoreApplication.processEvents()\n"
                       "    return job.state()\n"
                       "result = 'ok'"),
             QString("ok"));
    const QString preset = pressurePreset();
    QVERIFY2(!preset.isEmpty(), "Krita's preset b) Basic-5 Size is in the resource database");
    QCOMPARE(runPython(QString("preset = %1\nresult = 'ok'").arg("'" + preset + "'")), QString("ok"));
}

void TestPythonProtection::testQueriesFromPython()
{
    PythonDocument d;
    QCOMPARE(runPython("rect('Sky', 0, 0, 300, 100)\n"
                       "rect('Moon', 200, 10, 30, 30)\n"
                       "rect('Ground', 0, 100, 300, 100)\n"
                       "rect('Tower (north)', 20, 60, 40, 80)\n"
                       "names = lambda fs: [f.name() for f in fs]\n"
                       "moon = doc.feature('Moon')\n"
                       "box = krita.Selection()\n"
                       "box.select(0, 95, 10, 10, 255)\n"
                       "result = (names(doc.featuresAt(210, 20)), names(doc.featuresAt(-5, 3)),\n"
                       "          names(doc.featuresAt(float('nan'), 3)), names(doc.featuresAt(1e12, 3)),\n"
                       "          names(doc.featuresOverlapping(QRect(0, 95, 10, 10))), names(doc.featuresOverlapping(moon)),\n"
                       "          names(doc.featuresOverlapping(box)), names(doc.featuresTouching('Sky')),\n"
                       "          names(doc.featuresTouching(moon)))"),
             QString("(['Sky', 'Moon'], [], [], [], ['Sky', 'Ground'], ['Sky'], ['Sky', 'Ground'], ['Ground'], [])"));
    QCOMPARE(runPython("s = doc.selection('Sky - Moon')\n"
                       "q = doc.selection('\"Tower (north)\" + Moon')\n"
                       "px = lambda sel, x, y: bytes(sel.pixelData(x, y, 1, 1))[0]\n"
                       "result = (px(s, 5, 5), px(s, 210, 20), px(q, 30, 100), px(q, 210, 20), px(q, 5, 5),\n"
                       "          doc.selection('Sky - Sun'), doc.selection('Sky -'), doc.selection(''), doc.selection('(Sky'),\n"
                       "          doc.selection() is None or doc.selection().width() >= 0)"),
             QString("(255, 0, 255, 255, 0, None, None, None, None, True)"));
}

void TestPythonProtection::testProtectedJobFromPython()
{
    PythonDocument d;
    QVERIFY(!pressurePreset().isEmpty());
    // "Leave the buildings alone": the features, protected from Python, and a pass over the whole canvas.
    QCOMPARE(runPython("rect('Tower A', 20, 60, 40, 120)\n"
                       "b = rect('Tower B', 150, 60, 50, 120)\n"
                       "before_a, before_b = inside(20, 60, 40, 120), inside(150, 60, 50, 120)\n"
                       "flags = [doc.feature('Tower A').isProtected(), b.setProtected(True), b.isProtected(), doc.protectionActive()]\n"
                       "result = flags"),
             QString("[False, True, True, True]"));
    QCOMPARE(runPython("doc.feature('Tower A').setProtected(True)\n"
                       "strokes = [{'points': [[2, 3 * i + 2], [298, 3 * i + 2]], 'size': 4, 'color': '#ff0000'} for i in range(66)]\n"
                       "job = layer.paintStrokes(strokes, {'preset': preset})\n"
                       "final = settle(job)\n"
                       "result = (final, inside(20, 60, 40, 120) == before_a, inside(150, 60, 50, 120) == before_b,\n"
                       "          sorted(job.keptOut()), sorted(job.status()['keptOut']), sorted(doc.lastKeptOut()),\n"
                       "          sorted(doc.agentMoveKeptOut()), any(inside(70, 60, 60, 120)[3::4]))"),
             QString("('done', True, True, ['Tower A', 'Tower B'], ['Tower A', 'Tower B'], ['Tower A', 'Tower B'], ['Tower A', 'Tower B'], True)"));
    // allowProtected, as a dict from Python, is a deliberate edit; a wrong type is a failed job, not an exception.
    QCOMPARE(runPython("job = layer.paintStrokes(strokes, {'preset': preset, 'allowProtected': True})\n"
                       "final = settle(job)\n"
                       "bad = layer.paintStrokes(strokes, {'preset': preset, 'allowProtected': 'yes'})\n"
                       "result = (final, inside(20, 60, 40, 120) == before_a, job.keptOut(), bad.state(), 'allowProtected' in bad.errorString())"),
             QString("('done', False, [], 'failed', True)"));
}

void TestPythonProtection::testProtectedSelectionAndSuspensionFromPython()
{
    PythonDocument d;
    QCOMPARE(runPython("rect('Tower A', 20, 60, 40, 120, True)\n"
                       "p, o = doc.protectedSelection(), doc.protectedSelection(True)\n"
                       "px = lambda sel, x, y: bytes(sel.pixelData(x, y, 1, 1))[0]\n"
                       "p.select(0, 0, 300, 200, 255)\n"
                       "again = doc.protectedSelection()\n"
                       "result = (px(o, 30, 100), px(o, 5, 5), px(again, 30, 100), px(again, 5, 5), doc.protectionActive())"),
             QString("(0, 255, 255, 0, True)"));
    // Suspending is refused outside an agent move (False, not an exception) and allowed inside; the move's end resets it.
    QCOMPARE(runPython("outside = doc.setProtectionSuspended(True)\n"
                       "state_outside = (doc.protectionSuspended(), doc.protectionActive())\n"
                       "doc.beginAgentMove('deliberate')\n"
                       "inside_move = doc.setProtectionSuspended(True)\n"
                       "state_inside = (doc.protectionSuspended(), doc.protectionActive())\n"
                       "doc.endAgentMove()\n"
                       "doc.waitForDone()\n"
                       "QCoreApplication.processEvents()\n"
                       "doc.waitForDone()\n"
                       "result = (outside, state_outside, inside_move, state_inside, doc.protectionSuspended(), doc.protectionActive())"),
             QString("(False, (False, True), True, (True, False), False, True)"));
    // Raw writes in an agent move keep the protected pixels, and name what they were kept out of afterwards.
    QCOMPARE(runPython("import array\n"
                       "before = inside(20, 60, 40, 120)\n"
                       "red = bytes([0, 0, 255, 255]) * (300 * 200)\n"
                       "doc.beginAgentMove('red')\n"
                       "ok = layer.setPixelData(red, 0, 0, 300, 200)\n"
                       "doc.endAgentMove()\n"
                       "doc.waitForDone()\n"
                       "result = (ok, inside(20, 60, 40, 120) == before, inside(100, 60, 10, 10)[:4] == bytes([0, 0, 255, 255]),\n"
                       "          doc.lastKeptOut(), doc.agentMoveKeptOut())"),
             QString("(True, True, True, ['Tower A'], ['Tower A'])"));
    // A transform that would rewrite the protected pixels is refused (False, named), one clear of them is not.
    QCOMPARE(runPython("moved = layer.rotateNode(0.1)\n"
                       "result = (moved, doc.lastKeptOut())"),
             QString("(False, ['Tower A'])"));
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonProtection)
