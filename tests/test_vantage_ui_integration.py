"""Companion integration tests; no network or real EverQuest install."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config, ui_skin_updater
from vantage.helpers.application import SettingsSignals
from vantage.parsers.vantage_ui import (
    DEFAULT_EQ_ROOT, VantageUI, elevated_updater_command, normalize_eq_root,
    skin_target)


@pytest.fixture
def panel(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if not hasattr(app, "_signals"):
        app._signals = {}
    app._signals.setdefault("settings", SettingsSignals())
    original = copy.deepcopy(config.data)
    original_filename = config._filename
    config.data.setdefault("vantage_ui", {})
    config.data["vantage_ui"] = {
        "geometry": [20, 20, 700, 540], "toggled": False,
        "clickthrough": False, "auto_hide_menu": False,
        "always_on_top": False, "frameless": True, "opacity": 100,
        "eq_dir": DEFAULT_EQ_ROOT, "auto_update": False,
    }
    config._filename = str(tmp_path / "profile.json")
    monkeypatch.setattr(config, "save", lambda: None)
    widget = VantageUI()
    yield widget
    widget._pending_timer.stop()
    widget._automatic_timer.stop()
    widget.close()
    config.data = original
    config._filename = original_filename


@pytest.mark.parametrize("chosen", [
    r"D:\Games\EverQuest",
    r"D:\Games\EverQuest\eqgame.exe",
    r"D:\Games\EverQuest\uifiles",
    r"D:\Games\EverQuest\uifiles\VantageUI",
])
def test_path_normalization_always_targets_flat_vantageui(chosen):
    root = normalize_eq_root(chosen)
    assert Path(root).name == "EverQuest"
    assert Path(skin_target(chosen)).parts[-2:] == ("uifiles", "VantageUI")
    assert "VantageUI\\VantageUI" not in skin_target(chosen)


def test_elevation_command_prefers_separate_updater_candidate(tmp_path):
    companion = tmp_path / "Vantage.exe"
    updater = tmp_path / "VantageUI-Updater.exe"
    companion.touch()
    updater.touch()
    program, arguments = elevated_updater_command(
        r"D:\Games\EverQuest\eqgame.exe",
        current_executable=companion, frozen=True,
        source_script=tmp_path / "missing-updater.py")
    assert Path(program) == updater
    assert arguments == subprocess.list2cmdline([
        "--eq-dir", os.path.normpath(r"D:\Games\EverQuest")])
    assert "--vantage-ui-updater" not in arguments


def test_elevation_command_falls_back_to_one_file_companion(tmp_path):
    companion = tmp_path / "Vantage.exe"
    companion.touch()
    program, arguments = elevated_updater_command(
        r"D:\Games\EverQuest\uifiles\VantageUI",
        current_executable=companion, frozen=True,
        source_script=tmp_path / "missing-updater.py")
    assert Path(program) == companion
    assert arguments == subprocess.list2cmdline([
        "--vantage-ui-updater", "--eq-dir",
        os.path.normpath(r"D:\Games\EverQuest")])


def test_panel_title_copy_versions_and_accessibility(panel):
    assert panel.windowTitle() == panel._title.text() == "VantageUI"
    assert panel.target_value.text().endswith(r"uifiles\VantageUI")
    assert panel.installed_value.text() == "Not installed"
    assert panel.available_value.text() == "Not checked"
    assert "/loadskin VantageUI 1" in panel.instruction.text()
    for control in (
            panel.path_edit, panel.browse_button, panel.check_button,
            panel.update_button, panel.restore_button, panel.auto_update,
            panel.status, panel.log):
        assert control.accessibleName()
        assert control.toolTip() or control is panel.status


def test_fresh_install_button_checks_then_continues_verified_flow(
        panel, monkeypatch):
    panel._installed = ""
    panel._release = None
    panel._refresh_controls()
    assert panel.update_button.text() == "Install VantageUI"
    assert panel.update_button.accessibleName() == "Install VantageUI"
    assert "verified release" in panel.update_button.toolTip()
    assert not panel.update_button.isHidden()
    assert panel.update_button.isEnabled()

    checks = []
    def begin_check():
        checks.append(True)
        panel._busy = True
        panel._operation_token += 1
        panel._refresh_controls()
        return True
    monkeypatch.setattr(panel, "check_for_updates", begin_check)
    confirmations = []
    monkeypatch.setattr(
        panel, "_confirm",
        lambda title, text: confirmations.append((title, text)) or True)
    monkeypatch.setattr(ui_skin_updater, "game_running", lambda: False)
    installs = []
    monkeypatch.setattr(
        panel, "_install_release",
        lambda release: installs.append(release) or True)

    panel.update_button.click()
    assert checks == [True]
    assert panel._install_after_check is True
    assert not panel.update_button.isEnabled()
    release = SimpleNamespace(version="1.44.51")
    panel._operation_completed(panel._operation_token, "check", (release, ""))
    assert confirmations[0][0] == "Install VantageUI"
    assert confirmations[0][1].startswith("Install only")
    assert installs == [release]


def test_installed_action_labels_update_and_current_repair(panel):
    panel._installed = "1.44.50"
    panel._release = None
    panel._refresh_controls()
    assert panel.update_button.text() == "Update VantageUI"
    assert panel.update_button.isEnabled()

    panel._release = SimpleNamespace(version="1.44.51")
    panel._refresh_controls()
    assert panel.update_button.text() == "Update VantageUI"
    assert "back up" in panel.update_button.toolTip()

    panel._release = SimpleNamespace(version="1.44.50")
    panel._refresh_controls()
    assert panel.update_button.text() == "Repair VantageUI"
    assert panel.update_button.accessibleName() == "Repair VantageUI"
    assert "repair" in panel.update_button.toolTip().casefold()
    assert panel.update_button.isEnabled()


def test_primary_action_keeps_native_keyboard_order_and_activation(panel):
    app = QApplication.instance()
    panel.show()
    app.processEvents()
    assert panel.check_button.nextInFocusChain() is panel.update_button
    assert panel.update_button.nextInFocusChain() is panel.restore_button
    assert panel.update_button.focusPolicy() != Qt.FocusPolicy.NoFocus
    activated = []
    panel.update_button.clicked.connect(lambda: activated.append(True))
    # Keep the production slot inert; this test exercises native keyboard
    # activation without starting network work.
    panel._busy = True
    panel.update_button.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(panel.update_button, Qt.Key.Key_Space)
    assert activated == [True]


def test_check_completion_displays_installed_available_and_status(panel):
    panel._operation_token = 4
    panel._busy = True
    release = SimpleNamespace(version="2.3.4")
    panel._operation_completed(4, "check", (release, "2.3.3"))
    assert panel.installed_value.text() == "2.3.3"
    assert panel.available_value.text() == "2.3.4"
    assert "available" in panel.status.text().casefold()
    assert panel.update_button.isEnabled()


def test_update_queues_while_eq_runs_then_installs_after_exit(
        panel, monkeypatch):
    release = SimpleNamespace(version="2.0.0")
    panel._release = release
    running = iter((True, False))
    monkeypatch.setattr(ui_skin_updater, "game_running", lambda: next(running))
    installs = []
    def complete_install(selected):
        installs.append(selected)
        panel._busy = True
        panel._operation_token += 1
        panel._operation_completed(panel._operation_token, "update", selected)
        return True
    monkeypatch.setattr(panel, "_install_release", complete_install)
    assert panel.update_skin(confirm=False) is True
    assert panel._pending_release is release
    assert "queued" in panel.status.text().casefold()
    assert "Close EverQuest normally" in panel.pending_message.text()
    assert "keep Vantage open" in panel.pending_message.text()
    assert "never close the game" in panel.pending_message.text()
    assert skin_target(panel.path_edit.text()) in panel.pending_message.text()
    assert not panel.pending_banner.isHidden()
    assert panel.update_button.text() == "Waiting for EverQuest to close…"
    assert "Waiting for EverQuest" in panel.update_button.accessibleName()
    assert "never close the game" in panel.update_button.toolTip()
    assert not panel.update_button.isEnabled()
    assert installs == []
    panel._pending_timer.stop()
    panel._poll_pending_update()
    assert installs == [release]
    assert panel._pending_release is None
    assert panel.pending_banner.isHidden()
    assert panel._installed == release.version
    assert panel.update_button.text() == "Repair VantageUI"
    assert "install complete" in panel.status.text()


def test_queue_is_one_notice_and_never_changes_files_while_eq_is_open(
        panel, monkeypatch, tmp_path):
    eq_root = tmp_path / "EverQuest"
    target = Path(skin_target(eq_root))
    target.mkdir(parents=True)
    existing = target / "EQUI.xml"
    existing.write_bytes(b"existing skin remains untouched")
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    panel.path_edit.setText(str(eq_root))
    panel._refresh_target()
    panel._release = SimpleNamespace(version="1.44.51")
    announcements = []
    monkeypatch.setattr(panel, "_announce", announcements.append)
    monkeypatch.setattr(ui_skin_updater, "game_running", lambda: True)
    monkeypatch.setattr(
        ui_skin_updater, "install_release",
        lambda *_args, **_kwargs: pytest.fail(
            "installer must not run while EverQuest is open"))

    assert panel.update_skin(confirm=False)
    panel._poll_pending_update()
    panel._queue_pending_update(panel._release)

    after = {path.name: path.read_bytes() for path in target.iterdir()}
    assert after == before
    assert len(announcements) == 1
    assert announcements[0] == panel.pending_message.text()
    assert panel._pending_timer.isActive()


def test_pending_poll_failure_restores_usable_install_action(panel, monkeypatch):
    panel._release = SimpleNamespace(version="1.44.51")
    calls = 0

    def game_state():
        nonlocal calls
        calls += 1
        if calls == 1:
            return True
        raise OSError("process check unavailable")

    monkeypatch.setattr(ui_skin_updater, "game_running", game_state)
    assert panel.update_skin(confirm=False)
    panel._pending_timer.stop()
    panel._poll_pending_update()

    assert panel._pending_release is None
    assert panel.pending_banner.isHidden()
    assert panel.update_button.text() == "Install VantageUI"
    assert panel.update_button.isEnabled()
    assert "failed safely" in panel.status.text()


def test_check_update_restore_and_auto_use_verified_shared_core(
        panel, monkeypatch):
    release = SimpleNamespace(version="3.0.0")
    calls = []

    def immediate(action, callback, _status):
        result = callback(lambda line: calls.append(("log", line)))
        calls.append((action, result))
        return True

    monkeypatch.setattr(panel, "_start", immediate)
    monkeypatch.setattr(ui_skin_updater, "check_release", lambda: release)
    monkeypatch.setattr(ui_skin_updater, "installed_version", lambda _path: "2.0.0")
    monkeypatch.setattr(ui_skin_updater, "game_running", lambda: False)
    monkeypatch.setattr(
        ui_skin_updater, "install_release",
        lambda selected, root, state, log: (selected, root, state))
    monkeypatch.setattr(
        ui_skin_updater, "rollback_last",
        lambda root, state, log: (root, state))
    panel._release = release
    assert panel.check_for_updates()
    assert panel.update_skin(confirm=False)
    monkeypatch.setattr(panel, "_confirm", lambda *_args: True)
    assert panel.restore_skin()
    assert [entry[0] for entry in calls if entry[0] != "log"] == [
        "check", "update", "restore"]
    assert calls[1][1][0] is release
    assert calls[1][1][1].endswith("EverQuest")

    checked = []
    monkeypatch.setattr(panel, "check_for_updates", lambda: checked.append(True))
    panel.auto_update.setChecked(True)
    assert panel._automatic_timer.isActive()
    assert checked == [True]
    assert config.data["vantage_ui"]["auto_update"] is True


def test_permission_denial_offers_only_normal_windows_uac(panel, monkeypatch):
    panel._operation_token = 8
    panel._busy = True
    panel._operation_failed(8, "update", PermissionError("access denied"))
    assert not panel.elevation_button.isHidden()
    assert "UAC" in panel.status.text()
    assert "will not change folder permissions" in panel.status.text()
    requested = []
    monkeypatch.setattr(
        "vantage.parsers.vantage_ui.request_elevated_updater",
        lambda root: requested.append(root) or True)
    panel._request_elevation()
    assert requested == [panel.path_edit.text()]
    assert "Companion remains installed and open" in panel.status.text()


def test_quickbar_and_tray_toggle_vantageui(tmp_path):
    script = r'''\
import json
from vantage.helpers.application import VantageApp
app = VantageApp([])
panel = app._parsers_dict["vantage_ui"]
panel._loaded_once = True
bar = app._parsers_dict["quickbar"]
label = bar._buttons["vantage_ui"].accessibleName()
bar._trigger("vantage_ui")
app.processEvents()
opened = panel.isVisible()
bar._trigger("vantage_ui")
app.processEvents()
closed = not panel.isVisible()
tray_registered = panel in app._parsers
print(json.dumps({"label": label, "opened": opened, "closed": closed,
                  "tray_registered": tray_registered}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], env=env, check=True,
        capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "label": "VantageUI", "opened": True, "closed": True,
        "tray_registered": True}
