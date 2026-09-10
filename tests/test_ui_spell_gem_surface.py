"""Bright spell-gem tint surface and strict atlas-scope regression coverage."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / "ui" / "skin"
spec = importlib.util.spec_from_file_location(
    "ui_spell_gem_surface", ROOT / "scripts" / "ui_spell_gem_surface.py"
)
surface = importlib.util.module_from_spec(spec)
spec.loader.exec_module(surface)


def pixel(data, x, y):
    offset = 18 + (y * surface.ATLAS_WIDTH + x) * 4
    blue, green, red, alpha = data[offset:offset + 4]
    return red, green, blue, alpha


def test_spell_gems_use_the_bright_tintable_background():
    root = ET.parse(SKIN / "EQUI_CastSpellWnd.xml").getroot()
    animations = ET.parse(SKIN / "EQUI_Animations.xml").getroot()
    background = animations.find("Ui2DAnimation[@item='V3_CastBackground']/Frames")
    assert background.findtext("Texture") == "v3_controls.tga"
    assert tuple(int(background.findtext(f"Location/{axis}")) for axis in ("X", "Y")) == (0, 28)
    assert tuple(int(background.findtext(f"Size/{axis}")) for axis in ("CX", "CY")) == (120, 28)
    for index in range(8):
        template = root.find(f"SpellGem[@item='CSPW_Spell{index}']/SpellGemDrawTemplate")
        assert template.findtext("Background") == "V3_CastBackground"


def test_background_is_neutral_bright_and_keeps_3d_shading():
    data = (SKIN / "v3_controls.tga").read_bytes()
    visible = [
        pixel(data, x, surface.BACKGROUND_TOP + y)
        for y in range(surface.BACKGROUND_HEIGHT)
        for x in range(surface.BACKGROUND_WIDTH)
        if pixel(data, x, surface.BACKGROUND_TOP + y)[3]
    ]
    assert all(red == green == blue for red, green, blue, _ in visible)
    values = {red for red, _, _, _ in visible}
    assert min(values) == min(surface.BACKGROUND_SHADES) == 158
    assert max(values) == max(surface.BACKGROUND_SHADES) == 250
    assert pixel(data, 60, 34)[:3] == (250, 250, 250)
    assert pixel(data, 60, 53)[:3] == (158, 158, 158)


def test_generator_is_idempotent_and_changes_only_background_rgb():
    data = (SKIN / "v3_controls.tga").read_bytes()
    regenerated = surface.brighten_spell_gem_background(data)
    assert regenerated == data
    changed = bytearray(data)
    offset = 18 + (40 * surface.ATLAS_WIDTH + 60) * 4
    changed[offset:offset + 3] = bytes((1, 2, 3))
    repaired = surface.brighten_spell_gem_background(bytes(changed))
    assert repaired == data

    start = 18 + surface.BACKGROUND_TOP * surface.ATLAS_WIDTH * 4
    end = 18 + (surface.BACKGROUND_TOP + surface.BACKGROUND_HEIGHT) * surface.ATLAS_WIDTH * 4
    assert repaired[:start] == bytes(changed[:start])
    assert repaired[end:] == bytes(changed[end:])
    assert repaired[start + 3:end:4] == bytes(changed[start + 3:end:4])
