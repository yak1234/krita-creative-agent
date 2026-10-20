/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonStrokeJobs.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QFile>
#include <QScopedPointer>
#include <QSemaphore>
#include <QSharedPointer>

#include <Document.h>

#include <KisDocument.h>
#include <KisGlobalResourcesInterface.h>
#include <KisPart.h>
#include <KisResourceTypes.h>
#include <KoColorSpaceRegistry.h>
#include <KoResource.h>
#include <kis_image.h>
#include <kis_paint_layer.h>
#include <kundo2stack.h>
#include <kis_simple_stroke_strategy.h>

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

/// Holds an image's stroke queue (Krita busy with other work) until released or the end of the scope.
class Gate
{
    class Stroke : public KisSimpleStrokeStrategy
    {
    public:
        explicit Stroke(QSharedPointer<QSemaphore> open)
            : KisSimpleStrokeStrategy(QLatin1String("test-gate"))
            , m_open(open)
        {
            enableJob(JOB_INIT, true, KisStrokeJobData::BARRIER, KisStrokeJobData::EXCLUSIVE);
        }
        void initStrokeCallback() override
        {
            m_open->tryAcquire(1, 30000);
        }

    private:
        QSharedPointer<QSemaphore> m_open;
    };

public:
    explicit Gate(KisImageSP image)
        : m_open(new QSemaphore())
    {
        KisStrokeId id = image->startStroke(new Stroke(m_open));
        image->endStroke(id);
    }
    ~Gate()
    {
        release();
    }
    void release()
    {
        if (!m_released) m_open->release();
        m_released = true;
    }

private:
    QSharedPointer<QSemaphore> m_open;
    bool m_released = false;
};

/// A document with a paint layer "base", registered with KisPart, as `doc` and `layer` in Python.
struct PythonDocument {
    QScopedPointer<KisDocument> kisdoc {KisPart::instance()->createDocument()};
    KisImageSP image;
    QScopedPointer<Document> doc;

    PythonDocument()
    {
        image = new KisImage(0, 200, 100, KoColorSpaceRegistry::instance()->rgb8(), "test");
        image->addNode(new KisPaintLayer(image, "base", OPACITY_OPAQUE_U8));
        kisdoc->setCurrentImage(image);
        KisPart::instance()->addDocument(kisdoc.data(), false);
        image->waitForDone();
        kisdoc->undoStack()->clear();
        doc.reset(new Document(kisdoc.data(), false));
        runPython(QString("doc = sip.wrapinstance(%1, krita.Document)\n"
                          "layer = doc.nodeByName('base')\n"
                          "result = None").arg(quintptr(doc.data())));
    }

    ~PythonDocument()
    {
        runPython("job = None\njobs = None\nlayer = None\ndoc = None\nresult = None");
        doc.reset();
        image->waitForDone();
        QCoreApplication::processEvents();
        KisPart::instance()->removeDocument(kisdoc.data(), false);
    }
};

} // namespace

void TestPythonStrokeJobs::initTestCase()
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
                       "from PyQt6.QtCore import QCoreApplication\n"
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
                       "def column(layer, x, h=100):\n"
                       "    data = bytes(layer.pixelData(x, 0, 1, h))\n"
                       "    return sum(1 for a in data[3::4] if a > 32)\n"
                       "result = 'ok'"),
             QString("ok"));
    const QString preset = pressurePreset();
    QVERIFY2(!preset.isEmpty(), "Krita's preset b) Basic-5 Size is in the resource database");
    QCOMPARE(runPython(QString("preset = %1\nresult = 'ok'").arg("'" + preset + "'")), QString("ok"));
}

void TestPythonStrokeJobs::testPaintsAPressureStrokeFromPython()
{
    PythonDocument d;
    // The plugin's paint_pass form: a start, cubic segments, per-point pressure; dicts and lists from Python.
    QCOMPARE(runPython("stroke = {'start': [20, 50], 'segments': [[40, 50, 80, 50, 100, 50], [120, 50, 160, 50, 180, 50]],\n"
                       "          'pressure': [0.1, 1.0, 0.1], 'size': 40, 'color': '#203040', 'opacity': 1.0}\n"
                       "job = layer.paintStrokes([stroke], {'preset': preset, 'name': 'taper'})\n"
                       "first = job.state()\n"
                       "final = settle(job)\n"
                       "ends, middle = column(layer, 24), column(layer, 100)\n"
                       "result = (first in ('queued', 'running'), final, job.strokesDone(), job.strokesTotal(),\n"
                       "          0 < ends * 3 < middle, middle >= 30)"),
             QString("(True, 'done', 1, 1, True, True)"));
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("taper"));
}

void TestPythonStrokeJobs::testPollsStatusAndCancels()
{
    PythonDocument d;
    Gate gate(d.image); // the job waits behind other work: cancelled before it starts, deterministically
    QCOMPARE(runPython("strokes = [{'points': [[10 + 9 * i, 10], [10 + 9 * i, 90]], 'size': 6} for i in range(20)]\n"
                       "ended = []\n"
                       "job = layer.paintStrokes(strokes, {'preset': preset})\n"
                       "job.finished.connect(ended.append)\n"
                       "status = job.status()\n"
                       "result = (sorted(status.keys()), status['state'], status['done'], status['total'], job.cancel())"),
             QString("(['cancelReason', 'done', 'error', 'ms', 'name', 'progress', 'rect', 'state', 'total'], 'queued', 0, 20, True)"));
    gate.release();
    QCOMPARE(runPython("final = settle(job)\n"
                       "result = (final, job.strokesDone(), ended, job.status()['done'], job.cancel(), column(layer, 10))"),
             QString("('cancelled', 0, ['cancelled'], 0, False, 0)"));
}

void TestPythonStrokeJobs::testCancelReasonsFromPython()
{
    {
        PythonDocument d;
        // "" while not cancelled and when done; "script" for cancel(); the first reason stays.
        Gate gate(d.image);
        QCOMPARE(runPython("strokes = [{'points': [[10 + 9 * i, 10], [10 + 9 * i, 90]], 'size': 6} for i in range(20)]\n"
                           "job = layer.paintStrokes(strokes, {'preset': preset})\n"
                           "before = job.cancelReason()\n"
                           "job.cancel()\n"
                           "result = (before, job.cancelReason(), job.status()['cancelReason'])"),
                 QString("('', 'script', 'script')"));
        gate.release();
        QCOMPARE(runPython("final = settle(job)\nresult = (final, job.cancelReason())"), QString("('cancelled', 'script')"));
        QCOMPARE(runPython("job = layer.paintStrokes(strokes[:2], {'preset': preset})\n"
                           "final = settle(job)\n"
                           "result = (final, job.cancelReason(), job.cancel(), job.cancelReason())"),
                 QString("('done', '', False, '')"));
    }
    {
        // The artist's undo during the job.
        PythonDocument d;
        Gate gate(d.image);
        QCOMPARE(runPython("job = layer.paintStrokes([{'points': [[10 + 9 * (i % 20), 10], [10 + 9 * (i % 20), 90]], 'size': 6}\n"
                           "                          for i in range(100)], {'preset': preset, 'name': 'long'})\n"
                           "result = job.cancelReason()"),
                 QString(""));
        d.kisdoc->undoStack()->undo();
        gate.release();
        QCOMPARE(runPython("final = settle(job)\nresult = (final, job.cancelReason())"), QString("('cancelled', 'undo')"));
    }
    {
        // The document closing: the job (a Python object) outlives it.
        QScopedPointer<PythonDocument> d(new PythonDocument());
        Gate gate(d->image);
        QCOMPARE(runPython("job = layer.paintStrokes([{'points': [[10 + 9 * (i % 20), 10], [10 + 9 * (i % 20), 90]], 'size': 6}\n"
                           "                          for i in range(100)], {'preset': preset})\n"
                           "layer = None\n"
                           "result = job.cancelReason()"),
                 QString(""));
        d->image->notifyAboutToBeDeleted(); // what closing a document does first
        gate.release();
        QCOMPARE(runPython("final = settle(job)\nresult = (final, job.cancelReason())"), QString("('cancelled', 'document_closed')"));
    }
}

void TestPythonStrokeJobs::testDroppingTheJobKeepsPainting()
{
    PythonDocument d;
    QCOMPARE(runPython("job = layer.paintStrokes([{'points': [[10 + 9 * (i % 20) + (k % 2) * 3, (k * 7) % 90 + 5] for k in range(60)],\n"
                       "                           'size': 4} for i in range(200)], {'preset': preset})\n"
                       "while job.strokesDone() < 1:\n"
                       "    QCoreApplication.processEvents()\n"
                       "running = job.state()\n"
                       "job = None\n"
                       "result = running"),
             QString("running"));
    // The strokes all paint, and land as the job's one step.
    QTRY_COMPARE_WITH_TIMEOUT(d.kisdoc->undoStack()->count(), 1, 30000);
    d.image->waitForDone();
    QCOMPARE(runPython("result = all(column(layer, 10 + 9 * i) > 50 for i in range(20))"), QString("True"));
}

void TestPythonStrokeJobs::testWaitFromAnotherPythonThread()
{
    PythonDocument d;
    QCOMPARE(runPython("import threading\n"
                       "job = layer.paintStrokes([{'points': [[5, 2 + i], [195, 2 + i]], 'size': 3} for i in range(90)],\n"
                       "                         {'preset': preset})\n"
                       "out = []\n"
                       "waiter = threading.Thread(target=lambda: out.append(job.wait(20000)))\n"
                       "waiter.start()\n"
                       "while waiter.is_alive():\n"
                       "    QCoreApplication.processEvents()\n"
                       "    waiter.join(0.005)\n"
                       "result = (out, job.state(), job.strokesDone())"),
             QString("([True], 'done', 90)"));
}

void TestPythonStrokeJobs::testAgentMoveJobsAreOneStep()
{
    PythonDocument d;
    QCOMPARE(runPython("rows = lambda n, top: [{'points': [[5, top + i % 20], [195, top + i % 20]], 'size': 2} for i in range(n)]\n"
                       "with doc.agentMove('sky'):\n"
                       "    jobs = [layer.paintStrokes(rows(200, 10 + 20 * p), {'preset': preset}) for p in range(4)]\n"
                       "states = [settle(job) for job in jobs]\n"
                       "result = (states, [job.name() for job in jobs][0], sum(job.strokesDone() for job in jobs))"),
             QString("(['done', 'done', 'done', 'done'], 'Agent: sky', 800)"));
    d.image->waitForDone();
    QTRY_COMPARE(d.kisdoc->undoStack()->count(), 1);
    QCOMPARE(d.kisdoc->undoStack()->text(0), QString("Agent: sky"));
}

void TestPythonStrokeJobs::testRefusedJobIsFailedNotAnException()
{
    PythonDocument d;
    QCOMPARE(runPython("job = layer.paintStrokes([{'points': [[1, 2]]}], {'preset': 'no such preset'})\n"
                       "result = (job.state(), 'no brush preset' in job.errorString(), job.wait(0))"),
             QString("('failed', True, True)"));
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonStrokeJobs)
