from PySide6.QtWidgets import QApplication, QFileDialog, QTabWidget, QWidget

from vantage.parsers.market import (
    AuctionComposer, AuctionEntry, GearItem, P99_CHAT_LIMIT,
    P99_ITEM_LINK_DELIMITER, compose_auction_lines,
    normalize_auction_price, p99_item_link, parse_p99_inventory)
from vantage.helpers.eq_clipboard import clipboard_payloads


def _app():
    return QApplication.instance() or QApplication([])


def test_titanium_item_link_uses_exact_p99_payload():
    link = p99_item_link(6040, "Manastone")

    assert link.startswith(P99_ITEM_LINK_DELIMITER)
    assert link.endswith(P99_ITEM_LINK_DELIMITER)
    assert link[1:46] == "001798" + ("0" * 39)
    assert link[46:-1] == "Manastone"


def test_item_link_sanitizes_chat_controls_and_price_input():
    link = p99_item_link(2, "10 Dose\x12 Adrenaline\nTap")

    assert link.count(P99_ITEM_LINK_DELIMITER) == 2
    assert link.endswith("10 Dose Adrenaline Tap\x12")
    assert normalize_auction_price("1,500 pp") == "1500p"
    assert normalize_auction_price("1.50K") == "1.5k"
    assert normalize_auction_price("500") == "500p"


def test_inventory_output_supplies_authoritative_item_ids_and_quantities():
    rows = parse_p99_inventory(
        "General6-Slot1 Edge of the Nightwalker 5649 1 5\n"
        "Bank3 Fungus Covered Scale Tunic 2735 2 5\n"
        "not an inventory row")

    assert [(row.name, row.id, row.quantity) for row in rows] == [
        ("Edge of the Nightwalker", 5649, 1),
        ("Fungus Covered Scale Tunic", 2735, 2),
    ]


def test_titanium_clipboard_payload_preserves_item_link_control_bytes():
    text = p99_item_link(13401, "Manastone")
    ansi, unicode_text = clipboard_payloads(text)

    assert ansi.startswith(b"\x12") and ansi.endswith(b"\x12\0")
    assert unicode_text.startswith(b"\x12\0")
    assert unicode_text.endswith(b"\x12\0\0\0")


def test_composer_packs_multiple_custom_messages_without_cutting_links():
    entries = [
        AuctionEntry(6000 + index, f"A Particularly Long Item Name {index}", "12k")
        for index in range(8)]

    lines = compose_auction_lines(
        entries, "WTS", "{type} {items: // } {suffix}",
        "{item} @ {price} {qty}", separator="ignored", suffix="PST")

    assert len(lines) > 1
    assert all(len(line) <= P99_CHAT_LIMIT for line in lines)
    assert sum(line.count(P99_ITEM_LINK_DELIMITER) for line in lines) == 16
    assert all(line.startswith("WTS ") and line.endswith(" PST") for line in lines)


def test_wtb_messages_are_plain_text_even_with_valid_item_ids():
    lines = compose_auction_lines(
        [AuctionEntry(6040, "Manastone", "80k", 2)], "WTB",
        "{type} {items} {suffix}", "{item} {price} {qty}", " | ", "send tell")

    assert lines == ["WTB Manastone 80k 2x send tell"]
    assert P99_ITEM_LINK_DELIMITER not in lines[0]


def test_auction_composer_requires_imported_id_then_copies_real_wts_link(tmp_path):
    app = _app()
    composer = AuctionComposer(lambda name: 80000 if name == "Manastone" else 0)
    composer.set_catalog([
        GearItem("Manastone", id=6040),
        GearItem("Fungi Covered Great Staff", id=10400),
    ])
    composer.item_search.setText("mana")

    assert composer.add_search_item()
    assert composer.items.rowCount() == 1
    assert not composer.copy_button.isEnabled()
    assert "Import /outputfile inventory" in composer.preview_status.text()

    inventory = tmp_path / "Mindflux-Inventory.txt"
    inventory.write_text("General1 Manastone 13401 1 5\n", encoding="utf-8")
    assert composer.import_inventory(str(inventory))
    assert "[Manastone]" in composer.preview.toPlainText()
    assert composer.copy_next()
    copied = app.clipboard().text()
    assert copied.startswith("WTS ")
    assert P99_ITEM_LINK_DELIMITER in copied
    assert copied[5:11] == "003459"
    assert "80000p" in copied

    composer.trade_type.setCurrentIndex(1)
    assert composer.copy_next()
    copied = app.clipboard().text()
    assert copied == "WTB Manastone 80000p PST"
    assert P99_ITEM_LINK_DELIMITER not in copied
    composer.close()


def test_inventory_picker_stays_outside_scaled_market_surface(
        tmp_path, monkeypatch):
    _app()
    market_window = QWidget()
    composer = AuctionComposer(parent=market_window)
    tabs = QTabWidget()
    tabs.addTab(composer, "WTS / WTB Builder")
    inventory = tmp_path / "Mindflux-Inventory.txt"
    inventory.write_text("General1 Manastone 13401 1 5\n", encoding="utf-8")
    captured = {}

    def choose_file(parent, caption, start, file_filter, **kwargs):
        captured.update(
            parent=parent, caption=caption, start=start,
            file_filter=file_filter, options=kwargs.get("options"))
        return str(inventory), "EverQuest inventory (*.txt)"

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(choose_file))

    assert composer.import_inventory()
    assert captured["parent"] is market_window
    assert captured["options"] & QFileDialog.Option.DontUseNativeDialog
    assert composer.parentWidget() is not market_window
    assert "authentic item IDs ready" in composer.inventory_status.text()
    tabs.close()
    market_window.close()


def test_wtb_is_simple_and_does_not_require_an_inventory_export():
    app = _app()
    composer = AuctionComposer()
    composer.set_catalog([GearItem("Manastone", id=6040)])
    composer.trade_type.setCurrentIndex(1)
    composer.item_search.setText("Manastone")

    assert composer.add_search_item()
    assert composer.copy_next()
    assert app.clipboard().text() == "WTB Manastone PST"
    composer.close()


def test_advanced_templates_are_hidden_until_requested():
    _app()
    composer = AuctionComposer()

    assert not composer.advanced_panel.isVisible()
    composer.advanced_toggle.setChecked(True)
    assert not composer.advanced_panel.isHidden()
    composer.close()


def test_default_wts_quantity_is_easy_to_read_before_the_item():
    line = compose_auction_lines([
        AuctionEntry(13401, "Manastone", "80k", 2)])[0]

    assert line.startswith("WTS 2x ")
    assert "Manastone" in line
    assert line.endswith(" 80k PST")


def test_paste_help_expands_inline_without_opening_a_dialog():
    _app()
    composer = AuctionComposer()

    assert composer.paste_help.isHidden()
    composer.paste_help_button.click()
    assert not composer.paste_help.isHidden()
    assert "Alt+O" in composer.paste_help.text()
    composer.paste_help_button.click()
    assert composer.paste_help.isHidden()
    composer.close()


def test_token_buttons_insert_into_the_correct_easy_template_field():
    _app()
    composer = AuctionComposer()
    composer.message_template.clear()
    composer.item_template.clear()

    composer._insert_token("{items}", composer.message_template)
    composer._insert_token("{price}", composer.item_template)

    assert composer.message_template.text() == "{items}"
    assert composer.item_template.text() == "{price}"
    composer.close()
