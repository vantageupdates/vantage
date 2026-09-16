"""Compact, DPI-safe startup progress surface for Vantage."""

from PySide6.QtCore import QEventLoop, QSize, Qt
from PySide6.QtGui import QFontMetrics, QIcon, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout,
    QWidget)

from vantage.helpers import resource_path


class StartupSplash(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("StartupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAccessibleName("Vantage is loading")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(18, 16, 18, 14)
        self._root.setSpacing(9)
        identity = QHBoxLayout()
        identity.setSpacing(12)
        self._emblem = QLabel()
        self._emblem.setPixmap(QIcon(resource_path("data/ui/icon.png")).pixmap(
            QSize(58, 58), max(1.0, self.devicePixelRatioF())))
        self._emblem.setAccessibleName("")
        self._emblem.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        identity.addWidget(self._emblem)
        copy = QVBoxLayout()
        self.title = QLabel("VANTAGE")
        self.title.setObjectName("StartupSplashTitle")
        self.title.setWordWrap(True)
        copy.addWidget(self.title)
        self.subtitle = QLabel("FREE P99 COMPANION · LOG-BASED · STARTING")
        self.subtitle.setObjectName("StartupSplashSubtitle")
        self.subtitle.setWordWrap(True)
        copy.addWidget(self.subtitle)
        self.creator = QLabel(
            "Created by Mindflux / Harmflux · P99 Green Server")
        self.creator.setObjectName("StartupSplashCreator")
        self.creator.setWordWrap(True)
        copy.addWidget(self.creator)
        identity.addLayout(copy, 1)
        self._root.addLayout(identity)

        self.status = QLabel("Preparing preferences…")
        self.status.setObjectName("StartupSplashStatus")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self._root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setObjectName("StartupSplashProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(4)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Startup progress")
        self._root.addWidget(self.progress)
        self._fit_to_available_screen()

    def _available_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _content_width(self):
        """Measure real strings while keeping prose at a readable line length."""
        widths = []
        for label in (self.title, self.subtitle, self.creator, self.status):
            widths.append(
                QFontMetrics(label.font()).horizontalAdvance(label.text()))
        identity_extra = self._emblem.sizeHint().width() + 12
        margins = self._root.contentsMargins()
        outer = margins.left() + margins.right()
        return max(
            320,
            min(560, max(widths, default=320) + identity_extra + outer))

    def _fit_to_available_screen(self):
        self.ensurePolished()
        area = self._available_geometry()
        maximum_width = max(1, area.width() - 32) if area else 560
        maximum_height = max(1, area.height() - 32) if area else 360
        target_width = min(maximum_width, self._content_width())

        self._root.invalidate()
        height_for_width = self._root.totalHeightForWidth(target_width)
        if height_for_width < 0:
            height_for_width = self.sizeHint().height()
        target_height = min(maximum_height, max(1, height_for_width))
        self.resize(target_width, target_height)
        self._update_mask()

    def _update_mask(self):
        if self.width() <= 0 or self.height() <= 0:
            return
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 11, 11)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()

    def show_centered(self):
        self._fit_to_available_screen()
        area = self._available_geometry()
        if area:
            self.move(area.center() - self.rect().center())
        self.show()
        self.raise_()
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def step(self, text, value):
        self.status.setText(text)
        self.progress.setValue(max(0, min(100, int(value))))
        self.setAccessibleDescription(text)
        center = self.geometry().center()
        self._fit_to_available_screen()
        if self.isVisible():
            area = self._available_geometry()
            target = self.rect()
            target.moveCenter(center)
            if area:
                target.moveLeft(max(
                    area.left(), min(
                        target.left(), area.right() - target.width() + 1)))
                target.moveTop(max(
                    area.top(), min(
                        target.top(), area.bottom() - target.height() + 1)))
            self.move(target.topLeft())
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def complete(self):
        self.step("Vantage ready", 100)
        self.close()
