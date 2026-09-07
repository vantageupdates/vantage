from itertools import combinations
from pathlib import Path
import xml.etree.ElementTree as ET


SKIN_DIR = Path(__file__).resolve().parents[1] / "ui" / "skin"


def _root(filename):
    return ET.parse(SKIN_DIR / filename).getroot()


def _item(root, tag, name):
    matches = root.findall(f"./{tag}[@item='{name}']")
    assert len(matches) == 1, f"expected one {tag} item={name}, found {len(matches)}"
    return matches[0]


def _pair(element, child, first, second):
    value = element.find(child)
    assert value is not None, f"{element.attrib.get('item')} is missing {child}"
    return int(value.findtext(first)), int(value.findtext(second))


def _rect(element):
    x, y = _pair(element, "Location", "X", "Y")
    width, height = _pair(element, "Size", "CX", "CY")
    return x, y, width, height


def _assert_in_bounds(rect, bounds):
    x, y, width, height = rect
    bound_width, bound_height = bounds
    assert x >= 0 and y >= 0
    assert width > 0 and height > 0
    assert x + width <= bound_width
    assert y + height <= bound_height


def _assert_nonoverlapping(rectangles):
    for (left_name, left), (right_name, right) in combinations(rectangles.items(), 2):
        lx, ly, lw, lh = left
        rx, ry, rw, rh = right
        overlaps = lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh
        assert not overlaps, f"{left_name} overlaps {right_name}"


def test_inventory_native_equipment_slots_are_bound_and_nonoverlapping():
    root = _root("EQUI_Inventory.xml")
    window = _item(root, "Screen", "InventoryWindow")
    window_size = _pair(window, "Size", "CX", "CY")
    assert window_size == (355, 355)
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]

    # Preserve the existing minimal InvSlot0 definition rather than inventing a
    # new binding, while fully specifying the equipped EQTypes 1-21.
    stub = _item(root, "InvSlot", "InvSlot0")
    assert stub.findtext("ScreenID") == "InvSlot0"
    assert stub.find("EQType") is None
    assert stub.find("Location") is None
    assert stub.find("Size") is None
    assert pieces.count("InvSlot0") == 1

    rectangles = {}
    for eq_type in range(1, 22):
        name = f"InvSlot{eq_type}"
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == eq_type
        rect = _rect(slot)
        assert rect[2:] == (40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        rectangles[name] = rect

    assert len(rectangles) == 21
    _assert_nonoverlapping(rectangles)
    assert "InvDummy" not in pieces


def test_container_keeps_native_geometry_and_active_slot_contract():
    root = _root("EQUI_Container.xml")
    window = _item(root, "Screen", "ContainerWindow")
    window_size = _pair(window, "Size", "CX", "CY")
    assert window_size == (100, 366)
    assert window.findtext("DrawTemplate") == "WDT_Rounded"
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]

    rectangles = {}
    for index in range(1, 11):
        name = f"ContainerSlot{index}"
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == 29 + index
        rect = _rect(slot)
        expected_location = (6 + 40 * ((index - 1) % 2), 84 + 40 * ((index - 1) // 2))
        assert rect[:2] == expected_location
        assert rect[2:] == (40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        rectangles[name] = rect

    _assert_nonoverlapping(rectangles)
    custom_stretchy_prefixes = ("Container_BG", "Container_Border")
    assert not any(name.startswith(custom_stretchy_prefixes) for name in pieces)
    defined_items = {element.attrib["item"] for element in root if "item" in element.attrib}
    assert not any(name.startswith(custom_stretchy_prefixes) for name in defined_items)


def test_inventory_hint_frames_fit_the_declared_atlas_without_remapping_others():
    root = _root("EQUI_Animations.xml")
    atlas_name = "VantageSlotHints.tga"
    atlas = _item(root, "TextureInfo", atlas_name)
    atlas_size = _pair(atlas, "Size", "CX", "CY")
    assert atlas_size == (256, 256)

    expected = {
        "A_InvAboutBody",
        "A_InvAmmo",
        "A_InvArms",
        "A_InvChest",
        "A_InvEar",
        "A_InvFace",
        "A_InvFeet",
        "A_InvHands",
        "A_InvHead",
        "A_InvLegs",
        "A_InvNeck",
        "A_InvPrimary",
        "A_InvRange",
        "A_InvRing",
        "A_InvSecondary",
        "A_InvShoulders",
        "A_InvWaist",
        "A_InvWrist",
    }
    mapped = {
        animation.attrib.get("item")
        for animation in root.findall("./Ui2DAnimation")
        if any((frame.findtext("Texture") or "").strip() == atlas_name
               for frame in animation.findall("Frames"))
    }
    assert mapped == expected

    rectangles = {}
    for name in expected:
        animation = _item(root, "Ui2DAnimation", name)
        frames = animation.findall("Frames")
        assert len(frames) == 1
        frame = frames[0]
        assert frame.findtext("Texture") == atlas_name
        rect = _rect(frame)
        assert rect[2:] == (40, 40)
        _assert_in_bounds(rect, atlas_size)
        rectangles[name] = rect
    _assert_nonoverlapping(rectangles)


def test_primary_hotbutton_grid_and_inventory_panel_stay_separate_and_in_bounds():
    root = _root("EQUI_HotButtonWnd.xml")
    window = _item(root, "Screen", "HotButtonWnd")
    window_size = _pair(window, "Size", "CX", "CY")
    assert window_size == (364, 304)
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]

    hotbuttons = {}
    for index in range(1, 11):
        name = f"HB_Button{index}"
        button = _item(root, "Button", name)
        expected_location = (1 + 41 * ((index - 1) % 2), 1 + 41 * ((index - 1) // 2))
        rect = _rect(button)
        assert button.findtext("ScreenID") == name
        assert rect == (*expected_location, 40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        hotbuttons[name] = rect
    _assert_nonoverlapping(hotbuttons)

    gear_types = {
        "Ammo": 21,
        "Arms": 7,
        "Back": 8,
        "Belt": 20,
        "Boots": 19,
        "Chest": 17,
        "Earring1": 1,
        "Earring2": 4,
        "Face": 3,
        "Hands": 12,
        "Head": 2,
        "Legs": 18,
        "Neck": 5,
        "Prim": 13,
        "Ranged": 11,
        "Ring1": 15,
        "Ring2": 16,
        "Sec": 14,
        "Shoulder": 6,
        "Wrist1": 9,
        "Wrist2": 10,
    }
    inventory = {}
    for name, eq_type in gear_types.items():
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == eq_type
        rect = _rect(slot)
        assert rect[2:] == (40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        inventory[name] = rect

    assert set(gear_types.values()) == set(range(1, 22))
    for index in range(1, 9):
        name = f"Newslot{index}"
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == 21 + index
        rect = _rect(slot)
        assert rect[2:] == (40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        inventory[name] = rect

    assert len(inventory) == 29
    _assert_nonoverlapping(inventory)
    _assert_nonoverlapping({**hotbuttons, **inventory})
