"""Small non-interactive update notification that never enters the taskbar."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QCursor)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget)

from vantage.helpers.icons import game_icon, game_pixmap


class QuickUpdateToast(QWidget):
    """Top-right card for verified Companion and VantageUI releases."""

    def __init__(self, controller, application):
        super().__init__(None)
        self.controller = controller
        self.application = application
        self.info = None
        self._vantage_ui_version = ""
        self._one_click_active = False
        self._last_progress_announcement = 0
        self.setObjectName("QuickUpdateToast")
        self.setWindowTitle("Vantage Update")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(348, 88)
        self._build_ui()
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.setInterval(9000)
        self._auto_hide.timeout.connect(self.hide)
        self._legacy_present = QTimer(self)
        self._legacy_present.setSingleShot(True)
        self._legacy_present.setInterval(150)
        self._legacy_present.timeout.connect(self._present_ready)
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
        root.addLayout(heading)

        self.message = QLabel("A verified Vantage update is available.")
        self.message.setObjectName("QuickUpdateMessage")
        root.addWidget(self.message)
        self._set_status(self.message.text(), announce=False)

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

        # Compatibility handles remain hidden and unfocusable; this
        # show-without-activating surface is status-only. All update actions
        # live in the keyboard-operable Quick Bar Updates dialog.
        self.close_button = QPushButton("Dismiss", self)
        self.close_button.hide()
        self.close_button.setEnabled(False)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.update_button = QPushButton("Update Vantage", self)
        self.update_button.setObjectName("QuickUpdateAction")
        self.update_button.setIcon(game_icon("refresh"))
        self.update_button.setAccessibleName(
            "Download, verify, install, and restart Vantage")
        self.update_button.setEnabled(False)
        self.update_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.update_button.hide()
        self.ui_button = QPushButton("Update VantageUI", self)
        self.ui_button.setObjectName("QuickUpdateAction")
        self.ui_button.setIcon(game_icon("ph-layout"))
        self.ui_button.setAccessibleName(
            "Open VantageUI to review and install its verified update")
        self.ui_button.setEnabled(False)
        self.ui_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ui_button.hide()

    def show_for(self, info):
        self.info = info
        self._legacy_present.start()

    def show_for_vantage_ui(self, version):
        """Show a deduplicated VantageUI release without installing it."""
        self._vantage_ui_version = str(version or "").strip()
        if not self._vantage_ui_version:
            return
        self._legacy_present.start()

    def show_updates(self, *, info=None, vantage_ui_version=""):
        """Present both independently versioned products in one announcement."""
        self._legacy_present.stop()
        self.info = info
        self._vantage_ui_version = str(vantage_ui_version or "").strip()
        self._present_ready()

    def _present_ready(self):
        if self.info is None and not self._vantage_ui_version:
            self.hide()
            return
        self._one_click_active = False
        self._last_progress_announcement = 0
        self.progress.hide()
        self.progress.setValue(0)
        self._refresh_ready_content()
        self._move_top_right()
        self.show()
        self.raise_()
        self._announce_status()
        self._auto_hide.start()

    def clear_vantage_ui_update(self):
        """Remove a no-longer-current UI notice without losing Companion."""
        if not self._vantage_ui_version:
            return
        self._vantage_ui_version = ""
        if self._one_click_active:
            self.ui_button.hide()
            self.title.setText("VANTAGE UPDATE")
            self._set_status(
                "Downloading and verifying Vantage…", announce=False)
            return
        if self.info is not None:
            self._refresh_ready_content()
        elif self.title.text() != "UPDATE COMPLETE":
            self.hide()

    def _refresh_ready_content(self):
        companion_ready = self.info is not None
        ui_ready = bool(self._vantage_ui_version)
        if companion_ready and ui_ready:
            self.title.setText("UPDATES READY")
            self._set_status(
                f"Vantage {self.info.version} and VantageUI "
                f"{self._vantage_ui_version} are ready · open Updates in the Quick Bar",
                announce=False)
        elif companion_ready:
            self.title.setText("VANTAGE UPDATE")
            self._set_status(
                f"Vantage {self.info.version} is ready · open Updates in the Quick Bar",
                announce=False)
        elif ui_ready:
            self.title.setText("VANTAGEUI UPDATE")
            self._set_status(
                f"VantageUI {self._vantage_ui_version} is ready · open Updates in the Quick Bar",
                announce=False)

    def _open_vantage_ui(self):
        """Honor the user's click by opening the review/install panel."""
        if not self._vantage_ui_version:
            return
        self.application.open_vantage_ui()
        self._vantage_ui_version = ""
        if self.info is not None:
            self._refresh_ready_content()
        else:
            self.hide()

    def show_success(self, previous_version, current_version):
        """Keep post-restart success out of the top-right notification."""
        self.hide()

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
            self._set_status("Another update operation is already running.")
            return
        self._one_click_active = True
        self._last_progress_announcement = 0
        self._auto_hide.stop()
        self.close_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.ui_button.setEnabled(False)
        self.update_button.setText("Updating…")
        self.progress.setValue(0)
        self.progress.show()
        self._set_status("Downloading and verifying Vantage…")
        if not self.controller.download(self.info):
            self._failed("The update could not start.")

    def _download_progress(self, received, total):
        if not self._one_click_active:
            return
        total = total if total > 0 else (self.info.size if self.info else 0)
        value = round(received / total * 100) if total else 0
        value = max(0, min(100, value))
        self.progress.setValue(value)
        milestone = min(75, (value // 25) * 25)
        if milestone >= 25 and milestone > self._last_progress_announcement:
            self._last_progress_announcement = milestone
            self._set_status(
                f"Downloading and verifying Vantage · {milestone}%")

    def _download_ready(self, info, path):
        if not self._one_click_active:
            return
        self.progress.setValue(100)
        self._set_status("Verified · restarting Vantage…")
        self.application.install_quick_update(info, path, self)

    def _failed(self, message):
        if not self._one_click_active:
            return
        focused = QApplication.focusWidget()
        restore_focus = bool(
            self.isActiveWindow() and focused and
            (focused is self or self.isAncestorOf(focused)))
        self._one_click_active = False
        self.close_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.ui_button.setEnabled(True)
        self.update_button.setText("Try again")
        self._set_status(str(message))
        if restore_focus:
            QTimer.singleShot(
                0, lambda: self.update_button.setFocus(
                    Qt.FocusReason.OtherFocusReason))

    def _set_status(self, message, announce=True):
        """Synchronize visible and assistive status without taking focus."""
        message = " ".join(str(message or "").split())
        self.message.setText(message)
        self.message.setAccessibleName(f"Update status: {message}")
        self.message.setAccessibleDescription(message)
        if announce and self.isVisible():
            self._announce_status()

    def _announce_status(self):
        message = self.message.text()
        if not self.isVisible() or not message:
            return
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.message, message))
        except (AttributeError, RuntimeError, TypeError):
            pass
