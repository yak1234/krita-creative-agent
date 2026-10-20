/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonTraps.h"

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
#include <kis_stroke_strategy_undo_command_based.h>
#include <processing/KisToolFunctions.h>
#include <QElapsedTimer>
#include <QSignalSpy>

#define EXPECT_RUN(code, expected) \
    do { \
        const QString got_ = runPython(code); \
        QVERIFY2(got_ == (expected), qPrintable(QString("got: ") + got_)); \
    } while (0)

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
        paint->paintDevice()->fill(image->bounds(), KoColor(Qt::red, cs));
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

void TestPythonTraps::initTestCase()
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
    EXPECT_RUN("from PyQt6 import sip\n"
                       "from PyQt6.QtCore import QPointF, QRectF\n"
                       "from PyQt6.QtGui import QColor\n"
                       "from PyKrita import krita\n"
                       "import agentmove\n"
                       "agentmove.install(krita.Document)\n"
                       "result = 'ok'", QString("ok"));
}


void TestPythonTraps::testNoViewRefusesPainting()
{
    // No main window exists in this test: painting calls refuse instead of crashing.
    PythonDocument d;
    const QByteArray before = d.bytes();
    const int undoBefore = d.kisdoc->undoStack()->count();
    EXPECT_RUN("node = doc.nodeByName('paint')\n"
                       "node.paintLine(QPointF(5, 5), QPointF(60, 5), 1.0, 1.0)\n"
                       "node.paintRectangle(QRectF(5, 10, 30, 20))\n"
                       "node.paintEllipse(QRectF(5, 10, 30, 20))\n"
                       "result = node.paintAbility()", QString("UNPAINTABLE"));
    d.settle();
    QVERIFY(d.bytes() == before);
    QCOMPARE(d.kisdoc->undoStack()->count(), undoBefore);
}

void TestPythonTraps::testUndoableCallsFromPython()
{
    PythonDocument d;
    const QByteArray before = d.bytes();
    const int undoBefore = d.kisdoc->undoStack()->count();

    // Filter.apply: one undo step, within the selection; and the setters.
    EXPECT_RUN("node = doc.nodeByName('paint')\n"
                       "sel = krita.Selection()\n"
                       "sel.select(10, 10, 30, 30, 255)\n"
                       "doc.setSelection(sel)\n"
                       "f = krita.Filter()\n"
                       "f.setName('invert')\n"
                       "ok = f.apply(node, 0, 0, 120, 100)\n"
                       "inside = tuple(bytes(node.pixelData(20, 20, 1, 1)))\n"
                       "outside = tuple(bytes(node.pixelData(80, 80, 1, 1)))\n"
                       "result = (ok, inside, outside)", QString("(True, (255, 255, 0, 255), (0, 0, 255, 255))"));
    d.settle();
    // the selection is a step of its own; the filter is another
    QCOMPARE(d.kisdoc->undoStack()->count(), undoBefore + 2);
    d.kisdoc->undoStack()->undo();
    d.settle();
    EXPECT_RUN("result = tuple(bytes(node.pixelData(20, 20, 1, 1)))", QString("(0, 0, 255, 255)"));

    // setOpacity and setPixelData are undoable, and in an agent move are one step.
    const int before2 = d.doc->undoIndex(); // the undone filter step is replaced
    EXPECT_RUN("with doc.agentMove('py traps'):\n"
                       "    node.setOpacity(50)\n"
                       "    node.setPixelData(bytes([1, 2, 3, 255] * 16), 0, 0, 4, 4)\n"
                       "result = node.opacity()", QString("50"));
    d.settle();
    QVERIFY2(d.doc->undoIndex() == before2 + 1 && d.kisdoc->undoStack()->count() == before2 + 1, qPrintable(QString::number(d.kisdoc->undoStack()->count()) + " vs " + QString::number(before2 + 1)));
    QCOMPARE(d.doc->undoText(before2), QString("Agent: py traps"));
    d.kisdoc->undoStack()->undo();
    d.settle();
    EXPECT_RUN("result = (node.opacity(), tuple(bytes(node.pixelData(0, 0, 1, 1))))", QString("(255, (0, 0, 255, 255))"));
    Q_UNUSED(before);
}

void TestPythonTraps::testSelectionContractAndResizeFromPython()
{
    PythonDocument d;
    EXPECT_RUN("s = krita.Selection()\n"
                       "s.select(10, 10, 40, 30, 255)\n"
                       "s.contract(10)\n"
                       "a = (s.x(), s.y(), s.width(), s.height())\n"
                       "s.resize(10, 5)\n"
                       "b = (s.x(), s.y(), s.width(), s.height())\n"
                       "result = (a, b, tuple(bytes(s.pixelData(40, 12, 1, 1))))", QString("((10, 10, 30, 20), (10, 10, 10, 5), (0,))"));
}

void TestPythonTraps::testCallsReturnWhileTheArtistHoldsTheStroke()
{
    PythonDocument d;
    // The pen lifts however the test ends (a document with an open stroke never settles).
    struct Pen {
        KisImageSP image;
        KisStrokeId id;
        int limit = KisToolFunctions::waitLimit();
        ~Pen()
        {
            if (id) image->endStroke(id);
            KisToolFunctions::setWaitLimit(limit);
        }
    } pen;
    pen.image = d.image;
    KisToolFunctions::setWaitLimit(300);
    pen.id = d.image->startStroke(new KisStrokeStrategyUndoCommandBased(kundo2_noi18n("held"), false, d.image.data()));
    QVERIFY(pen.id);
    QSignalSpy endRequests(d.image.data(), SIGNAL(sigStrokeEndRequested()));
    QVERIFY(endRequests.isValid());
    QElapsedTimer timer;
    timer.start();
    EXPECT_RUN("f = krita.Filter()\n"
               "f.setName('invert')\n"
               "node = doc.nodeByName('paint')\n"
               "a = f.apply(node, 0, 0, 10, 10)\n"
               "node.setOpacity(10)\n"
               "node.setName('x')\n"
               "b = node.setPixelData(bytes([1, 2, 3, 255] * 16), 0, 0, 4, 4)\n"
               "result = (a, b)",
               QString("(False, False)"));
    QVERIFY2(timer.elapsed() < 10000, qPrintable(QString::number(timer.elapsed())));
    QVERIFY2(endRequests.count() == 0, qPrintable(QString::number(endRequests.count())));
    d.image->endStroke(pen.id);
    pen.id = KisStrokeId();
    d.settle();
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonTraps)
