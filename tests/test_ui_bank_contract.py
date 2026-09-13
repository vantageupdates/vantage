"""Keep bank interactions within the P99/Titanium native window contract.

The installed Titanium default BankWnd defines eight bank slots (2000-2007)
and two shared-bank placeholders with no EQType. Bag contents belong to the
client-managed ContainerWindow, not permanent child-slot mirrors in BankWnd.
These static checks do not reproduce native repainting or item transfers.
"""

from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SKIN = Path(__file__).resolve().parents[1] / "ui" / "skin"
BANK_SLOTS = [f"BW_BankSlot{i}" for i in range(8)]
SHARED_SLOTS = [f"BW_SharedBankSlot{i}" for i in range(2)]
NATIVE_SLOT_CONTRACT = [
    (name, name, str(2000 + index)) for index, name in enumerate(BANK_SLOTS)
] + [(name, name, None) for name in SHARED_SLOTS]
BANK_PIECES = (
    ["BW_BankerName"]
    + BANK_SLOTS
    + SHARED_SLOTS
    + ["BW_SharedMoney0"]
    + [f"BW_Money{i}" for i in range(4)]
    + ["BW_DoneButton", "BW_ChangeButton", "BW_AltStorageButton"]
)


def bank_xml():
    return ET.parse(SKIN / "EQUI_BankWnd.xml").getroot()


def item(xml, kind, name):
    node = xml.find(f"{kind}[@item='{name}']")
    assert node is not None, (kind, name)
    return node


def assert_native_bank_slots(xml):
    actual = [
        (slot.get("item"), slot.findtext("ScreenID"), slot.findtext("EQType"))
        for slot in xml.findall("InvSlot")
    ]
    assert actual == NATIVE_SLOT_CONTRACT, "Only native bank slots may be declared"


def test_bank_has_exact_native_slot_ids_screen_ids_and_eqtypes():
    assert_native_bank_slots(bank_xml())


def test_bank_has_no_permanent_inline_bag_content_slots_or_references():
    xml = bank_xml()
    assert not any("_Slot" in (node.get("item") or "") for node in xml)
    assert not any("_Slot" in (node.text or "") for node in xml.iter("Pieces"))
    assert not any(
        2031 <= int(node.text) <= 2110 for node in xml.iter("EQType")
    ), "Bag contents must be refreshed through the native ContainerWindow"


def test_bank_child_membership_preserves_native_controls_without_mirrors():
    xml = bank_xml()
    window = item(xml, "Screen", "BankWnd")
    assert [piece.text for piece in window.findall("Pieces")] == BANK_PIECES
    definitions = [node.get("item") for node in xml if node.get("item")]
    assert len(definitions) == len(set(definitions))
    assert all(name in definitions for name in BANK_PIECES)
    order = {name: index for index, name in enumerate(definitions)}
    assert all(order[name] < order["BankWnd"] for name in BANK_PIECES)


@pytest.mark.parametrize("index", range(8))
def test_native_bank_bag_slots_retain_vantage_hit_areas_and_styling(index):
    slot = item(bank_xml(), "InvSlot", BANK_SLOTS[index])
    geometry = tuple(int(slot.findtext(path)) for path in (
        "Location/X", "Location/Y", "Size/CX", "Size/CY"
    ))
    assert geometry == (-1, 34 + 29 * index, 30, 30)
    assert slot.findtext("Background") == f"A_dzBag{index + 1}"
    assert slot.findtext("ItemOffsetX") == slot.findtext("ItemOffsetY") == "0"
    assert slot.findtext("Style_Transparent") == "true"
    assert slot.findtext("Style_Border") == "true"
    assert slot.findtext("DrawTemplate") == "WDT_VantageSlotGold"


def test_bank_window_and_native_action_bindings_are_preserved():
    xml = bank_xml()
    window = item(xml, "Screen", "BankWnd")
    assert window.findtext("DrawTemplate") == "WDT_RoundedNoTitle"
    assert window.findtext("Style_Transparent") == "false"
    assert (window.findtext("Size/CX"), window.findtext("Size/CY")) == ("330", "274")
    for name, screen_id in [
        ("BW_SharedMoney0", "BW_SharedMoney0"),
        *[(f"BW_Money{i}", f"BW_Money{i}") for i in range(4)],
        ("BW_DoneButton", "DoneButton"),
        ("BW_ChangeButton", "ChangeButton"),
        ("BW_AltStorageButton", "AltStorageButton"),
    ]:
        assert item(xml, "Button", name).findtext("ScreenID") == screen_id


def test_contract_rejects_reintroduced_ghost_item_mirror():
    xml = bank_xml()
    mirror = deepcopy(item(xml, "InvSlot", "BW_BankSlot0"))
    mirror.set("item", "BW_BankSlot0_Slot1")
    mirror.remove(mirror.find("ScreenID"))
    mirror.find("EQType").text = "2031"
    xml.insert(2, mirror)
    with pytest.raises(AssertionError, match="Only native bank slots"):
        assert_native_bank_slots(xml)
