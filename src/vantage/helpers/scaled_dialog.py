"""Uniformly scaled dialog surface with no responsive reflow.

The dialog owns one immutable logical canvas. Resizing transforms that entire
canvas—text, controls, spacing, and icons together—so compact windows remain
faithful miniatures instead of rearranging their contents.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsItem, QGraphicsScene, QGraphicsView,
    QVBoxLayout, QWidget)

from vantage.helpers.scaled_tooltip import (
    forward_scaled_tooltip, sync_scaled_hover_tooltip)


class UniformScaleDialog(QDialog):
    """QDialog backed by a fixed logical surface and vector transform."""

    def __init__(
            self, design_size, parent=None, *, minimum_size=None,
            initial_size=None, lock_aspect=True):
        super().__init__(parent)
        self._dialog_design_size = QSize(design_size)
        self._dialog_lock_aspect = bool(lock_aspect)
        self._dialog_aspect_guard = False
        minimum_size = QSize(minimum_size or QSize(190, 120))
        self.setMinimumSize(minimum_size)
        self.resize(QSize(initial_size or self._dialog_design_size))

        self.scaled_surface = QWidget()
        self.scaled_surface.setObjectName("UniformScaleDialogSurface")
        self.scaled_surface.setFixedSize(self._dialog_design_size)

        self._dialog_scene = QGraphicsScene(self)
        self._dialog_scene.setItemIndexMethod(
            QGraphicsScene.ItemIndexMethod.NoIndex)
        self._dialog_proxy = self._dialog_scene.addWidget(self.scaled_surface)
        self._dialog_proxy.setCacheMode(QGraphicsItem.CacheMode.NoCache)

        self._dialog_view = QGraphicsView(self._dialog_scene, self)
        self._dialog_view.setObjectName("UniformScaleDialogView")
        self._dialog_view.setFrameShape(QFrame.Shape.NoFrame)
        self._dialog_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dialog_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dialog_view.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._dialog_view.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing)
        self._dialog_view.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._dialog_view.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self._dialog_view.setToolTip(
            "Resize to scale the complete dialog, including text and controls")
        self._dialog_view.viewport().setMouseTracking(True)
        self._dialog_view.viewport().installEventFilter(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._dialog_view)
        QTimer.singleShot(0, self._update_dialog_scale)

    @property
    def uniform_scale(self):
        """Current transform ratio, useful to tests and interaction helpers."""
        return self._dialog_view.transform().m11()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_dialog_scale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._dialog_lock_aspect and not self._dialog_aspect_guard:
            target = self._aspect_size(event.size(), event.oldSize())
            if target != event.size():
                self._dialog_aspect_guard = True
                self.resize(target)
                self._dialog_aspect_guard = False
        QTimer.singleShot(0, self._update_dialog_scale)

    def eventFilter(self, watched, event):
        if (watched is self._dialog_view.viewport()
                and event.type() == QEvent.Type.MouseMove):
            sync_scaled_hover_tooltip(
                self._dialog_view, self._dialog_proxy,
                self.scaled_surface, event.position().toPoint())
        if (watched is self._dialog_view.viewport()
                and event.type() == QEvent.Type.ToolTip
                and forward_scaled_tooltip(
                    self._dialog_view, self._dialog_proxy,
                    self.scaled_surface, event)):
            return True
        return super().eventFilter(watched, event)

    def _aspect_size(self, requested, previous):
        ratio = (
            self._dialog_design_size.width() /
            max(1, self._dialog_design_size.height()))
        width_changed = abs(requested.width() - previous.width())
        height_changed = abs(requested.height() - previous.height())
        if width_changed >= height_changed:
            width = max(self.minimumWidth(), requested.width())
            height = max(self.minimumHeight(), round(width / ratio))
            if height == self.minimumHeight():
                width = max(self.minimumWidth(), round(height * ratio))
        else:
            height = max(self.minimumHeight(), requested.height())
            width = max(self.minimumWidth(), round(height * ratio))
            if width == self.minimumWidth():
                height = max(self.minimumHeight(), round(width / ratio))
        return QSize(width, height)

    def _update_dialog_scale(self):
        if not self._dialog_view or not self._dialog_proxy:
            return
        width = max(1, self._dialog_design_size.width())
        height = max(1, self._dialog_design_size.height())
        self._dialog_scene.setSceneRect(QRectF(0, 0, width, height))
        viewport = self._dialog_view.viewport().size()
        scale = max(
            0.01, min(viewport.width() / width, viewport.height() / height))
        self._dialog_view.resetTransform()
        self._dialog_view.scale(scale, scale)
