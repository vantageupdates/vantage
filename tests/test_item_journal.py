from pathlib import Path

import pytest

from vantage.helpers.item_journal import (
    ItemJournal, character_from_filename, classify_location,
    parse_inventory_dump, reference_token, references_in)


SAMPLE = (
    "Location\tName\tID\tCount\tSlots\n"
    "Charm\tGuardian's Symbol\t100\t1\t0\n"
    "General1\tJourneyman's Boots\t2300\t1\t0\n"
    "General2-Slot1\tBone Chips\t13073\t20\t0\n"
    "Bank1\tFire Emerald\t10033\t3\t0\n"
    "SharedBank1\tPlatinum Token\t999\t2\t0\n")


def test_inventory_dump_parses_bank_bags_equipment_and_character(tmp_path):
    path = tmp_path / "Mindflux-Inventory.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    snapshot = parse_inventory_dump(path)

    assert snapshot["character"] == "Mindflux"
    assert [row["quantity"] for row in snapshot["items"]] == [1, 1, 20, 3, 2]
    assert [row["group"] for row in snapshot["items"]] == [
        "Equipped", "Inventory", "Bags", "Bank", "Shared Bank"]
    assert all(row["key"] for row in snapshot["items"])


def test_inventory_dump_accepts_utf16_and_rejects_unrelated_files(tmp_path):
    valid = tmp_path / "Velena_Inventory.txt"
    valid.write_text(SAMPLE, encoding="utf-16")
    assert parse_inventory_dump(valid)["character"] == "Velena"

    invalid = tmp_path / "notes.txt"
    invalid.write_text("hello\tworld\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Location and Name"):
        parse_inventory_dump(invalid)


def test_item_journal_replaces_per_character_keeps_history_and_undo(tmp_path):
    dump = tmp_path / "Pyco-Inventory.txt"
    dump.write_text(SAMPLE, encoding="utf-8")
    journal = ItemJournal(tmp_path / "items-notes.json")
    first = parse_inventory_dump(dump)
    journal.import_snapshot(first)
    key = journal.rows("Pyco")[2]["key"]

    assert journal.set_quantity("Pyco", key, 44)
    assert journal.rows("Pyco")[2]["quantity"] == 44
    assert journal.remove_item("Pyco", key)
    assert len(journal.rows("Pyco")) == 4
    assert journal.undo()
    assert len(journal.rows("Pyco")) == 5

    second = parse_inventory_dump(dump)
    second["items"] = second["items"][:2]
    journal.import_snapshot(second)
    assert len(journal.rows("Pyco")) == 2
    assert journal.restore_previous_import("Pyco")
    assert len(journal.rows("Pyco")) == 5

    reloaded = ItemJournal(tmp_path / "items-notes.json")
    assert len(reloaded.rows("Pyco")) == 5


def test_notes_and_portable_internal_reference_tokens_persist(tmp_path):
    journal = ItemJournal(tmp_path / "items-notes.json")
    boots = reference_token("item", "Journeyman's Boots")
    text = (
        f"Camp {boots} then do "
        f"{reference_token('quest', 'Journeyman Boots Quest')} in "
        f"{reference_token('zone', 'South Ro')}")
    note_id = journal.upsert_note("", "JBoots", text)

    reloaded = ItemJournal(tmp_path / "items-notes.json")
    assert reloaded.data["notes"][0]["id"] == note_id
    assert references_in(reloaded.data["notes"][0]["text"]) == (
        ("Item", "Journeyman's Boots"),
        ("Quest", "Journeyman Boots Quest"),
        ("Zone", "South Ro"))


def test_filename_and_location_helpers_are_defensive():
    assert character_from_filename(Path("Thora_inventory.txt")) == "Thora"
    assert classify_location("Bank42-Slot3") == "Bank"
    assert classify_location("General4-Slot2") == "Bags"
