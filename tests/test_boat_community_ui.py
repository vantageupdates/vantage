"""Boat UI regressions with isolated widgets, fake clients, and no network."""
import datetime
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAccessible
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel, QScrollArea, QWidget
from shiboken6 import isValid

from vantage.helpers import config
from vantage.helpers.boat_dialog import BoatArrivalDialog
from vantage.helpers.boats import BOAT_ROUTES, BoatSchedule
from vantage.parsers.spells import BoatScheduleGroup, Spells


UTC = datetime.timezone.utc


class FakeCommunityClient(QObject):
    busy_changed = Signal(bool)
    report_finished = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.is_reporting = False
        self.starts = True
        self.reports = []
        self.refreshes = []
        self.cache = {}

    def report_arrival(self, server, boat, start_point, reporter):
        self.reports.append((server, boat, start_point, reporter))
        if not self.starts:
            return False
        self.is_reporting = True
        self.busy_changed.emit(True)
        return True

    def complete(self, accepted, message, server=None):
        self.is_reporting = False
        self.report_finished.emit(server or self.reports[-1][0], accepted, message)
        self.busy_changed.emit(False)

    def refresh(self, server):
        self.refreshes.append(server)
        return True

    def cached_schedules(self, server):
        return list(self.cache.get(server, ()))


class BoatHarness(QWidget):
    """Bind actual boat methods without starting Vantage or any request timers."""
    _boat_character_server = Spells._boat_character_server
    _boat_server_name = Spells._boat_server_name
    _change_boat_view_server = Spells._change_boat_view_server
    _show_boat_arrival_dialog = Spells._show_boat_arrival_dialog
    _community_boats_ready = Spells._community_boats_ready
    _community_boats_status = Spells._community_boats_status
    _refresh_boat_schedules = Spells._refresh_boat_schedules
    _boat_reply_finished = Spells._boat_reply_finished

    def __init__(self):
        super().__init__()
        self._boat_group = BoatScheduleGroup()
        self._boat_group.setParent(self)
        self._boat_toggle = QCheckBox(self)
        self._boat_toggle.setChecked(True)
        self._boat_community = FakeCommunityClient()
        self._boat_server = "Green"
        self._boat_pending = False
        self._boat_arrival_dialog = None
        self._active_server = "Green"
        self._active_character = "Mindflux"
        self.fallback_refreshes = 0
        self._boat_group.server_changed.connect(self._change_boat_view_server)

    def _refresh_pigparse_boats(self):
        self.fallback_refreshes += 1


class FakeReply:
    def __init__(self, activities):
        self.payload = json.dumps(activities).encode("utf-8")
        self.read = False
        self.deleted = False

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def readAll(self):
        self.read = True
        return self.payload

    def deleteLater(self):
        self.deleted = True


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(config, "data", {
        "spells": {"boat_view_server": "Green", "boat_reporter": "",
                   "show_boat_schedules": False}})
    saves = []
    monkeypatch.setattr(config, "save", lambda: saves.append(True))
    return saves


@pytest.fixture
def widgets(app):
    created = []

    def track(widget):
        created.append(widget)
        return widget

    yield track
    for widget in reversed(created):
        if isValid(widget):
            widget.close()
            widget.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def dialog_for(widgets, app, client=None, **kwargs):
    client = client or FakeCommunityClient()
    dialog = widgets(BoatArrivalDialog(client, **kwargs))
    dialog.show()
    app.processEvents()
    return dialog, client


def community_schedule(route=BOAT_ROUTES[0], server="Green", reporter="Mindflux",
                       age=0, confidence="unconfirmed"):
    observed = datetime.datetime.now(UTC) - datetime.timedelta(seconds=age)
    return BoatSchedule(
        route, observed, 120, f"Vantage Community · {server}", False,
        reporter, confidence,
        observed - datetime.timedelta(seconds=route.announcement_to_dock))


def activity(route=BOAT_ROUTES[0], age=0):
    return {
        "boat": route.boat_id, "startPoint": route.start_point,
        "lastSeen": (datetime.datetime.now(UTC) -
                     datetime.timedelta(seconds=age)).isoformat()}


def test_explicit_confirmation_is_required_even_with_a_valid_public_name(widgets, app):
    dialog, client = dialog_for(widgets, app, active_server="Green", reporter="Mindflux")
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    dialog.submit.click()
    assert client.reports == []
    dialog.confirm.setChecked(True)
    assert dialog.submit.isEnabled()
    dialog.confirm.setChecked(False)
    assert not dialog.submit.isEnabled()
    assert client.reports == []


@pytest.mark.parametrize("name", [
    "", "1Mindflux", "<b>Mindflux</b>", "Mind\nflux", "Náme", "Name!", "  "])
def test_invalid_public_names_cannot_publish_even_after_confirmation(widgets, app, name):
    dialog, client = dialog_for(widgets, app, active_server="Green", reporter=name)
    dialog.confirm.setChecked(True)
    assert not dialog.submit.isEnabled()
    dialog.submit.click()
    assert client.reports == []


def test_public_report_disclosure_and_accessible_control_names_are_present(widgets, app):
    dialog, _client = dialog_for(widgets, app, active_server="Green", reporter="Mindflux")
    assert dialog.accessibleName()
    for control in (dialog.server, dialog.dock, dialog.reporter,
                    dialog.confirm, dialog.submit, dialog.status):
        assert control.accessibleName().strip()
    close_interface = QAccessible.queryAccessibleInterface(dialog.close_button)
    assert close_interface.text(QAccessible.Text.Name) == "Close"
    assert "public" in dialog.reporter.toolTip() and "not verified" in dialog.reporter.toolTip()
    text = " ".join(label.text() for label in dialog.scaled_surface.findChildren(QLabel))
    assert "public name" in text and "No logs" in text
    assert "not exact guarantees" in text


@pytest.mark.parametrize("active,viewed", [("Green", "Blue"), ("Blue", "Green")])
def test_report_uses_the_active_character_server_instead_of_viewed_server(
        widgets, app, active, viewed):
    dialog, client = dialog_for(
        widgets, app, active_server=active, viewed_server=viewed, reporter="Mindflux")
    assert dialog.server.currentText() == active
    assert not dialog.server.isEnabled()
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports[0][0] == active


def test_unknown_active_server_allows_manual_selection_without_publishing_on_open(widgets, app):
    dialog, client = dialog_for(
        widgets, app, active_server="", viewed_server="Green", reporter="Mindflux")
    assert dialog.server.isEnabled() and client.reports == []
    dialog.server.setCurrentText("Blue")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports == [("Blue", 0, "oasis", "Mindflux")]


@pytest.mark.parametrize("active", ["Red", "Quarm"])
def test_unsupported_active_server_stays_blocked_when_viewing_a_supported_server(
        widgets, app, active):
    dialog, client = dialog_for(
        widgets, app, active_server=active, viewed_server="Blue", reporter="Mindflux")
    dialog.server.setCurrentText("Green")
    dialog.confirm.setChecked(True)
    assert not dialog.submit.isEnabled()
    assert "Only Green and Blue" in dialog.status.text()
    dialog.submit.click()
    assert client.reports == []


@pytest.mark.parametrize("route", BOAT_ROUTES)
def test_exact_selected_dock_is_dispatched_as_a_manual_arrival(widgets, app, route):
    key = (route.boat_id, route.start_point)
    dialog, client = dialog_for(
        widgets, app, active_server="Green", reporter="O'Brien_2", route_key=key)
    assert dialog.dock.currentData() == key
    assert dialog.dock.count() == 7
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports == [("Green", *key, "O'Brien_2")]
    assert not dialog.submit.isEnabled() and "Sharing" in dialog.submit.text()
    dialog.submit.click()
    assert len(client.reports) == 1


@pytest.mark.parametrize("message", [
    "Correction pending independent confirmation; global timing has not changed.",
    "Community service is unavailable.",
])
def test_pending_and_failed_results_clear_consent_before_another_report(widgets, app, message):
    dialog, client = dialog_for(widgets, app, active_server="Green", reporter="Mindflux")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    client.complete(False, message)
    assert dialog.status.text() == message
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    assert dialog.status.textFormat() == Qt.TextFormat.PlainText
    dialog.submit.click()
    assert len(client.reports) == 1
    dialog.confirm.setChecked(True)
    assert dialog.submit.isEnabled()


def test_failed_to_start_report_clears_consent_without_a_completion_signal(widgets, app):
    client = FakeCommunityClient()
    client.starts = False
    dialog, _ = dialog_for(widgets, app, client, active_server="Green", reporter="Mindflux")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert "Could not start" in dialog.status.text()
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    assert len(client.reports) == 1


def test_accepted_report_saves_the_submitted_public_label_and_clears_confirmation(
        widgets, app, isolated_config):
    dialog, client = dialog_for(
        widgets, app, active_server="Green", reporter="  Mindflux  ")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports[0][3] == "Mindflux"
    # Editing during the request must not change the attribution that was sent.
    dialog.reporter.setText("Other")
    client.complete(True, "Arrival accepted as a community estimate.")
    assert config.data["spells"]["boat_reporter"] == "Mindflux"
    assert isolated_config == [True]
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()


def test_other_server_completion_does_not_clear_current_report_or_change_status(widgets, app):
    dialog, client = dialog_for(widgets, app, active_server="Green", reporter="Mindflux")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    client.report_finished.emit("Blue", False, "Unrelated failure")
    assert dialog.status.text() == "Sharing this arrival…"
    assert dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    client.complete(False, "The request timed out.")
    assert not dialog.confirm.isChecked()


def test_keyboard_tab_order_and_space_activation_reach_report_controls(widgets, app):
    dialog, client = dialog_for(
        widgets, app, active_server="", viewed_server="Green", reporter="Mindflux")
    dialog.server.setFocus()
    app.processEvents()
    for current, target in ((dialog.server, dialog.dock),
                            (dialog.dock, dialog.reporter),
                            (dialog.reporter, dialog.confirm)):
        assert current.hasFocus()
        QTest.keyClick(current, Qt.Key.Key_Tab)
        app.processEvents()
        assert target.hasFocus()
    QTest.keyClick(dialog.confirm, Qt.Key.Key_Space)
    assert dialog.confirm.isChecked() and dialog.submit.isEnabled()
    QTest.keyClick(dialog.confirm, Qt.Key.Key_Tab)
    app.processEvents()
    assert dialog.submit.hasFocus()
    QTest.keyClick(dialog.submit, Qt.Key.Key_Space)
    assert len(client.reports) == 1


def test_escape_closes_the_dialog_without_publishing(widgets, app):
    dialog, client = dialog_for(widgets, app, active_server="Green", reporter="Mindflux")
    finished = []
    dialog.finished.connect(finished.append)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    app.processEvents()
    assert finished == [QDialog.DialogCode.Rejected]
    assert client.reports == []


def test_group_controls_are_keyboard_accessible_and_sync_opens_only_on_request(widgets, app):
    group = widgets(BoatScheduleGroup())
    group.set_enabled(True)
    app.processEvents()
    requests = []
    changes = []
    group.report_requested.connect(requests.append)
    group.server_changed.connect(changes.append)
    assert group.server_selector.accessibleName() and group.sync_button.accessibleName()
    group.server_selector.setCurrentText("Blue")
    assert changes == ["Blue"] and requests == []
    group.sync_button.setFocus()
    QTest.keyClick(group.sync_button, Qt.Key.Key_Space)
    assert requests == [None]


def test_contributor_is_visible_plain_text_with_actual_arrival_age_and_confidence(
        widgets, app):
    group = widgets(BoatScheduleGroup())
    group.set_enabled(True)
    schedule = community_schedule(
        reporter="<b>Mindflux</b>", age=125, confidence="corroborated")
    group.update_schedules([schedule], "Green")
    app.processEvents()
    row = group.rows()[0]
    assert row.reporter_label.isVisible()
    assert row.reporter_label.textFormat() == Qt.TextFormat.PlainText
    plain_attribution = "Reported by <b>Mindflux</b> · 2m · corroborated"
    assert row.reporter_label.text().replace("\u200b", "") == plain_attribution
    assert row.reporter_label.accessibleName() == plain_attribution
    assert "self-reported name" in row.reporter_label.toolTip()
    assert "Vantage Community · Green" in row.toolTip()
    assert row.source_label.text() == "COMM · 2m"
    group.set_status("<b>Community estimate</b>")
    assert group.status.textFormat() == Qt.TextFormat.PlainText
    assert group.status.text() == "<b>Community estimate</b>"


def test_fallback_row_has_no_fabricated_contributor(widgets, app):
    group = widgets(BoatScheduleGroup())
    group.set_enabled(True)
    now = datetime.datetime.now(UTC)
    group.update_schedules([
        BoatSchedule(BOAT_ROUTES[0], now, 120, "PigParse API · Green", False)], "Green")
    app.processEvents()
    row = group.rows()[0]
    assert row.reporter_label.isHidden()
    assert row.source_label.text().startswith("PIG")
    assert "Reported by" not in row.toolTip()


def test_view_switch_clears_old_server_immediately_and_ignores_late_replies(widgets, app):
    harness = widgets(BoatHarness())
    green = community_schedule(server="Green")
    harness._boat_group.update_schedules([green], "Green")
    harness._boat_group.server_selector.setCurrentText("Blue")
    assert harness._boat_group.rows() == []
    assert harness._boat_server == "Blue"
    assert config.data["spells"]["boat_view_server"] == "Blue"
    assert harness._boat_community.refreshes == ["Blue"]
    before = harness._boat_group.status.text()
    harness._community_boats_ready("Green", [green], "Late Green community data")
    harness._community_boats_status("Green", "Late Green status")
    reply = FakeReply([activity()])
    harness._boat_reply_finished(reply, "Green")
    assert harness._boat_group.rows() == []
    assert harness._boat_group.status.text() == before
    assert not reply.read and reply.deleted
    app.processEvents()


def test_view_switch_loads_only_the_selected_server_cache(widgets, app):
    harness = widgets(BoatHarness())
    harness._boat_community.cache["Green"] = [community_schedule(server="Green")]
    harness._boat_community.cache["Blue"] = [
        community_schedule(BOAT_ROUTES[5], "Blue", "BlueReporter")]
    harness._boat_group.update_schedules(harness._boat_community.cache["Green"], "Green")
    harness._boat_group.server_selector.setCurrentText("Blue")
    rows = harness._boat_group.rows()
    assert len(rows) == 1 and rows[0]._schedule.source == "Vantage Community · Blue"
    assert rows[0]._schedule.reporter == "BlueReporter"
    assert "Blue" in harness._boat_group.status.text()
    assert harness._boat_community.refreshes == ["Blue"]


def test_hidden_boat_feature_ignores_community_data_and_status(widgets, app):
    harness = widgets(BoatHarness())
    harness._boat_toggle.setChecked(False)
    before = harness._boat_group.status.text()
    harness._community_boats_ready(
        "Green", [community_schedule()], "Should not become visible")
    harness._community_boats_status("Green", "Should not replace status")
    assert not harness._boat_group.rows()
    assert harness._boat_group.status.text() == before
    harness._refresh_boat_schedules()
    assert harness._boat_community.refreshes == []


def test_newer_local_arrival_beats_older_community_estimate(widgets, app):
    harness = widgets(BoatHarness())
    now = datetime.datetime.now(UTC)
    local = BoatSchedule(BOAT_ROUTES[0], now, 90, "EQ log · Mindflux", False)
    harness._boat_group.update_schedules([local], "Green")
    community_row = community_schedule(age=60)
    harness._community_boats_ready("Green", [community_row], "Community estimates · Green")
    assert harness._boat_group.rows()[0]._schedule is local
    assert harness.fallback_refreshes == 1


def test_new_community_snapshot_replaces_old_community_rows_without_ghosts(widgets, app):
    harness = widgets(BoatHarness())
    now = datetime.datetime.now(UTC)
    local = BoatSchedule(BOAT_ROUTES[5], now, 90, "EQ log · Mindflux", False)
    harness._boat_group.update_schedules([community_schedule(), local], "Green")
    harness._community_boats_ready("Green", [], "No community arrivals")
    assert [row._schedule for row in harness._boat_group.rows()] == [local]
    assert harness._boat_group.status.text() == "No community arrivals"


@pytest.mark.parametrize("source", ["EQ log · Mindflux", "PigParse API · Green"])
def test_unchanged_observation_keeps_absolute_arrival_during_community_remerge(
        widgets, app, source):
    harness = widgets(BoatHarness())
    now = datetime.datetime.now(UTC)
    existing = BoatSchedule(BOAT_ROUTES[0], now, 120, source, False)
    harness._boat_group.update_schedules([existing], "Green")
    row = harness._boat_group.rows()[0]
    # Simulate a countdown already partway through its cycle, without sleeping.
    countdown_deadline = now + datetime.timedelta(seconds=17)
    row._arrival_at = countdown_deadline
    harness._community_boats_ready(
        "Green", [community_schedule(BOAT_ROUTES[5])], "Community estimates · Green")
    assert row._schedule is existing
    assert row._arrival_at == countdown_deadline


def test_pigparse_only_fills_missing_boats_and_preserves_community_and_newer_local(
        widgets, app):
    harness = widgets(BoatHarness())
    community_row = community_schedule(age=60)
    now = datetime.datetime.now(UTC)
    local = BoatSchedule(BOAT_ROUTES[5], now, 90, "EQ log · Mindflux", False)
    harness._boat_group.update_schedules([community_row, local], "Green")
    reply = FakeReply([
        activity(BOAT_ROUTES[0]), activity(BOAT_ROUTES[3]),
        activity(BOAT_ROUTES[5], age=60)])
    harness._boat_reply_finished(reply, "Green")
    rows = {(row._schedule.route.boat_id, row._schedule.route.start_point):
            row._schedule for row in harness._boat_group.rows()}
    assert rows[(0, "oasis")] is community_row
    assert rows[(3, "nro")] is local
    assert rows[(2, "butcher")].source == "PigParse API · Green"
    assert rows[(2, "firiona")].source == "PigParse API · Green"
    assert reply.deleted and "PigParse fallback estimates" in harness._boat_group.status.text()


def test_open_report_dialog_passes_character_context_and_reuses_one_confirmation_window(
        widgets, app):
    harness = widgets(BoatHarness())
    harness._boat_group.server_selector.setCurrentText("Blue")
    harness._show_boat_arrival_dialog((3, "iceclad"))
    first = harness._boat_arrival_dialog
    assert first.server.currentText() == "Green"
    assert not first.server.isEnabled()
    assert first.reporter.text() == "Mindflux"
    assert first.dock.currentData() == (3, "iceclad")
    assert not first.confirm.isChecked()
    assert harness._boat_community.reports == []
    harness._show_boat_arrival_dialog((0, "oasis"))
    assert harness._boat_arrival_dialog is first
    first.reject()
    assert harness._boat_arrival_dialog is None


@pytest.mark.parametrize("raw,expected", [
    ("p1999Green", "Green"), ("p1999Blue", "Blue"),
    ("p1999Red", "Red"), ("Quarm", "Quarm"), ("", "")])
def test_character_server_detection_retains_unsupported_identity(widgets, app, raw, expected):
    harness = widgets(BoatHarness())
    harness._active_server = raw
    assert harness._boat_character_server() == expected


def test_nonempty_unrecognized_server_cannot_fall_back_to_a_supported_report(widgets, app):
    harness = widgets(BoatHarness())
    harness._active_server = "TestServer"
    detected = harness._boat_character_server()
    assert detected and detected not in ("Green", "Blue")
    harness._show_boat_arrival_dialog((0, "oasis"))
    dialog = harness._boat_arrival_dialog
    dialog.confirm.setChecked(True)
    assert not dialog.submit.isEnabled()
    dialog.submit.click()
    assert harness._boat_community.reports == []


def test_active_server_change_from_green_to_blue_requires_new_confirmation(widgets, app):
    current_server = ["Green"]
    dialog, client = dialog_for(
        widgets, app, active_server="Green", viewed_server="Green", reporter="Mindflux",
        active_server_provider=lambda: current_server[0])
    dialog.confirm.setChecked(True)
    current_server[0] = "Blue"
    dialog.submit.click()
    assert client.reports == []
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    assert dialog.server.currentText() == "Blue" and not dialog.server.isEnabled()
    assert not dialog._unsupported_server
    assert "confirm" in dialog.status.text().casefold()
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports == [("Blue", 0, "oasis", "Mindflux")]


def test_active_server_change_from_green_to_red_cancels_and_blocks_submission(widgets, app):
    current_server = ["Green"]
    dialog, client = dialog_for(
        widgets, app, active_server="Green", viewed_server="Blue", reporter="Mindflux",
        active_server_provider=lambda: current_server[0])
    dialog.confirm.setChecked(True)
    current_server[0] = "Red"
    dialog.submit.click()
    assert client.reports == []
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    assert dialog._unsupported_server
    assert "supported" in dialog.status.text().casefold()
    dialog.server.setCurrentText("Blue")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert not dialog.submit.isEnabled() and client.reports == []


def test_active_server_becoming_unknown_requires_manual_selection_and_reconfirmation(
        widgets, app):
    current_server = ["Green"]
    dialog, client = dialog_for(
        widgets, app, active_server="Green", viewed_server="Green", reporter="Mindflux",
        active_server_provider=lambda: current_server[0])
    dialog.confirm.setChecked(True)
    current_server[0] = ""
    dialog.submit.click()
    assert client.reports == []
    assert not dialog.confirm.isChecked() and not dialog.submit.isEnabled()
    assert dialog.server.isEnabled() and not dialog._unsupported_server
    assert "confirm" in dialog.status.text().casefold()
    dialog.server.setCurrentText("Blue")
    dialog.confirm.setChecked(True)
    dialog.submit.click()
    assert client.reports == [("Blue", 0, "oasis", "Mindflux")]


def test_larger_text_scrolls_complete_instructions_while_named_actions_stay_visible(
        widgets, app):
    dialog, client = dialog_for(
        widgets, app, active_server="Green", reporter="Mindflux")
    # The native body is 12px. Scope 150% text to this isolated dialog, even
    # when another test has applied an application-wide stylesheet.
    dialog.scaled_surface.setStyleSheet("QWidget { font-size: 18px; }")
    app.processEvents()
    scrolls = dialog.scaled_surface.findChildren(QScrollArea)
    assert len(scrolls) == 1
    body = scrolls[0]
    assert body.verticalScrollBar().maximum() > 0
    instructions = next(label for label in body.widget().findChildren(QLabel)
                        if label.text().startswith("Press Sync only"))
    assert instructions.wordWrap()
    assert instructions.height() >= instructions.heightForWidth(instructions.width())
    assert "not exact guarantees" in instructions.text()
    assert instructions.accessibleName()
    surface = dialog.scaled_surface

    def actions_in_bounds():
        for button in (dialog.submit, dialog.close_button):
            rect = QRect(button.mapTo(surface, QPoint(0, 0)), button.size())
            assert surface.rect().contains(rect)
            assert button.isVisible()
            interface = QAccessible.queryAccessibleInterface(button)
            assert interface.text(QAccessible.Text.Name).strip()

    actions_in_bounds()
    body.verticalScrollBar().setValue(body.verticalScrollBar().maximum())
    app.processEvents()
    actions_in_bounds()
    assert client.reports == []


def test_bundled_theme_keeps_scroll_body_dark_for_light_report_text(widgets, app):
    dialog, _client = dialog_for(
        widgets, app, active_server="Green", reporter="Mindflux")
    root = Path(__file__).resolve().parents[1]
    stylesheet = (root / "data" / "ui" / "_.css").read_text(encoding="utf-8")
    for token, filename in (
        ("CHECK", "check.svg"), ("CHECK_PARTIAL", "check-partial.svg"),
        ("CHEVRON_TOP", "chevron-top.svg"), ("CHEVRON_BOTTOM", "chevron-bottom.svg"),
    ):
        stylesheet = stylesheet.replace(
            f"__VANTAGE_{token}_ICON__", (root / "data" / "ui" / "icons" / filename).as_posix())
    dialog.scaled_surface.setStyleSheet(stylesheet)
    app.processEvents()
    body = dialog.body_scroll.widget()
    background = body.grab().toImage().pixelColor(body.width() - 3, body.height() - 3)
    assert max(background.red(), background.green(), background.blue()) < 40


def test_maximum_public_name_does_not_widen_the_compact_panel(widgets, app):
    group = widgets(BoatScheduleGroup())
    group.set_enabled(True)
    group.update_schedules([community_schedule(reporter="Mindflux")], "Green")
    app.processEvents()
    ordinary_minimum = group.minimumSizeHint().width()
    group.update_schedules([community_schedule(reporter="M" * 48)], "Green")
    group.resize(260, 450)
    app.processEvents()
    assert group.minimumSizeHint().width() <= ordinary_minimum
    assert group.width() <= max(260, ordinary_minimum)
