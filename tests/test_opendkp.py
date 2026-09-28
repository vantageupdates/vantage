import base64
import copy
import datetime
import json
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHeaderView, QLabel, QWidget)

from vantage.helpers import config
from vantage.helpers.opendkp import (
    OpenDkpClient, auction_bids, auction_id, auction_item_name, decode_token_username,
    normalize_guild_slug, rows_from_payload, watch_matches)
from vantage.helpers.raid_ledger import (
    MISSING, PENDING, VERIFIED, RaidLedger, raid_time_matches,
    remote_tick_evidence)
from vantage.parsers.opendkp import OpenDKP, SortItem, _date_cell
from vantage.parsers.opendkp import _raid_request_context, _raid_tick_phrases
from vantage.helpers.log_search_cache import SearchResult


def test_raid_ledger_persists_bounded_private_sessions_and_evidence(tmp_path):
    ledger = RaidLedger(tmp_path / "raid-ledger.sqlite", max_sessions=25)
    started = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(
        started, "Mindflux", "Green", "Kael Drakkel")
    assert session["waiting_for_who"] == 1
    assert ledger.add_tick(
        session["id"], started, "Raidlead", "RAID TICK", "log") is True
    assert ledger.add_roster(
        session["id"], started, "Kael Drakkel",
        ["Mindflux", "Raidlead"]) is True
    assert ledger.update_session(
        session["id"], mobs="Statue", notes="Present from start") is True
    assert ledger.link_remote(session["id"], "raid-42") is True
    ledger.set_check(
        session["id"], VERIFIED, remote_id="raid-42",
        remote_name="Statue", tick_count=1, dkp_total=10)
    assert ledger.end_session(session["id"], started + datetime.timedelta(hours=2))

    saved = ledger.session(session["id"])
    evidence = ledger.evidence(session["id"])
    assert saved["character"] == "Mindflux"
    assert saved["server"] == "Green"
    assert saved["waiting_for_who"] == 0
    assert saved["mobs"] == "Statue"
    assert saved["notes"] == "Present from start"
    assert saved["verification_status"] == VERIFIED
    assert evidence["ticks"][0]["speaker"] == "Raidlead"
    assert evidence["rosters"][0]["members"] == ["Mindflux", "Raidlead"]
    ledger.close()


def test_raid_log_capture_requires_complete_who_and_records_chat_speaker(tmp_path):
    ledger = RaidLedger(tmp_path / "raid-ledger.sqlite")
    stamp = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(stamp, "Mindflux", "Green", "Kael Drakkel")
    statuses = []
    harness = SimpleNamespace(
        raid_ledger=ledger, _who_captures={},
        ZONE_LINE=OpenDKP.ZONE_LINE, WHO_HEADER=OpenDKP.WHO_HEADER,
        WHO_ROW=OpenDKP.WHO_ROW, WHO_END=OpenDKP.WHO_END,
        RAID_CHAT=OpenDKP.RAID_CHAT,
        _raid_identity=lambda: ("Mindflux", "Green", "Kael Drakkel"),
        _set_my_raids_status=lambda *args, **kwargs: statuses.append(args),
        _schedule_my_raids_refresh=lambda: None)
    for line in (
            "Players in EverQuest:",
            "[60 Cleric] Mindflux (Human) <Castle>",
            "[60 Warrior] Raidlead (Ogre) <Castle>",
            "There are 2 players in Kael Drakkel.",
            "Raidlead tells the raid, 'RAID TICK'",
            "You say to your guild, 'RAID TICK'"):
        OpenDKP.parse(harness, stamp, line)

    saved = ledger.session(session["id"])
    evidence = ledger.evidence(session["id"])
    assert saved["waiting_for_who"] == 0
    assert saved["zone"] == "Kael Drakkel"
    assert evidence["rosters"][0]["members"] == ["Mindflux", "Raidlead"]
    assert [tick["speaker"] for tick in evidence["ticks"]] == [
        "Raidlead", "Mindflux"]
    assert any("Saved complete /who" in status[0] for status in statuses)
    ledger.close()


def test_incomplete_who_remains_waiting_and_is_not_persisted(tmp_path):
    ledger = RaidLedger(tmp_path / "raid-ledger.sqlite")
    stamp = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(stamp, "Mindflux", "Green", "Kael Drakkel")
    harness = SimpleNamespace(
        raid_ledger=ledger, _who_captures={},
        ZONE_LINE=OpenDKP.ZONE_LINE, WHO_HEADER=OpenDKP.WHO_HEADER,
        WHO_ROW=OpenDKP.WHO_ROW, WHO_END=OpenDKP.WHO_END,
        RAID_CHAT=OpenDKP.RAID_CHAT,
        _raid_identity=lambda: ("Mindflux", "Green", "Kael Drakkel"),
        _set_my_raids_status=lambda *_args, **_kwargs: None,
        _schedule_my_raids_refresh=lambda: None)
    OpenDKP.parse(harness, stamp, "Players in Kael Drakkel:")
    OpenDKP.parse(harness, stamp, "[60 Cleric] Mindflux (Human) <Castle>")
    OpenDKP.parse(harness, stamp, "There are 2 players in Kael Drakkel.")
    assert ledger.session(session["id"])["waiting_for_who"] == 1
    assert ledger.evidence(session["id"])["rosters"] == []
    ledger.close()


def test_who_capture_is_discarded_when_log_identity_changes(tmp_path):
    ledger = RaidLedger(tmp_path / "raid-ledger.sqlite")
    stamp = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(stamp, "Mindflux", "Green", "Kael Drakkel")
    identity = ["Mindflux", "Green", "Kael Drakkel"]
    harness = SimpleNamespace(
        raid_ledger=ledger, _who_captures={}, _last_raid_identity=None,
        ZONE_LINE=OpenDKP.ZONE_LINE, WHO_HEADER=OpenDKP.WHO_HEADER,
        WHO_ROW=OpenDKP.WHO_ROW, WHO_END=OpenDKP.WHO_END,
        RAID_CHAT=OpenDKP.RAID_CHAT,
        _raid_identity=lambda: tuple(identity),
        _set_my_raids_status=lambda *_args, **_kwargs: None,
        _schedule_my_raids_refresh=lambda: None)
    OpenDKP.parse(harness, stamp, "Players in EverQuest:")
    OpenDKP.parse(harness, stamp, "[60 Cleric] Mindflux (Human) <Castle>")
    identity[:] = ["Other", "Green", "Kael Drakkel"]
    OpenDKP.parse(harness, stamp, "[60 Warrior] Other (Ogre) <Castle>")
    identity[:] = ["Mindflux", "Green", "Kael Drakkel"]
    OpenDKP.parse(harness, stamp, "There is 1 player in Kael Drakkel.")
    assert ledger.session(session["id"])["waiting_for_who"] == 1
    assert ledger.evidence(session["id"])["rosters"] == []
    ledger.close()


def test_complete_who_uses_footer_zone_not_header_or_context(tmp_path):
    ledger = RaidLedger(tmp_path / "raid-ledger.sqlite")
    stamp = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(stamp, "Mindflux", "Green", "Kael Drakkel")
    harness = SimpleNamespace(
        raid_ledger=ledger, _who_captures={}, _last_raid_identity=None,
        ZONE_LINE=OpenDKP.ZONE_LINE, WHO_HEADER=OpenDKP.WHO_HEADER,
        WHO_ROW=OpenDKP.WHO_ROW, WHO_END=OpenDKP.WHO_END,
        RAID_CHAT=OpenDKP.RAID_CHAT,
        _raid_identity=lambda: ("Mindflux", "Green", "Kael Drakkel"),
        _set_my_raids_status=lambda *_args, **_kwargs: None,
        _schedule_my_raids_refresh=lambda: None)
    OpenDKP.parse(harness, stamp, "Players in EverQuest:")
    OpenDKP.parse(harness, stamp, "[60 Cleric] Mindflux (Human) <Castle>")
    OpenDKP.parse(harness, stamp, "There is 1 player in Plane of Sky.")
    saved = ledger.session(session["id"])
    evidence = ledger.evidence(session["id"])
    assert saved["zone"] == "Plane of Sky"
    assert evidence["rosters"][0]["zone"] == "Plane of Sky"
    ledger.close()


def test_raid_tick_phrases_are_configurable_and_bounded():
    original = copy.deepcopy(config.data)
    try:
        config.data = {"opendkp": {
            "raid_tick_phrases": [" RAID   TICK ", "raid tick", "Attendance"]}}
        assert _raid_tick_phrases() == ["RAID TICK", "Attendance"]
    finally:
        config.data = original


def test_correlated_raid_operations_reject_stale_generation_and_slug():
    calls = []
    harness = SimpleNamespace(
        client=SimpleNamespace(slug="castle"),
        _raid_check_slug="castle", _raid_check_token="new-generation",
        _receive_raid_list=lambda payload: calls.append(("list", payload)),
        _receive_raid_detail=lambda raid_id, payload:
            calls.append((raid_id, payload)))
    OpenDKP._response(
        harness, "raid_ledger|old-generation", {"Models": [{"Id": 1}]})
    OpenDKP._response(
        harness, "raid_ledger_detail|old-generation|1", {"Id": 1})
    OpenDKP._response(
        harness, "raid_ledger", {"Models": [{"Id": "legacy-stale"}]})
    assert calls == []
    OpenDKP._response(
        harness, "raid_ledger|new-generation", {"Models": [{"Id": 2}]})
    OpenDKP._response(
        harness, "raid_ledger_detail|new-generation|2", {"Id": 2})
    assert calls == [
        ("list", {"Models": [{"Id": 2}]}), ("2", {"Id": 2})]
    harness.client.slug = "another-guild"
    OpenDKP._response(
        harness, "raid_ledger|new-generation", {"Models": [{"Id": 3}]})
    assert len(calls) == 2


def test_raid_request_context_keeps_legacy_compatibility():
    assert _raid_request_context("raid_ledger") == ("list", "", "")
    assert _raid_request_context("raid_ledger|abc") == ("list", "abc", "")
    assert _raid_request_context("raid_ledger_detail:42") == (
        "detail", "", "42")
    assert _raid_request_context("raid_ledger_detail|abc|42") == (
        "detail", "abc", "42")


def test_client_raid_requests_include_generation_without_changing_routes():
    requests = []
    harness = SimpleNamespace(
        slug="castle",
        _request=lambda operation, method, path:
            requests.append((operation, method, path)))
    assert OpenDkpClient.fetch_raid_ledger(harness, "generation-2") is True
    assert OpenDkpClient.fetch_raid_details(
        harness, "raid/42", "generation-2") is True
    assert requests == [
        ("raid_ledger|generation-2", "GET",
         "/clients/castle/raids?count=100"),
        ("raid_ledger_detail|generation-2|raid/42", "GET",
         "/clients/castle/raids/raid%2F42"),
    ]


def test_my_raids_editor_and_sort_controls_are_keyboard_accessible(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        def __init__(self):
            QWidget.__init__(self)
            self.raid_ledger = RaidLedger(tmp_path / "ui-ledger.sqlite")
            self.client = SimpleNamespace(slug="")
            self._busy = False
            self._raid_refresh_scheduled = False
            self._active_character = "Mindflux"
            self._active_server = "Green"
            self._announce = lambda *_args, **_kwargs: None
            self.raid_ledger.start_session(
                datetime.datetime(2026, 9, 26, 19, 30),
                "Mindflux", "Green", "Kael Drakkel")

    widget = Harness()
    page = widget._build_my_raids()
    try:
        editor = widget.raid_mobs.parentWidget()
        assert isinstance(editor, QGroupBox)
        assert editor.accessibleName() == "Selected raid details"
        assert editor.accessibleDescription()
        assert widget.raid_notes.tabChangesFocus() is True
        assert widget.raid_mobs.isEnabled() is False
        assert widget.raid_notes.isEnabled() is False
        assert widget.raid_remote_id.isEnabled() is False
        assert widget.raid_sort_column.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert widget.raid_sort_button.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert widget.raid_sort_column.accessibleName() == "My raids sort column"
        assert widget.raid_sort_button.text() == "Sort ascending"
        assert widget.raid_sort_button.accessibleName() == "Sort ascending"
        assert widget.raid_mobs.accessibleName() == "Raid mobs or targets"
        assert widget.raid_notes.accessibleName() == "Raid notes"
        assert widget.raid_remote_id.accessibleName() == "OpenDKP remote raid ID"
        widget.raid_ledger.set_check(1, PENDING)
        widget._populate_my_raids()
        assert widget.my_raids_table.horizontalHeaderItem(0).text() == "Started"
        assert widget.my_raids_table.horizontalHeaderItem(1).text() == "Ended"
        assert widget.my_raids_table.item(0, 3).text() == "Green"
        assert widget.my_raids_table.item(0, 6).text() == (
            "Pending — needs review")
        widget.raid_ledger.set_check(1, MISSING)
        widget._populate_my_raids()
        assert widget.my_raids_table.item(0, 6).text() == (
            "Missing — review needed")
        assert widget._sort_my_raids() is True
        assert (widget.my_raids_table.horizontalHeader().sortIndicatorOrder() ==
                Qt.SortOrder.AscendingOrder)
        assert widget.raid_sort_button.text() == "Sort descending"
        assert widget.raid_sort_button.accessibleName() == "Sort descending"
        history_header = widget.my_raids_table.horizontalHeader()
        history_header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        assert widget.raid_sort_button.text() == "Sort ascending"
        assert widget.raid_sort_button.accessibleName() == "Sort ascending"
        history_header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        app.processEvents()
        assert widget.raid_sort_button.text() == "Sort descending"
        assert widget.raid_sort_button.accessibleName() == "Sort descending"
        widget.raid_sort_column.setCurrentIndex(1)
        assert widget.raid_sort_button.text() == "Sort ascending"
        assert widget.raid_sort_button.accessibleName() == "Sort ascending"
        assert widget._sort_my_raids() is True
        assert widget.my_raids_table.horizontalHeader().sortIndicatorSection() == 1
        assert (widget.my_raids_table.horizontalHeader().sortIndicatorOrder() ==
                Qt.SortOrder.AscendingOrder)
        assert widget.raid_sort_button.text() == "Sort descending"
        page.show()
        app.processEvents()
        assert widget._end_raid() is True
        app.processEvents()
        assert app.focusWidget() is widget.raid_start_button
    finally:
        widget.raid_ledger.close()
        page.deleteLater()
        widget.deleteLater()
        app.processEvents()


def test_my_raids_status_announcements_are_polite_and_deduplicated():
    app = QApplication.instance() or QApplication([])
    announcements = []
    harness = SimpleNamespace(
        my_raids_status=QLabel(), _last_my_raids_announcement="",
        _announce=lambda text, assertive=False:
            announcements.append((text, assertive)))
    OpenDKP._set_my_raids_status(
        harness, "Waiting for /who", "warning", announce=True)
    OpenDKP._set_my_raids_status(
        harness, "Waiting for /who", "warning", announce=True)
    assert announcements == [("Waiting for /who", False)]
    harness.my_raids_status.deleteLater()
    app.processEvents()


def test_my_raids_tick_finder_is_compact_keyboard_accessible_and_adjustable(
        tmp_path):
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        def __init__(self):
            QWidget.__init__(self)
            self.raid_ledger = RaidLedger(tmp_path / "finder-ui.sqlite")
            self.client = SimpleNamespace(slug="")
            self._busy = False
            self._raid_refresh_scheduled = False
            self._active_character = "Mindflux"
            self._active_server = "Green"
            self._announce = lambda *_args, **_kwargs: None

    widget = Harness()
    page = widget._build_my_raids()
    try:
        labels = [widget.raid_workspace_tabs.tabText(index)
                  for index in range(widget.raid_workspace_tabs.count())]
        assert labels == ["History & evidence", "Find raid ticks", "Tick phrases"]
        assert widget.raid_workspace_tabs.accessibleName() == "My raids workspaces"
        assert widget.raid_log_query.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert widget.raid_log_profile.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert widget.raid_log_range.focusPolicy() & Qt.FocusPolicy.TabFocus
        assert widget.raid_log_sort_button.text() == "Sort ascending"
        assert widget.raid_log_sort_button.accessibleName() == "Sort ascending"
        assert widget.raid_log_table.columnCount() == 5
        assert widget.raid_log_table.horizontalHeader().sectionResizeMode(0) == (
            QHeaderView.ResizeMode.Interactive)
        assert widget.raid_log_table.accessibleDescription()
        assert widget.raid_log_attach_button.text() == "Attach to selected raid"
        assert widget.raid_log_attach_button.isEnabled() is False
        assert widget.raid_log_status.accessibleName() == "Raid tick finder status"
        widget.raid_log_sort_column.setCurrentIndex(1)
        assert widget.raid_log_sort_button.text() == "Sort ascending"
        assert widget.raid_log_sort_button.accessibleName() == "Sort ascending"
        assert widget._sort_raid_log_results() is True
        assert widget.raid_log_table.horizontalHeader().sortIndicatorSection() == 1
        assert (widget.raid_log_table.horizontalHeader().sortIndicatorOrder() ==
                Qt.SortOrder.AscendingOrder)
        assert widget.raid_log_sort_button.text() == "Sort descending"
        finder_header = widget.raid_log_table.horizontalHeader()
        finder_header.setSortIndicator(1, Qt.SortOrder.DescendingOrder)
        app.processEvents()
        assert widget.raid_log_sort_button.text() == "Sort ascending"
        assert widget.raid_log_sort_button.accessibleName() == "Sort ascending"
        finder_header.setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        app.processEvents()
        assert widget.raid_log_sort_button.text() == "Sort descending"
        assert widget.raid_log_sort_button.accessibleName() == "Sort descending"
    finally:
        widget.raid_ledger.close()
        page.deleteLater()
        widget.deleteLater()
        app.processEvents()


def test_raid_tick_finder_attach_requires_raid_and_preserves_evidence(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        def __init__(self):
            QWidget.__init__(self)
            self.raid_ledger = RaidLedger(tmp_path / "attach.sqlite")
            self.client = SimpleNamespace(slug="")
            self._busy = False
            self._raid_refresh_scheduled = False
            self._active_character = "Mindflux"
            self._active_server = "Green"
            self._announce = lambda *_args, **_kwargs: None
            self.raid_ledger.start_session(
                datetime.datetime(2026, 9, 26, 19, 0),
                "Mindflux", "Green", "Kael Drakkel")

    widget = Harness()
    page = widget._build_my_raids()
    result = SearchResult(
        "2026-09-26T19:30:00", "Mindflux", "Green", "conversation",
        "Raidlead tells the raid, 'RAID TICK'",
        "archive/eqlog_Mindflux_Green.txt")
    try:
        widget._raid_log_search_token = "current"
        widget._raid_logs_directory = lambda: "C:/EverQuest/Logs"
        widget._raid_log_search_directory = "C:/EverQuest/Logs"
        widget._raid_log_search_complete("current", (result,), False, "")
        assert widget._attach_selected_raid_tick() is False
        assert widget.raid_ledger.evidence(1)["ticks"] == []
        assert "Select a local raid" in widget.raid_log_status.text()

        widget.my_raids_table.selectRow(0)
        widget._my_raid_selected()
        assert widget._attach_selected_raid_tick() is True
        tick = widget.raid_ledger.evidence(1)["ticks"][0]
        assert tick["timestamp"] == "2026-09-26T19:30:00"
        assert tick["speaker"] == "Raidlead"
        assert tick["message"] == "RAID TICK"
        assert tick["character"] == "Mindflux"
        assert tick["server"] == "Green"
        assert tick["source"] == (
            "log-search:archive/eqlog_Mindflux_Green.txt")
        assert widget._attach_selected_raid_tick() is False
        assert len(widget.raid_ledger.evidence(1)["ticks"]) == 1
        assert "already attached" in widget.raid_log_status.text()
    finally:
        widget.raid_ledger.close()
        page.deleteLater()
        widget.deleteLater()
        app.processEvents()


def test_raid_tick_search_ignores_stale_async_results(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        def __init__(self):
            QWidget.__init__(self)
            self.raid_ledger = RaidLedger(tmp_path / "stale.sqlite")
            self.client = SimpleNamespace(slug="")
            self._busy = False
            self._raid_refresh_scheduled = False
            self._active_character = "Mindflux"
            self._active_server = "Green"
            self._announce = lambda *_args, **_kwargs: None

    widget = Harness()
    page = widget._build_my_raids()
    stale = SearchResult(
        "2026-09-26T18:00:00", "Old", "Green", "conversation",
        "Old tells the raid, 'RAID TICK'", "old.txt")
    current = SearchResult(
        "2026-09-26T19:00:00", "New", "Green", "conversation",
        "New tells the raid, 'RAID TICK'", "new.txt")
    try:
        widget._raid_log_search_token = "new-token"
        widget._raid_logs_directory = lambda: "C:/EverQuest/Logs"
        widget._raid_log_search_directory = "C:/EverQuest/Logs"
        widget._raid_log_search_complete("old-token", (stale,), False, "")
        assert widget.raid_log_table.rowCount() == 0
        widget._raid_log_search_complete("new-token", (current,), False, "")
        assert widget.raid_log_table.rowCount() == 1
        assert widget.raid_log_table.item(0, 1).text() == "New"
        status = widget.raid_log_status.text()
        widget._raid_log_search_complete("old-token", (stale,), False, "")
        assert widget.raid_log_table.item(0, 1).text() == "New"
        assert widget.raid_log_status.text() == status
        widget._raid_log_search_token = "root-change"
        widget._raid_log_search_directory = "old-root"
        widget._raid_logs_directory = lambda: "new-root"
        widget._update_raid_log_source = lambda: "new-root"
        widget.raid_log_search_button.setEnabled(False)
        widget._set_raid_log_status("Searching every linked log…", "loading")
        widget._raid_log_search_complete("root-change", (stale,), False, "")
        assert widget.raid_log_table.item(0, 1).text() == "New"
        assert "Logs folder changed" in widget.raid_log_status.text()
        assert widget.raid_log_search_button.isEnabled() is True
        assert widget._raid_log_search_token == ""
    finally:
        widget.raid_ledger.close()
        page.deleteLater()
        widget.deleteLater()
        app.processEvents()


def test_raid_tick_finder_status_announcements_are_polite_and_deduplicated():
    app = QApplication.instance() or QApplication([])
    announcements = []
    harness = SimpleNamespace(
        raid_log_status=QLabel("Waiting"),
        _last_raid_log_announcement="",
        _announce=lambda text, assertive=False:
            announcements.append((text, assertive)))
    OpenDKP._set_raid_log_status(
        harness, "Found 2 matching raid tick messages", "ready")
    OpenDKP._set_raid_log_status(
        harness, "Found 2 matching raid tick messages", "ready")
    assert announcements == [
        ("Found 2 matching raid tick messages", False)]
    assert harness.raid_log_status.accessibleDescription() == (
        "Found 2 matching raid tick messages")
    harness.raid_log_status.deleteLater()
    app.processEvents()


def test_raid_log_index_preserves_moved_focus_and_settles_root_changes(tmp_path):
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        def __init__(self):
            QWidget.__init__(self)
            self.raid_ledger = RaidLedger(tmp_path / "focus.sqlite")
            self.client = SimpleNamespace(slug="")
            self._busy = False
            self._raid_refresh_scheduled = False
            self._active_character = "Mindflux"
            self._active_server = "Green"
            self._announce = lambda *_args, **_kwargs: None

    widget = Harness()
    page = widget._build_my_raids()
    summary = SimpleNamespace(
        characters=(("Mindflux", "Green"),), indexed_lines=20,
        files=2, added_lines=3)
    try:
        page.show()
        widget.raid_workspace_tabs.setCurrentIndex(1)
        app.processEvents()
        widget._raid_logs_directory = lambda: "C:/EverQuest/Logs"
        widget._raid_log_index_token = "complete"
        widget._raid_log_index_focus = widget.raid_log_refresh_button
        widget._raid_log_index_fallback_focus = widget.raid_log_search_button
        widget.raid_log_refresh_button.setEnabled(False)
        widget.raid_log_query.setFocus(Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        assert app.focusWidget() is widget.raid_log_query
        widget._raid_log_index_complete(
            "complete", summary, "", "C:/EverQuest/Logs")
        assert app.focusWidget() is widget.raid_log_query
        assert widget.raid_log_refresh_button.isEnabled() is True
        assert widget.raid_log_status.text().startswith("Cached 20 lines")

        widget._raid_log_index_token = "root-change"
        widget._raid_log_index_focus = widget.raid_log_refresh_button
        widget._raid_log_index_fallback_focus = widget.raid_log_search_button
        widget.raid_log_refresh_button.setEnabled(False)
        widget._raid_logs_directory = lambda: "D:/Other/Logs"
        widget._update_raid_log_source = lambda: "D:/Other/Logs"
        widget.raid_log_query.setFocus(Qt.FocusReason.OtherFocusReason)
        widget._raid_log_index_complete(
            "root-change", summary, "", "C:/EverQuest/Logs")
        assert widget.raid_log_refresh_button.isEnabled() is True
        assert widget._raid_log_index_token == ""
        assert "Logs folder changed" in widget.raid_log_status.text()
        assert widget.raid_log_progress.format() == "Logs folder changed"
        assert app.focusWidget() is widget.raid_log_query
    finally:
        widget.raid_ledger.close()
        page.deleteLater()
        widget.deleteLater()
        app.processEvents()


def test_official_opendkp_tick_shape_attributes_parent_value_to_toon():
    payload = {
        "Id": 42, "Name": "Statue",
        "Ticks": [
            {"TickId": 1, "Value": 5, "Description": "On time",
             "Characters": [{"Name": "Mindflux"}, {"Name": "Other"}]},
            {"TickId": 2, "Value": 7.5, "Description": "Hourly",
             "Characters": [{"Name": "Mindflux"}]},
            {"TickId": 3, "Value": 20, "Description": "Late",
             "Characters": [{"Name": "SomeoneElse"}]},
        ]}
    ticks, dkp = remote_tick_evidence(payload, "mindflux")
    assert [tick["TickId"] for tick in ticks] == [1, 2]
    assert dkp == 12.5


def test_raid_time_matching_rejects_unrelated_dates():
    session = {
        "started_at": "2026-09-26T19:00:00-04:00",
        "ended_at": "2026-09-26T23:00:00-04:00"}
    assert raid_time_matches(
        session, {"Timestamp": "2026-09-27T00:30:00Z"}) is True
    assert raid_time_matches(
        session, {"Timestamp": "2026-09-30T00:30:00Z"}) is False


def test_generic_guild_normalization_accepts_slug_or_opendkp_address_only():
    assert normalize_guild_slug("dragon-guild") == "dragon-guild"
    assert normalize_guild_slug("https://Dragon-Guild.OpenDKP.com/#/bids") == "dragon-guild"
    assert normalize_guild_slug("dragon-guild.opendkp.com") == "dragon-guild"
    assert normalize_guild_slug("https://example.com/dragon-guild") == ""
    assert normalize_guild_slug("bad guild") == ""
    assert normalize_guild_slug("-bad-") == ""


def test_payload_and_auction_helpers_support_current_and_legacy_shapes():
    row = {"Id": "42", "Item": {"Name": " Cloak   of Flames "},
           "bids": [{"CharacterId": 7, "Value": 50}]}
    assert rows_from_payload({"Models": [row]}, "Models") == [row]
    assert rows_from_payload([row], "Models") == [row]
    assert auction_id(row) == 42
    assert auction_item_name(row) == "Cloak of Flames"
    assert auction_bids(row) == row["bids"]
    assert watch_matches(row, ["cloak", "manastone"]) == ["cloak"]


def test_token_username_decode_never_requires_or_exposes_a_secret():
    encoded = base64.urlsafe_b64encode(json.dumps(
        {"cognito:username": "RaiderOne"}).encode()).decode().rstrip("=")
    assert decode_token_username(f"ignored.{encoded}.signature") == "RaiderOne"
    assert decode_token_username("not-a-token") == ""


def test_opendkp_profiles_and_sheets_are_bounded_and_never_store_passwords():
    original = copy.deepcopy(config.data)
    try:
        sheet_id = "a" * 32
        config.data = {"opendkp": {"active_guild": "GUILD-ONE", "guilds": [{
            "slug": "GUILD-ONE", "name": " Any Guild ",
            "character_id": "25", "character_name": " A Character ",
            "username": " Account ", "password": "must-not-survive",
            "watch_items": [" Cloak  of Flames ", "cloak of flames", "Manastone"],
        }, {"slug": "bad guild"}],
        "raid_tick_phrases": [" raid   tick ", "RAID TICK", "Attendance"],
        "active_sheet": sheet_id, "sheets": [{
            "id": sheet_id, "name": " Guild Loot ",
            "url": "https://docs.google.com/spreadsheets/d/" + "x" * 32 +
                   "/edit?gid=0",
        }, {"id": "bad", "name": "Unsafe", "url": "https://example.com"}]}}
        config.verify_settings()
        assert config.data["opendkp"]["active_guild"] == "guild-one"
        assert config.data["opendkp"]["guilds"] == [{
            "slug": "guild-one", "name": "Any Guild",
            "url": "https://guild-one.opendkp.com",
            "character_id": 25, "character_name": "A Character",
            "username": "Account",
            "watch_items": ["Cloak of Flames", "Manastone"],
        }]
        assert "password" not in json.dumps(config.data["opendkp"]).casefold()
        assert config.data["opendkp"]["raid_tick_phrases"] == [
            "raid tick", "Attendance"]
        assert config.data["opendkp"]["sheets"] == [{
            "id": sheet_id, "name": "Guild Loot",
            "url": "https://docs.google.com/spreadsheets/d/" + "x" * 32 +
                   "/edit?gid=0",
        }]
        assert config.data["opendkp"]["active_sheet"] == sheet_id
    finally:
        config.data = original


def test_quickbar_catalog_exposes_one_generic_opendkp_window():
    from vantage.helpers.quickbar_items import QUICKBAR_ITEMS
    matches = [item for item in QUICKBAR_ITEMS if item[0] == "opendkp"]
    assert matches == [
        ("opendkp", "Guild DKP & More", "ph-gavel", "windows")]


def test_mobile_guild_selector_accepts_only_saved_guild_profiles():
    class Harness:
        def __init__(self):
            self.filled = []
            self.loaded = []

        def _profiles(self):
            return [
                {"slug": "castle", "name": "Castle"},
                {"slug": "azure-guard", "name": "Azure Guard"},
            ]

        def _fill_guild_profiles(self, slug):
            self.filled.append(slug)

        def _load_guild(self, slug):
            self.loaded.append(slug)
            return True

    harness = Harness()
    assert OpenDKP.mobile_select(harness, "Azure-Guard.OpenDKP.com") is True
    assert harness.filled == ["azure-guard"]
    assert harness.loaded == ["azure-guard"]
    assert OpenDKP.mobile_select(harness, "not-saved") is False


def test_mobile_guild_snapshot_keeps_every_member_searchable():
    """A character beyond the old first-page cap must reach Mobile search."""
    standings = [{
        "CharacterName": f"Member{index:04d}",
        "CharacterClass": "Cleric",
        "CharacterLevel": 60,
        "CharacterRank": "Raider",
        "CurrentDKP": index,
        "Calculated_30": 0.75,
    } for index in range(620)]

    class Status:
        def text(self):
            return "Public guild data ready"

        def property(self, _name):
            return "ready"

    harness = SimpleNamespace(
        client=SimpleNamespace(slug="castle", authenticated=False),
        _guild_details={"Name": "Castle"},
        _datasets={
            "dkp": standings, "items": [], "raids": [],
            "active_auctions": []},
        guild_status=Status(), result_status=Status(),
        _profile=lambda _slug: {"slug": "castle", "name": "Castle"},
        _profiles=lambda: [{"slug": "castle", "name": "Castle"}],
    )
    snapshot = OpenDKP.mobile_snapshot(harness)
    assert snapshot["standings_total"] == 620
    assert len(snapshot["standings"]) == 620
    assert snapshot["standings"][-1]["name"] == "Member0619"
    assert snapshot["standings"][-1]["dkp"] == "619.0"


def test_history_dates_sort_chronologically_and_support_date_event_search():
    app = QApplication.instance() or QApplication([])
    class FilterHarness:
        MAX_TABLE_ROWS = 100
        result = ""

        def _set_result(self, text):
            self.result = text

    harness = FilterHarness()
    table = OpenDKP._table(
        harness, ("Date", "Raid / event"), "Test history",
        (0, Qt.SortOrder.DescendingOrder))
    OpenDKP._set_rows(harness, table, [
        (_date_cell("2025-12-31T23:30:00Z"), "Temple clear"),
        (_date_cell("2026-07-04T01:30:00Z"), "Sky raid"),
    ])
    assert table.item(0, 1).text() == "Sky raid"
    table.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert table.item(0, 1).text() == "Temple clear"
    OpenDKP._filter_table(harness, table, "2026-07-04 sky")
    visible_events = [
        table.item(row, 1).text() for row in range(table.rowCount())
        if not table.isRowHidden(row)]
    assert visible_events == ["Sky raid"]
    assert harness.result == "1 matching row"
    table.deleteLater()
    app.processEvents()


def test_numeric_sort_keys_do_not_sort_formatted_dkp_as_text():
    low = SortItem("950.0", sort_value=950)
    high = SortItem("1,200.0", sort_value=1200)
    assert low < high
    assert not high < low


def test_loot_item_cell_opens_the_matching_market_item_card():
    app = QApplication.instance() or QApplication([])
    opened = []
    prior = getattr(app, "_parsers_dict", None)
    app._parsers_dict = {
        "market": SimpleNamespace(
            _show_wiki_item_name=lambda name: opened.append(name) or object())}

    class TableHarness:
        MAX_TABLE_ROWS = 10

    harness = TableHarness()
    table = OpenDKP._table(
        harness, ("Date", "Item"), "Raid loot",
        (0, Qt.SortOrder.DescendingOrder))
    try:
        OpenDKP._set_rows(harness, table, [
            (_date_cell("2026-09-09T12:00:00Z"),
             OpenDKP._loot_item_cell("Crown of Rile")),
        ])
        assert OpenDKP._open_loot_item(harness, table, 0, 1) is True
        assert opened == ["Crown of Rile"]
        assert table.item(0, 1).toolTip() == "Open Crown of Rile item details"
    finally:
        if prior is None:
            delattr(app, "_parsers_dict")
        else:
            app._parsers_dict = prior
        table.deleteLater()
        app.processEvents()


def test_temporary_refresh_failure_keeps_permanent_saved_session(monkeypatch):
    class Timer:
        active = False
        def start(self):
            self.active = True
        def isActive(self):
            return self.active

    deleted = []
    states = []
    failures = []
    client = SimpleNamespace(
        slug="guild-one", client_details={"WebClientId": "client-id"},
        username="Raider", _refresh_token="saved-renewable-token",
        _refreshing=True, _id_token="id", _token_expires_at=1,
        _pending_auth=[object()], _session_retry_timer=Timer(),
        auth_changed=SimpleNamespace(
            emit=lambda *args: states.append(args)),
        failed=SimpleNamespace(emit=lambda *args: failures.append(args)))
    monkeypatch.setattr(
        "vantage.helpers.opendkp.delete_refresh_token",
        lambda slug: deleted.append(slug))

    OpenDkpClient._auth_failed(client, "refresh", "network offline", 0)

    assert client._refresh_token == "saved-renewable-token"
    assert deleted == []
    assert states[-1] == ("saved", "Raider")
    assert failures[-1] == ("session", "network offline", 0)
    assert client._session_retry_timer.isActive()


def test_rejected_refresh_removes_only_that_invalid_saved_session(monkeypatch):
    class Timer:
        def start(self):
            raise AssertionError("invalid credentials must not retry")
        def isActive(self):
            return False

    deleted = []
    states = []
    failures = []
    client = SimpleNamespace(
        slug="guild-one", client_details={"WebClientId": "client-id"},
        username="Raider", _refresh_token="expired-token",
        _refreshing=True, _id_token="id", _token_expires_at=1,
        _pending_auth=[object()], _session_retry_timer=Timer(),
        auth_changed=SimpleNamespace(
            emit=lambda *args: states.append(args)),
        failed=SimpleNamespace(emit=lambda *args: failures.append(args)))
    monkeypatch.setattr(
        "vantage.helpers.opendkp.delete_refresh_token",
        lambda slug: deleted.append(slug))

    OpenDkpClient._auth_failed(
        client, "refresh", "NotAuthorizedException", 400)

    assert client._refresh_token == ""
    assert deleted == ["guild-one"]
    assert states[-1] == ("expired", "Raider")
    assert not client._session_retry_timer.isActive()


def test_loading_saved_guild_restores_windows_credential(monkeypatch):
    states = []
    stopped = []
    timer_stops = []
    monkeypatch.setattr(
        "vantage.helpers.opendkp.read_refresh_token",
        lambda slug: ("Raider", "permanent-token") if slug == "guild-one"
        else ("", ""))
    client = SimpleNamespace(
        slug="", stop_live=lambda: stopped.append(True),
        _session_retry_timer=SimpleNamespace(
            stop=lambda: timer_stops.append(True)),
        client_details={"old": True}, _id_token="old", _token_expires_at=42,
        username="", _refresh_token="",
        auth_changed=SimpleNamespace(
            emit=lambda *args: states.append(args)))

    assert OpenDkpClient.set_guild(client, "guild-one.opendkp.com") == "guild-one"

    assert client.username == "Raider"
    assert client._refresh_token == "permanent-token"
    assert client._id_token == ""
    assert states == [("saved", "Raider")]
    assert stopped == [True]
    assert timer_stops == [True]
