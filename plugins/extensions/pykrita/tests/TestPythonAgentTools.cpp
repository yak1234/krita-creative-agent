/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonAgentTools.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>

#include <Document.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColor.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_layer_utils.h>
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

/// An undoable document with a white background and a "paint" layer holding a black box outline, as `doc` in Python.
struct PythonDocument {
    QScopedPointer<KisDocument> kisdoc {KisPart::instance()->createDocument()};
    KisImageSP image;
    KisPaintLayerSP paint;
    QScopedPointer<Document> doc;

    PythonDocument()
    {
        const KoColorSpace *cs = KoColorSpaceRegistry::instance()->rgb8();
        image = new KisImage(kisdoc->createUndoStore(), 120, 100, cs, "tools");
        KisPaintLayerSP background = new KisPaintLayer(image, "background", OPACITY_OPAQUE_U8);
        background->paintDevice()->fill(image->bounds(), KoColor(Qt::white, cs));
        image->addNode(background);
        paint = new KisPaintLayer(image, "paint", OPACITY_OPAQUE_U8);
        const KoColor black(Qt::black, cs);
        paint->paintDevice()->fill(QRect(20, 20, 60, 2), black);
        paint->paintDevice()->fill(QRect(20, 68, 60, 2), black);
        paint->paintDevice()->fill(QRect(20, 20, 2, 50), black);
        paint->paintDevice()->fill(QRect(78, 20, 2, 50), black);
        image->addNode(paint);
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data(), false);
        doc.reset(new Document(kisdoc.data(), false));
        settle();
        runPython(QString("doc = sip.wrapinstance(%1, krita.Document)\nresult = None").arg(quintptr(doc.data())));
    }

    ~PythonDocument()
    {
        runPython("doc = None\nnode = None\narea = None\nresult = None");
        doc.reset();
        image->waitForDone();
        QCoreApplication::processEvents();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }

    void settle()
    {
        for (int i = 0; i < 3; i++) {
            KisLayerUtils::forceAllDelayedNodesUpdate(image->root());
            image->waitForDone();
            QCoreApplication::processEvents();
        }
    }

    QByteArray bytes() const
    {
        QByteArray data(image->width() * image->height() * 4, 0);
        paint->paintDevice()->readBytes(reinterpret_cast<quint8 *>(data.data()), image->bounds());
        return data;
    }
};

} // namespace

void TestPythonAgentTools::initTestCase()
{
    // The built module as PyKrita.krita, and the krita package's agentmove.py beside it, in the temporary home.
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
                       "from PyQt6.QtCore import QPointF\n"
                       "from PyQt6.QtGui import QColor\n"
                       "from PyKrita import krita\n"
                       "import agentmove\n"
                       "agentmove.install(krita.Document)\n"
                       "result = 'ok'"),
             QString("ok"));
}

void TestPythonAgentTools::testToolsFromPython()
{
    PythonDocument d;
    const QByteArray before = d.bytes();
    const int undoBefore = d.kisdoc->undoStack()->count();

    // A fill alone: it stops at the box, and waits until its pixels are there (BGRA bytes).
    QCOMPARE(runPython("node = doc.nodeByName('paint')\n"
                       "def px(x, y):\n"
                       "    return tuple(bytes(node.pixelData(x, y, 1, 1)))\n"
                       "filled = node.fill(50, 45, QColor(255, 0, 0), {'threshold': 10, 'name': 'py fill'})\n"
                       "result = (filled, px(50, 45), px(5, 5))"),
             QString("(True, (0, 0, 255, 255), (0, 0, 0, 0))"));
    d.settle();
    QCOMPARE(d.kisdoc->undoStack()->count(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(undoBefore), QString("py fill"));
    d.kisdoc->undoStack()->undo();
    d.settle();
    QVERIFY(d.bytes() == before);

    // Every tool in one agent move, with options as a dict and a selection.
    QCOMPARE(runPython("area = krita.Selection()\n"
                       "area.select(60, 80, 12, 12, 255)\n"
                       "with doc.agentMove('py tools'):\n"
                       "    a = node.fill(50, 45, QColor('red'))\n"
                       "    b = node.gradient(QPointF(0, 0), QPointF(119, 0),\n"
                       "                      {'colors': [QColor(0, 255, 0), QColor(0, 0, 255)], 'shape': 'linear'}, area)\n"
                       "    c = node.smartPatch(area, {'accuracy': 40, 'patchRadius': 3})\n"
                       "    e = node.encloseAndFill(area, QColor('white'), {'regions': 'all'})\n"
                       "    f = node.move(4, 2)\n"
                       "result = (a, b, c, e, f, (node.position().x(), node.position().y()))"),
             QString("(True, True, True, True, True, (4, 2))"));
    d.settle();
    QCOMPARE(d.kisdoc->undoStack()->count(), undoBefore + 1);
    QCOMPARE(d.doc->undoText(undoBefore), QString("Agent: py tools"));
    QVERIFY(d.bytes() != before);

    // Refusals return False and change nothing.
    QCOMPARE(runPython("result = (node.fill(50, 45, QColor('red'), {'bogus': 1}),\n"
                       "          node.gradient(QPointF(0, 0), QPointF(9, 0), {'colors': [QColor('red')]}),\n"
                       "          node.smartPatch(krita.Selection()))"),
             QString("(False, False, False)"));
    d.settle();
    QCOMPARE(d.kisdoc->undoStack()->count(), undoBefore + 1);

    // One undo restores the layer and its position.
    d.kisdoc->undoStack()->undo();
    d.settle();
    QCOMPARE(QPoint(d.paint->x(), d.paint->y()), QPoint(0, 0));
    QVERIFY(d.bytes() == before);
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonAgentTools)
