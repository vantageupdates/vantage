"""Independent boat-window behavior without Vantage, EQ, or public requests."""

import copy
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QVBoxLayout, QWidget
from shiboken6 import isValid

from vantage.helpers import config
from vantage.helpers.boats import BOAT_ROUTES, BoatSchedule
from vantage.parsers.boats import BoatSchedules
from vantage.parsers.spells import BoatScheduleGroup, Spells


class SettingsSignals(QObject):
    config_updated = Signal()


class FakeCommunityClient(QObject):
    busy_changed = Signal(bool)
    report_finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.refreshes = []
        self.reports = []
        self.cache = {}
        self.is_reporting = False

    def refresh(self, server):
        self.refreshes.append(server)
        return True

    def cached_schedules(self, server):
        return list(self.cache.get(server, ()))

    def report_arrival(self, *args):
        self.reports.append(args)
        return True


class FakeSpellContainer(QFrame):
    def __init__(self, parent, group):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._boat_group = group
        self._layout.addWidget(group)
        self.empty_state_updates = 0

    def _sync_empty_state(self):
        self.empty_state_updates += 1


class BoatControllerHarness(QWidget):
    """Actual boat controller methods with a fake client, no periodic reads."""

    _boat_character_server = Spells._boat_character_server
    _boat_server_name = Spells._boat_server_name
    _change_boat_view_server = Spells._change_boat_view_server
    _show_boat_arrival_dialog = Spells._show_boat_arrival_dialog
    _community_boats_ready = Spells._community_boats_ready
    _community_boats_status = Spells._community_boats_status
    _toggle_boat_schedules = Spells._toggle_boat_schedules
    _boat_header_clicked = Spells._boat_header_clicked
    _manual_refresh_boats = Spells._manual_refresh_boats
    _refresh_boat_schedules = Spells._refresh_boat_schedules

    def __init__(self, enabled=False):
        super().__init__()
        self._boat_group = BoatScheduleGroup()
        self._spell_container = FakeSpellContainer(self, self._boat_group)
        self._boat_toggle = QCheckBox(self)
        self._boat_toggle.setChecked(enabled)
        self._boat_group.set_enabled(enabled)
        self._boat_community = FakeCommunityClient()
        self._boat_server = "Green"
        self._boat_pending = False
        self._boat_arrival_dialog = None
        self._active_server = "Green"
        self._active_character = "Mindflux"
        self.fallback_refreshes = 0
        self._boat_group.server_changed.connect(self._change_boat_view_server)
        self._boat_group.report_requested.connect(self._show_boat_arrival_dialog)

    def _refresh_pigparse_boats(self):
        self.fallback_refreshes += 1


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, app):
    boats = {path[1]: copy.deepcopy(value)
             for path, value in config.UI_PRESENTATION_DEFAULTS.items()
             if path[0] == "boats"}
    boats["geometry"] = [20, 30, 400, 560]
    monkeypatch.setattr(config, "data", {
        "general": {"startup_window_state": "normal", "window_flush": True},
        "boats": boats,
        "spells": {"boat_view_server": "Green", "boat_reporter": "",
                   "show_boat_schedules": False}})
    monkeypatch.setattr(config, "APP_EXIT", False)
    saves = []
    monkeypatch.setattr(config, "save", lambda: saves.append(True))
    signals = SettingsSignals(app)
    monkeypatch.setattr(app, "_signals", {"settings": signals}, raising=False)
    return saves


@pytest.fixture
def make_window(app):
    created = []

    def make(enabled=False):
        config.data["spells"]["show_boat_schedules"] = enabled
        controller = BoatControllerHarness(enabled)
        panel = BoatSchedules(controller)
        panel.finish_startup(show_on_launch=False)
        created.append((panel, controller))
        return panel, controller

    yield make
    for panel, controller in reversed(created):
        dialog = controller._boat_arrival_dialog
        if dialog is not None and isValid(dialog):
            dialog.close()
        router = getattr(app, "_parser_context_router", None)
        if router is not None and panel in router._windows:
            router._windows.remove(panel)
        if isValid(panel):
            panel.close()
            panel.deleteLater()
        if isValid(controller):
            controller.close()
            controller.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def schedule(server="Green", route=BOAT_ROUTES[0], remaining=120):
    observed = datetime.datetime.now(datetime.timezone.utc)
    return BoatSchedule(route, observed, remaining,
                        f"Vantage Community · {server}", False,
                        "Mindflux", "unconfirmed", observed)


def test_boat_panel_reuses_one_group_client_and_clock(make_window):
    panel, controller = make_window()
    assert panel.name == "boats" and panel.windowTitle() == "Boat Schedules"
    assert panel._design_size == QSize(400, 560)
    assert panel.group is controller._boat_group
    assert panel.group.parentWidget() is panel.scroll_area.widget()
    assert controller._boat_window is panel
    assert controller._spell_container._boat_group is None
    assert controller._spell_container._layout.indexOf(panel.group) == -1
    assert controller._spell_container.empty_state_updates == 1
    assert not panel._allow_clickthrough
    assert controller._boat_community.refreshes == []
    assert controller._boat_community.reports == []


def test_opening_directly_enables_reads_without_showing_buffs(make_window, app):
    panel, controller = make_window()
    panel.toggle()
    app.processEvents()
    assert panel.isVisible() and not controller.isVisible()
    assert panel.monitoring_toggle.isChecked()
    assert controller._boat_toggle.isChecked()
    assert config.data["spells"]["show_boat_schedules"]
    assert controller._boat_community.refreshes == ["Green"]
    assert controller.fallback_refreshes == 1
    assert panel.group._clock.isActive()
    assert not panel.paused_notice.isVisible()
    assert controller._boat_community.reports == []


def test_hidden_startup_does_not_enable_or_fetch_schedules(make_window):
    panel, controller = make_window()
    assert not panel.isVisible()
    assert not panel.monitoring_toggle.isChecked()
    assert not controller._boat_toggle.isChecked()
    assert not panel.group._clock.isActive()
    assert not config.data["spells"]["show_boat_schedules"]
    assert controller._boat_community.refreshes == []


def test_hiding_and_reopening_keeps_monitoring_and_existing_eta(make_window, app):
    panel, controller = make_window(enabled=True)
    original = schedule()
    panel.group.update_schedules([original])
    row = panel.group.rows()[0]
    arrival_at = row._arrival_at
    panel.toggle()
    panel.toggle()
    app.processEvents()
    assert not panel.isVisible() and panel.group._clock.isActive()
    assert controller._boat_toggle.isChecked()
    panel.toggle()
    app.processEvents()
    assert panel.group.rows() == [row]
    assert row._arrival_at == arrival_at
    assert controller._boat_community.refreshes == []
    assert controller._boat_community.reports == []


def test_monitoring_switch_pauses_and_resumes_the_existing_controller(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.show()
    original = schedule()
    panel.group.update_schedules([original])
    row = panel.group.rows()[0]
    arrival_at = row._arrival_at
    panel.monitoring_toggle.setChecked(False)
    app.processEvents()
    assert not controller._boat_toggle.isChecked()
    assert not panel.group._clock.isActive()
    assert panel.paused_notice.isVisible()
    assert not config.data["spells"]["show_boat_schedules"]
    panel.monitoring_toggle.setChecked(True)
    app.processEvents()
    assert controller._boat_toggle.isChecked() and panel.group._clock.isActive()
    assert not panel.paused_notice.isVisible()
    assert controller._boat_community.refreshes == ["Green"]
    assert panel.group.rows() == [row] and row._arrival_at == arrival_at
    assert controller._boat_community.reports == []


def test_reopening_paused_panel_resumes_and_refresh_button_can_resume(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.toggle()
    panel.monitoring_toggle.setChecked(False)
    panel.toggle()
    panel.toggle()
    app.processEvents()
    assert panel.monitoring_toggle.isChecked()
    assert controller._boat_community.refreshes == ["Green"]
    panel.monitoring_toggle.setChecked(False)
    panel.refresh_button.click()
    app.processEvents()
    assert panel.monitoring_toggle.isChecked() and controller._boat_toggle.isChecked()
    assert controller._boat_community.refreshes == ["Green", "Green"]
    assert controller._boat_community.reports == []


def test_refresh_checks_current_server_only_without_public_report(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.show()
    panel.refresh_button.click()
    app.processEvents()
    assert controller._boat_community.refreshes == ["Green"]
    assert controller.fallback_refreshes == 1
    assert controller._boat_community.reports == []


def test_server_switch_reuses_controller_and_never_mixes_servers(make_window, app):
    panel, controller = make_window(enabled=True)
    green = schedule("Green")
    blue = schedule("Blue", route=BOAT_ROUTES[2])
    panel.group.update_schedules([green], "Green")
    controller._boat_community.cache["Blue"] = [blue]
    panel.group.server_selector.setCurrentText("Blue")
    app.processEvents()
    assert panel.group is controller._boat_group
    assert config.data["spells"]["boat_view_server"] == "Blue"
    assert [row._schedule for row in panel.group.rows()] == [blue]
    assert controller._boat_community.refreshes == ["Blue"]
    controller._community_boats_ready("Green", [green], "Late Green reply")
    assert [row._schedule for row in panel.group.rows()] == [blue]
    assert "Late Green" not in panel.group.status.text()
    assert controller._boat_community.reports == []


def test_open_uses_cached_schedules_without_restarting_them_on_repeat_reads(make_window, app):
    panel, controller = make_window()
    original = schedule()
    controller._boat_community.cache["Green"] = [original]
    panel.toggle()
    app.processEvents()
    row = panel.group.rows()[0]
    arrival_at = row._arrival_at
    panel.refresh_button.click()
    controller._community_boats_ready("Green", [original], "Green · cached estimate")
    assert panel.group.rows() == [row] and row._arrival_at == arrival_at
    assert controller._boat_community.reports == []


@pytest.mark.parametrize("presentation_change", ["always_on_top", "frame", "saved_geometry"])
def test_monitoring_off_survives_technical_reshow_until_intentional_reopen(
        make_window, app, presentation_change):
    panel, controller = make_window(enabled=True)
    panel.toggle()
    original = schedule()
    panel.group.update_schedules([original])
    row = panel.group.rows()[0]
    arrival_at = row._arrival_at
    panel.monitoring_toggle.setChecked(False)
    assert not config.data["spells"]["show_boat_schedules"]
    if presentation_change == "always_on_top":
        panel._set_always_on_top(not panel._always_on_top)
    elif presentation_change == "frame":
        panel._toggle_frame()
    else:
        config.data["boats"]["geometry"] = [45, 55, 300, 360]
        config.data["boats"]["toggled"] = True
        panel.apply_saved_presentation()
    app.processEvents()
    assert panel.isVisible()
    assert not panel.monitoring_toggle.isChecked()
    assert not controller._boat_toggle.isChecked()
    assert not config.data["spells"]["show_boat_schedules"]
    assert not panel.group._clock.isActive()
    assert panel.paused_notice.isVisible()
    assert controller._boat_community.refreshes == []
    assert panel.group.rows() == [row] and row._arrival_at == arrival_at
    panel.toggle()
    panel.toggle()
    app.processEvents()
    assert panel.isVisible() and panel.monitoring_toggle.isChecked()
    assert controller._boat_toggle.isChecked()
    assert config.data["spells"]["show_boat_schedules"]
    assert panel.group._clock.isActive()
    assert not panel.paused_notice.isVisible()
    assert controller._boat_community.refreshes == ["Green"]
    assert panel.group.rows() == [row] and row._arrival_at == arrival_at
    assert controller._boat_community.reports == []


def test_sync_arrival_opens_singleton_parented_to_boat_window_not_buffs(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.show()
    panel.group.sync_button.click()
    app.processEvents()
    dialog = controller._boat_arrival_dialog
    assert dialog is not None and dialog.parentWidget() is panel
    assert dialog.isVisible() and not controller.isVisible()
    assert not dialog.confirm.isChecked()
    assert controller._boat_community.reports == []
    panel.group.sync_button.click()
    assert controller._boat_arrival_dialog is dialog
    dialog.close()
    app.processEvents()
    assert controller._boat_arrival_dialog is None
    assert controller._boat_community.reports == []


def test_legacy_buffs_boat_action_is_only_another_launcher(make_window, app):
    panel, controller = make_window()
    controller._boat_header_clicked(True)
    app.processEvents()
    assert panel.isVisible() and controller._boat_toggle.isChecked()
    assert not controller.isVisible()
    assert controller._boat_community.refreshes == ["Green"]
    controller._boat_header_clicked(False)
    assert not panel.isVisible() and controller._boat_toggle.isChecked()
    assert panel.group._clock.isActive()
    assert controller._boat_community.reports == []


def test_old_controller_switch_changes_are_reflected_without_second_refresh(make_window, app):
    panel, controller = make_window()
    controller._boat_toggle.setChecked(True)
    controller._toggle_boat_schedules(True)
    app.processEvents()
    assert panel.monitoring_toggle.isChecked()
    assert controller._boat_community.refreshes == ["Green"]
    controller._boat_toggle.setChecked(False)
    controller._toggle_boat_schedules(False)
    assert not panel.monitoring_toggle.isChecked()
    assert not panel.group._clock.isActive()


@pytest.mark.parametrize("scale", [.25, .35, .5, .75, 1.0])
def test_replica_sizes_are_exact_and_geometry_survives_rollup(make_window, app, scale):
    panel, controller = make_window(enabled=True)
    panel.show()
    panel._set_replica_scale(scale)
    QTest.qWait(10)
    expected = QSize(round(400 * scale), round(560 * scale))
    assert panel.size() == expected
    assert config.data["boats"]["geometry"][2:] == [expected.width(), expected.height()]
    panel._set_collapsed(True)
    QTest.qWait(10)
    assert panel.height() <= 28
    assert config.data["boats"]["geometry"][2:] == [expected.width(), expected.height()]
    panel._set_collapsed(False)
    QTest.qWait(10)
    assert panel.size() == expected
    assert panel.group._clock.isActive() and controller._boat_toggle.isChecked()


def test_tray_hide_preserves_size_and_live_schedules(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.show()
    panel._set_replica_scale(.35)
    expected = QSize(panel.size())
    panel._minimize_to_tray()
    app.processEvents()
    assert not panel.isVisible() and not panel._toggled
    assert not config.data["boats"]["toggled"]
    assert panel.group._clock.isActive()
    assert controller._boat_toggle.isChecked()
    panel.toggle()
    app.processEvents()
    assert panel.size() == expected and config.data["boats"]["toggled"]
    assert controller._boat_community.refreshes == []


def test_loaded_geometry_belongs_to_boats_not_buff_window(make_window, app):
    config.data["boats"]["geometry"] = [55, 65, 260, 310]
    config.data["spells"]["geometry"] = [400, 20, 210, 480]
    panel, controller = make_window(enabled=True)
    assert panel.size() == QSize(260, 310)
    panel.show()
    panel.move(45, 50)
    panel.resize(280, 320)
    panel._save_geometry()
    assert config.data["boats"]["geometry"][2:] == [280, 320]
    assert config.data["spells"]["geometry"] == [400, 20, 210, 480]
    panel.toggle()
    panel.toggle()
    app.processEvents()
    assert panel.size() == QSize(280, 320)
    assert not controller.isVisible()


def test_controls_are_named_and_manual_report_is_explained(make_window):
    panel, _controller = make_window()
    for widget in (panel, panel.monitoring_toggle, panel.refresh_button,
                   panel.scroll_area, panel.group.server_selector, panel.group.sync_button):
        assert widget.accessibleName().strip()
    assert panel.instructions.wordWrap()
    assert panel.instructions.textFormat() == Qt.TextFormat.PlainText
    assert "actually see arrive" in panel.instructions.text()
    assert "every minute" in panel.monitoring_toggle.toolTip()
    assert panel.monitoring_toggle.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert panel.refresh_button.focusPolicy() != Qt.FocusPolicy.NoFocus


def test_monitoring_refresh_server_and_sync_are_keyboard_operable(make_window, app):
    panel, controller = make_window(enabled=True)
    panel.show()
    panel.monitoring_toggle.setFocus()
    QTest.keyClick(panel.monitoring_toggle, Qt.Key.Key_Space)
    assert not controller._boat_toggle.isChecked()
    panel.refresh_button.setFocus()
    QTest.keyClick(panel.refresh_button, Qt.Key.Key_Space)
    assert controller._boat_toggle.isChecked()
    assert controller._boat_community.refreshes == ["Green"]
    panel.group.server_selector.setFocus()
    QTest.keyClick(panel.group.server_selector, Qt.Key.Key_End)
    assert panel.group.server_selector.currentText() == "Blue"
    assert controller._boat_community.refreshes == ["Green", "Blue"]
    panel.group.sync_button.setFocus()
    QTest.keyClick(panel.group.sync_button, Qt.Key.Key_Space)
    app.processEvents()
    dialog = controller._boat_arrival_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.parentWidget() is panel
    assert not dialog.confirm.isChecked()
    assert controller._boat_community.reports == []
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    app.processEvents()
    assert controller._boat_arrival_dialog is None


def test_boat_view_parse_is_a_noop_not_a_second_spell_or_boat_consumer(make_window):
    panel, controller = make_window(enabled=True)
    original = schedule()
    panel.group.update_schedules([original])
    row = panel.group.rows()[0]
    arrival_at = row._arrival_at
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    assert panel.parse(timestamp, "You begin casting Spirit of Wolf.") is None
    assert panel.parse(timestamp, "The boat has arrived!") is None
    assert panel.group.rows() == [row]
    assert row._schedule is original and row._arrival_at == arrival_at
    assert controller._boat_community.refreshes == []
    assert controller._boat_community.reports == []


def test_live_log_dispatch_crosses_boat_view_and_reaches_all_later_parsers(tmp_path):
    """The new panel must participate safely in VantageApp's parser loop."""
    root = Path(__file__).resolve().parents[1]
    script = r'''
import datetime
import json
from native_audit_fixture import isolate
isolate()
from vantage.helpers.application import VantageApp
app = VantageApp([])
boats = app._parsers_dict['boats']
spells = app._parsers_dict['spells']
calls = []
reports = []
expected_names = [parser.name for parser in app._parsers]
original_boat_parse = boats.parse
def boat_view_parse(timestamp, text):
    calls.append(('boats', timestamp.isoformat(), text))
    return original_boat_parse(timestamp, text)
boats.parse = boat_view_parse
for parser in app._parsers:
    if parser is boats:
        continue
    def record(timestamp, text, name=parser.name):
        calls.append((name, timestamp.isoformat(), text))
    parser.parse = record
spells._boat_community.report_arrival = lambda *args: reports.append(args)
timestamp = datetime.datetime(2026, 10, 12, 17, 0, 0)
text = 'You begin casting Regrowth of the Grove.'
app._parse((timestamp, text, 'AuditCleric', 'p1999green'))
first_delivery = list(calls)
calls.clear()
second_text = 'a tangrin begins to cast a spell.'
app._parse((timestamp, second_text, 'AuditCleric', 'p1999green'))
second_delivery = list(calls)
print(json.dumps({
    'expected_names': expected_names,
    'first_delivery': first_delivery,
    'second_delivery': second_delivery,
    'contexts': {
        parser.name: [parser._active_character, parser._active_server]
        for parser in app._parsers},
    'reports': reports,
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ACCESSIBILITY"] = "0"
    env["PYTHONPATH"] = os.pathsep.join((str(root / "tests"), str(root / "src")))
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, (
        f"Disposable log dispatch exited {completed.returncode}\n"
        f"STDERR:\n{completed.stderr[-6000:]}\nSTDOUT:\n{completed.stdout[-6000:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    expected = result["expected_names"]
    assert expected.index("spells") < expected.index("boats") < expected.index("vitals")
    assert all(name in expected for name in ("timers", "combat", "market", "zones", "quests"))
    for delivery, text in (
            (result["first_delivery"], "You begin casting Regrowth of the Grove."),
            (result["second_delivery"], "a tangrin begins to cast a spell.")):
        assert [call[0] for call in delivery] == expected
        assert sum(call[0] == "spells" for call in delivery) == 1
        assert sum(call[0] == "boats" for call in delivery) == 1
        assert all(call[1:] == ["2026-10-12T17:00:00", text] for call in delivery)
    assert all(context == ["AuditCleric", "p1999green"]
               for context in result["contexts"].values())
    assert result["reports"] == []


def test_actual_quickbar_boat_button_opens_only_the_independent_window(tmp_path):
    """Exercise the real launcher/controller wiring in a disposable app."""
    root = Path(__file__).resolve().parents[1]
    script = r'''
import json
from native_audit_fixture import isolate
isolate()
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
bar = app._parsers_dict['quickbar']
boats = app._parsers_dict['boats']
spells = app._parsers_dict['spells']
reads = []
spells._refresh_boat_schedules = lambda: reads.append(spells._boat_server_name())
button = bar._buttons['boats']
initial = {
    'hidden': not boats.isVisible(), 'buffs_hidden': not spells.isVisible(),
    'named': button.accessibleName(), 'shown': not button.isHidden(),
    'checkable': button.isCheckable(), 'icon': not button.icon().isNull(),
    'same_target': bar._window_targets['boats'] is boats,
    'same_group': boats.group is spells._boat_group,
    'detached': spells._spell_container._boat_group is None,
}
button.click()
QTest.qWait(20)
opened = boats.isVisible() and not spells.isVisible()
enabled = spells._boat_toggle.isChecked() and boats.monitoring_toggle.isChecked()
button.click()
QTest.qWait(20)
closed = not boats.isVisible() and not spells.isVisible()
live_hidden = boats.group._clock.isActive() and spells._boat_toggle.isChecked()
bar.toggle_orientation()
QTest.qWait(20)
vertical_has_button = not button.isHidden() and bar._orientation == 'vertical'
button.click()
QTest.qWait(20)
vertical_opened = boats.isVisible() and not spells.isVisible()
print(json.dumps({
    'initial': initial, 'opened': opened, 'enabled': enabled, 'closed': closed,
    'live_hidden': live_hidden, 'reads': reads,
    'vertical_has_button': vertical_has_button, 'vertical_opened': vertical_opened,
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ACCESSIBILITY"] = "0"
    env["PYTHONPATH"] = os.pathsep.join((str(root / "tests"), str(root / "src")))
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, (
        f"Disposable launcher exited {completed.returncode}\n"
        f"STDERR:\n{completed.stderr[-6000:]}\nSTDOUT:\n{completed.stdout[-6000:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["initial"] == {
        "hidden": True, "buffs_hidden": True, "named": "Boat Schedules",
        "shown": True, "checkable": True, "icon": True,
        "same_target": True, "same_group": True, "detached": True}
    assert all(result[key] for key in (
        "opened", "enabled", "closed", "live_hidden",
        "vertical_has_button", "vertical_opened"))
    assert result["reads"] == ["Green"]
