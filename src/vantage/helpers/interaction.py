"""Application-wide interaction polish for native controls."""

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QFormLayout, QLineEdit, QPushButton, QScrollBar, QTabBar)


INTERACTIVE_CONTROLS = (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit, QTabBar)


def _form_label(control):
    """Find the visible form label associated with a native control."""
    parent = control.parentWidget()
    if not parent or not isinstance(parent.layout(), QFormLayout):
        return ""
    label = parent.layout().labelForField(control)
    return label.text().replace("&", "").strip(" :") if label else ""


def _fallback_tooltip(control):
    label = control.accessibleName().strip() or _form_label(control)
    if isinstance(control, QScrollBar):
        return "Scroll the visible content"
    if isinstance(control, QTabBar):
        return "Switch between sections"
    if isinstance(control, QAbstractItemView) and not label:
        return "Browse this list or table with the pointer or arrow keys"
    if not label and isinstance(control, QAbstractButton):
        label = control.text().replace("&", "").strip()
    if not label and isinstance(control, QLineEdit):
        label = control.placeholderText().strip()
    if not label and control.objectName():
        label = control.objectName().replace(":", " · ").replace("_", " ")
    if isinstance(control, QComboBox) and label:
        return f"{label}: open the list to choose an option"
    if isinstance(control, QAbstractSpinBox) and label:
        return f"{label}: type a value or use the arrow keys"
    if isinstance(control, QLineEdit) and label:
        return f"{label}: type or edit this value"
    return label


class ButtonPolishFilter(QObject):
    """Give every interactive control a clear pointer, focus and tooltip."""

    def eventFilter(self, watched, event):
        if isinstance(watched, INTERACTIVE_CONTROLS) and event.type() in (
                QEvent.Type.Polish, QEvent.Type.EnabledChange,
                QEvent.Type.ToolTipChange):
            if isinstance(watched, (QAbstractButton, QComboBox)):
                watched.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if watched.isEnabled() else Qt.CursorShape.ArrowCursor)
            watched.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if (isinstance(watched, QPushButton)
                    and not watched.icon().isNull()
                    and watched.iconSize().width() < 16):
                watched.setIconSize(QSize(16, 16))
            if not watched.accessibleName():
                label = _form_label(watched)
                if isinstance(watched, QAbstractButton):
                    label = watched.text().replace("&", "").strip() or label
                watched.setAccessibleName(
                    label or watched.toolTip() or _fallback_tooltip(watched))
            if not watched.toolTip():
                tooltip = _fallback_tooltip(watched)
                if tooltip:
                    watched.setToolTip(tooltip)
        return super().eventFilter(watched, event)
