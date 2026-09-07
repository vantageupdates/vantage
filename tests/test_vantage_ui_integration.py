"""Companion integration tests; no network or real EverQuest install."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from vantage.helpers import config, ui_skin_updater
from vantage.helpers.application import SettingsSignals
from vantage.helpers.updater import RELEASE_HISTORY_API, UpdateController
from vantage.parsers import vantage_ui as vantage_ui_module
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
    widget._automatic_timer.stop()
    widget.close()
    config.data = original
    config._filename = original_filename


def _shared_release_history(*, malformed_ui=False):
    companion_tag = "v9.8.7"
    ui_tag = "vantage-ui-v2.3.4"
    companion = {
        "id": 901, "tag_name": companion_tag,
        "name": "Vantage 9.8.7", "body": "Shared history test.",
        "published_at": "2026-09-07T12:00:00Z",
        "html_url": (
            "https://github.com/vantageupdates/vantage/releases/tag/" +
            companion_tag),
        "draft": False, "prerelease": False,
        "assets": [{
            "name": "Vantage.exe", "size": 2 * 1024 * 1024,
            "digest": "sha256:" + "a" * 64,
            "browser_download_url": (
                "https://github.com/vantageupdates/vantage/releases/download/"
                f"{companion_tag}/Vantage.exe"),
        }],
    }
    ui_assets = []
    for name, size, digest in (
            (ui_skin_updater.MANIFEST_ASSET, 128, "b" * 64),
            (ui_skin_updater.PAYLOAD_ASSET, 4096, "c" * 64)):
        ui_assets.append({
            "name": name, "size": size,
            "digest": "" if malformed_ui and not ui_assets else
            "sha256:" + digest,
            "browser_download_url": (
                "https://github.com/vantageupdates/vantage/releases/download/"
                f"{ui_tag}/{name}"),
        })
    ui = {
        "id": 902, "tag_name": ui_tag, "name": "VantageUI 2.3.4",
        "body": "Independent UI release.",
        "published_at": "2026-09-07T12:01:00Z",
        "html_url": (
            "https://github.com/vantageupdates/vantage/releases/tag/" +
            ui_tag),
        "draft": False, "prerelease": False, "assets": ui_assets,
    }
    return [ui, companion]


class _HistoryReply(QObject):
    finished = Signal()

    def __init__(self, payload):
        super().__init__()
        self._payload = QByteArray(json.dumps(payload).encode("utf-8"))

    def attribute(self, attribute):
        if attribute == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return 200
        return None

    def readAll(self):
        return self._payload

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def errorString(self):
        return ""

    def deleteLater(self):
        pass


class _HistoryNetwork:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []
        self.reply = None

    def get(self, request):
        self.requests.append(request.url().toString())
        self.reply = _HistoryReply(self.payload)
        return self.reply


def test_shared_history_selects_both_products_with_one_network_start(
        panel, monkeypatch):
    history = _shared_release_history()
    network = _HistoryNetwork(history)
    controller = UpdateController("1.0.0")
    controller._network = network
    monkeypatch.setattr(
        vantage_ui_module, "_installed_selection",
        lambda _root: ("2.3.3", "VantageUI-v2.3.3"))
    monkeypatch.setattr(
        ui_skin_updater, "check_release",
        lambda **_kwargs: pytest.fail("shared consumption started a UI request"))
    emitted = []
    controller.release_history_ready.connect(emitted.append)
    panel._automatic_timer.start()
    assert panel.use_shared_update_controller(controller)
    assert not panel._automatic_timer.isActive()

    assert controller.check()
    assert controller.check() is False
    assert network.requests == [RELEASE_HISTORY_API]
    network.reply.finished.emit()

    assert network.requests == [RELEASE_HISTORY_API]
    assert len(emitted) == 1
    assert str(controller.latest_info.version) == "9.8.7"
    assert panel._release.version == "2.3.4"
    assert panel._installed == "2.3.3"
    assert panel._installed_folder == "VantageUI-v2.3.3"
    assert panel.update_snapshot()["update_available"] is True


def test_malformed_shared_ui_candidate_does_not_block_companion_selection(
        panel, monkeypatch):
    history = _shared_release_history(malformed_ui=True)
    network = _HistoryNetwork(history)
    controller = UpdateController("1.0.0")
    controller._network = network
    monkeypatch.setattr(
        vantage_ui_module, "_installed_selection",
        lambda _root: ("2.3.3", "VantageUI-v2.3.3"))
    announcements = []

    class AccessibleRecorder:
        @staticmethod
        def updateAccessibility(event):
            announcements.append(event.message())

    monkeypatch.setattr(vantage_ui_module, "QAccessible", AccessibleRecorder)
    companion_results = []
    controller.check_finished.connect(
        lambda info, _message: companion_results.append(info))
    assert panel.use_shared_update_controller(controller)

    assert controller.check()
    network.reply.finished.emit()

    assert network.requests == [RELEASE_HISTORY_API]
    assert len(companion_results) == 1
    assert str(companion_results[0].version) == "9.8.7"
    assert panel._release is None
    assert "sha-256" in panel.update_snapshot()["check_error"].casefold()
    assert announcements == []


def test_integrated_auto_update_uses_shared_controller_without_own_timer(panel):
    class SharedController(QObject):
        release_history_ready = Signal(object)
        check_failed = Signal(str)

        def __init__(self):
            super().__init__()
            self.checks = 0

        def check(self):
            self.checks += 1
            return True

    controller = SharedController()
    assert panel.use_shared_update_controller(controller)
    panel.auto_update.setChecked(True)

    assert controller.checks == 1
    assert not panel._automatic_timer.isActive()
    assert "no second background request" in panel.auto_update.toolTip()


def test_shared_history_preserves_opt_in_auto_install(panel, monkeypatch):
    class SharedController(QObject):
        release_history_ready = Signal(object)
        check_failed = Signal(str)

        def check(self):
            return True

    controller = SharedController()
    monkeypatch.setattr(
        vantage_ui_module, "_installed_selection",
        lambda _root: ("2.3.3", "VantageUI-v2.3.3"))
    installs = []
    monkeypatch.setattr(
        panel, "update_skin",
        lambda **options: installs.append(options) or True)
    panel.auto_update.blockSignals(True)
    panel.auto_update.setChecked(True)
    panel.auto_update.blockSignals(False)
    assert panel.use_shared_update_controller(controller)

    controller.release_history_ready.emit(_shared_release_history())

    assert installs == [{"confirm": False, "background": True}]
    assert panel._release.version == "2.3.4"


def test_shared_network_failure_is_quiet_and_does_not_replace_busy_state(
        panel, monkeypatch):
    class SharedController(QObject):
        release_history_ready = Signal(object)
        check_failed = Signal(str)

        def check(self):
            return True

    announcements = []

    class AccessibleRecorder:
        @staticmethod
        def updateAccessibility(event):
            announcements.append(event.message())

    monkeypatch.setattr(vantage_ui_module, "QAccessible", AccessibleRecorder)
    controller = SharedController()
    assert panel.use_shared_update_controller(controller)
    current_release = SimpleNamespace(version="2.3.3")
    panel._release = current_release
    panel._busy = True

    controller.release_history_ready.emit(_shared_release_history())
    controller.check_failed.emit("GitHub update check failed: rate limited")

    assert panel._release is current_release
    assert "rate limited" in panel.update_snapshot()["check_error"]
    assert announcements == []


@pytest.mark.parametrize("chosen", [
    r"D:\Games\EverQuest",
    r"D:\Games\EverQuest\eqgame.exe",
    r"D:\Games\EverQuest\uifiles",
    r"D:\Games\EverQuest\uifiles\VantageUI",
    r"D:\Games\EverQuest\uifiles\VantageUI-v1.44.52",
])
def test_path_normalization_always_targets_flat_versioned_vantageui(chosen):
    root = normalize_eq_root(chosen)
    assert Path(root).name == "EverQuest"
    target = skin_target(chosen, "1.44.52")
    assert Path(target).parts[-2:] == ("uifiles", "VantageUI-v1.44.52")
    assert "VantageUI-v1.44.52\\VantageUI" not in target


def test_elevation_command_uses_current_companion_not_older_sibling(tmp_path):
    companion = tmp_path / "Vantage.exe"
    updater = tmp_path / "VantageUI-Updater.exe"
    companion.touch()
    updater.touch()
    program, arguments = elevated_updater_command(
        r"D:\Games\EverQuest\eqgame.exe",
        current_executable=companion, frozen=True,
        source_script=tmp_path / "missing-updater.py")
    assert Path(program) == companion
    assert arguments == subprocess.list2cmdline([
        "--vantage-ui-updater", "--allow-game-running", "--eq-dir",
        os.path.normpath(r"D:\Games\EverQuest")])


def test_elevation_command_falls_back_to_one_file_companion(tmp_path):
    companion = tmp_path / "Vantage.exe"
    companion.touch()
    program, arguments = elevated_updater_command(
        r"D:\Games\EverQuest\uifiles\VantageUI",
        current_executable=companion, frozen=True,
        source_script=tmp_path / "missing-updater.py")
    assert Path(program) == companion
    assert arguments == subprocess.list2cmdline([
        "--vantage-ui-updater", "--allow-game-running", "--eq-dir",
        os.path.normpath(r"D:\Games\EverQuest")])


def test_source_elevation_command_opts_into_live_install(tmp_path):
    script = tmp_path / "vantage_ui_updater.py"
    script.touch()
    program, arguments = elevated_updater_command(
        r"D:\Games\EverQuest", current_executable=tmp_path / "python.exe",
        frozen=False, source_script=script)
    assert Path(program) == Path(sys.executable)
    assert arguments == subprocess.list2cmdline([
        str(script), "--allow-game-running", "--eq-dir",
        os.path.normpath(r"D:\Games\EverQuest")])


def test_live_install_code_has_no_process_termination_route():
    root = Path(__file__).resolve().parents[1]
    source = "\n".join((root / path).read_text(encoding="utf-8") for path in (
        "src/vantage/helpers/ui_skin_updater.py",
        "src/vantage/parsers/vantage_ui.py",
        "src/vantage/ui_skin_app.py"))
    for forbidden_call in ("TerminateProcess(", "taskkill ", ".terminate(",
                           ".kill(", "os.kill("):
        assert forbidden_call not in source


def test_panel_title_copy_versions_and_accessibility(panel):
    assert panel.windowTitle() == panel._title.text() == "VantageUI"
    assert panel.target_value.text() == (
        "Selected: Not installed\nNext install: Not checked")
    assert panel.installed_value.text() == "Not installed"
    assert panel.available_value.text() == "Not checked"
    assert panel.available_value.accessibleDescription() == (
        "The available VantageUI version has not been checked.")
    assert "exact <b>/loadskin</b> command" in panel.instruction.text()
    for control in (
            panel.path_edit, panel.browse_button, panel.check_button,
            panel.update_button, panel.restore_button,
            panel.copy_command_button, panel.auto_update,
            panel.status, panel.progress, panel.log):
        assert control.accessibleName()
        assert control.toolTip() or control is panel.status


def test_selected_and_available_folders_and_copy_command_are_exact(
        panel, monkeypatch):
    panel._installed = "1.44.51"
    panel._installed_folder = "VantageUI-v1.44.51"
    panel._release = SimpleNamespace(version="1.44.52")
    panel._refresh_versions()
    panel._refresh_controls()
    assert r"uifiles\VantageUI-v1.44.51" in panel.target_value.text()
    assert r"uifiles\VantageUI-v1.44.52" in panel.target_value.text()
    assert "/loadskin VantageUI-v1.44.51 1" in panel.instruction.text()
    assert panel.copy_command_button.isEnabled()

    monkeypatch.setattr(
        ui_skin_updater, "loadskin_command",
        lambda _root: "/loadskin VantageUI-v1.44.51 1")
    assert panel.copy_loadskin_command() is True
    assert QApplication.clipboard().text() == "/loadskin VantageUI-v1.44.51 1"
    assert "Copied /loadskin VantageUI-v1.44.51 1" in panel.status.text()


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
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.update_button.setFocus(Qt.FocusReason.OtherFocusReason)

    checks = []
    def begin_check():
        checks.append(True)
        panel._busy = True
        panel._operation_token += 1
        panel._initiating_control = panel.update_button
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
    panel._operation_completed(
        panel._operation_token, "check", (release, "", ""))
    assert confirmations[0][0] == "Install VantageUI"
    assert confirmations[0][1].startswith(
        "Install verified release files in uifiles\\VantageUI-v1.44.51")
    assert installs == [release]


def test_fresh_install_check_defers_confirmation_when_focus_leaves(
        panel, monkeypatch):
    panel._installed = ""
    panel._release = None
    panel._refresh_controls()
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.update_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def begin_check():
        panel._busy = True
        panel._operation_token += 1
        panel._initiating_control = panel.update_button
        panel._refresh_controls()
        return True

    monkeypatch.setattr(panel, "check_for_updates", begin_check)
    confirmations = []
    monkeypatch.setattr(
        panel, "_confirm",
        lambda *_args: confirmations.append(True) or True)
    panel.update_button.click()
    assert panel._install_after_check is True

    external = QLineEdit()
    external.show()
    external.activateWindow()
    external.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    panel._operation_completed(
        panel._operation_token, "check",
        (SimpleNamespace(version="1.44.51"), "", ""))
    QApplication.processEvents()
    QApplication.processEvents()

    assert confirmations == []
    assert QApplication.activeWindow() is external
    assert QApplication.focusWidget() is external
    assert panel._install_after_check is False
    assert panel._initiating_control is None
    assert panel.update_button.isEnabled()
    assert panel.update_button.text() == "Install VantageUI"
    assert "Click Install VantageUI" in panel.status.text()
    external.close()


def test_installed_action_labels_update_and_current(panel):
    panel._installed = "1.44.50"
    panel._installed_folder = "VantageUI-v1.44.50"
    panel._release = None
    panel._refresh_controls()
    assert panel.update_button.text() == "Update VantageUI"
    assert panel.update_button.isEnabled()

    panel._release = SimpleNamespace(version="1.44.51")
    panel._refresh_controls()
    assert panel.update_button.text() == "Update VantageUI"
    assert "new verified versioned folder" in panel.update_button.toolTip()

    panel._release = SimpleNamespace(version="1.44.50")
    panel._refresh_controls()
    assert panel.update_button.text() == "VantageUI is current"
    assert panel.update_button.accessibleName() == "VantageUI is current"
    assert "matches" in panel.update_button.toolTip().casefold()
    assert not panel.update_button.isEnabled()


def test_primary_action_keeps_native_keyboard_order_and_activation(panel):
    app = QApplication.instance()
    panel.show()
    app.processEvents()
    assert panel.check_button.nextInFocusChain() is panel.update_button
    assert panel.update_button.nextInFocusChain() is panel.restore_button
    def next_focusable(control):
        candidate = control.nextInFocusChain()
        while candidate.focusPolicy() == Qt.FocusPolicy.NoFocus:
            candidate = candidate.nextInFocusChain()
        return candidate

    assert next_focusable(panel.browse_button) is panel.target_value
    assert next_focusable(panel.target_value) is panel.check_button
    assert panel.target_value.focusPolicy() == Qt.FocusPolicy.StrongFocus
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
    panel._operation_completed(
        4, "check", (release, "2.3.3", "VantageUI-v2.3.3"))
    assert panel.installed_value.text() == "2.3.3"
    assert panel.available_value.text() == "2.3.4"
    assert panel.available_value.accessibleDescription() == (
        "Available VantageUI version 2.3.4.")
    assert "available" in panel.status.text().casefold()
    assert panel.update_button.isEnabled()
    assert "VantageUI-v2.3.3" in panel.target_value.text()


def test_automatic_new_release_starts_live_install_without_confirmation(
        panel, monkeypatch):
    panel.auto_update.blockSignals(True)
    panel.auto_update.setChecked(True)
    panel.auto_update.blockSignals(False)
    calls = []
    monkeypatch.setattr(
        panel, "update_skin",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True)
    panel._operation_token = 5
    panel._busy = True
    panel._operation_completed(
        5, "check", (SimpleNamespace(version="2.0.0"), "1.0.0",
                     "VantageUI-v1.0.0"))
    assert calls == [((), {"confirm": False, "background": True})]


def test_update_proceeds_immediately_while_eq_runs(panel, monkeypatch):
    release = SimpleNamespace(version="2.0.0")
    panel._release = release
    installs = []
    def complete_install(selected):
        installs.append(selected)
        panel._busy = True
        panel._operation_token += 1
        panel._operation_completed(
            panel._operation_token, "update",
            ui_skin_updater.InstallResult(
                selected.version, 5, "installed",
                ui_skin_updater.folder_name(selected.version)))
        return True
    monkeypatch.setattr(panel, "_install_release", complete_install)
    assert panel.update_skin(confirm=False) is True
    assert installs == [release]
    assert panel._installed == release.version
    assert panel._installed_folder == "VantageUI-v2.0.0"
    assert panel.update_button.text() == "VantageUI is current"
    assert "install complete" in panel.status.text()


def test_panel_install_invokes_core_with_live_opt_in_and_progress(
        panel, monkeypatch):
    panel._release = SimpleNamespace(version="1.44.51")
    calls = []
    def install(*args, **kwargs):
        calls.append((args, kwargs))
        kwargs["progress"]("Updating", 75, 3, 4)
        return ui_skin_updater.InstallResult(
            "1.44.51", 5, "installed", "VantageUI-v1.44.51")
    monkeypatch.setattr(ui_skin_updater, "install_release", install)
    def immediate(action, callback, _status, **_options):
        panel._busy = True
        panel._operation_token += 1
        result = callback(lambda _line: None, panel._progress_callback(
            panel._operation_token))
        QApplication.processEvents()
        panel._operation_completed(panel._operation_token, action, result)
        return True
    monkeypatch.setattr(panel, "_start", immediate)
    assert panel.update_skin(confirm=False)
    assert calls[0][1]["allow_game_running"] is True
    assert calls[0][1]["progress"] is not None
    assert panel.progress.value() == 100
    assert "/loadskin VantageUI-v1.44.51 1" in panel.status.text()


def test_install_result_shows_real_folder_and_preservation_warnings(panel):
    panel._release = SimpleNamespace(version="1.44.52")
    panel._operation_token = 7
    panel._busy = True
    result = ui_skin_updater.InstallResult(
        "1.44.52", 12, "installed", "VantageUI-v1.44.52",
        ("Preserved local changes in VantageUI-v1.44.50.",))
    panel._operation_completed(7, "update", result)
    assert panel._installed == "1.44.52"
    assert panel._installed_folder == "VantageUI-v1.44.52"
    assert "/loadskin VantageUI-v1.44.52 1" in panel.status.text()
    assert "preserved" in panel.status.text().casefold()
    assert "VantageUI-v1.44.50" in panel.log.toPlainText()
    assert panel.update_snapshot()["warnings"] == result.warnings


def test_restore_result_selects_previous_folder_and_exact_command(panel):
    panel._release = SimpleNamespace(version="1.44.52")
    panel._operation_token = 8
    panel._busy = True
    result = ui_skin_updater.InstallResult(
        "1.44.51", 0, "restored", "VantageUI-v1.44.51")
    panel._operation_completed(8, "restore", result)
    assert panel._installed == "1.44.51"
    assert panel._installed_folder == "VantageUI-v1.44.51"
    assert panel.update_snapshot()["loadskin_command"] == (
        "/loadskin VantageUI-v1.44.51 1")
    assert "/loadskin VantageUI-v1.44.51 1" in panel.status.text()


def test_progress_announces_stage_changes_and_quarter_milestones_once(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    announced = []
    monkeypatch.setattr(panel, "_announce", announced.append)
    assert panel._start("check", lambda *_args: None, "Starting check")
    token = panel._operation_token
    assert panel._announced_progress_milestone == 0

    for event in (
            ("Downloading", 5), ("Downloading", 10),
            ("Downloading", 25), ("Downloading", 25),
            ("Verifying", 25), ("Verifying", 51),
            ("Applying", 80), ("Applying", 80),
            ("Finalizing", 100)):
        panel._operation_progress(token, *event, 0, 0)

    assert announced == [
        "Starting check",
        "Downloading",
        "Downloading · 25%",
        "Verifying",
        "Verifying · 50%",
        "Applying · 75%",
        "Finalizing · 100%",
    ]
    assert panel.status.text() == "Finalizing · 100%"
    assert panel.progress.accessibleDescription() == "Finalizing. 100 percent."


def test_success_preserves_current_enabled_focus(panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.check_button.setFocus(Qt.FocusReason.OtherFocusReason)
    assert panel._start(
        "local", lambda *_args: ("", ""), "Reading local state")
    panel._operation_completed(panel._operation_token, "local", ("", ""))
    QApplication.processEvents()
    QApplication.processEvents()
    assert panel.update_button.isEnabled()
    assert panel._surface.focusWidget() is panel.log
    assert panel.log.hasFocus()


def test_non_permission_failure_preserves_current_enabled_focus(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.check_button.setFocus(Qt.FocusReason.OtherFocusReason)
    assert panel._start("check", lambda *_args: None, "Checking")
    panel._operation_failed(
        panel._operation_token, "check", RuntimeError("network unavailable"))
    QApplication.processEvents()
    QApplication.processEvents()
    assert panel.check_button.isEnabled()
    assert panel._surface.focusWidget() is panel.log
    assert panel.log.hasFocus()


def test_background_check_completion_never_activates_or_moves_focus(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    external = QLineEdit()
    external.show()
    external.activateWindow()
    external.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert panel.check_for_updates(background=True)
    assert panel._initiating_control is None
    panel._operation_completed(
        panel._operation_token, "check",
        (SimpleNamespace(version="2.0.0"), "1.0.0",
         "VantageUI-v1.0.0"))
    QApplication.processEvents()
    QApplication.processEvents()
    assert QApplication.activeWindow() is external
    assert QApplication.focusWidget() is external
    assert panel._initiating_control is None
    external.close()


def test_update_snapshot_distinguishes_installed_update_and_background_check(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel._installed = "1.44.51"
    panel._release = SimpleNamespace(version="1.44.52")
    current = panel.update_snapshot()
    assert current["update_available"] is True
    assert current["checking"] is False

    assert panel.check_for_updates(background=True)
    checking = panel.update_snapshot()
    assert checking["checking"] is True
    assert checking["busy"] is True
    assert panel._initiating_control is None

    panel._operation_failed(
        panel._operation_token, "check", RuntimeError("network unavailable"))
    failed = panel.update_snapshot()
    assert failed["checking"] is False
    assert failed["check_error"] == "network unavailable"

    panel._installed = ""
    assert panel.update_snapshot()["update_available"] is False


def test_background_heartbeat_is_silent_but_manual_check_announces(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    announcements = []

    class AccessibleRecorder:
        @staticmethod
        def updateAccessibility(event):
            announcements.append(event.message())

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    monkeypatch.setattr(vantage_ui_module, "QAccessible", AccessibleRecorder)

    panel.progress.setValue(37)
    panel.progress.setFormat("Previous manual operation · 37%")
    panel.progress.setAccessibleDescription(
        "Previous manual operation. 37 percent.")
    prior_progress = (
        panel.progress.value(), panel.progress.format(),
        panel.progress.accessibleDescription())

    assert panel.check_for_updates(background=True)
    token = panel._operation_token
    panel._operation_progress(token, "Downloading", 25, 25, 100)
    panel._operation_completed(
        token, "check", (SimpleNamespace(version="1.0.0"), "1.0.0",
                         "VantageUI-v1.0.0"))
    assert announcements == []
    assert (panel.progress.value(), panel.progress.format(),
            panel.progress.accessibleDescription()) == prior_progress

    assert panel.check_for_updates(background=True)
    token = panel._operation_token
    panel._operation_failed(token, "check", RuntimeError("offline"))
    assert announcements == []
    assert (panel.progress.value(), panel.progress.format(),
            panel.progress.accessibleDescription()) == prior_progress

    assert panel.check_for_updates(background=False)
    token = panel._operation_token
    panel._operation_progress(token, "Downloading", 25, 25, 100)
    panel._operation_failed(token, "check", RuntimeError("offline"))
    assert any("verified VantageUI release" in text
               for text in announcements)
    assert any("Downloading" in text for text in announcements)
    assert any("failed safely" in text for text in announcements)


def test_completion_preserves_focus_when_user_moves_to_log(panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.check_button.setFocus(Qt.FocusReason.OtherFocusReason)
    assert panel._start(
        "local", lambda *_args: ("", ""), "Reading local state")
    panel.log.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert panel._surface.focusWidget() is panel.log

    panel._operation_completed(panel._operation_token, "local", ("", ""))
    QApplication.processEvents()
    QApplication.processEvents()
    assert panel._surface.focusWidget() is panel.log
    assert panel.log.hasFocus()


def test_manual_completion_does_not_steal_focus_after_user_leaves_panel(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.check_button.setFocus(Qt.FocusReason.OtherFocusReason)
    assert panel._start(
        "local", lambda *_args: ("", ""), "Reading local state")
    assert panel._initiating_control is panel.check_button

    external = QLineEdit()
    external.show()
    external.activateWindow()
    external.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    panel._operation_completed(panel._operation_token, "local", ("", ""))
    QApplication.processEvents()
    QApplication.processEvents()
    assert QApplication.activeWindow() is external
    assert QApplication.focusWidget() is external
    assert panel._initiating_control is None
    external.close()


def test_permission_failure_does_not_steal_focus_after_user_leaves_panel(
        panel, monkeypatch):
    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass

    monkeypatch.setattr(vantage_ui_module.threading, "Thread", DormantThread)
    panel.show()
    panel.activateWindow()
    QApplication.processEvents()
    panel.update_button.setFocus(Qt.FocusReason.OtherFocusReason)
    assert panel._start("update", lambda *_args: None, "Installing")

    external = QLineEdit()
    external.show()
    external.activateWindow()
    external.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    panel._operation_failed(
        panel._operation_token, "update", PermissionError("access denied"))
    QApplication.processEvents()
    QApplication.processEvents()
    assert not panel.elevation_button.isHidden()
    assert QApplication.activeWindow() is external
    assert QApplication.focusWidget() is external
    assert panel._initiating_control is None
    external.close()


def test_automatic_timer_always_requests_background_check(panel, monkeypatch):
    checks = []
    monkeypatch.setattr(
        panel, "check_for_updates",
        lambda **options: checks.append(options))
    panel._automatic_timer.timeout.emit()
    assert checks == [{"background": True}]


def test_check_update_restore_and_auto_use_verified_shared_core(
        panel, monkeypatch):
    release = SimpleNamespace(version="3.0.0")
    calls = []

    def immediate(action, callback, _status, **_options):
        result = callback(lambda line: calls.append(("log", line)),
                          lambda *_args: None)
        calls.append((action, result))
        return True

    monkeypatch.setattr(panel, "_start", immediate)
    monkeypatch.setattr(ui_skin_updater, "check_release", lambda **_kwargs: release)
    monkeypatch.setattr(
        ui_skin_updater, "installed_folder",
        lambda _path: "VantageUI-v2.0.0")
    monkeypatch.setattr(ui_skin_updater, "installed_version", lambda _path: "2.0.0")
    monkeypatch.setattr(ui_skin_updater, "game_running", lambda: False)
    monkeypatch.setattr(
        ui_skin_updater, "install_release",
        lambda selected, root, state, **_kwargs: (selected, root, state))
    monkeypatch.setattr(
        ui_skin_updater, "rollback_last",
        lambda root, state, **_kwargs: (root, state))
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
    monkeypatch.setattr(
        panel, "check_for_updates",
        lambda **kwargs: checked.append(kwargs))
    panel.auto_update.setChecked(True)
    assert panel._automatic_timer.isActive()
    assert checked == [{"background": True}]
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


def test_locked_file_failure_is_truthful_and_never_shows_full_progress(panel):
    panel._operation_token = 9
    panel._busy = True
    panel._progress_value = 81
    panel.progress.setValue(81)
    error = ui_skin_updater.SkinUpdateError(
        "Windows could not replace EQUI_Test.xml: sharing violation. "
        "The update did not complete; do not reload the UI yet.")
    panel._operation_failed(9, "update", error)
    assert panel.progress.value() == 81
    assert "Failed" in panel.progress.text()
    assert "locked a file" in panel.status.text()
    assert "do not reload" in panel.status.text().casefold()
    assert panel.elevation_button.isHidden()


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
