"""Horizontal source geometry and frozen native contracts, not client proof."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / "ui" / "skin"
# Full normalized XML before the horizontal change, independently measured
# from git show 5544920:ui/skin/EQUI_BuffWindow.xml. Tests need no Git checkout.
VERTICAL_TREE = "68ba13683016126d3eb9e6e81a877e4791140ac7799966ca758ba0c9bf039e74"
# Only these inherited SIDL fields are new geometry inputs. Keep this allowlist
# independent of the generator so it cannot silently permit new native fields.
GEOMETRY_ANCHORS = (
    "AutoStretch", "TopAnchorToTop", "LeftAnchorToLeft", "BottomAnchorToTop",
    "RightAnchorToLeft", "TopAnchorOffset", "BottomAnchorOffset",
    "LeftAnchorOffset", "RightAnchorOffset",
)
NAME_PRESENTATION = {"NoWrap": "true", "AlignCenter": "false", "AlignRight": "true"}
BUFF_NAME_ITEMS = ({f"BW_Buff{index}_Label" for index in range(25)} |
                   {f"BW_Buff{index}_LabelBG" for index in range(15)})
PROTECTED_FILES = {
    "Buff_Background.tga": "c838ed81f5189f6b6d86e4e0b860875c366e971ab4a0fd81ba502ede5f7c6214",
    "wnd_bg_modern.png": "9a8a5ed13da0261c0569b4cb43de5f1bf5ef9fc9a478f3c24b3804ca2eb9b4e4",
    "window_pieces03_modern.png": "8c250d5f7a1e199360d1910a702f570ba965df972e0b19db4b9f4910dfd00529",
    "EQUI_ShortDurationBuffWindow.xml": "675effc38ab4d0d9aa539d3e63ee3fa72a8b2e4e11b21fed5d965539e502237c",
}


def xml(layout="horizontal"):
    source = (SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii")
    return ET.fromstring(getattr(generator(), layout + "_preset")(source))


def item(root, kind, name):
    nodes = root.findall(f"{kind}[@item='{name}']")
    assert len(nodes) == 1, (kind, name)
    return nodes[0]


def rect(node):
    return tuple(int(node.findtext(path)) for path in
                 ("Location/X", "Location/Y", "Size/CX", "Size/CY"))


def anchored_rect(node):
    """Resolve this explicit top/left SIDL model, not the game renderer."""
    for field in GEOMETRY_ANCHORS[:5]:
        assert len(node.findall(field)) == 1, field
        assert node.findtext(field) == "true", field
    offsets = []
    for field in ("LeftAnchorOffset", "TopAnchorOffset", "RightAnchorOffset",
                  "BottomAnchorOffset"):
        assert len(node.findall(field)) == 1, field
        offsets.append(int(node.findtext(field)))
    left, top, right, bottom = offsets
    assert right > left and bottom > top
    return left, top, right - left, bottom - top


def signature(node):
    return (node.tag, sorted(node.attrib.items()), (node.text or "").strip(),
            [signature(child) for child in node])


def tree_digest(root):
    return sha256(json.dumps(signature(root), separators=(",", ":")).encode()).hexdigest()


def native_client_sizes(screen):
    """Derive both native inset models from the shipped frame/title art."""
    templates = ET.parse(SKIN / "EQUI_Templates.xml").getroot()
    animations = ET.parse(SKIN / "EQUI_Animations.xml").getroot()
    rounded = item(templates, "WindowDrawTemplate", screen.findtext("DrawTemplate"))
    no_title = item(templates, "WindowDrawTemplate", "WDT_RoundedNoTitle")

    def frame_size(name):
        animation = item(animations, "Ui2DAnimation", name)
        assert len(animation.findall("Frames")) == 1
        return rect(animation.find("Frames"))[2:]

    sides = (("Left", 0), ("Right", 0), ("Top", 1), ("Bottom", 1))
    declared = {side: frame_size(rounded.findtext(f"Border/{side}"))[dimension]
                for side, dimension in sides}
    conservative = {
        side: max(declared[side], frame_size(no_title.findtext(f"Border/{side}"))[dimension])
        for side, dimension in sides}
    title_heights = {frame_size(rounded.findtext(f"Titlebar/{side}"))[1]
                     for side in ("Left", "Middle", "Right")}
    assert declared == {"Left": 4, "Right": 4, "Top": 2, "Bottom": 4}
    assert conservative == {"Left": 4, "Right": 4, "Top": 4, "Bottom": 4}
    assert title_heights == {16}
    width, height = rect(screen)[2:]
    return {
        model: (width - insets["Left"] - insets["Right"],
                height - insets["Top"] - insets["Bottom"] - 16)
        for model, insets in (("declared", declared), ("conservative", conservative))}


def native_contract(root):
    contract = ET.Element("NativeBuffContract", {
        "source": "5544920", "file": "ui/skin/EQUI_BuffWindow.xml"})
    allowed_fields = {
        "Button": ("Location",) + GEOMETRY_ANCHORS,
        "Label": ("Location", "Size"),
        "Screen": ("Location", "Size", "Style_Transparent", "DrawTemplate",
                   "Style_Titlebar", "Style_Border"),
    }
    for original in root:
        if original.tag not in allowed_fields:
            continue
        node = deepcopy(original)
        if node.tag == "Label" and node.attrib.get("item") in BUFF_NAME_ITEMS:
            # Only these known name labels may change wrapping/alignment.
            # Normalize to the unchanged frozen V reference, not all Labels.
            for field, value in NAME_PRESENTATION.items():
                assert len(node.findall(field)) == 1, field
                node.find(field).text = value
        if node.tag == "Screen" and node.findtext("Text") in ("Effects (V)", "Effects (H)"):
            node.find("Text").text = "Effects"
        for child in list(node):
            if child.tag in allowed_fields[node.tag]:
                node.remove(child)
        contract.append(node)
    return contract


def restore_vertical_geometry(root):
    """Normalize specifically allowed geometry, name presentation and chrome."""
    for index in range(25):
        button = item(root, "Button", f"BW_Buff{index}_Button")
        button.find("Location/X").text = "175"
        button.find("Location/Y").text = str(1 + 25 * index)
        for field in GEOMETRY_ANCHORS:
            for node in button.findall(field):
                button.remove(node)
        number = item(root, "Label", f"BW_Number{index}Label")
        for field, value in zip(("Location/X", "Location/Y", "Size/CX", "Size/CY"),
                                (175, 7 + 25 * index, 24, 12)):
            number.find(field).text = str(value)
        name = item(root, "Label", f"BW_Buff{index}_Label")
        for field, value in zip(("Location/X", "Location/Y", "Size/CX", "Size/CY"),
                                (30, 6 + 25 * index, 142, 12)):
            name.find(field).text = str(value)
        for field, value in NAME_PRESENTATION.items():
            assert len(name.findall(field)) == 1, field
            name.find(field).text = value
        if index < 15:
            shadow = item(root, "Label", f"BW_Buff{index}_LabelBG")
            for field, value in zip(("Location/X", "Location/Y", "Size/CX", "Size/CY"),
                                    (31, 7 + 25 * index, 142, 12)):
                shadow.find(field).text = str(value)
            for field, value in NAME_PRESENTATION.items():
                assert len(shadow.findall(field)) == 1, field
                shadow.find(field).text = value
    for index in range(3):
        background = item(root, "StaticAnimation", f"BW_BuffBackground{index}")
        for field, value in zip(("Location/X", "Location/Y", "Size/CX", "Size/CY"),
                                (175, 1 + 125 * index, 24, 124)):
            background.find(field).text = str(value)
    screen = item(root, "Screen", "BuffWindow")
    if screen.findtext("Text") in ("Effects (V)", "Effects (H)"):
        screen.find("Text").text = "Effects"
    for field, value in {
            "Location/X": "415", "Location/Y": "395", "Size/CX": "200", "Size/CY": "375",
            "Style_Transparent": "true", "DrawTemplate": "WDT_RoundedNoTitle",
            "Style_Titlebar": "false", "Style_Border": "false"}.items():
        screen.find(field).text = value
    return root


@pytest.mark.parametrize("layout", ("vertical", "horizontal"))
def test_presets_change_only_allowed_geometry_name_presentation_and_window_chrome(layout):
    root = restore_vertical_geometry(xml(layout))
    # This preserves all original IDs (including native duplicate label
    # ScreenIDs), EQTypes, Pieces/order, native decal/click fields and art.
    assert tree_digest(root) == VERTICAL_TREE


def test_native_bindings_match_the_frozen_ui102_xml_reference():
    # The fixture was exported from the historical source before this layout
    # existed. This is a direct XML comparison and does not import the layout
    # generator or depend on Git being installed on the test machine.
    reference = ET.parse(ROOT / "tests" / "fixtures" / "ui102_buff_native_contract.xml").getroot()
    assert signature(native_contract(xml())) == signature(reference)


def test_fifteen_p99_slots_fit_one_row_with_names_below_without_removing_native_controls():
    root = xml()
    screen = item(root, "Screen", "BuffWindow")
    pieces = [node.text for node in screen.findall("Pieces")]
    buttons = root.findall("Button")
    expected_ids = [f"Buff{index}" for index in range(25)]
    assert [node.findtext("ScreenID") for node in buttons] == expected_ids
    assert len(set(expected_ids)) == len(buttons)
    assert rect(screen) == (415, 395, 1066, 100)
    assert rect(screen)[0] + rect(screen)[2] <= 1920
    client_sizes = native_client_sizes(screen)
    assert client_sizes == {"declared": (1058, 78), "conservative": (1058, 76)}
    occupied = []
    for index, button in enumerate(buttons):
        assert button.attrib["item"] == f"BW_Buff{index}_Button"
        x, y, width, height = rect(button)
        column, row = index % 15, index // 15
        assert (x, y, width, height) == (27 + 70 * column, 4 + 80 * row, 24, 24)
        assert anchored_rect(button) == rect(button)
        name = item(root, "Label", f"BW_Buff{index}_Label")
        name_bounds = (6 + 70 * column, 32 + 80 * row, 66, 40)
        assert rect(name) == name_bounds
        assert name.findtext("EQType") == str(500 + index)
        assert name.findtext("Font") == "1"
        assert name.findtext("NoWrap") == name.findtext("AlignRight") == "false"
        assert name.findtext("AlignCenter") == "true"
        assert 2 * x + width == 2 * name_bounds[0] + name_bounds[2]
        assert name_bounds[1] == y + height + 4
        occupied.extend((rect(button), name_bounds))
        if index < 15:
            shadow = item(root, "Label", f"BW_Buff{index}_LabelBG")
            assert rect(shadow) == (name_bounds[0] + 1, name_bounds[1] + 1, 66, 40)
            assert shadow.findtext("EQType") == str(500 + index)
            assert shadow.findtext("Font") == "1"
            assert shadow.findtext("NoWrap") == shadow.findtext("AlignRight") == "false"
            assert shadow.findtext("AlignCenter") == "true"
            for client_width, client_height in client_sizes.values():
                sx, sy, sw, sh = rect(shadow)
                assert sx + sw <= client_width - 2
                assert sy + sh <= client_height - 2
        for client_width, client_height in client_sizes.values():
            assert 4 <= x and x + width <= client_width - 4
            if index < 15:
                assert 4 <= y and y + height <= client_height - 4
            else:
                # No new native capacity: retain the other Titanium controls
                # below the P99 pane, exactly as the old V preset did.
                assert y > client_height
                assert name_bounds[1] >= client_height
        assert pieces.count(button.attrib["item"]) == 1
        assert button.findtext("ButtonDrawTemplate/NormalDecal") == "BuffIcons"
        assert tuple(int(button.findtext(field)) for field in
                     ("DecalOffset/X", "DecalOffset/Y", "DecalSize/CX", "DecalSize/CY")) == (2, 2, 20, 20)
    assert {rect(button)[1] for button in buttons[:15]} == {4}
    assert {rect(button)[1] for button in buttons[15:]} == {84}
    assert rect(buttons[14]) == (1007, 4, 24, 24)
    assert len(buttons) == 25
    for index, (x, y, width, height) in enumerate(occupied):
        for client_width, client_height in client_sizes.values():
            assert 4 <= x and x + width <= client_width - 4
            if index < 30:
                assert 4 <= y and y + height <= client_height - 4
        for other_x, other_y, other_width, other_height in occupied[index + 1:]:
            assert (x + width <= other_x or other_x + other_width <= x or
                    y + height <= other_y or other_y + other_height <= y)


def test_explicit_button_anchors_keep_names_associated_after_native_location_reset():
    root = xml()
    screen = item(root, "Screen", "BuffWindow")
    client_width, _ = native_client_sizes(screen)["conservative"]
    for index, button in enumerate(root.findall("Button")):
        column, row = index % 15, index // 15
        expected = (27 + 70 * column, 4 + 80 * row, 24, 24)
        # The supplied screenshot has the native icons stacked at the right
        # while names retain their static layout. Model a native Location reset
        # and require the separate anchor fields to retain our intended grid.
        button.find("Location/X").text = str(client_width - 24)
        button.find("Location/Y").text = str(4 + 25 * index)
        assert anchored_rect(button) == expected
        name = item(root, "Label", f"BW_Buff{index}_Label")
        nx, ny, nw, nh = rect(name)
        bx, by, bw, bh = anchored_rect(button)
        assert 2 * nx + nw == 2 * bx + bw
        assert ny == by + bh + 4 and nh == 40 and (bw, bh) == (24, 24)


@pytest.mark.parametrize("field", GEOMETRY_ANCHORS)
def test_anchor_contract_rejects_missing_fields_even_when_locations_are_correct(field):
    button = item(xml(), "Button", "BW_Buff0_Button")
    assert rect(button) == (27, 4, 24, 24)
    button.remove(button.find(field))
    with pytest.raises(AssertionError):
        anchored_rect(button)


@pytest.mark.parametrize("field", GEOMETRY_ANCHORS[:5])
def test_anchor_contract_rejects_disabled_or_opposite_anchors_with_correct_locations(field):
    button = item(xml(), "Button", "BW_Buff0_Button")
    button.find(field).text = "false"
    assert rect(button) == (27, 4, 24, 24)
    with pytest.raises(AssertionError):
        anchored_rect(button)


def test_anchor_fields_are_inherited_native_sidl_elements():
    sidl = ET.parse(SKIN / "SIDL.xml").getroot()
    namespace = "{EverQuestData}"
    inherited = {node.attrib.get("name"): node.attrib.get("type")
                 for node in sidl.findall(f".//{namespace}ElementType[@name='ScreenPiece']/{namespace}element")}
    assert {field: inherited[field] for field in GEOMETRY_ANCHORS} == {
        field: ("boolean" if field in GEOMETRY_ANCHORS[:5] else "int")
        for field in GEOMETRY_ANCHORS}


def test_wrapping_name_presentation_uses_only_native_label_fields():
    sidl = ET.parse(SKIN / "SIDL.xml").getroot()
    namespace = "{EverQuestData}"
    fields = {node.attrib.get("name"): node.attrib.get("type")
              for node in sidl.findall(f".//{namespace}ElementType[@name='Label']/{namespace}element")}
    assert {field: fields[field] for field in NAME_PRESENTATION} == {
        field: "boolean" for field in NAME_PRESENTATION}
    horizontal_root, vertical_root = xml(), xml("vertical")
    for name in BUFF_NAME_ITEMS:
        horizontal = item(horizontal_root, "Label", name)
        vertical = item(vertical_root, "Label", name)
        assert horizontal.findtext("Font") == vertical.findtext("Font") == "1"
        assert {field: vertical.findtext(field) for field in NAME_PRESENTATION} == NAME_PRESENTATION
        assert {field: horizontal.findtext(field) for field in NAME_PRESENTATION} == {
            "NoWrap": "false", "AlignCenter": "true", "AlignRight": "false"}


@pytest.mark.parametrize("field,value", (("NoWrap", "true"), ("AlignCenter", "false"),
                                         ("AlignRight", "true")))
def test_name_presentation_normalization_does_not_erase_numeric_label_changes(field, value):
    root = xml()
    number = item(root, "Label", "BW_Number0Label")
    assert number.findtext(field) != value
    number.find(field).text = value
    reference = ET.parse(ROOT / "tests" / "fixtures" / "ui102_buff_native_contract.xml").getroot()
    assert signature(native_contract(root)) != signature(reference)
    assert tree_digest(restore_vertical_geometry(root)) != VERTICAL_TREE


def test_dark_native_titlebar_is_clear_of_icon_controls():
    root = xml()
    screen = item(root, "Screen", "BuffWindow")
    assert screen.findtext("Text") == "Effects (H)"
    assert screen.findtext("DrawTemplate") == "WDT_Rounded"
    assert screen.findtext("Style_Titlebar") == screen.findtext("Style_Border") == "true"
    assert screen.findtext("Style_Transparent") == "false"
    assert screen.findtext("Style_Sizable") == "false"
    assert screen.findtext("Style_Closebox") == screen.findtext("Style_Minimizebox") == "false"
    templates = ET.parse(SKIN / "EQUI_Templates.xml").getroot()
    template = item(templates, "WindowDrawTemplate", "WDT_Rounded")
    assert template.findtext("Background") == "wnd_bg_modern.png"
    assert template.find("Titlebar") is not None
    for node in root.findall("StaticAnimation") + [node for node in root.findall("Label")
                                                      if node.attrib["item"].startswith("BW_Number")]:
        assert rect(node) == (4, 20, 0, 0), node.attrib["item"]
    for node in root.findall("Label"):
        if node.find("EQType") is not None:
            assert 500 <= int(node.findtext("EQType")) <= 524


def test_client_area_model_catches_reserving_the_titlebar_twice():
    root = xml()
    screen = item(root, "Screen", "BuffWindow")
    # y=24 looks safe against a 52px outer screen, but the native client area
    # excludes title/frame insets. Catch the same class of UI100 clipping.
    screen.find("Size/CY").text = "52"
    button = item(root, "Button", "BW_Buff0_Button")
    button.find("Location/Y").text = "24"
    assert rect(button)[1] + rect(button)[3] <= rect(screen)[3]
    assert all(rect(button)[1] + rect(button)[3] > height
               for _, height in native_client_sizes(screen).values())


@pytest.mark.parametrize("filename,baseline", PROTECTED_FILES.items())
def test_horizontal_preset_keeps_existing_art_and_disabled_songs_screen(filename, baseline):
    assert sha256((SKIN / filename).read_bytes()).hexdigest() == baseline


def generator():
    spec = importlib.util.spec_from_file_location(
        "horizontal_buffs_generator", ROOT / "scripts" / "build_horizontal_buffs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_is_idempotent_and_preserves_comments_and_native_fields():
    module = generator()
    original = (SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii")
    source = module.horizontal_preset(original)
    assert module.horizontal_preset(source) == source
    vertical_source = module.vertical_preset(original)
    assert module.vertical_preset(vertical_source) == vertical_source
    assert module.horizontal_preset(vertical_source) == source
    assert module.vertical_preset(source) == vertical_source
    crlf_source = original.replace("\r\n", "\n").replace("\n", "\r\n")
    for layout in ("vertical", "horizontal"):
        crlf_result = getattr(module, layout + "_preset")(crlf_source)
        assert crlf_result.count("\n") == crlf_result.count("\r\n")
        assert getattr(module, layout + "_preset")(crlf_result) == crlf_result
    for button in ET.fromstring(vertical_source).findall("Button"):
        assert all(button.find(field) is None for field in GEOMETRY_ANCHORS)
    vertical = restore_vertical_geometry(xml())
    restored_source = ET.tostring(vertical, encoding="unicode")
    generated = module.horizontal_preset(restored_source)
    assert signature(ET.fromstring(generated)) == signature(xml())
    assert tree_digest(restore_vertical_geometry(ET.fromstring(generated))) == VERTICAL_TREE
    decorated = source.replace("<Text>Effects (H)</Text>", "<!-- retain this note -->\r\n    <Text>Effects (H)</Text>")
    assert module.horizontal_preset(decorated) == decorated


def test_exported_preset_matches_its_explicit_release_orientation():
    release = json.loads((ROOT / "ui/release.json").read_text())
    expected = {"1.44.104": "vertical", "1.44.105": "horizontal", "1.44.106": "horizontal", "1.44.107": "horizontal"}
    assert release["buff_layout"] == expected[release["version"]]
    source = (SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii")
    assert getattr(generator(), release["buff_layout"] + "_preset")(source) == source


def test_unknown_title_is_not_erased_by_frozen_native_contract_check():
    altered = xml()
    item(altered, "Screen", "BuffWindow").find("Text").text = "Unreviewed title"
    assert tree_digest(restore_vertical_geometry(altered)) != VERTICAL_TREE


def test_generator_rejects_duplicate_or_missing_native_buff_ids():
    module = generator()
    source = (SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii")
    with pytest.raises(ValueError, match="original Buff0 through Buff24"):
        module.horizontal_preset(source.replace("<ScreenID>Buff24</ScreenID>", "<ScreenID>Buff0</ScreenID>"))


@pytest.mark.parametrize("layout", ("vertical", "horizontal"))
@pytest.mark.parametrize("field", GEOMETRY_ANCHORS)
def test_generator_rejects_duplicate_geometry_anchor_fields(layout, field):
    module = generator()
    source = module.horizontal_preset((SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii"))
    first_button = item(ET.fromstring(source), "Button", "BW_Buff0_Button")
    value = first_button.findtext(field)
    source = source.replace(f"<{field}>{value}</{field}>",
                            f"<{field}>{value}</{field}>\r\n    <{field}>{value}</{field}>", 1)
    with pytest.raises(ValueError, match=f"at most one {field}"):
        getattr(module, layout + "_preset")(source)


@pytest.mark.parametrize("layout", ("vertical", "horizontal"))
def test_generator_rejects_duplicate_coordinate_fields(layout):
    module = generator()
    source = (SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii")
    source = source.replace("<X>27</X>", "<X>27</X><X>999</X>", 1)
    with pytest.raises(ValueError, match="Expected one X, found 2"):
        getattr(module, layout + "_preset")(source)


@pytest.mark.parametrize("layout", ("vertical", "horizontal"))
@pytest.mark.parametrize("field", NAME_PRESENTATION)
def test_generator_rejects_duplicate_name_presentation_fields(layout, field):
    module = generator()
    source = module.horizontal_preset((SKIN / "EQUI_BuffWindow.xml").read_bytes().decode("ascii"))
    first_name = item(ET.fromstring(source), "Label", "BW_Buff0_Label")
    value = first_name.findtext(field)
    start = source.index('<Label item="BW_Buff0_Label">')
    end = source.index('</Label>', start) + len('</Label>')
    original = source[start:end]
    changed = original.replace(f"<{field}>{value}</{field}>",
                               f"<{field}>{value}</{field}><{field}>{value}</{field}>")
    source = source[:start] + changed + source[end:]
    with pytest.raises(ValueError, match=f"Expected one {field}, found 2"):
        getattr(module, layout + "_preset")(source)


def test_frozen_contract_does_not_erase_other_native_layout_fields():
    root = xml()
    ET.SubElement(item(root, "Button", "BW_Buff0_Button"), "LayoutBox").text = "Unreviewed"
    assert tree_digest(restore_vertical_geometry(root)) != VERTICAL_TREE


def test_frozen_contract_detects_native_binding_changes():
    # Guard against a circular contract check: geometry normalization must
    # never erase a changed cancellation binding, decal, Piece, or EQType.
    root = xml()
    for field, value in (("ScreenID", "BuffDuplicate"), ("DecalSize/CX", "24"),
                         ("ButtonDrawTemplate/NormalDecal", "FakeBuffIcons")):
        altered = deepcopy(root)
        item(altered, "Button", "BW_Buff0_Button").find(field).text = value
        assert tree_digest(restore_vertical_geometry(altered)) != VERTICAL_TREE
    altered = deepcopy(root)
    item(altered, "Label", "BW_Buff0_Label").find("EQType").text = "600"
    assert tree_digest(restore_vertical_geometry(altered)) != VERTICAL_TREE
    altered = deepcopy(root)
    screen = item(altered, "Screen", "BuffWindow")
    screen.remove(screen.findall("Pieces")[-1])
    assert tree_digest(restore_vertical_geometry(altered)) != VERTICAL_TREE
