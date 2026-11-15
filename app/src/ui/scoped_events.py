"""Window-scoped interaction filters, never Python application-wide filters.

Passing every Qt receiver through a Python filter also wraps internal QObjects
while Qt is invalidating their bindings. Observe only the windows we own.
"""
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


def scoped_dialog_filter(observer, enabled=True):
    for target in getattr(observer, '_scoped_event_targets', ()):
        if isValid(target):
            target.removeEventFilter(observer)
    targets = []
    if enabled:
        parent = observer.parent()
        for target in (observer, parent, getattr(observer, 'shell', None),
                       getattr(observer, 'dialog', None), getattr(observer, 'backdrop', None)):
            if isinstance(target, QWidget) and isValid(target):
                for item in (target, target.window()):
                    if item not in targets:
                        targets.append(item)
        for target in targets:
            target.installEventFilter(observer)
    observer._scoped_event_targets = targets


def dismiss_deactivated(dialog, watched, event, dismiss):
    if watched is not dialog or event.type() != QEvent.Type.WindowDeactivate:
        return
    def settle():
        if not isValid(dialog) or not dialog.isVisible() or dialog.property('childWorkflow'):
            return
        active = QApplication.activeWindow()
        popup = QApplication.activePopupWidget()
        if popup is not None and (popup is dialog or dialog.isAncestorOf(popup)):
            return
        if active is not dialog and not (active is not None and dialog.isAncestorOf(active)):
            dismiss()
    QTimer.singleShot(0, dialog, settle)
