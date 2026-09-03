from PySide6.QtWidgets import QApplication, QSpinBox

from vantage.parsers.market import (
    AuctionComposer, AuctionEntry, AuctionQuantity, GearItem, P99_CHAT_LIMIT,
    P99_ITEM_LINK_DELIMITER, compose_auction_lines, normalize_auction_price,
    install_auction_hotbuttons, p99_item_link)
from vantage.helpers import config
from vantage.helpers.eq_clipboard import clipboard_payloads


def _app():
    return QApplication.instance() or QApplication([])


def test_titanium_item_link_uses_exact_p99_payload():
    link = p99_item_link(6040, "Manastone")

    assert link.startswith(P99_ITEM_LINK_DELIMITER)
    assert link.endswith(P99_ITEM_LINK_DELIMITER)
    assert link[1:46] == "001798" + ("0" * 39)
    assert link[46] == " "
    assert link[47:-1] == "Manastone"


def test_titanium_link_matches_the_documented_p99_blue_diamond_example():
    link = p99_item_link(22503, "Blue Diamond")

    assert link[1:7] == "0057E7"
    assert link[1:46] == "0057E7" + ("0" * 39)
    assert link[46:-1] == " Blue Diamond"


def test_item_link_sanitizes_chat_controls_and_price_input():
    link = p99_item_link(2, "10 Dose\x12 Adrenaline\nTap")

    assert link.count(P99_ITEM_LINK_DELIMITER) == 2
    assert link.endswith(" 10 Dose Adrenaline Tap\x12")
    assert normalize_auction_price("1,500 pp") == "1500p"
    assert normalize_auction_price("1.50K") == "1.5k"
    assert normalize_auction_price("500") == "500p"


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


def test_composer_copies_plain_wts_and_builds_linked_hotbutton_without_inventory():
    app = _app()
    composer = AuctionComposer(lambda name: 80000 if name == "Manastone" else 0)
    composer.set_catalog([
        GearItem("Manastone", id=6040, peqId=13401),
        GearItem("Fungi Covered Great Staff", id=10400, peqId=10400),
    ])
    composer.item_search.setText("mana")

    assert composer.add_search_item()
    assert composer.items.rowCount() == 1
    assert composer.copy_button.isEnabled()
    assert "ready for WTS Social" in composer.preview_status.text()
    assert "WTS Manastone 80000p PST" in composer.preview.toPlainText()
    assert P99_ITEM_LINK_DELIMITER in composer._linked_lines[0]
    assert composer.copy_next()
    copied = app.clipboard().text()
    assert copied == "WTS Manastone 80000p PST"
    assert P99_ITEM_LINK_DELIMITER not in copied

    composer.trade_type.setCurrentIndex(1)
    assert composer.copy_next()
    copied = app.clipboard().text()
    assert copied == "WTB Manastone 80000p PST"
    assert P99_ITEM_LINK_DELIMITER not in copied
    composer.close()


def test_linked_wts_installs_into_free_p99_social_with_backup(tmp_path):
    ini = tmp_path / "Mindflux_P1999Green.ini"
    original = (
        "[Socials]\r\n"
        "Page2Button1Name=KeepMe\r\n"
        "Page2Button1Color=0\r\n"
        "Page2Button1Line1=/loc\r\n"
        "\r\n[ChatManager]\r\nLocked=0\r\n")
    ini.write_bytes(original.encode("cp1252"))
    linked = compose_auction_lines([
        AuctionEntry(14701, "Black Sapphire Electrum Earring", "599p")])

    slots, backup = install_auction_hotbuttons(ini, linked)

    assert slots == ("Page2Button2",)
    assert backup.read_bytes() == original.encode("cp1252")
    installed = ini.read_bytes().decode("cp1252")
    assert "Page2Button1Name=KeepMe" in installed
    assert "Page2Button2Name=VantageWTS1" in installed
    assert "Page2Button2Line1=/auction WTS " in installed
    assert P99_ITEM_LINK_DELIMITER in installed
    assert "00396D" in installed
    assert "[ChatManager]" in installed


def test_plain_wtb_installs_separately_without_replacing_wts_buttons(tmp_path):
    ini = tmp_path / "Mindflux_P1999Green.ini"
    original = (
        "[Socials]\r\n"
        "Page2Button1Name=VantageWTS1\r\n"
        "Page2Button1Color=0\r\n"
        "Page2Button1Line1=/auction WTS Manastone 90k PST\r\n")
    ini.write_bytes(original.encode("cp1252"))

    slots, _backup = install_auction_hotbuttons(
        ini, ["WTB Manastone 80k PST"], "WTB")

    assert slots == ("Page2Button2",)
    installed = ini.read_text(encoding="cp1252")
    assert "Page2Button1Name=VantageWTS1" in installed
    assert "Page2Button1Line1=/auction WTS Manastone 90k PST" in installed
    assert "Page2Button2Name=VantageWTB1" in installed
    assert "Page2Button2Line1=/auction WTB Manastone 80k PST" in installed
    assert P99_ITEM_LINK_DELIMITER not in installed


def test_clickable_install_uses_inline_detected_character_without_dialog(tmp_path):
    _app()
    eq_root = tmp_path / "EverQuest"
    logs = eq_root / "Logs"
    logs.mkdir(parents=True)
    ini = eq_root / "Mindflux_P1999Green.ini"
    ini.write_text("[Socials]\n", encoding="cp1252")
    general = config.data.setdefault("general", {})
    previous_logs = general.get("eq_log_dir", "")
    try:
        config.data["general"]["eq_log_dir"] = str(logs)
        composer = AuctionComposer()
        composer.set_catalog([GearItem(
            "Manastone", id=6040, peqId=13401)])
        composer.item_search.setText("Manastone")
        assert composer.add_search_item()
        assert composer.character_ini.currentText() == "Mindflux · Green"
        assert not composer.hotbutton_button.isEnabled()

        composer.camped_out.setChecked(True)
        assert composer.hotbutton_button.isEnabled()
        assert composer.install_hotbuttons() is True
        assert "Installed" in composer.preview_status.text()
        assert "Page2Button1Line1=/auction WTS" in ini.read_text(
            encoding="cp1252")
        assert not composer.camped_out.isChecked()
        composer.close()
    finally:
        config.data["general"]["eq_log_dir"] = previous_logs


def test_composer_has_no_inventory_import_step():
    _app()
    composer = AuctionComposer()

    assert not hasattr(composer, "import_button")
    assert "no inventory file needed" in composer.link_status.text()
    assert composer.link_status.accessibleName() == "P99 item link source"
    composer.close()


def test_wtb_is_simple_and_does_not_require_an_inventory_export():
    app = _app()
    composer = AuctionComposer()
    composer.set_catalog([GearItem("Manastone", id=6040, peqId=13401)])
    composer.trade_type.setCurrentIndex(1)
    composer.item_search.setText("Manastone")

    assert composer.copy_button.accessibleName() == \
        "Copy WTB auction message"
    assert "WTB" in composer.copy_button.toolTip()
    assert not composer.hotbutton_button.isHidden()
    assert composer.hotbutton_button.text() == "Install WTB button…"
    assert composer.hotbutton_button.accessibleName() == \
        "Install WTB EQ Social button using plain text"
    assert composer.add_search_item()
    assert composer.copy_next()
    assert app.clipboard().text() == "WTB Manastone PST"
    assert composer.copy_button.accessibleName() == \
        "Copy WTB 1/1 auction message"
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


def test_quantity_uses_compact_themed_minus_and_plus_buttons():
    _app()
    composer = AuctionComposer()
    composer.set_catalog([GearItem("Manastone")])
    composer.item_search.setText("Manastone")
    assert composer.add_search_item()
    quantity = composer.items.cellWidget(0, 2)

    assert isinstance(quantity, AuctionQuantity)
    assert not quantity.findChildren(QSpinBox)
    quantity.plus.click()
    assert quantity.value() == 2
    assert composer.preview.toPlainText().startswith("1. WTS 2x ")
    assert "Manastone" in composer.preview.toPlainText()
    quantity.minus.click()
    assert quantity.value() == 1
    composer.close()


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
