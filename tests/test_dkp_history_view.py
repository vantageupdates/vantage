from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from vantage.helpers.dkp_history_view import DkpHistoryView, finite_total
from vantage.helpers.opendkp import OpenDkpClient
from vantage.parsers.opendkp import OpenDKP


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        event = QWidget.event
        resizeEvent = QWidget.resizeEvent
        closeEvent = QWidget.closeEvent
        showEvent = QWidget.showEvent
        enterEvent = QWidget.enterEvent
        leaveEvent = QWidget.leaveEvent

        def __init__(self):
            QWidget.__init__(self)
            self.requests = []
            self.client = SimpleNamespace(slug="guild", fetch_character_details=lambda *args:
                                          self.requests.append(args), fetch_history_raid=lambda *args:
                                          self.requests.append(args))
            self._history_token = ""
            self._history_identity = None
            self._history_states = {}
            self._history_details = {}
            self._history_detail_status = ""
            self._datasets = {key: [] for key in ("dkp", "characters", "items", "character_dkp",
                "character_items", "character_raids", "character_adjustments")}
            self._profile = lambda: {"character_id": 1}
            self._save_profile = lambda **kwargs: None
            self.page = self._build_overview()

    widget = Harness()
    yield widget
    widget.page.deleteLater()
    widget.deleteLater()
    app.processEvents()


def select_character(panel):
    panel._datasets["dkp"] = [{"CharacterId": 1, "CharacterName": "Hero", "CurrentDKP": 32}]
    panel._populate_characters()
    return panel._history_token


def test_saved_character_loads_history_once_and_refresh_gets_new_generation(panel):
    token = select_character(panel)
    assert panel.requests == [(1, 90, token)]
    panel._populate_characters()
    assert len(panel.requests) == 1
    panel.history_view.refresh.click()
    assert len(panel.requests) == 2
    assert token != panel._history_token
    assert "loading" in panel.history_view.status.text()


def test_stale_history_success_failure_and_guild_change_rejected(panel):
    token = select_character(panel)
    panel._load_character_history(force=True)
    panel._response(f"character_adjustments|{token}|1", [{"Value": 99}])
    panel._failed(f"character_adjustments|{token}|1", "bad", 500)
    assert panel._datasets["character_adjustments"] == []
    assert panel._history_states["character_adjustments"] == "loading"
    token = panel._history_token
    panel.client.slug = "other"
    panel._response(f"character_adjustments|{token}|1", [{"Value": 99}])
    assert panel._datasets["character_adjustments"] == []


def test_loaded_empty_is_not_a_fake_record_and_failure_is_retryable(panel):
    token = select_character(panel)
    panel._response(f"character_adjustments|{token}|1", {"Models": []})
    assert panel._datasets["character_adjustments"] == []
    assert panel._history_states["character_adjustments"] == "ready"
    panel._failed(f"character_items|{token}|1", "timeout", 0)
    assert "Refresh history to retry" in panel.history_view.status.text()
    panel._response(f"character_raids|{token}|1", {"error": "bad"})
    assert "unexpected response" in panel.history_view.status.text()


def test_transactions_enrich_raid_and_detail_is_read_only(panel):
    token = select_character(panel)
    date = datetime.now(timezone.utc).isoformat()
    panel._response(f"character_raids|{token}|1", [
        {"RaidId": 7, "RaidName": "Dragon", "Timestamp": date, "PoolName": "Main",
         "Ticks": [{"TickId": 8, "Attended": 1}]}])
    panel._response(f"character_dkp|{token}|1", [
        {"CharacterId": 1, "CharacterName": "Hero", "SourceType": "Raid",
         "SourceId": 7, "TickId": 8, "Value": 5, "Date": date, "Source": "Kill bonus"}])
    assert panel.history_view.model.rowCount() == 1
    assert panel.history_view.model.rows[0]["amount"] == 5
    assert "Raids +5" in panel.history_view.summary.text()
    assert "Kill bonus" in panel.history_view.detail.toPlainText()
    panel.history_view.check_raid.click()
    assert panel.requests[-1] == ("7", token)


def test_period_changes_reload_with_correlated_bounded_request(panel):
    select_character(panel)
    panel.history_view.period.setCurrentIndex(2)
    assert panel.requests[-1][1] == 365
    calls = []
    client = SimpleNamespace(slug="guild", _request=lambda *args: calls.append(args))
    OpenDkpClient.fetch_character_details(client, 1, 99999, "token")
    assert calls[-1] == ("character_raids|token|1", "GET",
                          "/clients/guild/characters/1/raids?lookback=3650")


def test_history_search_covers_all_rows_sort_and_unknown_pool_are_safe(panel):
    view = panel.history_view
    date = datetime.now(timezone.utc).isoformat()
    rows = [{"source": f"Raid {i}", "kind": "raid", "timestamp": date, "amount": i,
             "pool": "Main", "pool_key": "id:1", "description": "", "raid_id": str(i),
             "ticks": [], "raw": {}} for i in range(800)]
    rows.append(dict(rows[0], kind="adjustment", source="Officer correction", amount=7,
                     pool="Unknown pool", pool_key=""))
    view.set_history(rows, "Hero", "Sources loaded.")
    assert view.model.rowCount() == 801
    assert "Pool not supplied" in view.summary.text()
    assert "not your current balance" in view.status.text()
    view.query.setText("Raid 799")
    assert view.model.rowCount() == 1
    view.query.clear()
    view.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    assert view.model.rows[0]["amount"] == 799
    view.kind.setCurrentIndex(2)
    assert view.model.rowCount() == 1
    assert view.model.rows[0]["source"] == "Officer correction"
    assert not view.check_raid.isEnabled()


def test_clearing_character_clears_history_details_and_summary(panel):
    select_character(panel)
    panel.character_selector.setCurrentIndex(0)
    assert panel.history_view.model.rowCount() == 0
    assert "Choose a character" in panel.history_view.status.text()
    assert not panel.history_view.refresh.isEnabled()


def test_history_preserves_selected_raid_across_refresh_and_sort(panel):
    view = panel.history_view
    date = datetime.now(timezone.utc).isoformat()
    rows = [{"source": name, "kind": "raid", "timestamp": date, "amount": amount,
             "pool": "Main", "pool_key": "id:1", "description": "", "raid_id": name,
             "ticks": [], "raw": {}} for name, amount in (("Dragon", 5), ("Statue", None))]
    view.set_history(rows, "Hero", "Loaded")
    view.table.selectRow(1)
    assert "Statue" in view.detail.toPlainText()
    rows[1]["amount"] = 10
    view.set_history(rows, "Hero", "Details checked")
    assert "Statue" in view.detail.toPlainText()
    view.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    assert "Statue" in view.detail.toPlainText()


def test_loot_link_uses_canonical_name_not_source(panel):
    view = panel.history_view
    row = {"source": "Temple - White Dragon Helm", "item_name": "White Dragon Helm",
           "kind": "loot", "timestamp": "", "amount": -10, "pool": "Main",
           "pool_key": "id:1", "description": "", "raid_id": "7", "ticks": [], "raw": {}}
    view.set_history([row], "Hero", "Loaded")
    opened = []
    view.item_requested.connect(opened.append)
    view.open_item.click()
    assert opened == ["White Dragon Helm"]


def test_summary_overflow_is_unknown_not_infinite():
    assert finite_total([1e308, 1e308]) is None


def test_guild_clear_does_not_erase_saved_character(panel):
    select_character(panel)
    saves = []
    panel._save_profile = lambda **kwargs: saves.append(kwargs)
    panel._invalidate_attendance = lambda: None
    panel._update_attendance_alt_summary = lambda: None
    dummy = SimpleNamespace(clear=lambda: None, setRowCount=lambda count: None,
                            setEnabled=lambda state: None)
    for name in ('attendance_character', 'standings_table', 'active_table', 'auctions_table',
                 'bid_table', 'loot_table', 'raids_table', 'adjustments_table', 'bid_character',
                 'site_button', 'refresh_button', 'sign_in_button'):
        setattr(panel, name, dummy)
    panel._clear_views()
    assert saves == []
    assert not panel._history_token
    assert not panel.history_view.character
    assert panel.history_balance.text() == 'Current DKP: —'


def test_character_without_standings_is_still_selectable(panel):
    panel._datasets['characters'] = [{'Id': 2, 'Name': 'NewCleric'}]
    select_character(panel)
    index = panel.character_selector.findData(2)
    assert index > 0
    panel.character_selector.setCurrentIndex(index)
    assert panel.requests[-1][0] == 2
    assert panel.history_view.character == 'NewCleric'
    assert panel.history_balance.text() == 'Current DKP: —'
