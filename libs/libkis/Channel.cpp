/*
 *  SPDX-FileCopyrightText: 2016 Boudewijn Rempt <boud@valdyas.org>
 *
 *  SPDX-License-Identifier: LGPL-2.0-or-later
 */
#include "Channel.h"

#include <cstring>

#include <QByteArray>
#include <QDebug>
#include <QDataStream>
#include <QIODevice>

#include <KoColorModelStandardIds.h>
#include <KoConfig.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorSpace.h>
#include <kis_sequential_iterator.h>
#include <kis_layer.h>
#include <kis_image.h>
#include <kis_pixel_selection.h>
#include <KisFeatureList.h>
#include <KisFeatureProtection.h>
#include "DocumentHistory.h"

#ifdef HAVE_OPENEXR
#include <half.h>
#endif

struct Channel::Private {
    Private() {}

    KisNodeSP node;
    KoChannelInfo *channel {0};

};

Channel::Channel(KisNodeSP node, KoChannelInfo *channel, QObject *parent)
    : QObject(parent)
    , d(new Private)
{
    d->node = node;
    d->channel = channel;
}

Channel::~Channel()
{
    delete d;
}


bool Channel::operator==(const Channel &other) const
{
    return (d->node == other.d->node
            && d->channel == other.d->channel);
}

bool Channel::operator!=(const Channel &other) const
{
    return !(operator==(other));
}


bool Channel::visible() const
{
    if (!d->node || !d->channel) return false;
    if (!d->node->inherits("KisLayer")) return false;

    const QList<KoChannelInfo *> channelInfo = d->node->colorSpace()->channels();

    for (int i = 0; i < channelInfo.size(); ++i) {
        if (channelInfo[i] == d->channel) {
            KisLayerSP layer = qobject_cast<KisLayer*>(d->node.data());
            const QBitArray& flags = layer->channelFlags();
            return flags.isEmpty() || flags.testBit(i);
        }
    }

    return false;
}

void Channel::setVisible(bool value)
{
    if (!d->node || !d->channel) return;
    if (!d->node->inherits("KisLayer")) return;

    const QList<KoChannelInfo *> channelInfo = d->node->colorSpace()->channels();

    KisLayerSP layer = qobject_cast<KisLayer*>(d->node.data());
    QBitArray flags = layer->channelFlags();
    if (flags.isEmpty()) {
        flags.fill(1, channelInfo.size());
    }

    for (int i = 0; i < channelInfo.size(); ++i) {
        if (channelInfo[i] == d->channel) {
            flags.setBit(i, value);
            layer->setChannelFlags(flags);
            break;
        }
    }

}

QString Channel::name() const
{
    return d->channel->name();
}

int Channel::position() const
{
    return d->channel->pos();
}

int Channel::channelSize() const
{
    return d->channel->size();
}

QRect Channel::bounds() const
{
    if (!d->node || !d->channel) return QRect();

    QRect rect = d->node->exactBounds();

    KisPaintDeviceSP dev;
    if (d->node->colorSpace()->colorDepthId() == Integer8BitsColorDepthID) {
        dev = new KisPaintDevice(KoColorSpaceRegistry::instance()->alpha8());
    }
    else if (d->node->colorSpace()->colorDepthId() ==  Integer16BitsColorDepthID) {
        dev = new KisPaintDevice(KoColorSpaceRegistry::instance()->alpha16());
    }
#ifdef HAVE_OPENEXR
    else if (d->node->colorSpace()->colorDepthId() == Float16BitsColorDepthID) {
        dev = new KisPaintDevice(KoColorSpaceRegistry::instance()->alpha16f());
    }
#endif
    else if (d->node->colorSpace()->colorDepthId() == Float32BitsColorDepthID) {
        dev = new KisPaintDevice(KoColorSpaceRegistry::instance()->alpha32f());
    }

    KisSequentialConstIterator srcIt(d->node->projection(), rect);
    KisSequentialIterator dstIt(dev, rect);

    while(srcIt.nextPixel() && dstIt.nextPixel()) {
        const quint8 *srcPtr = srcIt.rawDataConst();
        memcpy(dstIt.rawData(), srcPtr + d->channel->pos(), d->channel->size());

    }

    if (dev) {
        return dev->exactBounds();
    }

    return QRect();
}

QByteArray Channel::pixelData(const QRect &rect) const
{
    QByteArray ba;

    if (!d->node || !d->channel) return ba;

    QDataStream stream(&ba, QIODevice::WriteOnly);
    KisSequentialConstIterator srcIt(d->node->projection(), rect);

    if (d->node->colorSpace()->colorDepthId() == Integer8BitsColorDepthID) {
        while(srcIt.nextPixel()) {
            quint8 v;
            memcpy(&v, srcIt.rawDataConst() + d->channel->pos(), sizeof(v));
            stream << v;
        }
    }
    else if (d->node->colorSpace()->colorDepthId() ==  Integer16BitsColorDepthID) {
        while(srcIt.nextPixel()) {
            quint16 v;
            memcpy(&v, srcIt.rawDataConst() + d->channel->pos(), sizeof(v));
            stream << v;
        }
    }
#ifdef HAVE_OPENEXR
    else if (d->node->colorSpace()->colorDepthId() == Float16BitsColorDepthID) {
        while(srcIt.nextPixel()) {
            half v;
            memcpy(&v, srcIt.rawDataConst() + d->channel->pos(), sizeof(v));
            stream << (float) v;
        }
    }
#endif
    else if (d->node->colorSpace()->colorDepthId() == Float32BitsColorDepthID) {
        while(srcIt.nextPixel()) {
            float v;
            memcpy(&v, srcIt.rawDataConst() + d->channel->pos(), sizeof(v));
            stream << v;
        }

    }

    return ba;
}

void Channel::setPixelData(QByteArray value, const QRect &rect)
{
    if (!d->node || !d->channel || d->node->paintDevice() == 0) return;

    // Krita Agent (krita-fork 6.5): while the agent works, pixels inside protected features keep their channel value.
    // The device's bytes in the rectangle are saved first, and the protected pixels' channel bytes are put back when
    // the write is over (row by row: the iterator below walks tile by tile).
    struct Restore {
        KisPaintDeviceSP device;
        QRect rect;
        QByteArray saved, mask;
        int pos = 0, size = 0;
        ~Restore()
        {
            if (mask.isEmpty()) return;
            const int pixel = device->pixelSize();
            QByteArray now(saved.size(), 0);
            device->readBytes(reinterpret_cast<quint8 *>(now.data()), rect);
            for (int i = 0; i < mask.size(); i++) {
                if (mask.at(i) != 0) memcpy(now.data() + i * pixel + pos, saved.constData() + i * pixel + pos, size);
            }
            device->writeBytes(reinterpret_cast<const quint8 *>(now.constData()), rect.x(), rect.y(), rect.width(), rect.height());
        }
    } restore;
    {
        KisNodeSP layerNode = d->node;
        while (layerNode && !qobject_cast<KisLayer *>(layerNode.data())) layerNode = layerNode->parent();
        KisImageSP image;
        if (layerNode) image = KisImageSP(qobject_cast<KisLayer *>(layerNode.data())->image());
        if (DocumentHistory::protectionFor(image)) {
            const QString why = KisFeatureProtection::whyNotCanvasAligned(image, d->node);
            if (!why.isEmpty() || qint64(rect.width()) * rect.height() >= (qint64(1) << 24)) {
                qWarning() << "Channel.setPixelData() refused:" << (why.isEmpty() ? QStringLiteral("the rectangle is too large") : why);
                return;
            }
            if (KisPixelSelectionSP protectedArea = image->featureList()->protectedMask()) {
                KisPaintDeviceSP device = d->node->paintDevice();
                restore.device = device;
                restore.rect = rect;
                restore.pos = d->channel->pos();
                restore.size = d->channel->size();
                restore.saved.resize(int(qint64(rect.width()) * rect.height() * device->pixelSize()));
                device->readBytes(reinterpret_cast<quint8 *>(restore.saved.data()), rect);
                restore.mask.resize(int(qint64(rect.width()) * rect.height()));
                protectedArea->readBytes(reinterpret_cast<quint8 *>(restore.mask.data()), rect);
                image->featureList()->recordKeptOut(KisFeatureProtection::keptOutOf(image, rect));
            }
        }
    }

    QDataStream stream(&value, QIODevice::ReadOnly);
    KisSequentialIterator dstIt(d->node->paintDevice(), rect);

    if (d->node->colorSpace()->colorDepthId() == Integer8BitsColorDepthID) {
        while (dstIt.nextPixel()) {
            quint8 v;
            stream >> v;
            memcpy(dstIt.rawData() + d->channel->pos(), &v, sizeof(v));
        }
    }
    else if (d->node->colorSpace()->colorDepthId() ==  Integer16BitsColorDepthID) {
        while (dstIt.nextPixel()) {
            quint16 v;
            stream >> v;
            memcpy(dstIt.rawData() + d->channel->pos(), &v, sizeof(v));
        }
    }
#ifdef HAVE_OPENEXR
    else if (d->node->colorSpace()->colorDepthId() == Float16BitsColorDepthID) {
        while (dstIt.nextPixel()) {
            float f;
            stream >> f;
            half v = f;
            memcpy(dstIt.rawData() + d->channel->pos(), &v, sizeof(v));
        }

    }
#endif
    else if (d->node->colorSpace()->colorDepthId() == Float32BitsColorDepthID) {
        while (dstIt.nextPixel()) {
            float v;
            stream >> v;
            memcpy(dstIt.rawData() + d->channel->pos(), &v, sizeof(v));
        }
    }
}




