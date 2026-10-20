/*
 * SPDX-FileCopyrightText: 2025 Krita Developers
 * SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Ported from Krita-Revamp (10zindraws / Tenzin Rangdol, GPL-3.0), commits b908ad5 and 681ef9f.
 */
#include "KisPaintOpPresetSessionStorage.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QFileInfo>
#include <QDomDocument>
#include <QGlobalStatic>
#include <QHash>
#include <QThread>
#include <QTimer>

#include <KConfigGroup>
#include <KSharedConfig>

#include <KisAppIdentity.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>
#include <kis_debug.h>
#include <kis_properties_configuration.h>

#include "KisAgentHooks.h"

namespace {
/// How long after the last change the file is written (a drag changes the preset many times a second).
const int kSyncDelayMs = 400;
}

struct KisPaintOpPresetSessionStorage::Private
{
    explicit Private(const QString &name)
        : config(KSharedConfig::openConfig(name, KConfig::SimpleConfig))
    {
    }

    KSharedConfigPtr config;
    QHash<int, QString> scriptChanged; ///< resource id -> the settings XML before a script first changed the preset
    int scriptSelectionDepth = 0;
    QTimer syncTimer;
};

Q_GLOBAL_STATIC(KisPaintOpPresetSessionStorage, s_instance)

QString KisPaintOpPresetSessionStorage::defaultConfigFileName()
{
    return KisAppIdentity::configFileName(QStringLiteral("presetTweaksrc"));
}

KisPaintOpPresetSessionStorage::KisPaintOpPresetSessionStorage(const QString &configFileName)
    : m_d(new Private(configFileName))
{
    m_d->syncTimer.setSingleShot(true);
    m_d->syncTimer.setInterval(kSyncDelayMs);
    connect(&m_d->syncTimer, &QTimer::timeout, this, [this] () { m_d->config->sync(); });
    if (QCoreApplication::instance()) {
        connect(QCoreApplication::instance(), &QCoreApplication::aboutToQuit, this, [this] () { sync(); });
    }
}

KisPaintOpPresetSessionStorage::~KisPaintOpPresetSessionStorage()
{
    m_d->config->sync();
}

KisPaintOpPresetSessionStorage *KisPaintOpPresetSessionStorage::instance()
{
    return s_instance;
}

QString KisPaintOpPresetSessionStorage::filePath() const
{
    // The config name is "<identity folder>/presetTweaksrc" (or plain for stock): the file is in the identity's config folder
    return KisAppIdentity::configLocation() + QLatin1Char('/') + QFileInfo(m_d->config->name()).fileName();
}

QString KisPaintOpPresetSessionStorage::tweakKey(KisPaintOpPresetSP preset) const
{
    if (!preset || preset->resourceId() < 0) {
        return QString();
    }

    // Use resource ID and MD5 to create a unique key
    // The MD5 helps distinguish if the preset was modified on disk
    const QString md5 = preset->md5Sum(false);
    if (md5.isEmpty()) {
        // Fallback to just resource ID if no MD5
        return QString("Preset_%1").arg(preset->resourceId());
    }
    return QString("Preset_%1_%2").arg(preset->resourceId()).arg(md5);
}

bool KisPaintOpPresetSessionStorage::saveTweaks(KisPaintOpPresetSP preset)
{
    if (!preset || !preset->settings() || preset->resourceId() < 0) {
        return false;
    }

    // Krita Agent: only the artist's own changes are tweaks.
    if (KisAgentHooks::agentWorkOpen()) {
        return false;
    }
    if (m_d->scriptChanged.contains(preset->resourceId())) {
        // A script changed it. If the settings are back as they were (restore_brush), they are the artist's again.
        if (preset->settings()->toXML() != m_d->scriptChanged.value(preset->resourceId())) {
            return false;
        }
        m_d->scriptChanged.remove(preset->resourceId());
        qInfo() << "Krita Agent: brush preset" << preset->name() << "is back as it was before a script changed it; your tweaks to it are saved again";
    }

    const QString key = tweakKey(preset);
    if (key.isEmpty()) {
        return false;
    }

    // Serialize the preset settings to XML
    QDomDocument doc;
    QDomElement root = doc.createElement("PresetTweaks");
    doc.appendChild(root);

    preset->settings()->toXML(doc, root);

    // Transient state that is not a tweak: the eraser switch and the blending mode follow the tool, not the brush.
    for (QDomElement e = root.firstChildElement("param"); !e.isNull();) {
        const QDomElement next = e.nextSiblingElement("param");
        const QString name = e.attribute("name");
        if (name == QLatin1String("EraserMode") || name == QLatin1String("CompositeOp")) {
            root.removeChild(e);
        }
        e = next;
    }

    const QString settingsXml = doc.toString();

    KConfigGroup group = m_d->config->group(key);
    group.writeEntry("settings", settingsXml);
    group.writeEntry("name", preset->name());
    group.writeEntry("timestamp", QDateTime::currentDateTime().toString(Qt::ISODate));

    scheduleSync();

    dbgResources << "Saved tweaks for preset:" << preset->name() << "key:" << key;

    Q_EMIT sigTweaksSaved(preset->name());
    return true;
}

bool KisPaintOpPresetSessionStorage::loadTweaks(KisPaintOpPresetSP preset)
{
    if (!preset || !preset->settings() || preset->resourceId() < 0) {
        return false;
    }

    // Krita Agent: never while an agent works or a script selects the preset (it must get the preset as saved), and
    // never over newer state in memory (a preset changed since it was read: the memory wins).
    if (KisAgentHooks::agentWorkOpen() || m_d->scriptSelectionDepth > 0 || preset->isDirty()) {
        return false;
    }

    const QString key = tweakKey(preset);
    if (key.isEmpty()) {
        return false;
    }

    if (!m_d->config->hasGroup(key)) {
        return false;
    }

    KConfigGroup group = m_d->config->group(key);
    const QString settingsXml = group.readEntry("settings", QString());

    if (settingsXml.isEmpty()) {
        return false;
    }

    // Parse the XML and apply settings
    QDomDocument doc;
    if (!doc.setContent(settingsXml)) {
        warnKrita << "Failed to parse saved preset tweaks for:" << preset->name();
        return false;
    }

    const QDomElement root = doc.documentElement();
    if (root.isNull()) {
        return false;
    }

    // Apply the saved settings to the preset. Krita Agent: through setProperty(), one by one, not
    // settings()->fromXML(root): fromXML writes the properties without telling the settings, which keep serving the
    // brush they cached (the old size, tip and spacing) and never announce the change to the brush editor.
    KisPropertiesConfiguration tweaks;
    tweaks.fromXML(root);
    {
        KisPaintOpPreset::UpdatedPostponer postponer(preset);
        const QMap<QString, QVariant> properties = tweaks.getProperties();
        for (auto it = properties.constBegin(); it != properties.constEnd(); ++it) {
            preset->settings()->setProperty(it.key(), it.value());
        }
    }
    preset->setDirty(true);
    // The stored tweaks replaced the settings: a script's leftovers are gone.
    m_d->scriptChanged.remove(preset->resourceId());

    dbgResources << "Loaded tweaks for preset:" << preset->name() << "key:" << key;
    return true;
}

bool KisPaintOpPresetSessionStorage::hasTweaks(KisPaintOpPresetSP preset) const
{
    if (!preset || preset->resourceId() < 0) {
        return false;
    }

    const QString key = tweakKey(preset);
    if (key.isEmpty()) {
        return false;
    }

    return m_d->config->hasGroup(key);
}

void KisPaintOpPresetSessionStorage::clearTweaks(KisPaintOpPresetSP preset)
{
    if (!preset || preset->resourceId() < 0) {
        return;
    }

    m_d->scriptChanged.remove(preset->resourceId());

    // Every tweak of this resource, whatever MD5 it was keyed with: saving a preset changes its MD5, and the tweaks
    // of the old file must not stay behind.
    const QString exact = QString("Preset_%1").arg(preset->resourceId());
    const QString prefix = exact + QLatin1Char('_');
    bool removed = false;
    Q_FOREACH (const QString &group, m_d->config->groupList()) {
        if (group == exact || group.startsWith(prefix)) {
            m_d->config->deleteGroup(group);
            removed = true;
        }
    }

    if (removed) {
        m_d->syncTimer.stop();
        m_d->config->sync();
        dbgResources << "Cleared tweaks for preset:" << preset->name();
        Q_EMIT sigTweaksCleared(preset->name());
    }
}

void KisPaintOpPresetSessionStorage::markScriptChanged(KisPaintOpPresetSP preset)
{
    if (!preset || !preset->settings() || preset->resourceId() < 0 || m_d->scriptChanged.contains(preset->resourceId())) {
        return;
    }
    // Called before the script's change: the settings as they are now are what a restore brings back.
    m_d->scriptChanged.insert(preset->resourceId(), preset->settings()->toXML());
    qInfo() << "Krita Agent: brush preset" << preset->name()
            << "is being changed by a script; its changes are not saved as your tweaks until it is restored, reloaded or saved";
}

void KisPaintOpPresetSessionStorage::beginScriptSelection()
{
    m_d->scriptSelectionDepth++;
}

void KisPaintOpPresetSessionStorage::endScriptSelection()
{
    if (m_d->scriptSelectionDepth > 0) m_d->scriptSelectionDepth--;
}

bool KisPaintOpPresetSessionStorage::isScriptChanged(KisPaintOpPresetSP preset) const
{
    return preset && m_d->scriptChanged.contains(preset->resourceId());
}

void KisPaintOpPresetSessionStorage::scheduleSync()
{
    if (QCoreApplication::instance() && QThread::currentThread() == QCoreApplication::instance()->thread()) {
        m_d->syncTimer.start();
    } else {
        m_d->config->sync();
    }
}

void KisPaintOpPresetSessionStorage::sync()
{
    m_d->syncTimer.stop();
    m_d->config->sync();
}
