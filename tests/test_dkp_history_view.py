from datetime import datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from vantage.helpers.dkp_history_view import DkpHistoryView, finite_total
from vantage.helpers.opendkp import OpenDkpClient
from vantage.parsers.opendkp import OpenDKP
from vantage.parsers import opendkp as parser_module


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
    # This page has no parent and can be shown by focus tests. Close it before
    # deletion so it cannot receive mouse input intended for later map tests.
    widget.page.close()
    widget.page.deleteLater()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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
    client = SimpleNamespace(slug="guild", _request=lambda *args: calls.append(args),
                             _cancel_public_requests=lambda _matches: None)
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
    assert view.model.index(0, 1).data() == "White Dragon Helm"
    assert "Temple - White Dragon Helm" in view.model.index(0, 1).data(Qt.ItemDataRole.ToolTipRole)
    assert "Temple - White Dragon Helm" in view.detail.toPlainText()


@pytest.mark.parametrize("order", list(permutations(("items", "raids", "dkp"))))
@pytest.mark.parametrize("matched_by_id", [False, True])
def test_async_history_keeps_selected_purchase_and_full_provenance(panel, order, matched_by_id):
    token = select_character(panel)
    view = panel.history_view
    now = datetime.now(timezone.utc)
    older = (now - timedelta(days=2)).isoformat()
    newer = (now - timedelta(days=1)).isoformat()
    original_source = "Temple raid officer note https://example.invalid/raid - White Dragon Helm"
    payloads = {
        "items": [
            {"PurchaseId": 201, "ItemName": "White Dragon Helm", "RaidID": 7,
             "DkpValue": 20, "Timestamp": older},
            {"PurchaseId": 202, "ItemName": "White Dragon Helm", "RaidID": 8,
             "DkpValue": 40, "Timestamp": newer},
        ],
        "raids": [
            {"RaidId": raid_id, "RaidName": name, "Timestamp": stamp,
             "PoolName": "Main", "PoolId": 1, "Ticks": []}
            for raid_id, name, stamp in ((7, "Old raid", older), (8, "Temple raid", newer),
                                          (9, "Newest raid", now.isoformat()))
        ],
        # A partial transaction source must preserve the other loaded purchase.
        "dkp": [{"CharacterId": 1, "CharacterName": "Hero", "SourceType": "Item",
                 "SourceId": 8, "ItemName": "White Dragon Helm", "Value": -40,
                 "Date": newer,
                 "Source": original_source, "Notes": "Auction receipt"}],
    }
    if matched_by_id:
        payloads["dkp"][0].update(PurchaseId=202, Date=(now - timedelta(days=1, minutes=-15)).isoformat())
    selected = False
    for source in order:
        panel._response(f"character_{source}|{token}|1", payloads[source])
        target = next((i for i, row in enumerate(view.model.rows)
                       if row["kind"] == "loot" and row["amount"] == -40), None)
        if not selected and target is not None:
            view.table.selectRow(target)
            selected = True
        if selected:
            assert view._selected()["kind"] == "loot"
            assert view._selected()["amount"] == -40
            assert view.open_item.isEnabled()
            assert view.table.currentIndex().siblingAtColumn(1).data() == "White Dragon Helm"
    assert sum(row["kind"] == "loot" for row in view.model.rows) == 2
    assert original_source in view.detail.toPlainText()
    assert "Auction receipt" in view.detail.toPlainText()
    assert view._selected()["pool_key"] == "id:1"
    view.query.setText("officer note")
    assert view.model.rowCount() == 1
    assert view._selected()["amount"] == -40
    view.query.clear()
    view.kind.setCurrentIndex(view.kind.findData("loot"))
    view.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    assert view._selected()["amount"] == -40
    opened = []
    view.item_requested.connect(opened.append)
    view.open_item.click()
    assert opened == ["White Dragon Helm"]


def test_same_named_purchase_selection_uses_unique_identity_and_aliases(panel):
    view = panel.history_view
    purchase = {"source": "Helm", "item_name": "Helm", "kind": "loot",
                "timestamp": "", "amount": -10, "pool": "Unknown pool", "pool_key": "",
                "description": "", "raid_id": "7", "ticks": [], "raw": {}}
    first = dict(purchase, history_id="ledger:first")
    second = dict(purchase, history_id="ledger:second")
    view.set_history([first, second], "Hero", "Loading")
    view.table.selectRow(1)
    enriched = dict(second, history_id="purchase:second", history_aliases=["ledger:second"],
                    timestamp=datetime.now(timezone.utc).isoformat(), pool="Main", pool_key="id:1")
    view.set_history([enriched, first], "Hero", "Loaded")
    assert view._selected()["history_id"] == "purchase:second"
    view.query.setText("Helm")
    assert view._selected()["history_id"] == "purchase:second"
    view.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert view._selected()["history_id"] == "purchase:second"


def test_ambiguous_alias_never_selects_a_different_purchase(panel):
    view = panel.history_view
    purchase = {"source": "Helm", "item_name": "Helm", "kind": "loot", "timestamp": "",
                "amount": -10, "pool": "Main", "pool_key": "id:1", "description": "",
                "raid_id": "7", "ticks": [], "raw": {}, "history_aliases": ["shared"]}
    first, second = (dict(purchase, history_id=value) for value in ("first", "second"))
    view.set_history([first, second], "Hero", "Loaded")
    view.table.selectRow(0)
    view.set_history([second], "Hero", "Loaded")
    assert view._selected() is None
    assert not view.open_item.isEnabled()


def test_removing_same_named_cost_sibling_keeps_selected_purchase(panel):
    token = select_character(panel)
    view = panel.history_view
    item = {"ItemName": "Helm", "RaidID": 7, "Timestamp": datetime.now(timezone.utc).isoformat()}
    panel._response(f"character_items|{token}|1", [dict(item, DkpValue=5), dict(item, DkpValue=10)])
    view.table.selectRow(next(i for i, row in enumerate(view.model.rows) if row["amount"] == -10))
    selected_id = view._selected()["history_id"]
    panel._response(f"character_items|{token}|1", [dict(item, DkpValue=10)])
    assert view._selected()["history_id"] == selected_id
    assert view._selected()["amount"] == -10


def test_character_change_does_not_carry_purchase_selection(panel):
    view = panel.history_view
    raid = {"source": "Raid", "kind": "raid", "timestamp": "", "amount": 5,
            "pool": "Main", "pool_key": "id:1", "description": "", "raid_id": "7",
            "ticks": [], "raw": {}}
    loot = dict(raid, kind="loot", source="Helm", item_name="Helm", history_id="same-purchase")
    view.set_history([raid, loot], "Hero", "Loaded")
    view.table.selectRow(1)
    view.set_history([raid, loot], "Other", "Loaded")
    assert view._selected()["kind"] == "raid"
    assert not view.open_item.isEnabled()


def test_async_enrichment_retains_keyboard_focus_and_item_action(panel):
    view = panel.history_view
    loot = {"source": "Helm", "item_name": "Helm", "history_id": "purchase:1", "kind": "loot",
            "timestamp": "", "amount": -10, "pool": "Unknown pool", "pool_key": "",
            "description": "", "raid_id": "7", "ticks": [], "raw": {}}
    view.set_history([loot], "Hero", "Loading")
    panel.page.show()
    QApplication.processEvents()
    view.open_item.setFocus()
    assert view.open_item.hasFocus()
    enriched = dict(loot, source="Raid - Helm", pool="Main", pool_key="id:1",
                    timestamp=datetime.now(timezone.utc).isoformat())
    view.set_history([enriched], "Hero", "Loaded")
    assert view.open_item.hasFocus()
    opened = []
    view.item_requested.connect(opened.append)
    QTest.keyClick(view.open_item, Qt.Key.Key_Space)
    assert opened == ["Helm"]
    view.query.setFocus()
    view.set_history([enriched], "Hero", "Checked")
    assert view.query.hasFocus()
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_Down)
    assert view._selected()["history_id"] == "purchase:1"


def test_summary_overflow_is_unknown_not_infinite():
    assert finite_total([1e308, 1e308]) is None


def test_unchanged_history_is_not_rebuilt_for_other_overview_updates(panel, monkeypatch):
    builds = []
    original = parser_module.build_dkp_history

    def build(*args, **kwargs):
        builds.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(parser_module, "build_dkp_history", build)
    token = select_character(panel)
    initial = len(builds)
    resets = []
    panel.history_view.model.modelReset.connect(lambda: resets.append(True))
    for _ in range(4):
        panel._update_overview()
    assert len(builds) == initial and not resets
    panel._failed(f"character_items|{token}|1", "Timeout", 0)
    assert len(builds) == initial
    assert "unavailable" in panel.history_view.status.text()
    panel._response(f"character_items|{token}|1", [{"ItemName": "Helm", "DkpValue": 7}])
    assert len(builds) == initial + 1
    assert panel.history_view.model.rowCount() == 1


@pytest.mark.parametrize("replacement", ["newer", "character", "guild"])
def test_large_history_yields_to_ui_and_discards_obsolete_preparation(panel, monkeypatch, replacement):
    token = select_character(panel)
    original = parser_module.build_dkp_history
    entered, release = threading.Event(), threading.Event()
    builds = []
    gui_thread = threading.get_ident()

    def build(raids, adjustments, items, **kwargs):
        builds.append((len(items), threading.get_ident()))
        if len(items) == 1001:
            entered.set()
            assert release.wait(3)
        return original(raids, adjustments, items, **kwargs)

    monkeypatch.setattr(parser_module, "build_dkp_history", build)
    now = datetime.now(timezone.utc).isoformat()
    rows = [{"PurchaseId": index + 1, "ItemName": f"Item {index}",
             "Date": now, "DkpValue": 1} for index in range(1001)]
    try:
        panel._response(f"character_items|{token}|1", rows)
        assert entered.wait(1)
        assert "Preparing personal history" in panel.history_view.status.text()
        # A timer can run while reconciliation is deliberately held open.
        from PySide6.QtCore import QTimer
        pulse = []
        QTimer.singleShot(0, lambda: pulse.append(True))
        QApplication.processEvents()
        assert pulse == [True]
        if replacement == "newer":
            panel._response(f"character_items|{token}|1", [*rows, dict(rows[0], PurchaseId=1002)])
            panel._update_overview()
            assert len(builds) == 1
        else:
            if replacement == "character":
                panel.character_selector.setCurrentIndex(0)
            else:
                panel.client.slug = "other"
                panel._load_character_history(force=True)
            assert panel.history_view.model.rowCount() == 0
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while getattr(panel, "_history_worker_context", None) is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert panel._history_worker_context is None
    assert builds[0][1] != gui_thread
    if replacement == "newer":
        assert [size for size, _thread in builds] == [1001, 1002]
        assert all(thread != gui_thread for _size, thread in builds)
        assert panel.history_view.model.rowCount() == 1002
        assert "Preparing personal history" not in panel.history_view.status.text()
    else:
        assert panel.history_view.model.rowCount() == 0


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
