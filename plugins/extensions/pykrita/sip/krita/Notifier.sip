class Notifier : QObject
{
%TypeHeaderCode
#include "Notifier.h"
%End
    Notifier(const Notifier & __0);
public:
    Notifier(QObject*  parent /TransferThis/ = 0);
    virtual ~Notifier();
    bool active() const;
    void setActive(bool value);
Q_SIGNALS:
    void applicationClosing();
    void imageCreated(Document*  image);
    void imageSaved(const QString &filename);
    void imageClosed(const QString &filename);
    void viewCreated(View *view);
    void viewClosed(View *view);
    void windowIsBeingCreated(Window *window);
    void windowCreated();
    void configurationChanged();
    void imageChanged(Document *document, const QRect &rect, const QString &source);
    void nodeAdded(Document *document, Node *node);
    void nodeRemoved(Document *document, Node *node);
    void nodeChanged(Document *document, Node *node);
    void nodePixelsChanged(Document *document, Node *node, const QRect &rect, const QString &source);
    void selectionChanged(Document *document);
    void undoIndexChanged(Document *document, int index);
    void documentModified(Document *document, bool modified);
    void activeNodeChanged(Document *document, Node *node);
    void toolChanged(Document *document, const QString &toolId);
    void brushPresetChanged(Document *document, const QString &presetName);
};
