"""Native child lookup contracts: valid definitions alone do not create children.

The Sep 13 2026 client log explicitly requires InventoryWindow/IW_FacePick.
The installed Titanium default also requires TargetWindow/TargetHP. Its log
entry had a corrupted name, so only a real reload can correlate that error.
"""

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SKIN = Path(__file__).resolve().parents[1] / "ui" / "skin"


def root(filename):
    return ET.parse(SKIN / filename).getroot()


def native_child(xml, parent_name, kind, screen_id):
    parent = xml.find(f"Screen[@item='{parent_name}']")
    assert parent is not None
    definitions = {node.get("item"): node for node in xml if node.get("item")}
    children = [definitions[p.text.split(":")[-1].strip()] for p in parent.findall("Pieces")]
    matches = [node for node in children if node.findtext("ScreenID") == screen_id]
    assert len(matches) == 1, f"{parent_name} must instantiate native child {screen_id} once"
    assert matches[0].tag == kind
    assert list(xml).index(matches[0]) < list(xml).index(parent)
    return matches[0]


def assert_off_canvas(node):
    x, y, width, height = (
        int(node.findtext(path))
        for path in ("Location/X", "Location/Y", "Size/CX", "Size/CY")
    )
    assert width > 0 and height > 0
    assert x + width < 0 and y + height < 0
    assert node.findtext("RelativePosition") == "true"
    assert node.findtext("Style_Transparent") == "true"


def test_inventory_instantiates_required_face_button_outside_visible_footer():
    button = native_child(root("EQUI_Inventory.xml"), "InventoryWindow", "Button", "IW_FacePick")
    assert button.get("item") == "IW_FacePick"
    assert_off_canvas(button)
    assert button.findtext("Style_Border") == "false"
    assert button.findtext("Text", "") == ""


@pytest.mark.parametrize("kind,screen_id", [
    ("Gauge", "TargetHP"),
    ("Label", "HPLabel"),
    ("Label", "HPPercLabel"),
    ("StaticAnimation", "A_TargetBoxStaticAnim"),
])
def test_target_instantiates_native_default_child_screen_ids(kind, screen_id):
    native_child(root("EQUI_TargetWindow.xml"), "TargetWindow", kind, screen_id)


def test_target_native_gauge_does_not_repaint_visible_health_layers():
    xml = root("EQUI_TargetWindow.xml")
    gauge = native_child(xml, "TargetWindow", "Gauge", "TargetHP")
    assert gauge.get("item") == "Target_HP"
    assert gauge.findtext("EQType") == "6"
    assert_off_canvas(gauge)
    visible = xml.find("Gauge[@item='VantageTarget_HP_0']")
    assert visible is not None and visible.findtext("EQType") == "6"
    assert visible.find("ScreenID") is None


def test_rejects_declared_but_uninstantiated_target_gauge():
    xml = root("EQUI_TargetWindow.xml")
    parent = xml.find("Screen[@item='TargetWindow']")
    for piece in list(parent.findall("Pieces")):
        if piece.text == "Target_HP":
            parent.remove(piece)
    assert xml.find("Gauge[@item='Target_HP']/ScreenID").text == "TargetHP"
    with pytest.raises(AssertionError, match="must instantiate native child TargetHP once"):
        native_child(xml, "TargetWindow", "Gauge", "TargetHP")
