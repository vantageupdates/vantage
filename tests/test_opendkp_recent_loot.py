"""Personal loot ownership and complete, responsive guild loot presentation."""

from datetime import datetime, timezone
from time import perf_counter
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QTableView, QTabWidget, QWidget

from vantage.parsers.opendkp import OpenDKP


@pytest.fixture
def panel(monkeypatch):
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
            self.requests, self.statuses, self.opened = [], [], []
            self.client = SimpleNamespace(slug="castle", authenticated=False, loot_generation=1,
                fetch_character_details=lambda *args: self.requests.append(args))
            self._history_token, self._history_identity = "", None
            self._history_states, self._history_details, self._loot_loading = {}, {}, {}
            self._history_sources_ready = set()
            self._history_detail_status = ""
            self._datasets = {key: [] for key in ("dkp", "characters", "raids", "items", "active_auctions",
                "character_items", "character_raids", "character_dkp", "character_adjustments")}
            self._profile = lambda *_args: {"character_id": 163372, "slug": "castle", "name": "Castle"}
            self._profiles = lambda: []
            self._guild_details = {"Name": "Castle"}
            self._save_profile = lambda **_kwargs: None
            self._set_status = lambda *args, **_kwargs: self.statuses.append(args)
            self._set_result = lambda *args, **_kwargs: None
            self._guild_name = lambda: "Castle"
            self.guild_status, self.result_status = QLabel("Ready"), QLabel("")
            self.guild_status.setProperty("state", "ready")
            self.tabs = QTabWidget()
            self.tabs.setObjectName("OpenDkpTabs")
            self.page, self.loot_page = self._build_overview(), self._build_loot()
            self.tabs.addTab(self.page, "Overview")
            self.tabs.addTab(self.loot_page, "Loot")

    widget = Harness()
    monkeypatch.setattr(app, "_parsers_dict", {"market": SimpleNamespace(
        _show_wiki_item_name=lambda name: widget.opened.append(name) or True)}, raising=False)
    widget._datasets["dkp"] = [
        {"CharacterId": 163372, "CharacterName": "Mindflux", "CurrentDKP": 42},
        {"CharacterId": 2, "CharacterName": "Other", "CurrentDKP": 5},
    ]
    widget._populate_characters()
    yield widget
    widget.tabs.deleteLater()
    widget.deleteLater()
    app.processEvents()


def guild_item(transaction=4390959, **values):
    return {"TransactionId": transaction, "ItemName": "Head of the Serpent", "ItemID": 10622,
            "CharacterId": 163372, "CharacterName": "Mindflux", "DKP": 1,
            "RaidId": 103899, "Timestamp": "2026-10-20T12:25:00Z", "Raid": "Yelinak kill", **values}


def personal_item(**values):
    return {"ItemName": "Head of the Serpent", "ItemID": 10622, "GameItemId": 10622,
            "RaidID": 103899, "Date": "2026-10-20T12:25:00Z", "DkpValue": 1,
            "Raid": "Yelinak kill", **values}


def receive_personal(panel, items, token=None):
    panel._response(f"character_items|{token or panel._history_token}|163372", items)


def settle_model(panel):
    deadline = perf_counter() + 10
    longest = 0
    while panel._loot_model.preparing and perf_counter() < deadline:
        start = perf_counter()
        QApplication.processEvents()
        longest = max(longest, perf_counter() - start)
    assert not panel._loot_model.preparing
    return longest


def test_scoped_personal_loot_survives_ownerless_response_and_other_sources(panel):
    panel._response("items", {"Items": [guild_item(), guild_item(2, CharacterId=2, CharacterName="Other")]})
    assert panel.character_loot.rowCount() == 1
    panel.character_loot.setCurrentCell(0, 1)
    receive_personal(panel, [personal_item()])
    assert panel.character_loot.rowCount() == 1
    assert panel.character_loot.item(0, 0).text() != "—"
    assert panel.character_loot.item(0, 2).text() == "1.0"
    assert panel.character_loot.columnWidth(0) == 125
    assert panel.character_loot.columnWidth(1) == 210
    assert panel.character_loot.columnWidth(2) == 65
    assert panel.character_loot.currentItem().text() == "Head of the Serpent"
    for source in ("character_dkp", "character_adjustments", "character_raids"):
        panel._response(f"{source}|{panel._history_token}|163372", [])
        assert panel.character_loot.rowCount() == 1
    panel._response("items", {"Items": [guild_item(3, ItemName="New guild item")]})
    assert panel.character_loot.item(0, 1).text() == "Head of the Serpent"
    panel.tabs.show()
    panel.overview_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    panel.character_loot.setFocus()
    QTest.keyClick(panel.character_loot, Qt.Key.Key_Return)
    assert panel.opened == ["Head of the Serpent"]


def test_scoped_loot_rejects_explicit_conflicts_and_empty_is_authoritative(panel):
    panel._response("items", {"Items": [guild_item()]})
    receive_personal(panel, [personal_item(), personal_item(CharacterId=2, CharacterName="Mindflux"),
                             personal_item(CharacterId=163372, CharacterName="Other")])
    assert panel.character_loot.rowCount() == 1
    receive_personal(panel, [])
    assert panel.character_loot.rowCount() == 0
    panel._response("items", {"Items": [guild_item()]})
    assert panel.character_loot.rowCount() == 0


def test_recent_loot_refresh_keeps_data_and_rejects_old_character_or_guild(panel):
    receive_personal(panel, [personal_item()])
    panel.character_loot.setCurrentCell(0, 1)
    old = panel._history_token
    panel._load_character_history(force=True)
    assert panel.character_loot.rowCount() == 1
    assert "Refreshing" in panel.character_loot_status.text()
    receive_personal(panel, [personal_item(ItemName="Stale")], old)
    panel._failed(f"character_items|{old}|163372", "Old timeout", 0)
    assert panel.character_loot.item(0, 1).text() == "Head of the Serpent"
    panel._failed(f"character_items|{panel._history_token}|163372", "Timeout", 0)
    assert panel.character_loot.rowCount() == 1
    assert "unavailable" in panel.character_loot_status.text()
    assert panel.character_loot.currentItem().text() == "Head of the Serpent"
    panel._response("character_items:163372", [personal_item(ItemName="Legacy stale")])
    assert panel.character_loot.item(0, 1).text() == "Head of the Serpent"
    old = panel._history_token
    panel.character_selector.setCurrentIndex(panel.character_selector.findData(2))
    assert panel.character_loot.rowCount() == 0
    receive_personal(panel, [personal_item()], old)
    assert panel.character_loot.rowCount() == 0
    panel.character_selector.setCurrentIndex(panel.character_selector.findData(163372))
    old = panel._history_token
    panel.client.slug = "different-guild"
    receive_personal(panel, [personal_item()], old)
    assert panel.character_loot.rowCount() == 0


def test_guild_progress_and_failure_keep_previous_complete_dataset(panel):
    complete = {"Items": [guild_item()], "GuildSlug": "castle", "Generation": 1, "Complete": True}
    panel._response("items", complete)
    panel._loot_progress("castle", {"generation": 1, "loaded": 500, "total": 30362, "complete": False})
    assert "500 of 30,362" in panel.loot_summary.text()
    assert panel._loot_model.rowCount() == 1
    previous = panel.loot_summary.text()
    panel._loot_progress("other", {"generation": 1, "loaded": 99})
    panel._loot_progress("castle", {"generation": 0, "loaded": 99})
    assert panel.loot_summary.text() == previous
    panel._response("items", dict(complete, Items=[], Complete=False))
    panel._response("items", dict(complete, Items=[], Generation=0))
    panel._response("items", dict(complete, Items=[], GuildSlug="other"))
    panel._failed("items", "Page 2 unavailable", 500)
    assert panel._loot_model.rowCount() == 1
    assert "previous records retained" in panel.loot_summary.text()
    assert "Page 2" in panel.loot_summary.text()


def test_all_30362_guild_rows_search_sort_link_and_snapshot_remain_responsive(panel):
    items = [guild_item(index + 1, ItemName=f"Item {index:05d}", DKP=index,
                        CharacterId=2, CharacterName="Other") for index in range(30362)]
    panel.tabs.resize(1100, 650)
    panel.tabs.setCurrentWidget(panel.loot_page)
    panel.tabs.show()
    QApplication.processEvents()
    start = perf_counter()
    panel._response("items", {"Items": items, "GuildSlug": "castle", "Generation": 1, "Complete": True})
    receive_seconds = perf_counter() - start
    assert panel._loot_model.preparing
    assert "Preparing 30,362" in panel.loot_summary.text()
    longest_batch = settle_model(panel)
    assert isinstance(panel.loot_table, QTableView)
    assert panel._loot_model.rowCount() == 30362
    panel.loot_search.setFocus()
    start = perf_counter()
    panel.loot_search.setText("Item 30361")
    search_seconds = perf_counter() - start
    assert panel.loot_search.hasFocus()
    assert panel._loot_model.rowCount() == 1
    panel.loot_table.setCurrentIndex(panel._loot_model.index(0, 1))
    panel.loot_table.setFocus()
    QTest.keyClick(panel.loot_table, Qt.Key.Key_Return)
    assert panel.opened == ["Item 30361"]
    panel.loot_search.clear()
    start = perf_counter()
    panel.loot_table.sortByColumn(3, Qt.SortOrder.AscendingOrder)
    sort_seconds = perf_counter() - start
    assert panel.loot_table.currentIndex().siblingAtColumn(1).data() == "Item 30361"
    assert panel._loot_model.index(30361, 3).data() == "30,361.0"
    first = panel.mobile_snapshot()
    start = perf_counter()
    second = panel.mobile_snapshot()
    snapshot_seconds = perf_counter() - start
    assert len(first["loot"]) == first["loot_total"] == 30362
    assert second["loot"] is first["loot"]
    assert second["loot"] is panel._loot_model.snapshot
    print(f"30362 rows: receive={receive_seconds:.4f}s longest_batch={longest_batch:.4f}s "
          f"search={search_seconds:.4f}s sort={sort_seconds:.4f}s repeated_snapshot={snapshot_seconds:.6f}s")
    # Large construction is yielded; thresholds allow slower CI hosts while
    # catching an accidental full rebuild or synchronous cell allocation.
    assert receive_seconds < 0.5
    assert longest_batch < 0.5
    assert search_seconds < 0.5
    assert snapshot_seconds < 0.1


def test_new_dataset_cancels_pending_guild_preparation(panel):
    panel._datasets["items"] = [guild_item(index) for index in range(2000)]
    panel._populate_items()
    assert panel._loot_model.preparing
    panel._datasets["items"] = [guild_item(9, ItemName="Latest")]
    panel._populate_items()
    QApplication.processEvents()
    assert panel._loot_model.rowCount() == 1
    assert panel._loot_model.index(0, 1).data() == "Latest"
    assert panel.mobile_snapshot()["loot"][0]["item"] == "Latest"


@pytest.mark.parametrize("transaction", [None, 4390959])
@pytest.mark.parametrize("conflict", [
    {"CharacterId": 2}, {"CharacterName": "Other"}, {"PoolId": 2},
    {"PoolName": "Other pool"}, {"Pool": {"Id": 2}},
])
def test_selection_never_crosses_explicit_owner_or_pool_conflicts(panel, transaction, conflict):
    original = guild_item(transaction, PoolId=1, PoolName="Main")
    panel._response("items", {"Items": [original]})
    panel.loot_table.setCurrentIndex(panel._loot_model.index(0, 1))
    replacement = dict(original, **conflict)
    if "Pool" in conflict:
        replacement.pop("PoolId")
    panel._response("items", {"Items": [replacement]})
    assert not panel.loot_table.currentIndex().isValid()
    assert not panel.loot_table.selectionModel().selectedIndexes()


@pytest.mark.parametrize("transaction", [None, 4390959])
def test_selection_never_crosses_string_pool_conflict(panel, transaction):
    original = guild_item(transaction, Pool="Main")
    panel._response("items", {"Items": [original]})
    panel.loot_table.setCurrentIndex(panel._loot_model.index(0, 1))
    panel._response("items", {"Items": [dict(original, Pool="Other")]})
    assert not panel.loot_table.currentIndex().isValid()


def test_snapshot_completion_tracks_published_rows_through_prepare_refresh_and_failure(panel):
    complete = {"GuildSlug": "castle", "Generation": 1, "Complete": True}
    first = [guild_item(index) for index in range(2000)]
    panel._response("items", dict(complete, Items=first))
    pending = panel.mobile_snapshot()
    assert pending["loot"] == []
    assert not pending["loot_complete"]
    assert pending["loading"] and pending["loot_loading"]
    assert "Preparing 2,000" in pending["status"] == pending["loot_status"]
    settle_model(panel)
    published = panel.mobile_snapshot()
    assert len(published["loot"]) == 2000 and published["loot_complete"]
    assert not published["loot_loading"]
    panel._loot_progress("castle", {"generation": 1, "loaded": 500, "total": 3000})
    fetching = panel.mobile_snapshot()
    assert fetching["loot"] is published["loot"]
    assert fetching["loot_complete"] and fetching["loot_loading"]
    assert "500 of 3,000" in fetching["status"]
    second = [guild_item(index) for index in range(3000)]
    panel._response("items", dict(complete, Items=second))
    preparing = panel.mobile_snapshot()
    assert preparing["loot"] is published["loot"]
    assert preparing["loot_total"] == 2000 and preparing["loot_complete"]
    settle_model(panel)
    assert panel.mobile_snapshot()["loot_complete"]
    assert panel.mobile_snapshot()["loot_total"] == 3000
    panel._failed("items", "Page 2 unavailable", 500)
    failed = panel.mobile_snapshot()
    assert failed["loot_total"] == 3000 and failed["loot_complete"]
    assert not failed["loot_loading"]
    assert failed["loot_error"] == "Page 2 unavailable"
    assert "previous records retained" in failed["status"]


def test_failed_initial_load_cannot_export_complete_loot(panel):
    panel._failed("items", "Page 1 unavailable", 500)
    snapshot = panel.mobile_snapshot()
    assert not snapshot["loot_complete"] and not snapshot["loot_loading"]
    assert snapshot["loot"] == []
    assert snapshot["loot_error"] == "Page 1 unavailable"


def test_prepared_snapshot_retains_its_completion_if_next_refresh_starts(panel):
    panel._response("items", {"Items": [guild_item(index) for index in range(2000)],
                              "GuildSlug": "castle", "Generation": 1, "Complete": True})
    panel._loot_progress("castle", {"generation": 1, "loaded": 0, "complete": False})
    settle_model(panel)
    snapshot = panel.mobile_snapshot()
    assert snapshot["loot_complete"] and snapshot["loot_loading"]
    assert snapshot["loot_total"] == 2000
    # Model preparation is cancelled on actual guild switches by _clear_views;
    # use its cache/model reset here without the unrelated auction controls.
    panel.client.slug = "other-guild"
    panel._datasets["items"] = []
    panel._loot_loading = {}
    panel._populate_items()
    switched = panel.mobile_snapshot()
    assert switched["loot"] == [] and not switched["loot_complete"]


def test_loot_keyboard_arrows_enter_and_tab_exit_without_refresh_focus_steal(panel):
    items = [guild_item(None, DKP=5), guild_item(None, DKP=10)]
    panel._response("items", {"Items": items})
    panel.tabs.show()
    panel.tabs.setCurrentWidget(panel.loot_page)
    QApplication.processEvents()
    panel.loot_table.setCurrentIndex(panel._loot_model.index(0, 1))
    panel.loot_table.setFocus()
    QTest.keyClick(panel.loot_table, Qt.Key.Key_Down)
    assert panel.loot_table.currentIndex().row() == 1
    # Removing a same-named, differently-priced sibling must keep this exact
    # purchase selected and must not move focus out of the search field.
    panel.loot_search.setFocus()
    panel._response("items", {"Items": [dict(items[1])]})
    assert panel.loot_search.hasFocus()
    assert panel.loot_table.currentIndex().siblingAtColumn(3).data() == "10.0"
    panel.loot_table.setFocus()
    QTest.keyClick(panel.loot_table, Qt.Key.Key_Return)
    assert panel.opened == ["Head of the Serpent"]
    QTest.keyClick(panel.loot_table, Qt.Key.Key_Tab)
    assert not panel.loot_table.hasFocus()
    panel.loot_table.setFocus()
    QTest.keyClick(panel.loot_table, Qt.Key.Key_Backtab)
    assert panel.loot_search.hasFocus()
    receive_personal(panel, [personal_item()])
    panel.tabs.setCurrentWidget(panel.page)
    panel.overview_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    panel.character_loot.setCurrentCell(0, 1)
    panel.character_loot.setFocus()
    QTest.keyClick(panel.character_loot, Qt.Key.Key_Tab)
    assert panel.character_raids.hasFocus()
