"""VantageUI installer panel backed by the verified updater core."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import ResponsiveActionBar
from vantage.helpers import ui_skin_updater


DEFAULT_EQ_ROOT = r"C:\Program Files (x86)\Sony\EverQuest"
PENDING_POLL_MS = 3000
AUTO_CHECK_MS = 5 * 60 * 1000


def normalize_eq_root(value):
    """Normalize common Browse results to the canonical EverQuest root."""
    text = str(value or "").strip().strip('"')
    if not text:
        return DEFAULT_EQ_ROOT
    path = Path(os.path.abspath(os.path.expanduser(text)))
    if path.name.casefold() == "eqgame.exe":
        path = path.parent
    if (path.name.casefold() == ui_skin_updater.SKIN_FOLDER.casefold()
            and path.parent.name.casefold() == "uifiles"):
        path = path.parent.parent
    elif path.name.casefold() == "uifiles":
        path = path.parent
    return os.path.normpath(str(path))


def skin_target(eq_root):
    return str(Path(normalize_eq_root(eq_root)) / "uifiles" /
               ui_skin_updater.SKIN_FOLDER)


def version_is_newer(installed, available):
    def version_key(value):
        try:
            parts = tuple(int(part) for part in str(value).split("."))
            return parts if len(parts) == 3 else (0, 0, 0)
        except (TypeError, ValueError):
            return (0, 0, 0)
    return bool(available) and (
        not installed or version_key(available) > version_key(installed))


def elevated_updater_command(eq_root, *, current_executable=None,
                             frozen=None, source_script=None):
    """Return the safest available updater command for normal UAC launch."""
    current = Path(current_executable or sys.executable).resolve()
    app_dir = current.parent
    executable = app_dir / "VantageUI-Updater.exe"
    if executable.is_file():
        program = str(executable)
        arguments = subprocess.list2cmdline(["--eq-dir", normalize_eq_root(eq_root)])
        return program, arguments
    source = (Path(source_script) if source_script is not None else
              Path(__file__).resolve().parents[3] / "vantage_ui_updater.py")
    if source.is_file():
        program = sys.executable
        arguments = subprocess.list2cmdline(
            [str(source), "--eq-dir", normalize_eq_root(eq_root)])
        return program, arguments
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    if is_frozen and current.is_file():
        program = str(current)
        arguments = subprocess.list2cmdline([
            "--vantage-ui-updater", "--eq-dir", normalize_eq_root(eq_root)])
        return program, arguments
    return None


def request_elevated_updater(eq_root):
    """Ask Windows UAC to launch the verified updater; never alter ACLs."""
    if os.name != "nt":
        return False
    command = elevated_updater_command(eq_root)
    if command is None:
        return False
    program, arguments = command
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", program, arguments, None, 1)
    return int(result) > 32


class _WorkerSignals(QObject):
    completed = Signal(int, str, object)
    failed = Signal(int, str, object)
    log = Signal(int, str)


class VantageUI(ParserWindow):
    """Independent, non-blocking VantageUI management surface."""

    name = "vantage_ui"
    _allow_clickthrough = False
    _minimum_scale = 0.80

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VantageUI")
        self._title.setText("VantageUI")
        self._signals = _WorkerSignals(self)
        self._signals.completed.connect(self._operation_completed)
        self._signals.failed.connect(self._operation_failed)
        self._signals.log.connect(self._append_log)
        self._operation_token = 0
        self._busy = False
        self._loaded_once = False
        self._installed = ""
        self._release = None
        self._pending_release = None
        self._install_after_check = False
        self._install_action = ""
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._poll_pending_update)
        self._automatic_timer = QTimer(self)
        self._automatic_timer.setInterval(AUTO_CHECK_MS)
        self._automatic_timer.timeout.connect(self.check_for_updates)
        self._build_ui()
        if self.auto_update.isChecked():
            self._automatic_timer.start()

    @property
    def state_directory(self):
        return data_dir("ui-updater", "backups")

    def _build_ui(self):
        body = QFrame()
        body.setObjectName("VantageUIBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Install and maintain the optional VantageUI skin for EverQuest "
            "Titanium / Project 1999.")
        intro.setObjectName("VantageUIIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        path_card = QFrame()
        path_card.setObjectName("VantageUICard")
        path_layout = QGridLayout(path_card)
        path_layout.setContentsMargins(8, 7, 8, 7)
        path_layout.setHorizontalSpacing(6)
        path_layout.setVerticalSpacing(5)
        path_label = QLabel("EverQuest folder")
        self.path_edit = QLineEdit(normalize_eq_root(
            config.data["vantage_ui"].get("eq_dir", DEFAULT_EQ_ROOT)))
        self.path_edit.setAccessibleName("Selected EverQuest folder")
        self.path_edit.setToolTip(
            "EverQuest root containing eqgame.exe and the uifiles folder")
        self.path_edit.editingFinished.connect(self._path_edited)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setIcon(game_icon("ph-folder-open"))
        self.browse_button.setAccessibleName("Browse for EverQuest folder")
        self.browse_button.setToolTip(
            "Select the EverQuest root; VantageUI always installs below uifiles")
        self.browse_button.clicked.connect(self.browse)
        path_layout.addWidget(path_label, 0, 0)
        path_layout.addWidget(self.path_edit, 0, 1)
        path_layout.addWidget(self.browse_button, 0, 2)
        target_caption = QLabel("Install target")
        self.target_value = QLabel()
        self.target_value.setWordWrap(True)
        self.target_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_value.setAccessibleName("VantageUI install target")
        path_layout.addWidget(target_caption, 1, 0)
        path_layout.addWidget(self.target_value, 1, 1, 1, 2)
        layout.addWidget(path_card)

        versions = QFrame()
        versions.setObjectName("VantageUICard")
        versions_layout = QGridLayout(versions)
        versions_layout.setContentsMargins(8, 7, 8, 7)
        self.installed_value = QLabel("Not checked")
        self.available_value = QLabel("Not checked")
        self.installed_value.setAccessibleName("Installed VantageUI version")
        self.available_value.setAccessibleName("Available VantageUI version")
        versions_layout.addWidget(QLabel("Installed version"), 0, 0)
        versions_layout.addWidget(self.installed_value, 0, 1)
        versions_layout.addWidget(QLabel("Available version"), 1, 0)
        versions_layout.addWidget(self.available_value, 1, 1)
        layout.addWidget(versions)

        actions = ResponsiveActionBar(min_cell_width=120)
        self.check_button = QPushButton("Check for updates")
        self.check_button.setIcon(game_icon("refresh"))
        self.check_button.setAccessibleName("Check for VantageUI updates")
        self.check_button.setToolTip(
            "Check verified Vantage GitHub release assets for VantageUI")
        self.check_button.clicked.connect(self.check_for_updates)
        actions.addWidget(self.check_button)
        self.update_button = QPushButton("Install VantageUI")
        self.update_button.setIcon(game_icon("ph-download"))
        self.update_button.clicked.connect(self.update_skin)
        actions.addWidget(self.update_button)
        self.restore_button = QPushButton("Restore")
        self.restore_button.setIcon(game_icon("ph-reload"))
        self.restore_button.setAccessibleName("Restore previous VantageUI")
        self.restore_button.setToolTip(
            "Restore files from the last VantageUI update without touching other skins")
        self.restore_button.clicked.connect(self.restore_skin)
        actions.addWidget(self.restore_button)
        layout.addWidget(actions)

        # Keep the primary action in the ordinary left-to-right keyboard path.
        # Native buttons retain Enter/Space activation and the shared focus ring.
        QWidget.setTabOrder(self.path_edit, self.browse_button)
        QWidget.setTabOrder(self.browse_button, self.check_button)
        QWidget.setTabOrder(self.check_button, self.update_button)
        QWidget.setTabOrder(self.update_button, self.restore_button)

        self.pending_banner = QFrame()
        self.pending_banner.setObjectName("VantageUICard")
        self.pending_banner.setAccessibleName("VantageUI installation queued")
        pending_layout = QVBoxLayout(self.pending_banner)
        pending_layout.setContentsMargins(10, 8, 10, 8)
        pending_layout.setSpacing(3)
        pending_heading = QLabel("INSTALLATION QUEUED")
        pending_font = pending_heading.font()
        pending_font.setBold(True)
        pending_heading.setFont(pending_font)
        self.pending_message = QLabel()
        self.pending_message.setWordWrap(True)
        self.pending_message.setAccessibleName(
            "Queued VantageUI installation instructions")
        pending_layout.addWidget(pending_heading)
        pending_layout.addWidget(self.pending_message)
        self.pending_banner.hide()
        layout.addWidget(self.pending_banner)

        self.auto_update = QCheckBox("Automatically check and update VantageUI")
        self.auto_update.setChecked(bool(
            config.data["vantage_ui"].get("auto_update", False)))
        self.auto_update.setAccessibleName("Automatic VantageUI updates")
        self.auto_update.setToolTip(
            "Opt in to checks every five minutes; updates wait until EverQuest exits")
        self.auto_update.toggled.connect(self._auto_update_changed)
        layout.addWidget(self.auto_update)

        self.elevation_button = QPushButton("Retry with Windows permission…")
        self.elevation_button.setAccessibleName(
            "Open the VantageUI updater with Windows administrator permission")
        self.elevation_button.setToolTip(
            "Use the normal Windows UAC prompt; Vantage never changes folder permissions")
        self.elevation_button.clicked.connect(self._request_elevation)
        self.elevation_button.hide()
        layout.addWidget(self.elevation_button)

        self.status = QLabel(
            "Ready. Choose the EverQuest folder, then Install VantageUI.")
        self.status.setObjectName("VantageUIStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("VantageUI status")
        layout.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setObjectName("VantageUILog")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(80)
        self.log.setAccessibleName("VantageUI operation details")
        self.log.setToolTip("Recent verified update and recovery details")
        layout.addWidget(self.log, 1)

        self.instruction = QLabel(
            "After installing, enter <b>/loadskin VantageUI 1</b> in EverQuest. "
            "Confirm the windows and controls in game; Companion cannot verify "
            "the skin inside EverQuest.")
        self.instruction.setWordWrap(True)
        self.instruction.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.instruction)
        scope = QLabel(
            "Only uifiles\\VantageUI is managed. Other skins, character INIs, "
            "game binaries, running processes, and Companion are never replaced.")
        scope.setObjectName("VantageUIScope")
        scope.setWordWrap(True)
        layout.addWidget(scope)

        self.content.addWidget(body, 1)
        self._refresh_target()
        self._refresh_versions()
        self._refresh_controls()

    def parse(self, _timestamp, _text):
        """VantageUI is independent of EverQuest log parsing."""

    def toggle(self):
        opening = not self.isVisible()
        super().toggle()
        if opening and self.isVisible():
            QTimer.singleShot(0, lambda: self.path_edit.setFocus(
                Qt.FocusReason.OtherFocusReason))
            if not self._loaded_once:
                self._loaded_once = True
                self.refresh_local()

    def _announce(self, text):
        try:
            event = QAccessibleAnnouncementEvent(self.status, str(text))
            QAccessible.updateAccessibility(event)
        except (AttributeError, RuntimeError):
            pass

    def _set_status(self, text, announce=True):
        self.status.setText(str(text))
        self.status.setAccessibleDescription(str(text))
        if announce:
            self._announce(text)

    def _append_log(self, token, text):
        if token == self._operation_token:
            self.log.appendPlainText(str(text))

    def _refresh_target(self):
        self.target_value.setText(skin_target(self.path_edit.text()))

    def _refresh_versions(self):
        self.installed_value.setText(self._installed or "Not installed")
        self.available_value.setText(
            self._release.version if self._release else "Not checked")

    def _primary_action_kind(self):
        if not self._installed:
            return "install"
        if (self._release is not None and
                not version_is_newer(self._installed, self._release.version)):
            return "repair"
        return "update"

    def _refresh_primary_action(self):
        if self._pending_release is not None:
            text = "Waiting for EverQuest to close…"
            self.update_button.setText(text)
            self.update_button.setAccessibleName(
                "Waiting for EverQuest to close before installing VantageUI")
            self.update_button.setToolTip(
                "Installation is queued. Close EverQuest normally and keep "
                "Vantage open; Vantage will never close the game.")
            return
        kind = self._primary_action_kind()
        if kind == "install":
            text = "Install VantageUI"
            tooltip = (
                "Check for the verified release, then install only "
                "uifiles\\VantageUI")
        elif kind == "repair":
            text = "Repair VantageUI"
            tooltip = (
                "Verify and repair the current VantageUI files using the "
                "verified release")
        else:
            text = "Update VantageUI"
            tooltip = (
                "Check, back up, and update only uifiles\\VantageUI")
        self.update_button.setText(text)
        self.update_button.setAccessibleName(text)
        self.update_button.setToolTip(tooltip)

    def _refresh_controls(self):
        self._refresh_primary_action()
        for control in (
                self.path_edit, self.browse_button, self.check_button,
                self.restore_button, self.auto_update):
            control.setEnabled(not self._busy)
        self.update_button.setEnabled(
            not self._busy and self._pending_release is None)

    def _save_settings(self):
        config.data["vantage_ui"]["eq_dir"] = normalize_eq_root(
            self.path_edit.text())
        config.data["vantage_ui"]["auto_update"] = self.auto_update.isChecked()
        config.save()

    def _path_edited(self):
        normalized = normalize_eq_root(self.path_edit.text())
        self.path_edit.setText(normalized)
        self._release = None
        self._installed = ""
        self._install_after_check = False
        self._clear_pending_wait()
        self._refresh_target()
        self._refresh_versions()
        self._save_settings()
        self.refresh_local()

    def browse(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Select the EverQuest folder containing eqgame.exe",
            self.path_edit.text())
        if chosen:
            self.path_edit.setText(normalize_eq_root(chosen))
            self._path_edited()

    def _start(self, action, callback, status):
        if self._busy:
            return False
        self._busy = True
        self._operation_token += 1
        token = self._operation_token
        self.elevation_button.hide()
        self._set_status(status)
        self._refresh_controls()

        def run():
            try:
                result = callback(lambda message: self._signals.log.emit(
                    token, str(message)))
            except BaseException as error:
                self._signals.failed.emit(token, action, error)
            else:
                self._signals.completed.emit(token, action, result)

        threading.Thread(
            target=run, name=f"VantageUI-{action}", daemon=True).start()
        return True

    def refresh_local(self):
        eq_root = normalize_eq_root(self.path_edit.text())

        def read_local(log):
            ui_skin_updater.recover_pending(
                eq_root, self.state_directory, log=log)
            return ui_skin_updater.installed_version(eq_root)

        return self._start(
            "local", read_local,
            "Checking the selected EverQuest folder and recovery state…")

    def check_for_updates(self):
        eq_root = normalize_eq_root(self.path_edit.text())

        def check(_log):
            release = ui_skin_updater.check_release()
            installed = ui_skin_updater.installed_version(eq_root)
            return release, installed

        return self._start(
            "check", check,
            "Checking the official verified VantageUI release…")

    def _confirm(self, title, text):
        dialog = QMessageBox(
            QMessageBox.Icon.Question, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def update_skin(self, _checked=False, confirm=True):
        if self._busy or self._pending_release is not None:
            return False
        if self._release is None:
            # The primary first-install control is intentionally one action:
            # fetch the verified release, then continue through the existing
            # confirmation and installer path when that check completes.
            self._install_after_check = True
            started = self.check_for_updates()
            if not started:
                self._install_after_check = False
            return started
        action = self._primary_action_kind()
        self._install_action = action
        title = {
            "install": "Install VantageUI",
            "update": "Update VantageUI",
            "repair": "Repair VantageUI",
        }[action]
        prompt = {
            "install": "Install only uifiles\\VantageUI using verified release files?",
            "update": "Update only uifiles\\VantageUI using verified release files?",
            "repair": "Verify and repair only uifiles\\VantageUI using verified release files?",
        }[action]
        if confirm and not self._confirm(
                title, prompt + "\n\n"
                "Existing replaced files receive a recoverable backup. "
                "EverQuest will never be closed by Vantage."):
            self._set_status(f"VantageUI {action} cancelled. Nothing changed.")
            self._install_action = ""
            return False
        try:
            running = ui_skin_updater.game_running()
        except Exception as error:
            self._operation_failed(
                self._operation_token, "update", error)
            return False
        if running:
            self._queue_pending_update(self._release)
            return True
        return self._install_release(self._release)

    def _install_release(self, release):
        eq_root = normalize_eq_root(self.path_edit.text())
        action = self._install_action or self._primary_action_kind()
        progress_verb = {
            "install": "installing",
            "update": "updating",
            "repair": "repairing",
        }[action]
        return self._start(
            "update",
            lambda log: ui_skin_updater.install_release(
                release, eq_root, self.state_directory, log=log),
            f"Verifying, backing up, and {progress_verb} only VantageUI…")

    def _queue_pending_update(self, release):
        first_notice = self._pending_release is None
        self._pending_release = release
        self._pending_timer.start(PENDING_POLL_MS)
        target = skin_target(self.path_edit.text())
        message = (
            f"Installation queued for {target}. Close EverQuest normally and "
            "keep Vantage open; installation will continue automatically. "
            "Vantage will never close the game.")
        self.pending_message.setText(message)
        self.pending_banner.setAccessibleDescription(message)
        self.pending_banner.show()
        if first_notice:
            self._set_status(message)
        self._refresh_controls()

    def _clear_pending_wait(self):
        self._pending_timer.stop()
        self._pending_release = None
        self.pending_banner.hide()

    def _poll_pending_update(self):
        if self._pending_release is None or self._busy:
            return
        release = self._pending_release
        try:
            if ui_skin_updater.game_running():
                self._pending_timer.start(PENDING_POLL_MS)
                return
        except Exception as error:
            self._clear_pending_wait()
            self._install_action = ""
            self._operation_failed(self._operation_token, "wait", error)
            return
        self._clear_pending_wait()
        self._install_release(release)

    def restore_skin(self):
        if self._busy:
            return False
        if not self._confirm(
                "Restore VantageUI",
                "Restore the files replaced by the last VantageUI update?\n\n"
                "Later personal changes are protected and other skins are untouched."):
            self._set_status("Restore cancelled. Nothing changed.")
            return False
        try:
            if ui_skin_updater.game_running():
                self._set_status(
                    "Close EverQuest before Restore. Vantage will not stop it.")
                return False
        except Exception as error:
            self._operation_failed(self._operation_token, "restore", error)
            return False
        eq_root = normalize_eq_root(self.path_edit.text())
        return self._start(
            "restore",
            lambda log: ui_skin_updater.rollback_last(
                eq_root, self.state_directory, log=log),
            "Restoring the previous VantageUI files…")

    def _operation_completed(self, token, action, result):
        if token != self._operation_token:
            return
        self._busy = False
        if action == "local":
            self._installed = str(result or "")
            next_action = (
                "Install VantageUI" if not self._installed else
                "Update VantageUI")
            self._set_status(
                f"EverQuest folder ready. Choose {next_action}; Vantage will "
                "check the verified release first.")
        elif action == "check":
            self._release, self._installed = result
            newer = version_is_newer(self._installed, self._release.version)
            continue_install = self._install_after_check
            self._install_after_check = False
            if newer:
                self._set_status(
                    f"VantageUI {self._release.version} is available.")
            else:
                self._set_status(
                    "Installed VantageUI is current. Repair can verify its files.")
        elif action == "update":
            completed_action = self._install_action or "update"
            self._installed = result.version
            self._clear_pending_wait()
            self._set_status(
                f"VantageUI {completed_action} complete. In EverQuest use "
                "/loadskin VantageUI 1, "
                "then verify the UI in game.")
            self._install_action = ""
        elif action == "restore":
            self._installed = result.version
            self._set_status(
                "Previous VantageUI restored. Verify it in game with "
                "/loadskin VantageUI 1.")
        self._refresh_versions()
        self._refresh_controls()
        if action == "check":
            if continue_install:
                self.update_skin(confirm=True)
            elif newer and self.auto_update.isChecked():
                self.update_skin(confirm=False)

    def _operation_failed(self, token, action, error):
        if token != self._operation_token:
            return
        self._busy = False
        if action == "check":
            self._install_after_check = False
        message = str(error or "Unknown error")
        permission = (
            isinstance(error, PermissionError) or
            getattr(error, "winerror", None) == 5 or
            any(term in message.casefold() for term in (
                "permission denied", "access is denied")))
        if action == "update" and "close everquest" in message.casefold():
            self._queue_pending_update(self._release)
            return
        if permission:
            self.elevation_button.show()
            self._set_status(
                "Windows denied write access. Nothing unsafe was changed. "
                "Use the normal UAC button below or choose another valid installation; "
                "Vantage will not change folder permissions.")
        else:
            failed_action = self._install_action or action
            self._install_action = ""
            self._set_status(
                f"VantageUI {failed_action} failed safely: {message}. "
                "Nothing else was changed.")
        self._append_log(token, message)
        self._refresh_controls()

    def _auto_update_changed(self, enabled):
        self._save_settings()
        if enabled:
            self._automatic_timer.start()
            self.check_for_updates()
        else:
            self._automatic_timer.stop()
            self._clear_pending_wait()
            self._install_action = ""
            self._refresh_controls()
            self._set_status("Automatic VantageUI updates are off.")

    def _request_elevation(self):
        try:
            started = request_elevated_updater(self.path_edit.text())
        except (AttributeError, OSError) as error:
            started = False
            self._append_log(self._operation_token, str(error))
        self._set_status(
            "Windows UAC request opened in the dedicated VantageUI updater. "
            "This Companion remains installed and open."
            if started else
            "The Windows UAC updater could not start. Right-click the dedicated "
            "VantageUI updater and choose Run as administrator.")
