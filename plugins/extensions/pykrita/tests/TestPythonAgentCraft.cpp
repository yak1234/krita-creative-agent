/*
 *  SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */

// Python first: Qt's "slots" macro must not be defined when Python.h declares PyType_Spec::slots.
#include <Python.h>

#include "TestPythonAgentCraft.h"

#include <simpletest.h>
#include <testui.h>
#include <KisTemporaryHomeUiTest.h>

#include <QDir>
#include <QDomDocument>
#include <QFile>

#include <KisPart.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>
#include <KisResourceModel.h>
#include <KisResourceTypes.h>

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

/// The XML of a pixel-brush preset from the resource database (one of Krita's own, with a brush tip).
QString defaultPixelBrushXml()
{
    KisPaintOpPresetSP preset;
    KisResourceModel model(ResourceType::PaintOpPresets);
    for (int row = 0; row < model.rowCount() && !preset; row++) {
        KisPaintOpPresetSP candidate = model.resourceForIndex(model.index(row, 0)).dynamicCast<KisPaintOpPreset>();
        if (candidate && candidate->paintOp().id() == "paintbrush"
            && candidate->settings()->hasProperty("brush_definition")) {
            preset = candidate;
        }
    }
    if (!preset) return QString();
    QDomDocument doc;
    QDomElement root = doc.createElement("Preset");
    preset->toXML(doc, root);
    doc.appendChild(root);
    return doc.toString();
}

} // namespace

void TestPythonAgentCraft::initTestCase()
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
    QCOMPARE(runPython("from PyQt6 import sip\n"
                       "from PyQt6.QtCore import QRect\n"
                       "from PyQt6.QtGui import QImage, QColor\n"
                       "from PyKrita import krita\n"
                       "app = krita.Krita.instance()\n"
                       "result = 'ok'"),
             QString("ok"));
}

void TestPythonAgentCraft::testBrushTipAndPreset()
{
    const QString xml = defaultPixelBrushXml();
    QVERIFY(!xml.isEmpty());
    QFile xmlFile(QDir::homePath() + "/base-preset.xml");
    QVERIFY(xmlFile.open(QIODevice::WriteOnly));
    xmlFile.write(xml.toUtf8());
    xmlFile.close();

    const QString out = runPython(QString(
        "image = QImage(16, 12, QImage.Format.Format_ARGB32)\n"
        "image.fill(QColor(0, 0, 0, 200))\n"
        "tip = app.createBrushTip(image, 'py tip')\n"
        "stamp = app.createBrushTip(image, 'py stamp', 'image')\n"
        "bad = app.createBrushTip(image, 'py bad', 'sparkle')\n"
        "base = open(%1).read()\n"
        "preset = app.createPreset(base, tip, 'py preset')\n"
        "again = app.createPreset(preset, stamp, 'py preset 2')\n"
        "listed = 'py preset 2' in app.resources('preset')\n"
        "result = '%s %s %s %s %s %s %s' % (tip.type(), tip.name(), stamp.type(), bad, preset.type(),\n"
        "                                 again.name(), listed)\n")
                                      .arg(QString("'%1'").arg(xmlFile.fileName())));
    QCOMPARE(out, QString("brush py tip brush None preset py preset 2 True"));
    xmlFile.remove();
}

void TestPythonAgentCraft::testMergeGroupsAndBake()
{
    const QString out = runPython(
        "doc = app.createDocument(64, 48, 'py craft', 'RGBA', 'U8', '', 72.0)\n"
        "root = doc.rootNode()\n"
        "groups = []\n"
        "for name, x in (('g1', 4), ('g2', 30)):\n"
        "    group = doc.createGroupLayer(name)\n"
        "    root.addChildNode(group, None)\n"
        "    layer = doc.createNode(name + ' paint', 'paintlayer')\n"
        "    group.addChildNode(layer, None)\n"
        "    layer.setPixelData(bytes([0, 0, 255, 255]) * (20 * 20), x, 10, 20, 20)\n"
        "    groups.append(group)\n"
        "doc.waitForDone()\n"
        "merged = doc.mergeGroups(groups)\n"
        "names = [n.name() for n in root.childNodes()]\n"
        "blur = app.filter('blur')\n"
        "mask = doc.createFilterMask('blur', blur, merged)\n"
        "merged.addChildNode(mask, None)\n"
        "doc.waitForDone()\n"
        "baked = mask.bake()\n"
        "left = len(merged.childNodes())\n"
        "area = app.createBrushTip(doc, QRect(0, 0, 32, 32), 'py area tip')\n"
        "empty = doc.mergeGroups([])\n"
        "result = '%s %d %s %d %s %s' % (merged.type(), len(names), baked, left, area.type(), empty)\n"
        "doc.close()\n");
    QCOMPARE(out, QString("paintlayer 2 True 0 brush None")); // the new document's background and the merged layer
}

KISTEST_TEMPORARY_HOME_MAIN(TestPythonAgentCraft)
