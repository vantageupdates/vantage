"""Keep bank interactions within the P99/Titanium native window contract.

The installed Titanium default BankWnd defines eight bank slots (2000-2007)
and two shared-bank placeholders with no EQType. Bag contents belong to the
client-managed ContainerWindow, not permanent child-slot mirrors in BankWnd.
These static checks do not reproduce native repainting or item transfers.
"""

from copy import deepcopy
from itertools import combinations
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


def rect(node):
    return tuple(int(node.findtext(path)) for path in (
        "Location/X", "Location/Y", "Size/CX", "Size/CY"
    ))


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
    assert rect(slot) == (1 + 32 * (index % 4), 21 + 32 * (index // 4), 30, 30)
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
    assert rect(window) == (0, 25, 136, 160)
    for name, screen_id in [
        ("BW_SharedMoney0", "BW_SharedMoney0"),
        *[(f"BW_Money{i}", f"BW_Money{i}") for i in range(4)],
        ("BW_DoneButton", "DoneButton"),
        ("BW_ChangeButton", "ChangeButton"),
        ("BW_AltStorageButton", "AltStorageButton"),
    ]:
        assert item(xml, "Button", name).findtext("ScreenID") == screen_id


def test_compact_bank_has_balanced_grid_gaps_and_separate_content_groups():
    xml = bank_xml()
    title = item(xml, "Label", "BW_BankerName")
    assert rect(title) == (1, 1, 126, 16)
    assert title.findtext("ScreenID") == "BW_BankerName"
    assert title.findtext("Font") == "2"
    assert title.findtext("AlignCenter") == title.findtext("NoWrap") == "true"
    boxes = [rect(item(xml, "InvSlot", name)) for name in BANK_SLOTS]
    for row in range(2):
        row_boxes = boxes[4 * row:4 * row + 4]
        assert row_boxes[0][0] == 128 - (row_boxes[-1][0] + row_boxes[-1][2]) == 1
        assert all(b[0] - (a[0] + a[2]) == 2 for a, b in zip(row_boxes, row_boxes[1:]))
    assert boxes[4][1] - (boxes[0][1] + boxes[0][3]) == 2
    assert boxes[0][1] - (rect(title)[1] + rect(title)[3]) == 4
    assert rect(item(xml, "Button", "BW_Money0"))[1] - (boxes[4][1] + boxes[4][3]) == 4


@pytest.mark.parametrize("index,decal", tuple(enumerate(("dz_Plat", "dz_Gold", "dz_Silver", "A_CopperCoin"))))
def test_compact_coin_controls_keep_native_decals_and_five_digit_room(index, decal):
    coin = item(bank_xml(), "Button", f"BW_Money{index}")
    assert rect(coin) == (1 + 64 * (index % 2), 87 + 18 * (index // 2), 62, 16)
    assert coin.findtext("Font") == "2"
    assert coin.findtext("ButtonDrawTemplate/NormalDecal") == decal
    assert coin.findtext("ScreenID") == f"BW_Money{index}"
    assert coin.findtext("Style_Checkbox") == "false"
    assert coin.findtext("Style_Transparent") == "false"
    assert coin.findtext("Text") == "60000"
    assert (coin.findtext("DecalOffset/X"), coin.findtext("DecalOffset/Y")) == ("2", "3")
    assert (coin.findtext("DecalSize/CX"), coin.findtext("DecalSize/CY")) == ("7", "9")
    # Conservative 8px digit budget for five centered glyphs. This verifies
    # geometry, not the native font renderer; retain two pixels after the icon.
    text_left = (62 - 5 * 8) // 2
    assert text_left - (2 + 7) >= 2
    assert 16 >= 12 + 2 * 2


def test_compact_bank_footer_keeps_equal_native_actions_and_bottom_clearance():
    xml = bank_xml()
    change = item(xml, "Button", "BW_ChangeButton")
    done = item(xml, "Button", "BW_DoneButton")
    assert rect(change) == (1, 127, 61, 20)
    assert rect(done) == (66, 127, 61, 20)
    assert 66 - (1 + 61) == 4
    assert 127 - (105 + 16) == 6
    assert 152 - (127 + 20) == 5
    for button in (change, done):
        for state in ("Normal", "Pressed", "Flyby", "Disabled", "PressedFlyby"):
            assert button.findtext(f"ButtonDrawTemplate/{state}") == f"A_Btn{state}"
        assert button.findtext("Style_Checkbox") == "false"


def test_every_visible_bank_control_fits_native_client_area_without_overlap():
    xml = bank_xml()
    window = item(xml, "Screen", "BankWnd")
    templates = ET.parse(SKIN / "EQUI_Templates.xml").getroot()
    animations = ET.parse(SKIN / "EQUI_Animations.xml").getroot()
    border = item(templates, "WindowDrawTemplate", window.findtext("DrawTemplate")).find("Border")
    insets = {}
    for side, dimension in (("Left", "CX"), ("Right", "CX"), ("Top", "CY"), ("Bottom", "CY")):
        frame = item(animations, "Ui2DAnimation", border.findtext(side))
        insets[side] = int(frame.findtext(f"Frames/Size/{dimension}")) - int(border.findtext("Overlap" + side))
    assert insets == {"Left": 4, "Right": 4, "Top": 4, "Bottom": 4}
    client_width = int(window.findtext("Size/CX")) - insets["Left"] - insets["Right"]
    client_height = int(window.findtext("Size/CY")) - insets["Top"] - insets["Bottom"]
    assert (client_width, client_height) == (128, 152)
    visible = []
    for name in BANK_PIECES:
        node = next(node for node in xml if node.get("item") == name)
        width, height = int(node.findtext("Size/CX")), int(node.findtext("Size/CY"))
        if (width, height) == (1, 1):
            continue  # Unchanged native shared/alternate-storage placeholders.
        box = rect(node)
        x, y, width, height = box
        assert node.findtext("RelativePosition") == "true", name
        assert x >= 1 and y >= 1, name
        assert x + width <= client_width - 1 and y + height <= client_height - 1, name
        visible.append((name, box))
    assert len(visible) == 15  # Title, eight bags, four coin controls, two actions.
    for (a_name, (ax, ay, aw, ah)), (b_name, (bx, by, bw, bh)) in combinations(visible, 2):
        assert not (ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah), (a_name, b_name)


def test_contract_rejects_reintroduced_ghost_item_mirror():
    xml = bank_xml()
    mirror = deepcopy(item(xml, "InvSlot", "BW_BankSlot0"))
    mirror.set("item", "BW_BankSlot0_Slot1")
    mirror.remove(mirror.find("ScreenID"))
    mirror.find("EQType").text = "2031"
    xml.insert(2, mirror)
    with pytest.raises(AssertionError, match="Only native bank slots"):
        assert_native_bank_slots(xml)
