"""Compact startup progress surface for Vantage."""

from PySide6.QtCore import QEventLoop, QSize, Qt
from PySide6.QtGui import QIcon, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget)

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
        self.setFixedSize(410, 176)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 11, 11)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.setAccessibleName("Vantage is loading")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(9)
        identity = QHBoxLayout()
        identity.setSpacing(12)
        emblem = QLabel()
        emblem.setPixmap(QIcon(resource_path("data/ui/icon.png")).pixmap(
            QSize(58, 58), max(1.0, self.devicePixelRatioF())))
        emblem.setAccessibleName("")
        identity.addWidget(emblem)
        copy = QVBoxLayout()
        title = QLabel("VANTAGE")
        title.setObjectName("StartupSplashTitle")
        copy.addWidget(title)
        subtitle = QLabel("FREE P99 COMPANION · LOG-BASED · STARTING")
        subtitle.setObjectName("StartupSplashSubtitle")
        copy.addWidget(subtitle)
        creator = QLabel("Created by Mindflux / Harmflux · P99 Green Server")
        creator.setObjectName("StartupSplashCreator")
        copy.addWidget(creator)
        identity.addLayout(copy, 1)
        root.addLayout(identity)

        self.status = QLabel("Preparing preferences…")
        self.status.setObjectName("StartupSplashStatus")
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setObjectName("StartupSplashProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(4)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Startup progress")
        root.addWidget(self.progress)

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.center() - self.rect().center())
        self.show()
        self.raise_()
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def step(self, text, value):
        self.status.setText(text)
        self.progress.setValue(max(0, min(100, int(value))))
        self.setAccessibleDescription(text)
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def complete(self):
        self.step("Vantage ready", 100)
        self.close()
