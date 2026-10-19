/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonAgentMove.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>

#include <Document.h>

#include <KisDocument.h>
#include <KisPart.h>
#include <KoColorSpaceRegistry.h>
#include <kis_image.h>
#include <kis_paint_layer.h>

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

/// A document with a paint layer, registered with KisPart, and its libkis wrapper as `doc` in Python.
struct PythonDocument {
    QScopedPointer<KisDocument> kisdoc {KisPart::instance()->createDocument()};
    KisImageSP image;
    QScopedPointer<Document> doc;

    PythonDocument()
    {
        image = new KisImage(0, 64, 64, KoColorSpaceRegistry::instance()->rgb8(), "test");
        image->addNode(new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data(), false);
        doc.reset(new Document(kisdoc.data(), false));
        runPython(QString("doc = sip.wrapinstance(%1, krita.Document)\nresult = None").arg(quintptr(doc.data())));
    }

    ~PythonDocument()
    {
        runPython("doc = None\nresult = None");
        doc.reset();
        image->waitForDone();
        QCoreApplication::processEvents();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }
};

} // namespace

void TestPythonAgentMove::initTestCase()
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
    // As the krita package's __init__.py does.
    QCOMPARE(runPython("from PyQt6 import sip\n"
                       "from PyKrita import krita\n"
                       "import agentmove\n"
                       "agentmove.install(krita.Document)\n"
                       "result = 'ok'"),
             QString("ok"));
}

void TestPythonAgentMove::testClosesAtTheEndOfTheBlock()
{
    PythonDocument d;
    QCOMPARE(runPython("with doc.agentMove('sky'):\n"
                       "    inside = doc.agentMoveOpen(), doc.agentMoveName()\n"
                       "result = (inside, doc.agentMoveOpen())"),
             QString("((True, 'sky'), False)"));
}

void TestPythonAgentMove::testClosesOnAnException()
{
    PythonDocument d;
    QCOMPARE(runPython("try:\n"
                       "    with doc.agentMove('broken'):\n"
                       "        raise ValueError('a script error')\n"
                       "except ValueError as error:\n"
                       "    caught = str(error)\n"
                       "result = (caught, doc.agentMoveOpen())"),
             QString("('a script error', False)"));
    // The document takes a new move afterwards.
    QVERIFY(d.doc->beginAgentMove("next"));
    QVERIFY(d.doc->endAgentMove());
}

void TestPythonAgentMove::testRefusedBeginRaises()
{
    PythonDocument d;
    QVERIFY(d.doc->beginAgentMove("open"));
    QCOMPARE(runPython("try:\n"
                       "    with doc.agentMove('second'):\n"
                       "        ran = True\n"
                       "except RuntimeError:\n"
                       "    ran = 'refused'\n"
                       "result = (ran, doc.agentMoveName())"),
             QString("('refused', 'open')"));
    QVERIFY(d.doc->endAgentMove());
}

void TestPythonAgentMove::testOldBlockLeavesNewMove()
{
    PythonDocument d;
    QCOMPARE(runPython("block = doc.agentMove('old')\n"
                       "block.__enter__()\n"
                       "result = doc.agentMoveName()"),
             QString("old"));
    // The old move closes by itself (the artist presses Undo), and the script begins a new one.
    d.kisdoc->undoStack()->undo();
    QVERIFY(d.doc->beginAgentMove("new"));
    // The old block ends: it leaves the new move open, and says so.
    QCOMPARE(runPython("import warnings\n"
                       "with warnings.catch_warnings(record=True) as caught:\n"
                       "    warnings.simplefilter('always')\n"
                       "    block.__exit__(None, None, None)\n"
                       "result = (doc.agentMoveName(), len(caught))"),
             QString("('new', 1)"));
    QVERIFY(d.doc->endAgentMove());
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonAgentMove)
