"""Tooltip event bridge for uniformly transformed native Qt controls."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QLineEdit


def _scaled_tooltip_target(view, proxy, surface, viewport_position):
    """Return the authored logical control underneath a scaled pointer."""
    scene_position = view.mapToScene(viewport_position)
    logical_position = proxy.mapFromScene(scene_position).toPoint()
    child = surface.childAt(logical_position)
    # Qt spin boxes place an implementation-detail QLineEdit over nearly the
    # whole control. Prefer the public spin box's authored tooltip instead of
    # the generic fallback assigned to that private editor.
    if (isinstance(child, QLineEdit) and
            isinstance(child.parentWidget(), QAbstractSpinBox) and
            child.parentWidget().toolTip().strip()):
        child = child.parentWidget()
    while child is not None and child is not surface:
        if child.toolTip().strip():
            return child, logical_position
        child = child.parentWidget()
    return None, logical_position


def sync_scaled_hover_tooltip(view, proxy, surface, viewport_position):
    """Prime the graphics viewport with the tooltip under the pointer.

    A QGraphicsProxyWidget can paint and click its logical children without
    advertising their tooltip to the real viewport. Keeping the viewport's
    tooltip synchronized makes normal Windows hover timing generate the help
    event, which ``forward_scaled_tooltip`` then delivers to the exact control.
    """
    child, _logical_position = _scaled_tooltip_target(
        view, proxy, surface, viewport_position)
    tooltip = child.toolTip().strip() if child is not None else ""
    viewport = view.viewport()
    if viewport.toolTip() != tooltip:
        viewport.setToolTip(tooltip)
    return tooltip


def forward_scaled_tooltip(view, proxy, surface, event):
    """Map one viewport help event back to the native logical child."""
    if event.type() != QEvent.Type.ToolTip:
        return False
    try:
        viewport_position = event.position().toPoint()
    except AttributeError:
        viewport_position = event.pos()
    child, logical_position = _scaled_tooltip_target(
        view, proxy, surface, viewport_position)
    if child is not None:
        local_position = child.mapFrom(surface, logical_position)
        try:
            global_position = event.globalPosition().toPoint()
        except AttributeError:
            global_position = event.globalPos()
        forwarded = QHelpEvent(
            QEvent.Type.ToolTip, local_position, global_position)
        QApplication.sendEvent(child, forwarded)
        event.accept()
        return True
    return False
