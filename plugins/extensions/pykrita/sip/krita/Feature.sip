// SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
// SPDX-License-Identifier: LGPL-2.0-or-later
class Feature : QObject
{
%TypeHeaderCode
#include "Feature.h"
%End

%ConvertToSubClassCode
  // Without it a Feature passed through a QObject is provided as a QObject (as Selection.sip does).
  Feature* mc = qobject_cast<Feature*>(sipCpp);
  sipType = 0;
  if (mc) {
      sipType = sipType_Feature;
  }
%End

    Feature(const Feature & __0);
public:
    virtual ~Feature();
    bool operator==(const Feature &other) const;
    bool operator!=(const Feature &other) const;
public Q_SLOTS:
    QString id() const;
    QString name() const;
    QString kind() const;
    QString author() const;
    QString state() const;
    bool isProtected() const;
    bool setProtected(bool value);
    QRect bounds() const;
    qint64 area() const;
    QColor meanColor() const;
    Selection *mask() const /Factory/;
    bool isInDocument() const;
private:
};
