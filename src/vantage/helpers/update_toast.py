"""Small one-click update notification that never enters the taskbar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget)

from vantage.helpers.icons import game_icon, game_pixmap


class QuickUpdateToast(QWidget):
    """Top-right update card; a click downloads, verifies, and installs."""

    def __init__(self, controller, application):
        super().__init__(None)
        self.controller = controller
        self.application = application
        self.info = None
        self._one_click_active = False
        self.setObjectName("QuickUpdateToast")
        self.setWindowTitle("Vantage Update")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(326, 112)
        self._build_ui()
        controller.download_progress.connect(self._download_progress)
        controller.download_ready.connect(self._download_ready)
        controller.failed.connect(self._failed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 7, 8, 8)
        root.setSpacing(4)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(5)
        icon = QLabel()
        icon.setPixmap(game_pixmap("refresh", 17, self))
        icon.setAccessibleName("")
        heading.addWidget(icon, 0)
        self.title = QLabel("VANTAGE UPDATE")
        self.title.setObjectName("QuickUpdateTitle")
        heading.addWidget(self.title, 1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("QuickUpdateClose")
        self.close_button.setAccessibleName("Dismiss update notification")
        self.close_button.setToolTip(
            "Dismiss this notification; update remains available in Vantage")
        self.close_button.clicked.connect(self.hide)
        heading.addWidget(self.close_button, 0)
        root.addLayout(heading)

        self.message = QLabel("A verified Vantage update is available.")
        self.message.setObjectName("QuickUpdateMessage")
        self.message.setAccessibleName("Update status")
        root.addWidget(self.message)

        self.progress = QProgressBar()
        self.progress.setObjectName("QuickUpdateProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Update download progress")
        self.progress.setToolTip(
            "The download is verified against GitHub size and SHA-256")
        self.progress.hide()
        root.addWidget(self.progress)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        self.update_button = QPushButton("Update")
        self.update_button.setObjectName("QuickUpdateAction")
        self.update_button.setIcon(game_icon("refresh"))
        self.update_button.setAccessibleName(
            "Download, verify, install, and restart Vantage")
        self.update_button.setToolTip(
            "One click updates only Vantage; EverQuest and WinEQ remain open")
        self.update_button.clicked.connect(self.start_one_click_update)
        actions.addWidget(self.update_button)
        root.addLayout(actions)

    def show_for(self, info):
        try:
            self.update_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.update_button.clicked.connect(self.start_one_click_update)
        self.info = info
        self._one_click_active = False
        self.progress.hide()
        self.progress.setValue(0)
        self.close_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.update_button.setText("Update")
        self.title.setText("VANTAGE UPDATE")
        self.message.setText(
            f"Vantage {info.version} is ready · verified GitHub Release")
        self._move_top_right()
        self.show()
        self.raise_()

    def show_success(self, previous_version, current_version):
        """Leave an unmistakable receipt after the replacement restarts."""
        self.info = None
        self._one_click_active = False
        self.progress.setValue(100)
        self.progress.show()
        self.close_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.update_button.setText("Done")
        try:
            self.update_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.update_button.clicked.connect(self.hide)
        self.title.setText("UPDATE COMPLETE")
        self.message.setText(
            f"Vantage {current_version} is installed · was {previous_version}")
        self._move_top_right()
        self.show()
        self.raise_()

    def _move_top_right(self):
        screen = QApplication.screenAt(QCursor.pos()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        margin = 12
        self.move(
            area.right() - self.width() - margin + 1,
            area.top() + margin)

    def start_one_click_update(self):
        if not self.info or self.controller.busy:
            self.message.setText(
                "Another update operation is already running.")
            return
        self._one_click_active = True
        self.close_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.update_button.setText("Updating…")
        self.progress.setValue(0)
        self.progress.show()
        self.message.setText("Downloading and verifying Vantage…")
        if not self.controller.download(self.info):
            self._failed("The update could not start.")

    def _download_progress(self, received, total):
        if not self._one_click_active:
            return
        total = total if total > 0 else (self.info.size if self.info else 0)
        value = round(received / total * 100) if total else 0
        self.progress.setValue(max(0, min(100, value)))

    def _download_ready(self, info, path):
        if not self._one_click_active:
            return
        self.progress.setValue(100)
        self.message.setText("Verified · restarting Vantage…")
        self.application.install_quick_update(info, path, self)

    def _failed(self, message):
        if not self._one_click_active:
            return
        self._one_click_active = False
        self.close_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.update_button.setText("Try again")
        self.message.setText(str(message))
