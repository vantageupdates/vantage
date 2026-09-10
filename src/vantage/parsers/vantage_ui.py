"""VantageUI installer panel backed by the verified updater core."""

from __future__ import annotations

import ctypes
from datetime import datetime
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import ResponsiveActionBar
from vantage.helpers import ui_skin_updater
from vantage.helpers.ui_profile_manager import (
    UIProfileError, apply_skin_to_all, copy_layout,
    discover_character_profiles, list_backups, read_elevated_profile_result,
    request_elevated_profile_action, restore_backup)


DEFAULT_EQ_ROOT = r"C:\Program Files (x86)\Sony\EverQuest"
AUTO_CHECK_MS = 5 * 60 * 1000


def normalize_eq_root(value):
    """Normalize common Browse results to the canonical EverQuest root."""
    text = str(value or "").strip().strip('"')
    if not text:
        return DEFAULT_EQ_ROOT
    path = Path(os.path.abspath(os.path.expanduser(text)))
    if path.name.casefold() == "eqgame.exe":
        path = path.parent
    folder = path.name
    versioned = False
    prefix = ui_skin_updater.SKIN_FOLDER + "-v"
    if folder.startswith(prefix):
        try:
            versioned = ui_skin_updater.folder_name(
                folder[len(prefix):]) == folder
        except (TypeError, ValueError, ui_skin_updater.SkinUpdateError):
            versioned = False
    if ((folder.casefold() == ui_skin_updater.SKIN_FOLDER.casefold() or
         versioned) and path.parent.name.casefold() == "uifiles"):
        path = path.parent.parent
    elif path.name.casefold() == "uifiles":
        path = path.parent
    return os.path.normpath(str(path))


def skin_target(eq_root, version):
    """Return the canonical destination for one verified release version."""
    return str(Path(normalize_eq_root(eq_root)) / "uifiles" /
               ui_skin_updater.folder_name(str(version)))


def _installed_selection(eq_root):
    """Read and cross-check the selected folder and reported version."""
    folder = ui_skin_updater.installed_folder(eq_root)
    version = ui_skin_updater.installed_version(eq_root)
    if bool(folder) != bool(version):
        raise ui_skin_updater.SkinUpdateError(
            "The selected VantageUI folder and version disagree.")
    if folder and ui_skin_updater.folder_name(version) != folder:
        raise ui_skin_updater.SkinUpdateError(
            "The selected VantageUI folder is not a verified versioned folder.")
    return version, folder


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
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    if is_frozen and current.is_file():
        program = str(current)
        arguments = subprocess.list2cmdline([
            "--vantage-ui-updater", "--allow-game-running",
            "--eq-dir", normalize_eq_root(eq_root)])
        return program, arguments
    source = (Path(source_script) if source_script is not None else
              Path(__file__).resolve().parents[3] / "vantage_ui_updater.py")
    if source.is_file():
        program = sys.executable
        arguments = subprocess.list2cmdline(
            [str(source), "--allow-game-running",
             "--eq-dir", normalize_eq_root(eq_root)])
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
    progress = Signal(int, str, int, int, int)


class CharacterUIManagerDialog(QDialog):
    """Reversible multi-character VantageUI and layout manager."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self._profiles = ()
        self._skin = ""
        self._queued_action = None
        self._pending_elevation = None
        self._poll_attempts = 0
        self.setWindowTitle("Character UI & layouts · VantageUI")
        self.setModal(False)
        self.resize(760, 590)
        self.setMinimumSize(620, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 10)
        root.setSpacing(7)
        intro = QLabel(
            "Update every character to the selected VantageUI version, or "
            "copy one character's complete window and chat layout to others. "
            "Macros, socials, friends, and hotkeys are never copied.")
        intro.setWordWrap(True)
        intro.setObjectName("VantageUIIntro")
        root.addWidget(intro)

        skin_card = QFrame()
        skin_card.setObjectName("VantageUICard")
        skin_layout = QGridLayout(skin_card)
        skin_layout.setContentsMargins(8, 7, 8, 7)
        skin_title = QLabel("1 · Update every character")
        skin_title.setObjectName("OpenDkpPanelTitle")
        skin_layout.addWidget(skin_title, 0, 0, 1, 2)
        self.skin_value = QLabel("No verified VantageUI selected")
        self.skin_value.setAccessibleName("VantageUI version for all characters")
        skin_layout.addWidget(self.skin_value, 1, 0, 1, 2)
        self.include_default = QCheckBox(
            "Also use this skin for new characters (eqclient.ini)")
        self.include_default.setChecked(True)
        self.include_default.setToolTip(
            "Updates only UISkin in eqclient.ini; all other game settings stay unchanged")
        skin_layout.addWidget(self.include_default, 2, 0)
        self.apply_all_button = QPushButton("Apply to all characters…")
        self.apply_all_button.setIcon(game_icon("ph-wand"))
        self.apply_all_button.setAccessibleName(
            "Apply selected VantageUI to every character")
        self.apply_all_button.setToolTip(
            "Back up every affected INI, then change only its UISkin value")
        self.apply_all_button.clicked.connect(self.apply_skin)
        skin_layout.addWidget(self.apply_all_button, 2, 1)
        skin_layout.setColumnStretch(0, 1)
        root.addWidget(skin_card)

        layout_card = QFrame()
        layout_card.setObjectName("VantageUICard")
        layout_grid = QGridLayout(layout_card)
        layout_grid.setContentsMargins(8, 7, 8, 7)
        layout_grid.setHorizontalSpacing(6)
        layout_grid.setVerticalSpacing(5)
        layout_title = QLabel("2 · Copy a character layout")
        layout_title.setObjectName("OpenDkpPanelTitle")
        layout_grid.addWidget(layout_title, 0, 0, 1, 3)
        source_label = QLabel("Copy from")
        self.source_combo = QComboBox()
        self.source_combo.setAccessibleName("Source character UI layout")
        self.source_combo.setToolTip(
            "Choose the character whose complete UI window layout is correct")
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        source_label.setBuddy(self.source_combo)
        layout_grid.addWidget(source_label, 1, 0)
        layout_grid.addWidget(self.source_combo, 1, 1, 1, 2)
        target_label = QLabel("Apply to")
        self.target_list = QListWidget()
        self.target_list.setAccessibleName("Characters receiving the copied layout")
        self.target_list.setToolTip(
            "Check every character that should receive the source window layout")
        target_label.setBuddy(self.target_list)
        layout_grid.addWidget(target_label, 2, 0, Qt.AlignmentFlag.AlignTop)
        layout_grid.addWidget(self.target_list, 2, 1, 1, 2)
        target_actions = QHBoxLayout()
        self.select_all_button = QPushButton("Select all others")
        self.select_all_button.setToolTip(
            "Select every character except the source")
        self.select_all_button.clicked.connect(self._select_all_targets)
        target_actions.addWidget(self.select_all_button)
        self.clear_targets_button = QPushButton("Clear")
        self.clear_targets_button.setToolTip("Clear all target characters")
        self.clear_targets_button.clicked.connect(self._clear_targets)
        target_actions.addWidget(self.clear_targets_button)
        target_actions.addStretch(1)
        self.copy_layout_button = QPushButton("Copy layout…")
        self.copy_layout_button.setIcon(game_icon("copy"))
        self.copy_layout_button.setAccessibleName(
            "Copy source UI layout to selected characters")
        self.copy_layout_button.setToolTip(
            "Back up each target, then copy window and chat layout only")
        self.copy_layout_button.clicked.connect(self.apply_layout)
        target_actions.addWidget(self.copy_layout_button)
        layout_grid.addLayout(target_actions, 3, 1, 1, 2)
        layout_grid.setColumnStretch(1, 1)
        root.addWidget(layout_card, 1)

        restore_card = QFrame()
        restore_card.setObjectName("VantageUICard")
        restore_layout = QGridLayout(restore_card)
        restore_layout.setContentsMargins(8, 7, 8, 7)
        restore_title = QLabel("Restore")
        restore_title.setObjectName("OpenDkpPanelTitle")
        restore_layout.addWidget(restore_title, 0, 0, 1, 2)
        self.backup_combo = QComboBox()
        self.backup_combo.setAccessibleName("Character UI backup to restore")
        self.backup_combo.setToolTip(
            "Choose any previous skin or layout operation to undo")
        restore_layout.addWidget(self.backup_combo, 1, 0)
        self.restore_button = QPushButton("Restore selected…")
        self.restore_button.setIcon(game_icon("ph-reload"))
        self.restore_button.setAccessibleName("Restore selected character UI backup")
        self.restore_button.setToolTip(
            "Back up the current files first, then restore this operation")
        self.restore_button.clicked.connect(self.restore_selected)
        restore_layout.addWidget(self.restore_button, 1, 1)
        restore_layout.setColumnStretch(0, 1)
        root.addWidget(restore_card)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Ready · 0%")
        self.progress.setAccessibleName("Character UI operation progress")
        root.addWidget(self.progress)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setObjectName("VantageUIStatus")
        self.status.setAccessibleName("Character UI manager status")
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)

        self._game_timer = QTimer(self)
        self._game_timer.setInterval(1000)
        self._game_timer.timeout.connect(self._run_queued_when_game_closes)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll_elevation)
        self.refresh()

    @property
    def state_directory(self):
        return data_dir("ui-profile-backups")

    def refresh(self):
        previous_source = str(self.source_combo.currentData() or "")
        try:
            root = normalize_eq_root(self.panel.path_edit.text())
            self._profiles = discover_character_profiles(root)
            skin = ui_skin_updater.installed_folder(root)
            self._skin = skin
            backups = list_backups(self.state_directory, root)
        except (OSError, UIProfileError, ui_skin_updater.SkinUpdateError) as error:
            self._profiles, self._skin, skin, backups = (), "", "", ()
            self._set_status(f"Cannot load character UI profiles · {error}", error=True)
        self.skin_value.setText(
            f"Selected: {skin} · {len(self._profiles)} characters detected"
            if skin else
            f"No verified VantageUI selected · {len(self._profiles)} characters detected")
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for profile in self._profiles:
            self.source_combo.addItem(
                f"{profile.label} · {profile.skin or 'no skin'}", profile.filename)
        index = self.source_combo.findData(previous_source)
        self.source_combo.setCurrentIndex(max(0, index))
        self.source_combo.blockSignals(False)
        self._rebuild_targets()
        self.backup_combo.clear()
        for backup in backups:
            try:
                created = datetime.fromisoformat(
                    backup.created_utc.replace("Z", "+00:00")).astimezone()
                when = created.strftime("%b %d, %Y · %I:%M %p")
            except (TypeError, ValueError):
                when = backup.created_utc[:19]
            self.backup_combo.addItem(
                f"{when} · {backup.label} · {backup.file_count} files",
                backup.backup_id)
        ready = bool(skin and self._profiles)
        self.apply_all_button.setEnabled(ready)
        self.copy_layout_button.setEnabled(ready and len(self._profiles) > 1)
        self.restore_button.setEnabled(self.backup_combo.count() > 0)
        if ready and not self._queued_action and not self._pending_elevation:
            self._set_status(
                f"Ready · {len(self._profiles)} character UI profiles · backups enabled",
                announce=False)

    def _rebuild_targets(self):
        source = str(self.source_combo.currentData() or "")
        previously_checked = {
            str(self.target_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.target_list.count())
            if self.target_list.item(index).checkState() == Qt.CheckState.Checked}
        self.target_list.clear()
        for profile in self._profiles:
            item = QListWidgetItem(profile.label)
            item.setData(Qt.ItemDataRole.UserRole, profile.filename)
            selectable = profile.filename != source
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                if selectable else item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(
                Qt.CheckState.Checked if selectable and (
                    not previously_checked or profile.filename in previously_checked)
                else Qt.CheckState.Unchecked)
            if not selectable:
                item.setToolTip("This is the source character")
            self.target_list.addItem(item)

    def _source_changed(self, _index):
        self._rebuild_targets()

    def _select_all_targets(self):
        source = str(self.source_combo.currentData() or "")
        for index in range(self.target_list.count()):
            item = self.target_list.item(index)
            item.setCheckState(
                Qt.CheckState.Unchecked
                if item.data(Qt.ItemDataRole.UserRole) == source else
                Qt.CheckState.Checked)

    def _clear_targets(self):
        for index in range(self.target_list.count()):
            self.target_list.item(index).setCheckState(Qt.CheckState.Unchecked)

    def _checked_targets(self):
        return [
            str(self.target_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.target_list.count())
            if self.target_list.item(index).checkState() == Qt.CheckState.Checked]

    def _confirm(self, title, text):
        dialog = QMessageBox(
            QMessageBox.Icon.Question, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def apply_skin(self):
        root = normalize_eq_root(self.panel.path_edit.text())
        try:
            skin = ui_skin_updater.installed_folder(root)
        except (OSError, ui_skin_updater.SkinUpdateError) as error:
            self._set_status(f"Cannot verify VantageUI · {error}", error=True)
            return False
        count = len(self._profiles) + int(
            self.include_default.isChecked() and (Path(root) / "eqclient.ini").is_file())
        if not skin or not self._profiles:
            self._set_status("Install or select VantageUI and refresh first", error=True)
            return False
        if not self._confirm(
                "Apply VantageUI to all characters",
                f"Change only UISkin to {skin} in {count} INI files?\n\n"
                "Every affected file is backed up first. Macros, socials, "
                "friends, hotkeys, and window positions stay unchanged."):
            return False
        return self._run_or_queue("skin", {
            "skin_folder": skin,
            "include_eqclient": self.include_default.isChecked()})

    def apply_layout(self):
        root = normalize_eq_root(self.panel.path_edit.text())
        try:
            skin = ui_skin_updater.installed_folder(root)
        except (OSError, ui_skin_updater.SkinUpdateError) as error:
            self._set_status(f"Cannot verify VantageUI · {error}", error=True)
            return False
        source = str(self.source_combo.currentData() or "")
        targets = self._checked_targets()
        if not skin or not source or not targets:
            self._set_status("Choose a source and at least one target character", error=True)
            return False
        source_label = self.source_combo.currentText().split(" · ", 1)[0]
        if not self._confirm(
                "Copy character UI layout",
                f"Copy {source_label}'s complete window and chat layout to "
                f"{len(targets)} selected characters?\n\nEach target is backed up "
                "first. Character macros, socials, friends, and hotkeys are in "
                "separate files and are never copied."):
            return False
        return self._run_or_queue("layout", {
            "skin_folder": skin, "source": source, "targets": targets})

    def restore_selected(self):
        backup_id = str(self.backup_combo.currentData() or "")
        if not backup_id:
            self._set_status("Choose a backup to restore", error=True)
            return False
        if not self._confirm(
                "Restore character UI backup",
                "Restore every file in the selected operation?\n\nVantage first "
                "backs up the current files, so this restore can also be undone."):
            return False
        return self._run_or_queue("restore", {"backup_id": backup_id})

    def _run_or_queue(self, action, options):
        try:
            running = ui_skin_updater.game_running()
        except Exception as error:
            self._set_status(f"Cannot safely check EverQuest · {error}", error=True)
            return False
        if running:
            self._queued_action = (action, dict(options))
            self._set_busy(True)
            self._game_timer.start()
            self._set_status(
                "Queued · close EverQuest once; Vantage will apply this operation "
                "automatically and will never close the game")
            return True
        return self._execute(action, options)

    def _run_queued_when_game_closes(self):
        if self._queued_action is None:
            self._game_timer.stop()
            return
        try:
            if ui_skin_updater.game_running():
                return
        except Exception as error:
            self._queued_action = None
            self._game_timer.stop()
            self._set_busy(False)
            self._set_status(f"Queued operation stopped · {error}", error=True)
            return
        action, options = self._queued_action
        self._queued_action = None
        self._game_timer.stop()
        self._execute(action, options)

    def _execute(self, action, options):
        root = normalize_eq_root(self.panel.path_edit.text())
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Working…")
        try:
            if action == "skin":
                result = apply_skin_to_all(
                    root, options["skin_folder"], self.state_directory,
                    include_eqclient=bool(options.get("include_eqclient", True)))
            elif action == "layout":
                result = copy_layout(
                    root, options["skin_folder"], options["source"],
                    options["targets"], self.state_directory)
            else:
                result = restore_backup(
                    root, self.state_directory, options["backup_id"])
        except OSError as error:
            permission_denied = (
                isinstance(error, PermissionError) or
                getattr(error, "winerror", None) == 5 or
                "permission denied" in str(error).casefold() or
                "access is denied" in str(error).casefold())
            if permission_denied:
                return self._request_elevation(action, root, options)
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status(f"Operation failed · {error}", error=True)
            return False
        except (UIProfileError, ui_skin_updater.SkinUpdateError) as error:
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status(f"Operation not applied · {error}", error=True)
            return False
        self._finish(action, result.changed, result.backup_id)
        return True

    def _request_elevation(self, action, root, options):
        pending = request_elevated_profile_action(action, root, **options)
        if pending is None:
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status(
                "Windows permission was not granted; nothing was changed", error=True)
            return False
        self._pending_elevation = pending
        self._poll_attempts = 0
        self._poll_timer.start()
        self._set_status(
            "Approve the Windows permission prompt; Vantage will finish this "
            "profile operation automatically")
        return True

    def _poll_elevation(self):
        pending = self._pending_elevation
        if pending is None:
            self._poll_timer.stop()
            return
        self._poll_attempts += 1
        try:
            result = read_elevated_profile_result(pending)
        except (OSError, UIProfileError, json.JSONDecodeError) as error:
            self._pending_elevation = None
            self._poll_timer.stop()
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status(f"Invalid Windows response · {error}", error=True)
            return
        if result is None:
            if self._poll_attempts < 480:
                return
            pending.request_path.unlink(missing_ok=True)
            self._pending_elevation = None
            self._poll_timer.stop()
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status("Windows permission request timed out", error=True)
            return
        self._pending_elevation = None
        self._poll_timer.stop()
        if not result.get("ok"):
            self._set_busy(False)
            self.progress.setRange(0, 100)
            self._set_status(
                f"Operation not applied · {result.get('error', 'permission denied')}",
                error=True)
            return
        self._finish(
            str(result.get("action") or "operation"),
            int(result.get("changed") or 0), str(result.get("backup_id") or ""))

    def _finish(self, action, changed, backup_id):
        labels = {
            "skin": "VantageUI applied", "layout": "Layout copied",
            "restore": "Backup restored"}
        self._set_busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Complete · 100%")
        self.refresh()
        self._set_status(
            f"{labels.get(action, 'Operation complete')} · {changed} files · "
            f"restore point {backup_id[:8]}")

    def _set_busy(self, busy):
        for control in (
                self.include_default, self.backup_combo, self.source_combo,
                self.target_list, self.select_all_button,
                self.clear_targets_button):
            control.setEnabled(not busy)
        ready = bool(self._skin and self._profiles)
        self.apply_all_button.setEnabled(not busy and ready)
        self.copy_layout_button.setEnabled(
            not busy and ready and len(self._profiles) > 1)
        self.restore_button.setEnabled(
            not busy and self.backup_combo.count() > 0)

    def _set_status(self, text, *, error=False, announce=True):
        self.status.setText(str(text))
        self.status.setProperty("state", "error" if error else "ready")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setAccessibleDescription(str(text))
        if announce:
            try:
                event = QAccessibleAnnouncementEvent(self.status, str(text))
                QAccessible.updateAccessibility(event)
            except (AttributeError, RuntimeError):
                pass


class VantageUI(ParserWindow):
    """Independent, non-blocking VantageUI management surface."""

    name = "vantage_ui"
    update_state_changed = Signal(object)
    _allow_clickthrough = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VantageUI")
        self._title.setText("VantageUI")
        self._signals = _WorkerSignals(self)
        self._signals.completed.connect(self._operation_completed)
        self._signals.failed.connect(self._operation_failed)
        self._signals.log.connect(self._append_log)
        self._signals.progress.connect(self._operation_progress)
        self._operation_token = 0
        self._busy = False
        self._active_action = ""
        self._update_check_error = ""
        self._loaded_once = False
        self._installed = ""
        self._installed_folder = ""
        self._release = None
        self._install_after_check = False
        self._install_action = ""
        self._progress_value = 0
        self._progress_stage = "Ready"
        self._announced_progress_stage = ""
        self._announced_progress_milestone = 0
        self._operation_announcements = True
        self._progress_updates_enabled = True
        self._initiating_control = None
        self._last_warnings = ()
        self._shared_update_controller = None
        self._profile_manager = None
        self._automatic_timer = QTimer(self)
        self._automatic_timer.setInterval(AUTO_CHECK_MS)
        self._automatic_timer.timeout.connect(self._automatic_check)
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
        self.path_edit.setAccessibleDescription(
            "EverQuest root containing eqgame.exe and uifiles; each verified "
            "VantageUI release uses its own versioned folder")
        self.path_edit.setToolTip(
            "EverQuest root containing eqgame.exe and the uifiles folder")
        self.path_edit.editingFinished.connect(self._path_edited)
        path_label.setBuddy(self.path_edit)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.setIcon(game_icon("ph-folder-open"))
        self.browse_button.setAccessibleName("Browse for EverQuest folder")
        self.browse_button.setToolTip(
            "Select the EverQuest root; VantageUI always installs below uifiles")
        self.browse_button.clicked.connect(self.browse)
        path_layout.addWidget(path_label, 0, 0)
        path_layout.addWidget(self.path_edit, 0, 1)
        path_layout.addWidget(self.browse_button, 0, 2)
        target_caption = QLabel("Versioned folders")
        self.target_value = QLabel()
        self.target_value.setWordWrap(True)
        self.target_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard |
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_value.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.target_value.setAccessibleName(
            "Selected and available VantageUI folders")
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
            "Select the previous verified VantageUI folder without overwriting files")
        self.restore_button.clicked.connect(self.restore_skin)
        actions.addWidget(self.restore_button)
        self.copy_command_button = QPushButton("Copy /loadskin")
        self.copy_command_button.setIcon(game_icon("copy"))
        self.copy_command_button.setAccessibleName(
            "Copy the selected VantageUI loadskin command")
        self.copy_command_button.setToolTip(
            "Copy the exact /loadskin command for the selected verified folder")
        self.copy_command_button.clicked.connect(self.copy_loadskin_command)
        actions.addWidget(self.copy_command_button)
        self.character_ui_button = QPushButton("Character UI & layouts…")
        self.character_ui_button.setIcon(game_icon("ph-stack"))
        self.character_ui_button.setAccessibleName(
            "Manage character VantageUI settings and layouts")
        self.character_ui_button.setToolTip(
            "Back up and update every character's selected VantageUI, copy "
            "one character's window layout to others, or restore a backup")
        self.character_ui_button.clicked.connect(self.show_profile_manager)
        actions.addWidget(self.character_ui_button)
        layout.addWidget(actions)

        # Keep the primary action in the ordinary left-to-right keyboard path.
        # Native buttons retain Enter/Space activation and the shared focus ring.
        QWidget.setTabOrder(self.path_edit, self.browse_button)
        QWidget.setTabOrder(self.browse_button, self.target_value)
        QWidget.setTabOrder(self.target_value, self.check_button)
        QWidget.setTabOrder(self.check_button, self.update_button)
        QWidget.setTabOrder(self.update_button, self.restore_button)
        QWidget.setTabOrder(
            self.restore_button, self.copy_command_button)
        QWidget.setTabOrder(
            self.copy_command_button, self.character_ui_button)

        self.auto_update = QCheckBox("Automatically check and update VantageUI")
        self.auto_update.setChecked(bool(
            config.data["vantage_ui"].get("auto_update", False)))
        self.auto_update.setAccessibleName("Automatic VantageUI updates")
        self.auto_update.setToolTip(
            "Opt in to checks every five minutes and verified live installation; "
            "reload VantageUI in EverQuest after an update")
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

        self.progress = QProgressBar()
        self.progress.setObjectName("UpdateProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Ready · 0%")
        self.progress.setAccessibleName("VantageUI operation progress")
        self.progress.setAccessibleDescription(
            "Ready. No VantageUI operation is running.")
        self.progress.setToolTip(
            "Progress for checking, installing, updating, or restoring VantageUI")
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setObjectName("VantageUILog")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(80)
        self.log.setAccessibleName("VantageUI operation details")
        self.log.setToolTip("Recent verified update and recovery details")
        layout.addWidget(self.log, 1)

        self.instruction = QLabel(
            "Install or select a verified VantageUI version to get its exact "
            "<b>/loadskin</b> command.")
        self.instruction.setAccessibleName("VantageUI loadskin command")
        self.instruction.setAccessibleDescription(
            "Shows the exact EverQuest command for the selected versioned folder")
        self.instruction.setToolTip(
            "Use the selected folder's command after installation or restore")
        self.instruction.setWordWrap(True)
        self.instruction.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.instruction)
        scope = QLabel(
            "Only verified uifiles\\VantageUI-vX.Y.Z folders are managed. The "
            "legacy VantageUI folder and other skins are never changed. Character "
            "UI_*.ini files change only through Character UI & layouts, with a "
            "restore point first. Character settings INIs, game binaries, running "
            "processes, and Companion are never replaced.")
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
        self.update_state_changed.emit(self.update_snapshot())
        if announce and self._operation_announcements:
            self._announce(text)

    def _append_log(self, token, text):
        if token == self._operation_token:
            self.log.appendPlainText(str(text))

    def _refresh_target(self):
        eq_root = normalize_eq_root(self.path_edit.text())
        base = Path(eq_root) / "uifiles"
        selected = (
            str(base / self._installed_folder)
            if self._installed_folder else "Not installed")
        upcoming = (
            skin_target(eq_root, self._release.version)
            if self._release else "Not checked")
        text = f"Selected: {selected}\nNext install: {upcoming}"
        self.target_value.setText(text)
        self.target_value.setAccessibleDescription(text)

    def _loadskin_command(self):
        if not self._installed_folder:
            return ""
        return f"/loadskin {self._installed_folder} 1"

    def _refresh_instruction(self):
        command = self._loadskin_command()
        if command:
            self.instruction.setText(
                "In EverQuest, load the selected version with "
                f"<b>{html.escape(command)}</b>, then verify it in game.")
            description = (
                f"Selected VantageUI command: {command}. Verify the UI in game.")
        else:
            self.instruction.setText(
                "Install or select a verified VantageUI version to get its "
                "exact <b>/loadskin</b> command.")
            description = (
                "No verified VantageUI folder is selected. Install or restore "
                "a version to get its exact EverQuest loadskin command.")
        self.instruction.setAccessibleDescription(description)

    def _refresh_versions(self):
        self.installed_value.setText(self._installed or "Not installed")
        self.available_value.setText(
            self._release.version if self._release else "Not checked")
        installed_description = (
            f"Installed VantageUI {self._installed}, selected folder "
            f"{self._installed_folder}."
            if self._installed and self._installed_folder else
            "No verified versioned VantageUI installation is selected.")
        self.installed_value.setAccessibleDescription(installed_description)
        self.available_value.setAccessibleDescription(
            f"Available VantageUI version {self._release.version}."
            if self._release else
            "The available VantageUI version has not been checked.")
        self._refresh_target()
        self._refresh_instruction()
        self.update_state_changed.emit(self.update_snapshot())

    def update_snapshot(self):
        """Small read-only bridge for the independent Companion update dialog."""
        available = self._release.version if self._release else ""
        return {
            "installed": self._installed or "",
            "installed_folder": self._installed_folder or "",
            "loadskin_command": self._loadskin_command(),
            "available": available,
            "busy": bool(self._busy),
            "checking": bool(
                self._busy and self._active_action == "check"),
            "update_available": bool(
                self._installed and available and
                version_is_newer(self._installed, available)),
            "check_error": self._update_check_error,
            "auto_update": bool(
                hasattr(self, "auto_update") and
                self.auto_update.isChecked()),
            "status": self.status.text() if hasattr(self, "status") else "",
            "warnings": self._last_warnings,
        }

    def use_shared_update_controller(self, controller):
        """Use one Companion-owned release feed for integrated background work."""
        if controller is self._shared_update_controller:
            return True
        previous = self._shared_update_controller
        if previous is not None:
            for name, callback in (
                    ("release_history_ready", self.consume_release_history),
                    ("check_failed", self.shared_release_history_failed)):
                try:
                    getattr(previous, name).disconnect(callback)
                except (AttributeError, RuntimeError, TypeError):
                    pass
        if (controller is None or
                getattr(controller, "release_history_ready", None) is None or
                getattr(controller, "check_failed", None) is None or
                not callable(getattr(controller, "check", None))):
            self._shared_update_controller = None
            if self.auto_update.isChecked():
                self._automatic_timer.start()
            return False
        self._shared_update_controller = controller
        controller.release_history_ready.connect(self.consume_release_history)
        controller.check_failed.connect(self.shared_release_history_failed)
        # The integrated Companion heartbeat owns periodic discovery. Keeping
        # this independent timer running would double-hit the same GitHub API.
        self._automatic_timer.stop()
        description = (
            "Uses the Companion's shared periodic release check and installs "
            "verified VantageUI updates; no second background request is made")
        self.auto_update.setToolTip(description)
        self.auto_update.setAccessibleDescription(description)
        return True

    def consume_release_history(self, payload, background=True):
        """Select VantageUI from a shared history without network activity."""
        if self._busy:
            return False
        eq_root = normalize_eq_root(self.path_edit.text())
        try:
            release = ui_skin_updater.select_release_history(payload)
            installed, folder = _installed_selection(eq_root)
        except (OSError, TypeError, ValueError,
                ui_skin_updater.SkinUpdateError) as error:
            self.shared_release_history_failed(str(error))
            return False
        self._release = release
        self._installed = installed
        self._installed_folder = folder
        self._update_check_error = ""
        self._refresh_versions()
        self._refresh_controls()
        if (self.auto_update.isChecked() and
                version_is_newer(installed, release.version)):
            return self.update_skin(confirm=False, background=True)
        return True

    def shared_release_history_failed(self, message):
        """Record a background feed failure without focus or live announcements."""
        self._update_check_error = " ".join(str(message or "").split())
        self.update_state_changed.emit(self.update_snapshot())

    def _automatic_check(self):
        if self._shared_update_controller is not None:
            return self._shared_update_controller.check()
        return self.check_for_updates(background=True)

    def _primary_action_kind(self):
        if not self._installed:
            return "install"
        if (self._release is not None and
                not version_is_newer(self._installed, self._release.version)):
            return "current"
        return "update"

    def _refresh_primary_action(self):
        kind = self._primary_action_kind()
        if kind == "install":
            text = "Install VantageUI"
            tooltip = (
                "Check for the verified release, then install its versioned "
                "VantageUI folder; if EverQuest is open, reload the skin afterward")
        elif kind == "current":
            text = "VantageUI is current"
            tooltip = (
                "The selected verified VantageUI version matches the available release")
        else:
            text = "Update VantageUI"
            tooltip = (
                "Check and install the release into a new verified versioned folder")
        self.update_button.setText(text)
        self.update_button.setAccessibleName(text)
        self.update_button.setToolTip(tooltip)

    def _refresh_controls(self):
        self._refresh_primary_action()
        for control in (
                self.path_edit, self.browse_button, self.check_button,
                self.restore_button, self.copy_command_button,
                self.character_ui_button, self.auto_update):
            control.setEnabled(not self._busy)
        self.copy_command_button.setEnabled(
            not self._busy and bool(self._installed_folder))
        self.update_button.setEnabled(
            not self._busy and self._primary_action_kind() != "current")

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
        self._installed_folder = ""
        self._last_warnings = ()
        self._install_after_check = False
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

    def copy_loadskin_command(self):
        """Copy the updater-selected folder command without taking focus."""
        if self._busy:
            return False
        try:
            command = ui_skin_updater.loadskin_command(
                normalize_eq_root(self.path_edit.text()))
        except (OSError, ui_skin_updater.SkinUpdateError) as error:
            self._set_status(
                f"Could not verify the selected VantageUI command: {error}")
            return False
        if not command:
            self._set_status(
                "No verified VantageUI folder is selected. Install or restore one first.")
            return False
        QApplication.clipboard().setText(command)
        self._set_status(f"Copied {command}")
        return True

    def show_profile_manager(self):
        """Open the reversible character UI workflow without duplicating it."""
        if self._profile_manager is None:
            self._profile_manager = CharacterUIManagerDialog(self)
        self._profile_manager.refresh()
        self._profile_manager.show()
        self._profile_manager.raise_()
        self._profile_manager.activateWindow()
        return self._profile_manager

    def _panel_owns_active_focus(self):
        focused = QApplication.focusWidget()
        return bool(
            self.isVisible() and QApplication.activeWindow() is self and
            focused is not None and
            (focused is self or self.isAncestorOf(focused)))

    def _start(self, action, callback, status, *, restore_focus=True,
               announce=True):
        if self._busy:
            return False
        focused = self._surface.focusWidget()
        self._initiating_control = (
            focused if restore_focus and self._panel_owns_active_focus() and
            focused is not None and
            (focused is self._surface or self._surface.isAncestorOf(focused))
            else None)
        self._busy = True
        self._active_action = action
        self._operation_announcements = bool(announce)
        self._progress_updates_enabled = bool(announce)
        if action == "check":
            self._update_check_error = ""
        self._operation_token += 1
        token = self._operation_token
        self._progress_value = 0
        self._progress_stage = status
        self._announced_progress_stage = str(status).strip().casefold()
        self._announced_progress_milestone = 0
        if self._progress_updates_enabled:
            self.progress.setValue(0)
            self.progress.setFormat("Starting · 0%")
            self.progress.setAccessibleDescription(f"{status} 0 percent.")
        self.elevation_button.hide()
        self._set_status(status)
        self._refresh_controls()

        def run():
            try:
                result = callback(
                    lambda message: self._signals.log.emit(token, str(message)),
                    self._progress_callback(token))
            except BaseException as error:
                self._signals.failed.emit(token, action, error)
            else:
                self._signals.completed.emit(token, action, result)

        threading.Thread(
            target=run, name=f"VantageUI-{action}", daemon=True).start()
        return True

    def _progress_callback(self, token):
        return lambda stage, percent, received=0, total=0: self._signals.progress.emit(
            token, str(stage), int(percent), int(received), int(total))

    def _operation_progress(self, token, stage, percent, received, total):
        if token != self._operation_token or not self._busy:
            return
        stage = str(stage).strip() or "Working"
        value = max(self._progress_value, min(100, max(0, int(percent))))
        self._progress_value = value
        self._progress_stage = stage
        detail = f"{stage}. {value} percent."
        if total > 0:
            detail += f" {received} of {total} bytes received."
        if self._progress_updates_enabled:
            self.progress.setValue(value)
            self.progress.setFormat(f"{stage} · {value}%")
            self.progress.setAccessibleDescription(detail)
        stage_key = stage.casefold()
        stage_changed = stage_key != self._announced_progress_stage
        milestone = min(100, (value // 25) * 25)
        milestone_changed = (
            milestone >= 25 and
            milestone > self._announced_progress_milestone)
        if stage_changed or milestone_changed:
            self._announced_progress_stage = stage_key
            if milestone_changed:
                self._announced_progress_milestone = milestone
            status = stage
            if milestone_changed:
                status += f" · {milestone}%"
            self._set_status(status, announce=True)

    def _consume_initiating_control(self):
        initiating = self._initiating_control
        self._initiating_control = None
        return initiating

    def _focus_after_operation(self, preferred=None, *, initiating=None):
        """Return keyboard focus after an asynchronous panel operation."""
        if initiating is None or not self._panel_owns_active_focus():
            return False
        focused = self._surface.focusWidget()
        if (focused is not None and focused is not initiating and
                focused.isEnabled() and
                (focused is self._surface or
                 self._surface.isAncestorOf(focused))):
            # The user deliberately moved to another usable control while the
            # operation ran (commonly the log). Preserve that reading context.
            return False
        candidates = (
            preferred, self.update_button, self.check_button,
            self.restore_button, self.path_edit)

        def restore():
            if not self._panel_owns_active_focus():
                return
            for control in candidates:
                if (control is not None and control.isVisibleTo(self) and
                        control.isEnabled() and
                        control.focusPolicy() != Qt.FocusPolicy.NoFocus):
                    self._surface.setFocusProxy(control)
                    self._scale_view.setFocus(
                        Qt.FocusReason.OtherFocusReason)
                    self._scale_scene.setFocus(
                        Qt.FocusReason.OtherFocusReason)
                    self._scale_proxy.setFocusPolicy(
                        Qt.FocusPolicy.StrongFocus)
                    self._scale_scene.setActivePanel(self._scale_proxy)
                    self._scale_scene.setFocusItem(
                        self._scale_proxy,
                        Qt.FocusReason.OtherFocusReason)
                    self._scale_proxy.setFocus(
                        Qt.FocusReason.OtherFocusReason)
                    self._surface.setFocus(
                        Qt.FocusReason.OtherFocusReason)
                    control.setFocus(Qt.FocusReason.OtherFocusReason)
                    return

        def activate():
            if not self._panel_owns_active_focus():
                return
            self._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
            QTimer.singleShot(0, restore)

        QTimer.singleShot(0, activate)
        return True

    def _retry_control(self, action, initiating=None):
        if (initiating is not None and initiating in (
                self.check_button, self.update_button, self.restore_button)):
            return initiating
        return {
            "check": self.check_button,
            "restore": self.restore_button,
            "update": self.update_button,
        }.get(action, self.update_button)

    def refresh_local(self):
        eq_root = normalize_eq_root(self.path_edit.text())

        def read_local(log, progress):
            ui_skin_updater.recover_pending(
                eq_root, self.state_directory, log=log,
                allow_game_running=True, progress=progress)
            return _installed_selection(eq_root)

        return self._start(
            "local", read_local,
            "Checking the selected EverQuest folder and recovery state…")

    def check_for_updates(self, *, background=False):
        if background and self._shared_update_controller is not None:
            return self._shared_update_controller.check()
        eq_root = normalize_eq_root(self.path_edit.text())

        def check(_log, progress):
            installed, folder = _installed_selection(eq_root)
            release = ui_skin_updater.check_release(progress=progress)
            return release, installed, folder

        return self._start(
            "check", check,
            "Checking the official verified VantageUI release…",
            restore_focus=not background, announce=not background)

    def _confirm(self, title, text):
        dialog = QMessageBox(
            QMessageBox.Icon.Question, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def update_skin(self, _checked=False, confirm=True, *, background=False):
        if self._busy:
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
        if action == "current":
            self._set_status(
                f"VantageUI {self._installed} is already the selected current release.")
            return False
        self._install_action = action
        title = {
            "install": "Install VantageUI",
            "update": "Update VantageUI",
        }[action]
        next_folder = ui_skin_updater.folder_name(self._release.version)
        prompt = {
            "install": f"Install verified release files in uifiles\\{next_folder}?",
            "update": f"Install the update in a new uifiles\\{next_folder} folder?",
        }[action]
        if confirm and not self._confirm(
                title, prompt + "\n\n"
                "The selected version and one previous restore version are kept. "
                "Modified, unmanaged, and legacy VantageUI folders are preserved. "
                "Vantage never closes or signals EverQuest. If EverQuest is open, "
                "do not reload the UI during installation; after success, run "
                f"/loadskin {next_folder} 1 to apply the new files."):
            self._set_status(f"VantageUI {action} cancelled. Nothing changed.")
            self._install_action = ""
            return False
        if background:
            return self._install_release(self._release, background=True)
        return self._install_release(self._release)

    def _install_release(self, release, *, background=False):
        eq_root = normalize_eq_root(self.path_edit.text())
        action = self._install_action or self._primary_action_kind()
        progress_verb = {
            "install": "installing",
            "update": "updating",
        }[action]
        return self._start(
            "update",
            lambda log, progress: ui_skin_updater.install_release(
                release, eq_root, self.state_directory, log=log,
                allow_game_running=True, progress=progress),
            "Updating — do not reload the UI yet. "
            f"Vantage is safely {progress_verb} only VantageUI…",
            restore_focus=not background, announce=not background)

    def restore_skin(self):
        if self._busy:
            return False
        if not self._confirm(
                "Restore VantageUI",
                "Select the previous verified VantageUI folder?\n\n"
                "No UI files or character INIs will be overwritten. After restore, "
                "use the command shown by Vantage to load that version.\n\n"
                "EverQuest must be closed for this selection change."):
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
        if self.auto_update.isChecked():
            self.auto_update.setChecked(False)
        eq_root = normalize_eq_root(self.path_edit.text())
        return self._start(
            "restore",
            lambda log, progress: ui_skin_updater.rollback_last(
                eq_root, self.state_directory, log=log, progress=progress),
            "Selecting the previous verified VantageUI folder…")

    def _operation_completed(self, token, action, result):
        if token != self._operation_token:
            return
        initiating = self._consume_initiating_control()
        self._busy = False
        if action == "check":
            self._update_check_error = ""
        self._progress_value = 100
        if self._progress_updates_enabled:
            self.progress.setValue(100)
        if action == "local":
            self._installed, self._installed_folder = result
            next_action = (
                "Install VantageUI" if not self._installed else
                "Update VantageUI")
            self._set_status(
                f"EverQuest folder ready. Choose {next_action}; Vantage will "
                "check the verified release first. The legacy VantageUI folder "
                "is preserved and is not treated as a versioned installation.")
        elif action == "check":
            self._release, self._installed, self._installed_folder = result
            newer = version_is_newer(self._installed, self._release.version)
            continue_install = self._install_after_check
            self._install_after_check = False
            if newer:
                self._set_status(
                    f"VantageUI {self._release.version} is available.")
            else:
                self._set_status(
                    "The selected verified VantageUI version is current.")
        elif action == "update":
            completed_action = self._install_action or "update"
            self._installed = result.version
            self._installed_folder = result.folder
            self._last_warnings = tuple(result.warnings)
            for warning in self._last_warnings:
                self._append_log(token, warning)
            command = self._loadskin_command()
            self._set_status(
                f"VantageUI {completed_action} complete. In EverQuest use "
                f"{command}, then verify the UI in game."
                + (" Some folders were preserved; review the operation details."
                   if self._last_warnings else ""))
            self._install_action = ""
        elif action == "restore":
            self._installed = result.version
            self._installed_folder = result.folder
            self._last_warnings = tuple(result.warnings)
            for warning in self._last_warnings:
                self._append_log(token, warning)
            self._set_status(
                "Previous verified VantageUI selected. Verify it in game with "
                f"{self._loadskin_command()}.")
        final_text = self.status.text()
        if self._progress_updates_enabled:
            self.progress.setFormat("Complete · 100%")
            self.progress.setAccessibleDescription(
                f"VantageUI operation complete. 100 percent. {final_text}")
        self._refresh_versions()
        self._refresh_controls()
        if action == "check":
            if continue_install:
                if (initiating is not None and
                        self._panel_owns_active_focus()):
                    if (initiating.isEnabled() and
                            initiating.isVisibleTo(self)):
                        self._surface.setFocusProxy(initiating)
                        initiating.setFocus(
                            Qt.FocusReason.OtherFocusReason)
                    self.update_skin(confirm=True)
                else:
                    self._set_status(
                        "VantageUI check complete. Click Install VantageUI "
                        "to review and continue.")
            elif newer and self.auto_update.isChecked():
                self.update_skin(confirm=False, background=True)
            else:
                self._focus_after_operation(
                    self.update_button, initiating=initiating)
        else:
            self._focus_after_operation(
                self.update_button, initiating=initiating)
        if not self._busy:
            self._active_action = ""
            self._operation_announcements = True
            self._progress_updates_enabled = True

    def _operation_failed(self, token, action, error):
        if token != self._operation_token:
            return
        initiating = self._consume_initiating_control()
        self._busy = False
        if action == "check":
            self._install_after_check = False
        message = str(error or "Unknown error")
        if action == "check":
            self._update_check_error = message
        sharing = (
            getattr(error, "winerror", None) in (32, 33) or
            any(term in message.casefold() for term in (
                "being used by another process", "sharing violation",
                "cannot access the file because it is being used")))
        permission = (
            not sharing and (isinstance(error, PermissionError) or
            getattr(error, "winerror", None) == 5 or
            any(term in message.casefold() for term in (
                "permission denied", "access is denied"))))
        if sharing:
            self._install_action = ""
            self._set_status(
                f"VantageUI update stopped safely because Windows locked a file: "
                f"{message} Close any tool using that file and try again. "
                "Do not reload the UI; installation did not complete.")
        elif permission:
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
        if self._progress_updates_enabled:
            self.progress.setFormat(f"Failed · {self._progress_value}%")
            self.progress.setAccessibleDescription(
                f"VantageUI operation failed at {self._progress_value} percent. "
                f"{self.status.text()}")
        self._refresh_controls()
        if permission:
            self._focus_after_operation(
                self.elevation_button, initiating=initiating)
        else:
            self._focus_after_operation(
                self._retry_control(action, initiating),
                initiating=initiating)
        self._active_action = ""
        self._operation_announcements = True
        self._progress_updates_enabled = True

    def _auto_update_changed(self, enabled):
        self._save_settings()
        if enabled:
            if self._shared_update_controller is not None:
                self._automatic_timer.stop()
                self._shared_update_controller.check()
            else:
                self._automatic_timer.start()
                self.check_for_updates(background=True)
        else:
            self._automatic_timer.stop()
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
