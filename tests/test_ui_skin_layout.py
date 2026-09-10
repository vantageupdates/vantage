from copy import deepcopy
from collections import Counter
from itertools import combinations
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import pytest


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


def _assert_uniform_equipment_columns(rectangles, y_offset=0):
    assert len(rectangles) == 21
    assert Counter(r[0] for r in rectangles.values()) == {86: 7, 115: 7, 144: 7}
    for x in (86, 115, 144):
        column = sorted(r for r in rectangles.values() if r[0] == x)
        assert column == [(x, 1 + y_offset + 29 * row, 29, 29) for row in range(7)]


def _signature(element):
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_signature(child) for child in element),
    )


def _only_frame(animation):
    frames = animation.findall("Frames")
    assert len(frames) == 1
    return frames[0]


def test_inventory_native_equipment_slots_are_bound_and_nonoverlapping():
    root = _root("EQUI_Inventory.xml")
    window = _item(root, "Screen", "InventoryWindow")
    window_size = _pair(window, "Size", "CX", "CY")
    assert window_size == (389, 355)
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
    assert window_size == (92, 350)
    assert window.findtext("DrawTemplate") == "WDT_Rounded"
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]

    rectangles = {}
    for index in range(1, 11):
        name = f"ContainerSlot{index}"
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == 29 + index
        rect = _rect(slot)
        expected_location = (2 + 40 * ((index - 1) % 2), 76 + 40 * ((index - 1) // 2))
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
    assert window_size == (215, 237)
    # Only add a 22px identity band; retain the exact 215px body grid.
    header_height = 22
    # Inventory sizing is independent: never enlarge Actions to match it.
    assert window.findtext("Style_VScroll") == "false"
    assert window.findtext("Style_HScroll") == "false"
    assert window.findtext("Style_Sizable") == "false"
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]

    hotbuttons = {}
    for index in range(1, 11):
        name = f"HB_Button{index}"
        button = _item(root, "Button", name)
        expected_location = (1 + 41 * ((index - 1) % 2), 1 + header_height + 41 * ((index - 1) // 2))
        rect = _rect(button)
        assert button.findtext("ScreenID") == name
        assert rect == (*expected_location, 40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        hotbuttons[name] = rect
        for tag, alias in (("InvSlot", f"HB_InvSlot{index}"), ("SpellGem", f"HB_SpellGem{index}")):
            layer = _item(root, tag, alias)
            assert layer.findtext("ScreenID") == alias
            assert _rect(layer) == rect
            assert pieces.count(alias) == 1
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
    gear_locations = {
        "Head": (115, 30),
        "Face": (115, 59),
        "Neck": (144, 59),
        "Shoulder": (86, 88),
        "Arms": (144, 88),
        "Hands": (115, 117),
        "Back": (86, 59),
        "Earring1": (86, 30),
        "Earring2": (144, 30),
        "Wrist1": (86, 117),
        "Wrist2": (144, 117),
        "Ring1": (86, 146),
        "Ring2": (144, 146),
        "Belt": (115, 146),
        "Prim": (86, 1),
        "Sec": (115, 1),
        "Ranged": (144, 175),
        "Ammo": (144, 1),
        "Chest": (115, 88),
        "Legs": (115, 175),
        "Boots": (86, 175),
    }
    inventory = {}
    for name, eq_type in gear_types.items():
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == eq_type
        rect = _rect(slot)
        gx, gy = gear_locations[name]
        assert rect == (gx, gy + header_height, 29, 29)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        inventory[name] = rect

    assert set(gear_types.values()) == set(range(1, 22))
    _assert_uniform_equipment_columns(inventory, y_offset=header_height)
    for index in range(1, 9):
        name = f"Newslot{index}"
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == 21 + index
        rect = _rect(slot)
        expected_location = (178, header_height + (1, 26, 52, 77, 103, 128, 154, 179)[index - 1])
        assert rect == (*expected_location, 25, 25)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        inventory[name] = rect

    assert len(inventory) == 29
    # Ranged fills the lower-right equipment cell, directly below Ring2.
    assert inventory['Ranged'][:2] == (inventory['Ring2'][0], inventory['Ring2'][1] + 29)
    # Eight proportional bags form their own column with no equipment above it.
    assert inventory['Newslot1'][1] == inventory['Ammo'][1]
    assert inventory['Newslot8'][1] + 25 == inventory['Ranged'][1] + 29
    assert inventory['Ammo'][0] + 29 + 5 == inventory['Newslot1'][0]
    _assert_nonoverlapping(inventory)
    _assert_nonoverlapping({**hotbuttons, **inventory})


def test_uniform_equipment_guard_rejects_the_previous_detached_ammo_slot():
    equipment = {str(7 * col + row): (86 + 29 * col, 1 + 29 * row, 29, 29)
                 for col in range(3) for row in range(7)}
    _assert_uniform_equipment_columns(equipment)
    equipment['14'] = (176, 0, 31, 31)
    with pytest.raises(AssertionError):
        _assert_uniform_equipment_columns(equipment)


def test_hotbar_gold_version_tab_is_bound_to_release_and_clear_of_the_grid():
    root = _root("EQUI_HotButtonWnd.xml")
    window = _item(root, "Screen", "HotButtonWnd")
    label = _item(root, "Label", "HB_VantageVersionLabel")
    tab = _item(root, "StaticAnimation", "HB_VantageBrandTab")
    animation = _item(root, "Ui2DAnimation", "A_VantageBrandTab")
    release = json.loads((SKIN_DIR.parent / "release.json").read_text())
    assert label.findtext("Text") == f"v{release['version']}"
    assert label.findtext("Font") == "2"
    assert label.findtext("NoWrap") == label.findtext("AlignCenter") == "true"
    assert label.find("EQType") is None  # Never let live game data overwrite it.
    assert _rect(label) == (129, 5, 56, 14)
    assert tuple(int(label.findtext(f"TextColor/{c}")) for c in "RGB") == (218, 195, 147)
    assert _rect(tab) == (1, 1, 202, 20)
    assert tab.findtext("Animation") == animation.attrib["item"]
    assert tab.findtext("AutoDraw") == "true"
    assert animation.findtext("Cycle") == "false"
    assert window.findtext("Style_Transparent") == "false"
    assert window.findtext("DrawTemplate") == "WDT_RoundedNoTitle"
    assert _rect(window)[2:] == (215, 237)
    assert list(root).index(animation) < list(root).index(tab) < list(root).index(label) < list(root).index(window)
    pieces = [p.text.strip() for p in window.findall("Pieces")]
    assert pieces[:2] == ["HB_VantageBrandTab", "HB_VantageVersionLabel"]
    assert pieces.count("HB_VantageBrandTab") == pieces.count("HB_VantageVersionLabel") == 1
    for name in pieces[2:]:
        node = next(n for n in root if n.attrib.get("item") == name)
        x, y, width, height = _rect(node)
        if x < 0:  # Existing hidden native paging controls remain hidden.
            assert (x, y, width, height) == (-1, -1, 1, 1)
        else:
            assert y >= 23
            _assert_in_bounds((x, y, width, height), (207, 229))

    frame = _only_frame(animation)
    assert tab.findtext("TooltipReference") == "Vantage UI"
    assert frame.findtext("Texture") == "VantageBrandHeader.tga"
    assert _rect(frame) == (2, 2, 202, 20)
    _assert_in_bounds(_rect(frame), (256, 32))
    texture = _item(root, "TextureInfo", "VantageBrandHeader.tga")
    assert _pair(texture, "Size", "CX", "CY") == (256, 32)
    atlas = (SKIN_DIR / "VantageBrandHeader.tga").read_bytes()
    assert atlas[12:18] == bytes((0, 1, 32, 0, 32, 40))
    def alpha(x, y):
        return atlas[18 + (y * 256 + x) * 4 + 3]
    assert alpha(103, 12) == 255
    assert all(alpha(x, y) <= 16 for x in (2, 203) for y in (2, 21))
    assert all(alpha(x, y) == 0 for x in range(1, 205) for y in (1, 22))
    assert all(alpha(x, y) == 0 for x in (1, 204) for y in range(1, 23))


def test_all_drawable_inventory_slots_use_the_dedicated_gold_border():
    drawable = []
    placeholders = []
    for path in sorted(SKIN_DIR.glob("*.xml")):
        root = ET.parse(path).getroot()
        for slot in root.findall("./InvSlot"):
            size = slot.find("Size")
            if size is None:
                placeholders.append((path.name, slot.attrib["item"], None))
                continue
            dimensions = _pair(slot, "Size", "CX", "CY")
            if min(dimensions) < 6:
                placeholders.append((path.name, slot.attrib["item"], dimensions))
                continue
            drawable.append((path.name, slot))

    assert len(drawable) == 435
    assert set(placeholders) == {
        ("EQUI_BankWnd.xml", "BW_SharedBankSlot0", (1, 1)),
        ("EQUI_BankWnd.xml", "BW_SharedBankSlot1", (1, 1)),
        ("EQUI_Inventory.xml", "InvSlot0", None),
        ("EQUI_Inventoryd.xml", "InvSlot0", (1, 1)),
    }
    for filename, slot in drawable:
        assert slot.findtext("Style_Transparent") == "true", (filename, slot.attrib["item"])
        assert slot.findtext("Style_Border") == "true", (filename, slot.attrib["item"])
        assert slot.findtext("DrawTemplate") == "WDT_VantageSlotGold", (
            filename,
            slot.attrib["item"],
        )
    for filename, item, _ in placeholders:
        slot = _item(_root(filename), "InvSlot", item)
        assert slot.findtext("DrawTemplate") != "WDT_VantageSlotGold"


def test_gold_slot_edge_and_health_tick_resources_are_complete_and_in_bounds():
    root = _root("EQUI_Animations.xml")
    texture_name = "VantageControlEdges.tga"
    texture = _item(root, "TextureInfo", texture_name)
    texture_size = _pair(texture, "Size", "CX", "CY")
    assert texture_size == (512, 128)
    assert (SKIN_DIR / texture_name).is_file()

    roles = (
        "TopLeft", "Top", "TopRight", "RightTop", "Right", "RightBottom",
        "BottomRight", "Bottom", "BottomLeft", "LeftTop", "Left", "LeftBottom",
    )
    expected_sizes = {
        **{
            f"A_VantageSlotGold{role}": (
                (6, 1)
                if role in {"TopLeft", "TopRight", "BottomLeft", "BottomRight"}
                else (1, 5)
                if role in {"LeftTop", "LeftBottom", "RightTop", "RightBottom"}
                else (1, 1)
            )
            for role in roles
        },
        "A_VantageHP240Lines": (240, 20),
        "A_VantageHP100Lines": (100, 20),
        "A_VantageSpellGemOutline": (120, 28),
    }
    mapped = {}
    for animation in root.findall("./Ui2DAnimation"):
        frames = animation.findall("Frames")
        if len(frames) == 1 and (frames[0].findtext("Texture") or "").strip() == texture_name:
            mapped[animation.attrib["item"]] = animation
    assert set(mapped) == set(expected_sizes)
    assert len(mapped) == 15

    for name, expected_size in expected_sizes.items():
        animation = mapped[name]
        assert animation.findtext("Cycle") == "false"
        frame = _only_frame(animation)
        assert _pair(frame, "Size", "CX", "CY") == expected_size
        _assert_in_bounds(_rect(frame), texture_size)

    templates = _root("EQUI_Templates.xml")
    border = _item(templates, "WindowDrawTemplate", "WDT_VantageSlotGold").find("Border")
    assert border is not None
    for role in roles:
        assert border.findtext(role) == f"A_VantageSlotGold{role}"


def test_health_layers_keep_native_bindings_without_floating_tick_overlays():
    palette = {
        "0": (239, 68, 68),
        "1": (249, 115, 22),
        "2": (245, 158, 11),
        "3": (240, 220, 0),
        "4": (0, 240, 0),
    }
    configurations = [
        ("EQUI_PlayerWindow.xml", "Player", "PlayerWindow", 1, 240),
        *(("EQUI_GroupWindow.xml", f"Party{index}", "GroupWindow", 10 + index, 100)
          for index in range(1, 6)),
        ("EQUI_PetInfoWindow.xml", "Pet", "PetInfoWindow", 16, 100),
        ("EQUI_TargetWindow.xml", "VantageTarget", "TargetWindow", 6, 240),
    ]
    suffixes = ["0", *(f"{stage}{side}" for stage in range(1, 5) for side in ("A", "B"))]

    for filename, prefix, screen_name, eq_type, width in configurations:
        root = _root(filename)
        screen = _item(root, "Screen", screen_name)
        pieces = [piece.text.strip() for piece in screen.findall("Pieces")]
        for suffix in suffixes:
            gauge = _item(root, "Gauge", f"{prefix}_HP_{suffix}")
            assert int(gauge.findtext("EQType")) == eq_type
            assert tuple(int(gauge.findtext(f"FillTint/{channel}")) for channel in "RGB") == palette[suffix[0]]
            assert pieces.count(gauge.attrib["item"]) == (0 if suffix.endswith("A") else 1)
        ticks = _item(root, "StaticAnimation", f"{prefix}_HP_VantageTicks")
        base = _item(root, "Gauge", f"{prefix}_HP_0")
        assert _rect(ticks) == _rect(base)
        assert _pair(ticks, "Size", "CX", "CY") == (width, 20)
        assert ticks.findtext("Animation") == f"A_VantageHP{width}Lines"
        assert ticks.findtext("AutoDraw") == "true"
        assert pieces.count(ticks.attrib["item"]) == 0

    auxiliary_pet = _item(_root("EQUI_PlayerWindow.xml"), "Gauge", "Pet_HP")
    assert int(auxiliary_pet.findtext("EQType")) == 16
    assert tuple(int(auxiliary_pet.findtext(f"FillTint/{channel}")) for channel in "RGB") == palette["4"]


def _normalize_target_clone(element):
    result = deepcopy(element)
    if result.get("item"):
        result.set(
            "item",
            result.get("item").replace("VantageTarget_HP_", "Player_HP_")
            .replace("VantageTarget_GaugeFill", "PW_GaugeFill"),
        )
    for node in result.iter():
        if node.tag == "EQType":
            node.text = "1"
        elif node.text:
            node.text = node.text.replace("VantageTarget_HP_", "Player_HP_").replace(
                "VantageTarget_GaugeFill", "PW_GaugeFill"
            )
    return result


def test_target_threshold_layers_are_native_player_clones_with_target_binding():
    player = _root("EQUI_PlayerWindow.xml")
    target = _root("EQUI_TargetWindow.xml")

    for stage in range(1, 5):
        player_animation = _item(player, "Ui2DAnimation", f"PW_GaugeFill{stage}")
        target_animation = _item(target, "Ui2DAnimation", f"VantageTarget_GaugeFill{stage}")
        assert _signature(player_animation) == _signature(_normalize_target_clone(target_animation))

    for suffix in ["0", *(f"{stage}{side}" for stage in range(1, 5) for side in ("A", "B"))]:
        player_gauge = _item(player, "Gauge", f"Player_HP_{suffix}")
        target_gauge = _item(target, "Gauge", f"VantageTarget_HP_{suffix}")
        assert int(target_gauge.findtext("EQType")) == 6
        assert _signature(player_gauge) == _signature(_normalize_target_clone(target_gauge))
        if suffix.endswith("A"):
            player_clip = _item(player, "Screen", f"Player_HP_{suffix}_X")
            target_clip = _item(target, "Screen", f"VantageTarget_HP_{suffix}_X")
            assert _signature(player_clip) == _signature(_normalize_target_clone(target_clip))

    target_body = _item(target, "Gauge", "Target_HP2")
    assert int(target_body.findtext("EQType")) == 6
    assert _rect(target_body) == (0, 21, 280, 33)
    assert int(target_body.findtext("GaugeOffsetX")) == 20
    assert int(target_body.findtext("GaugeOffsetY")) == 0
    draw = target_body.find("GaugeDrawTemplate")
    assert draw is not None and draw.findtext("Background") == "A_dzLongBackground"
    assert all(draw.find(tag) is None for tag in ("Fill", "Lines", "LinesFill"))

    pieces = [piece.text.strip() for piece in _item(target, "Screen", "TargetWindow").findall("Pieces")]
    expected = ["VantageTarget_HP_0"]
    for stage in range(1, 5):
        expected.extend((f"VantageTarget_HP_{stage}A_X", f"VantageTarget_HP_{stage}B"))
    assert all(pieces.count(name) == 1 for name in expected)
    assert [name for name in pieces if name in expected] == expected


def test_actions_alias_rows_have_real_gaps_and_clipping_safe_page_height():
    root = _root("EQUI_ActionsWindow.xml")
    window = _item(root, "Screen", "ActionsWindow")
    assert _pair(window, "Size", "CX", "CY") == (144, 182)
    assert window.findtext("Style_Sizable") == "false"
    page = _item(root, "Page", "ActionsMainPage")
    pieces = [piece.text.strip() for piece in page.findall("Pieces")]
    states = {
        "Normal": "A_VantageActionsNormal",
        "Pressed": "A_VantageActionsPressed",
        "Flyby": "A_VantageActionsFlyby",
        "Disabled": "A_VantageActionsDisabled",
        "PressedFlyby": "A_VantageActionsPressedFlyby",
    }
    rows = (
        (87, ("AMP_CampButton",)),
        (109, ("AMP_SitButton", "AMP_StandButton")),
        (131, ("AMP_RunButton", "AMP_WalkButton")),
    )
    representatives = {}
    for y, aliases in rows:
        alias_rects = []
        for name in aliases:
            button = _item(root, "Button", name)
            assert button.findtext("ScreenID") == name
            assert pieces.count(name) == 1
            assert _rect(button) == (4, y, 128, 18)
            # Preserve the row centers and native font/text instead of
            # compressing labels along with the smaller button surfaces.
            assert button.find("Font") is None
            assert button.findtext("Style_Transparent") == "true"
            assert button.findtext("Style_Border") == "false"
            assert button.findtext("Text") == name.removeprefix("AMP_").removesuffix("Button")
            draw = button.find("ButtonDrawTemplate")
            assert draw is not None
            assert {state: draw.findtext(state) for state in states} == states
            alias_rects.append(_rect(button))
        assert len(set(alias_rects)) == 1
        representatives[str(y)] = alias_rects[0]
    _assert_nonoverlapping(representatives)
    assert 109 - (87 + 18) == 4
    assert 131 - (109 + 18) == 4

    animations = _root("EQUI_Animations.xml")
    templates = _root("EQUI_Templates.xml")
    rounded = _item(templates, "WindowDrawTemplate", "WDT_RoundedNoTitle")
    top = _item(animations, "Ui2DAnimation", rounded.findtext("Border/Top"))
    bottom = _item(animations, "Ui2DAnimation", rounded.findtext("Border/Bottom"))
    top_height = _pair(_only_frame(top), "Size", "CX", "CY")[1]
    bottom_height = _pair(_only_frame(bottom), "Size", "CX", "CY")[1]
    assert (top_height, bottom_height) == (4, 4)

    tabs = _item(root, "TabBox", "ACTW_ActionsSubwindows")
    assert tabs.findtext("AutoStretch") == "true"
    tab_heights = set()
    for page_name in (piece.text.strip() for piece in tabs.findall("Pages")):
        tab_page = _item(root, "Page", page_name)
        for field in ("TabIcon", "TabIconActive"):
            icon = _item(animations, "Ui2DAnimation", tab_page.findtext(field))
            tab_heights.add(_pair(_only_frame(icon), "Size", "CX", "CY")[1])
    assert tab_heights == {18}
    conservative_page_height = 182 - top_height - bottom_height - 18
    assert conservative_page_height - (131 + 18) == 7


@pytest.mark.parametrize("state,index", [
    ("Normal", 0), ("Flyby", 1), ("Pressed", 2),
    ("PressedFlyby", 3), ("Disabled", 4),
])
def test_actions_button_art_matches_hitbox_and_has_clear_rounded_gutters(state, index):
    root = _root("EQUI_ActionsWindow.xml")
    animation_name = f"A_VantageActions{state}"
    animation = _item(root, "Ui2DAnimation", animation_name)
    frame = _only_frame(animation)
    assert frame.findtext("Texture") == "VantageControlEdges.tga"
    assert _rect(frame) == (352, 4 + index * 24, 128, 18)
    assert _pair(frame, "Hotspot", "X", "Y") == (0, 0)
    assert animation.findtext("Cycle") == "true"
    assert frame.findtext("Duration") == "1000"
    expected_users = {
        "AMP_CampButton", "AMP_SitButton", "AMP_StandButton",
        "AMP_RunButton", "AMP_WalkButton",
    }
    users = set()
    for node in root.findall("Button"):
        if node.findtext(f"ButtonDrawTemplate/{state}") == animation_name:
            users.add(node.attrib["item"])
            assert list(root).index(animation) < list(root).index(node)
            assert _pair(node, "Size", "CX", "CY") == (128, 18)
    assert users == expected_users

    # Other windows keep their shared, unscaled 120x24 button states.
    shared = _root("EQUI_Animations.xml")
    original = _item(shared, "Ui2DAnimation", f"A_Btn{state}")
    original_frame = _only_frame(original)
    assert original_frame.findtext("Texture") == "window_pieces03_modern.png"
    assert _rect(original_frame) == (100, index * 24, 120, 24)

    # Inspect the shipping texture, not just the XML rectangles. These cells
    # are flat, top-origin uncompressed 32-bit BGRA with transparent gutters.
    atlas = (SKIN_DIR / "VantageControlEdges.tga").read_bytes()
    assert atlas[:3] == bytes((0, 0, 2))
    assert atlas[12:18] == bytes((0, 2, 128, 0, 32, 40))
    assert len(atlas) == 18 + 512 * 128 * 4

    def alpha(x, y):
        return atlas[18 + (y * 512 + x) * 4 + 3]

    x, y, width, height = _rect(frame)
    _assert_in_bounds((x, y, width, height), (512, 128))
    assert alpha(x + width // 2, y + height // 2) >= 240
    # A broad, symmetrical curve in every state, not a one-pixel corner cut.
    for dy in range(height):
        for dx in range(width):
            a = alpha(x + dx, y + dy)
            assert a == alpha(x + width - 1 - dx, y + dy)
            assert a == alpha(x + dx, y + height - 1 - dy)
    assert all(alpha(x + dx, y) == 0 for dx in range(5))
    assert all(alpha(x, y + dy) == 0 for dy in range(5))
    assert len({alpha(x + dx, y + dy) for dx in range(9) for dy in range(9)}) >= 8
    for px, py in ((x, y), (x + width - 1, y),
                   (x, y + height - 1), (x + width - 1, y + height - 1)):
        assert alpha(px, py) <= 16
    for py in range(y - 1, y + height + 1):
        assert alpha(x - 1, py) == alpha(x + width, py) == 0
    for px in range(x - 1, x + width + 1):
        assert alpha(px, y - 1) == alpha(px, y + height) == 0


def test_attack_indicator_follows_full_client_perimeter_not_the_name_row():
    root = _root("EQUI_PlayerWindow.xml")
    window = _item(root, "Screen", "PlayerWindow")
    window_size = _pair(window, "Size", "CX", "CY")
    texture = _item(root, "TextureInfo", "AttackIndicator.tga")
    texture_size = _pair(texture, "Size", "CX", "CY")
    assert texture_size == (512, 128)

    animation = _item(root, "Ui2DAnimation", "A_AttackIndicator")
    assert animation.findtext("Cycle") == "false"
    frame = _only_frame(animation)
    assert frame.findtext("Texture") == "AttackIndicator.tga"
    assert _rect(frame) == (0, 0, 262, 57)
    _assert_in_bounds(_rect(frame), texture_size)

    indicator = _item(root, "StaticAnimation", "A_AttackIndicatorAnim")
    assert indicator.findtext("ScreenID") == "A_AttackIndicatorAnim"
    assert indicator.findtext("Animation") == "A_AttackIndicator"
    assert indicator.findtext("RelativePosition") == "true"
    assert _rect(indicator) == (0, 0, 262, 57)
    _assert_in_bounds(_rect(indicator), window_size)
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]
    assert pieces.count("A_AttackIndicatorAnim") == 1

    assert _rect(indicator)[2:] == (window_size[0] - 8, window_size[1] - 8)
    mana = _item(root, "Gauge", "Player_Mana")
    assert _rect(mana)[1] + _rect(mana)[3] < _rect(indicator)[3] - 1
