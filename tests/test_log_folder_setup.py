import os
from pathlib import Path
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import vantage.helpers.log_folder_setup as log_setup_module

from vantage.helpers.log_folder_setup import (
    LogFolderCandidate, LogFolderDialog, discover_log_folders,
    resolve_log_folder,
)


def _write_log(path, modified):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Thu Aug 28 19:20:01 2026] Test line\n", encoding="utf-8")
    os.utime(path, (modified, modified))


def test_auto_discovery_finds_nested_program_and_appdata_logs_newest_first(tmp_path):
    older = tmp_path / "Program Files" / "Sony" / "EverQuest" / "Logs"
    newer = tmp_path / "AppData" / "Local" / "Project1999" / "Logs"
    now = time.time()
    _write_log(older / "eqlog_Old_p1999Green.txt", now - 500)
    _write_log(newer / "eqlog_New_p1999Blue.txt", now - 10)
    (newer / "not-an-eq-log.txt").write_text("ignored", encoding="utf-8")

    candidates = discover_log_folders(
        search_roots=(tmp_path / "Program Files", tmp_path / "AppData"))

    assert [Path(item.path) for item in candidates] == [newer, older]
    assert candidates[0].file_count == 1
    assert candidates[0].newest_log == "eqlog_New_p1999Blue.txt"


def test_fast_discovery_checks_common_program_files_location(tmp_path):
    program_files = tmp_path / "Program Files (x86)"
    logs = program_files / "Sony" / "EverQuest" / "Logs"
    _write_log(logs / "eqlog_Main_p1999Green.txt", time.time())

    candidates = discover_log_folders(
        environment={"ProgramFiles(x86)": str(program_files)},
        deep_search=False)

    assert len(candidates) == 1
    assert Path(candidates[0].path) == logs


def test_manual_selection_accepts_eq_root_or_logs_and_rejects_empty_folder(tmp_path):
    eq_root = tmp_path / "Custom EQ"
    logs = eq_root / "Logs"
    _write_log(logs / "eqlog_Mindflux_p1999Green.txt", time.time())

    assert Path(resolve_log_folder(eq_root).path) == logs
    assert Path(resolve_log_folder(logs).path) == logs
    assert resolve_log_folder(tmp_path / "empty") is None


def test_dialog_selects_freshest_detected_folder_and_exposes_manual_fallback(
        tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    newest = LogFolderCandidate(
        str(tmp_path / "Logs"), 4, time.time(),
        "eqlog_Mindflux_p1999Green.txt")
    older = LogFolderCandidate(
        str(tmp_path / "Old Logs"), 2, time.time() - 800,
        "eqlog_Alt_p1999Green.txt")
    announcements = []
    original_accessible = log_setup_module.QAccessible

    class AccessibleRecorder:
        AnnouncementPoliteness = original_accessible.AnnouncementPoliteness

        @staticmethod
        def updateAccessibility(event):
            announcements.append(event.message())

    monkeypatch.setattr(
        log_setup_module, "QAccessible", AccessibleRecorder)
    dialog = LogFolderDialog(auto_start=False)
    assert dialog.use_button.isDefault()
    assert dialog.use_button.objectName() == "PrimaryAction"
    assert dialog.detected_label.buddy() is dialog.detected
    dialog.show()
    app.processEvents()
    assert dialog.manual_button.hasFocus()
    dialog._scan_finished((newest, older), "")
    app.processEvents()

    assert dialog.detected.currentData() == newest
    assert dialog.use_button.isEnabled()
    assert dialog.manual_button.isEnabled()
    assert dialog.detected.accessibleName() == \
        "Automatically detected EverQuest Logs folders"
    assert "newest activity is selected" in dialog.status.text()
    assert dialog.detected.hasFocus()
    assert announcements[-1] == \
        "Found 2 log folders · newest activity is selected"

    dialog.use_button.setFocus()
    QTest.keyClick(dialog.use_button, Qt.Key.Key_Tab)
    assert dialog.detected.hasFocus()
    QTest.keyClick(
        dialog.detected, Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.ShiftModifier)
    assert dialog.use_button.hasFocus()
    dialog.detected.setFocus()
    QTest.keyClick(dialog.detected, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_path == newest.path
    dialog.close()

    scanning = LogFolderDialog(auto_start=False)
    scanning.show()
    app.processEvents()
    scanning.detected.setEnabled(False)
    scanning.scan_button.setEnabled(False)
    scanning.use_button.setEnabled(False)
    scanning.cancel_button.setFocus()
    QTest.keyClick(scanning.cancel_button, Qt.Key.Key_Tab)
    assert scanning.manual_button.hasFocus()
    QTest.keyClick(
        scanning.manual_button, Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.ShiftModifier)
    assert scanning.cancel_button.hasFocus()
    scanning.close()

    manual_root = tmp_path / "Manual EQ"
    manual_logs = manual_root / "Logs"
    _write_log(
        manual_logs / "eqlog_Manual_p1999Green.txt", time.time())
    manual = LogFolderDialog(auto_start=False)
    monkeypatch.setattr(
        "vantage.helpers.log_folder_setup.QFileDialog.getExistingDirectory",
        lambda *_args: str(manual_root))
    manual._choose_manual()
    assert manual.result() == QDialog.DialogCode.Accepted
    assert Path(manual.selected_path) == manual_logs
    manual.close()
    app.processEvents()
