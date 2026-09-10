import base64
import copy
import json
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.opendkp import (
    OpenDkpClient, auction_bids, auction_id, auction_item_name, decode_token_username,
    normalize_guild_slug, rows_from_payload, watch_matches)
from vantage.parsers.opendkp import OpenDKP, SortItem, _date_cell


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
        }, {"slug": "bad guild"}], "active_sheet": sheet_id, "sheets": [{
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
