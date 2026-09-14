"""Bright spell-gem tint surface and strict atlas-scope regression coverage."""

import importlib.util
import hashlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


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


def name_plate_pixel(data, x, y):
    """Read local coordinates in the existing 120x28 untinted outline cell."""
    offset = 18 + ((y + 34) * 512 + x + 2) * 4
    blue, green, red, alpha = data[offset:offset + 4]
    return red, green, blue, alpha


def contrast(foreground, background):
    def luminance(rgb):
        values = [value / 255 for value in rgb]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in values]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    left, right = sorted((luminance(foreground), luminance(background)))
    return (right + .05) / (left + .05)


def composite(pixel_rgba, background):
    alpha = pixel_rgba[3]
    return tuple((front * alpha + back * (255 - alpha) + 127) // 255
                 for front, back in zip(pixel_rgba[:3], background))


def test_name_plate_changes_only_the_existing_label_lane_and_preserves_all_other_art():
    data = (SKIN / 'VantageControlEdges.tga').read_bytes()
    assert data[:3] == bytes((0, 0, 2))
    assert data[12:18] == bytes((0, 2, 128, 0, 32, 40))
    assert len(data) == 18 + 512 * 128 * 4
    masked = bytearray(data)
    # Fingerprint captured before this change, with only the approved name
    # inset zeroed. Protects every other control, icon lane, rim and gutter.
    for y in range(2, 26):
        for x in range(30, 118):
            offset = 18 + ((y + 34) * 512 + x + 2) * 4
            masked[offset:offset + 4] = bytes(4)
    assert hashlib.sha256(masked).hexdigest() == (
        'b7f12dbbb5c47580a8d580b0b660b25dfcfdc7306aa1f1914f0739024a4ab3c4'
    )
    assert name_plate_pixel(data, 60, 12) == (238, 232, 215, 190)
    assert name_plate_pixel(data, 60, 2) == (214, 209, 194, 190)
    assert name_plate_pixel(data, 30, 2)[3] == 0
    # This cutout reveals the original grey outer rim, not a square plate.
    assert name_plate_pixel(data, 117, 25) == (148, 148, 148, 115)
    assert all(name_plate_pixel(data, x, y)[3] == 0
               for y in range(4, 24) for x in range(5, 30))
    # Category-tinted Background, empty Holder and Highlight stay unchanged.
    assert hashlib.sha256((SKIN / 'v3_controls.tga').read_bytes()).hexdigest() == (
        'cc40f8ea9c32bce5c0c47131fc2b137357a7e745dbd8061a359fa9eff8ac6e0f'
    )


@pytest.mark.parametrize('background', [
    (160, 26, 26),   # Screenshot f171... red at (115,36).
    (149, 161, 32),  # Yellow-green at (115,126).
    (61, 50, 162),   # Blue at (115,186).
    (0, 0, 0),      # Darkest possible underlying pixel, including empty rows.
    (255, 255, 255),
])
def test_near_black_names_have_contrast_throughout_the_modeled_two_line_ink_area(background):
    data = (SKIN / 'VantageControlEdges.tga').read_bytes()
    # Existing screenshot-based glyph budget: label local (30,3), 2px ink
    # inset, 12px line pitch, 9px ink. Include the entire envelope, even the
    # between-line gap and antialiased plate corners; not just its center.
    for y in range(5, 26):
        for x in range(32, 116):
            plate = name_plate_pixel(data, x, y)
            assert 160 <= plate[3] <= 190
            assert contrast((8, 10, 13), composite(plate, background)) >= 4.5


def test_near_black_names_keep_native_bindings_and_reuse_the_existing_untinted_layer():
    root = ET.parse(SKIN / 'EQUI_CastSpellWnd.xml').getroot()
    window = root.find("Screen[@item='CastSpellWnd']")
    pieces = [piece.text for piece in window.findall('Pieces')]
    assert len(pieces) == len(set(pieces)) == 73  # No added drawables or labels.
    for index in range(8):
        name = f'CSPW_Spell{index}'
        labels = [label for label in root.findall('Label')
                  if label.findtext('EQType') == str(60 + index)]
        assert len(labels) == 1
        label = labels[0]
        assert label.get('item') == label.findtext('ScreenID') == name + '_Name'
        assert tuple(int(label.findtext('TextColor/' + c)) for c in 'RGB') == (8, 10, 13)
        assert label.findtext('NoWrap') == 'false'
        assert label.findtext('AlignCenter') == 'true'
        outline = root.find(f"StaticAnimation[@item='{name}_Outline']")
        assert outline.findtext('AutoDraw') == 'true'
        assert outline.findtext('Animation') == 'A_VantageSpellGemOutline'
        assert outline.find('Tint') is None
        assert pieces.index(name) < pieces.index(name + '_Outline') < pieces.index(name + '_Name')
        assert root.find(f"SpellGem[@item='{name}']/SpellGemDrawTemplate/Holder").text == 'V3_CastHolder'


@pytest.mark.skipif(sys.platform != 'win32', reason='Native deterministic atlas generator uses System.Drawing')
def test_scoped_plate_generator_repairs_and_is_byte_idempotent(tmp_path):
    actual = (SKIN / 'VantageControlEdges.tga').read_bytes()
    candidate = tmp_path / 'VantageControlEdges.tga'
    corrupted = bytearray(actual)
    offset = 18 + ((34 + 12) * 512 + 2 + 60) * 4
    corrupted[offset:offset + 4] = bytes((1, 2, 3, 4))
    candidate.write_bytes(corrupted)
    source = str(ROOT / 'scripts' / 'ui_control_edges.cs').replace("'", "''")
    destination = str(candidate).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path '{source}' -ReferencedAssemblies System.Drawing; "
        f"[VantageControlEdgesRenderer]::RenderSpellNamePlate('{destination}'); "
        f"$first=[IO.File]::ReadAllBytes('{destination}'); "
        f"[VantageControlEdgesRenderer]::RenderSpellNamePlate('{destination}'); "
        f"$second=[IO.File]::ReadAllBytes('{destination}'); "
        "if([Convert]::ToBase64String($first) -ne [Convert]::ToBase64String($second)) "
        "{ throw 'Plate generator is not idempotent' }"
    )
    subprocess.run([
        str(Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')),
        '-NoProfile', '-NonInteractive', '-Command', command,
    ], check=True, capture_output=True, text=True, timeout=60)
    assert candidate.read_bytes() == actual
