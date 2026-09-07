from copy import deepcopy
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
    assert window_size == (226, 386)
    assert window.findtext("Style_Sizable") == "false"
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
        "Head": (88, 1),
        "Face": (88, 43),
        "Neck": (88, 85),
        "Shoulder": (88, 127),
        "Arms": (88, 169),
        "Hands": (88, 211),
        "Back": (88, 253),
        "Earring1": (130, 1),
        "Earring2": (130, 43),
        "Wrist1": (130, 85),
        "Wrist2": (130, 127),
        "Ring1": (130, 169),
        "Ring2": (130, 211),
        "Belt": (130, 253),
        "Prim": (1, 211),
        "Sec": (42, 211),
        "Ranged": (1, 253),
        "Ammo": (42, 253),
        "Chest": (1, 295),
        "Legs": (42, 295),
        "Boots": (1, 337),
    }
    inventory = {}
    for name, eq_type in gear_types.items():
        slot = _item(root, "InvSlot", name)
        assert slot.findtext("ScreenID") == name
        assert int(slot.findtext("EQType")) == eq_type
        rect = _rect(slot)
        assert rect == (*gear_locations[name], 40, 40)
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
        expected_location = (176, 1 + 41 * (index - 1))
        assert rect == (*expected_location, 40, 40)
        _assert_in_bounds(rect, window_size)
        assert pieces.count(name) == 1
        inventory[name] = rect

    assert len(inventory) == 29
    _assert_nonoverlapping(inventory)
    _assert_nonoverlapping({**hotbuttons, **inventory})


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
                (3, 1)
                if role in {"TopLeft", "TopRight", "BottomLeft", "BottomRight"}
                else (1, 2)
                if role in {"LeftTop", "LeftBottom", "RightTop", "RightBottom"}
                else (1, 1)
            )
            for role in roles
        },
        "A_VantageHP240Lines": (240, 20),
        "A_VantageHP100Lines": (100, 20),
    }
    mapped = {}
    for animation in root.findall("./Ui2DAnimation"):
        frames = animation.findall("Frames")
        if len(frames) == 1 and (frames[0].findtext("Texture") or "").strip() == texture_name:
            mapped[animation.attrib["item"]] = animation
    assert set(mapped) == set(expected_sizes)
    assert len(mapped) == 14

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


def test_health_layers_keep_native_bindings_palette_and_tick_overlays():
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
        assert pieces.count(ticks.attrib["item"]) == 1

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
        "Normal": "A_BtnNormal",
        "Pressed": "A_BtnPressed",
        "Flyby": "A_BtnFlyby",
        "Disabled": "A_BtnDisabled",
        "PressedFlyby": "A_BtnPressedFlyby",
    }
    rows = (
        (86, ("AMP_CampButton",)),
        (108, ("AMP_SitButton", "AMP_StandButton")),
        (130, ("AMP_RunButton", "AMP_WalkButton")),
    )
    representatives = {}
    for y, aliases in rows:
        alias_rects = []
        for name in aliases:
            button = _item(root, "Button", name)
            assert button.findtext("ScreenID") == name
            assert pieces.count(name) == 1
            assert _rect(button) == (1, y, 134, 20)
            draw = button.find("ButtonDrawTemplate")
            assert draw is not None
            assert {state: draw.findtext(state) for state in states} == states
            alias_rects.append(_rect(button))
        assert len(set(alias_rects)) == 1
        representatives[str(y)] = alias_rects[0]
    _assert_nonoverlapping(representatives)
    assert 108 - (86 + 20) == 2
    assert 130 - (108 + 20) == 2

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
    assert conservative_page_height - (130 + 20) >= 4


def test_attack_indicator_crop_retains_native_binding_and_title_clearance():
    root = _root("EQUI_PlayerWindow.xml")
    window = _item(root, "Screen", "PlayerWindow")
    window_size = _pair(window, "Size", "CX", "CY")
    texture = _item(root, "TextureInfo", "AttackIndicator.tga")
    texture_size = _pair(texture, "Size", "CX", "CY")
    assert texture_size == (256, 256)

    animation = _item(root, "Ui2DAnimation", "A_AttackIndicator")
    assert animation.findtext("Cycle") == "false"
    frame = _only_frame(animation)
    assert frame.findtext("Texture") == "AttackIndicator.tga"
    assert _rect(frame) == (0, 0, 256, 20)
    _assert_in_bounds(_rect(frame), texture_size)

    indicator = _item(root, "StaticAnimation", "A_AttackIndicatorAnim")
    assert indicator.findtext("ScreenID") == "A_AttackIndicatorAnim"
    assert indicator.findtext("Animation") == "A_AttackIndicator"
    assert indicator.findtext("RelativePosition") == "true"
    assert _rect(indicator) == (0, 0, 256, 20)
    _assert_in_bounds(_rect(indicator), window_size)
    pieces = [piece.text.strip() for piece in window.findall("Pieces")]
    assert pieces.count("A_AttackIndicatorAnim") == 1

    hp = _item(root, "Gauge", "Player_HP_0")
    assert _rect(indicator)[1] + _rect(indicator)[3] <= _rect(hp)[1]
