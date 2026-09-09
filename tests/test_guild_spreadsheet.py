import copy

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
import pytest

from vantage.helpers import config
from vantage.helpers.guild_spreadsheet import (
    normalize_google_sheet_url, parse_spreadsheet_csv)
from vantage.helpers.settings import SettingsSignals
import vantage.parsers.opendkp as opendkp_module
from vantage.parsers.opendkp import OpenDKP


def _app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(("source", "expected"), (
    (
        "https://docs.google.com/spreadsheets/d/" + "a" * 32 +
        "/edit?gid=910620751#gid=910620751",
        "https://docs.google.com/spreadsheets/d/" + "a" * 32 +
        "/export?format=csv&gid=910620751",
    ),
    (
        "https://docs.google.com/spreadsheets/d/e/" + "b" * 32 +
        "/pubhtml",
        "https://docs.google.com/spreadsheets/d/e/" + "b" * 32 +
        "/pub?output=csv",
    ),
))
def test_public_google_sheet_links_normalize_to_read_only_csv(source, expected):
    assert normalize_google_sheet_url(source) == expected


@pytest.mark.parametrize("source", (
    "http://docs.google.com/spreadsheets/d/unsafe/edit",
    "https://example.com/spreadsheets/d/unsafe/edit",
    "https://docs.google.com/document/d/not-a-sheet/edit",
))
def test_spreadsheet_url_rejects_unsafe_or_non_sheet_sources(source):
    with pytest.raises(ValueError):
        normalize_google_sheet_url(source)


def test_spreadsheet_parser_supports_headers_inventory_and_custom_matrices():
    table = parse_spreadsheet_csv(
        b"Item,Bounty Pay,Turn in Location\nBat Wing,5,Freeport\n")
    assert table.kind == "Table"
    assert table.headers == ("Item", "Bounty Pay", "Turn in Location")
    assert table.rows == (("Bat Wing", "5", "Freeport"),)

    inventory = parse_spreadsheet_csv(
        b"Cgvelious,Primary,Short Sword,9998,1,5,9/7/2026\n"
        b"Cgvelious,Head,Cloth Cap,1001,1,5,9/7/2026\n")
    assert inventory.kind == "Inventory"
    assert inventory.headers[:5] == (
        "Character", "Slot", "Item", "Item ID", "Quantity")

    matrix = parse_spreadsheet_csv(b",Alice,Bob\nManastone,1,0\n")
    assert matrix.kind == "Custom"
    assert matrix.headers == ("Column 1", "Column 2", "Column 3")


def test_guild_sheets_ui_is_named_and_supports_multiple_independent_panels(
        monkeypatch):
    class FakeClient(QObject):
        response = Signal(str, object)
        failed = Signal(str, str, int)
        busy_changed = Signal(bool, str)
        auth_changed = Signal(str, str)
        live_changed = Signal(str)
        auction_event = Signal(str, object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.slug = ""
            self.username = ""
            self._refresh_token = ""

        def close(self):
            pass

    monkeypatch.setattr(opendkp_module, "OpenDkpClient", FakeClient)
    monkeypatch.setattr(config, "save", lambda: None)
    app = _app()
    if not hasattr(app, "_signals"):
        app._signals = {}
    app._signals.setdefault("settings", SettingsSignals())
    original = copy.deepcopy(config.data)
    try:
        config.data.setdefault("opendkp", {})["sheets"] = []
        config.data["opendkp"]["active_sheet"] = ""
        window = OpenDKP()
        assert window.windowTitle() == "Guild DKP & More · Vantage"
        assert window._title.text() == "Guild DKP & More"
        assert window.tabs.tabText(window.tabs.count() - 1) == "Guild Sheets"
        assert window.sheet_save_button.text() == "Add sheet"
        assert "independent" in window.sheet_tabs.toolTip()
        window.close()
    finally:
        config.data = original
