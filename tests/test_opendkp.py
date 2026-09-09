import base64
import copy
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.opendkp import (
    auction_bids, auction_id, auction_item_name, decode_token_username,
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
