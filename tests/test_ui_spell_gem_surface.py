"""Restrained spell-gem tint surface and strict atlas-scope regression coverage."""

import importlib.util
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


def test_spell_gems_use_the_neutral_tintable_background():
    root = ET.parse(SKIN / "EQUI_CastSpellWnd.xml").getroot()
    animations = ET.parse(SKIN / "EQUI_Animations.xml").getroot()
    background = animations.find("Ui2DAnimation[@item='V3_CastBackground']/Frames")
    assert background.findtext("Texture") == "v3_controls.tga"
    assert tuple(int(background.findtext(f"Location/{axis}")) for axis in ("X", "Y")) == (0, 28)
    assert tuple(int(background.findtext(f"Size/{axis}")) for axis in ("CX", "CY")) == (136, 28)
    for index in range(8):
        template = root.find(f"SpellGem[@item='CSPW_Spell{index}']/SpellGemDrawTemplate")
        assert template.findtext("Background") == "V3_CastBackground"


def test_background_is_neutral_restrained_and_keeps_3d_shading():
    data = (SKIN / "v3_controls.tga").read_bytes()
    visible = [
        pixel(data, x, surface.BACKGROUND_TOP + y)
        for y in range(surface.BACKGROUND_HEIGHT)
        for x in range(surface.BACKGROUND_WIDTH)
        if pixel(data, x, surface.BACKGROUND_TOP + y)[3]
    ]
    assert all(red == green == blue for red, green, blue, _ in visible)
    values = {red for red, _, _, _ in visible}
    expected_ramp = (
        186, 206, 216, 223, 229, 232, 234, 232, 230, 227, 223, 220,
        216, 212, 208, 202, 197, 192, 186, 180, 174, 168, 163, 158,
        152, 148, 160, 184,
    )
    assert surface.BACKGROUND_SHADES == expected_ramp
    assert tuple(pixel(data, 60, surface.BACKGROUND_TOP + y)[0]
                 for y in range(surface.BACKGROUND_HEIGHT)) == expected_ramp
    assert min(values) == min(expected_ramp) == 148
    assert max(values) == max(expected_ramp) == 234
    assert pixel(data, 60, 34)[:3] == (234, 234, 234)
    assert pixel(data, 60, 53)[:3] == (148, 148, 148)


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

    alpha_changed = bytearray(data)
    alpha_changed[offset + 3] = 37
    alpha_preserved = surface.brighten_spell_gem_background(bytes(alpha_changed))
    assert alpha_preserved[offset + 3] == 37
    assert alpha_preserved[21::4] == bytes(alpha_changed[21::4])


def linear_luminance(rgb):
    def linear(channel):
        channel /= 255
        return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
    return sum(linear(channel) * weight
               for channel, weight in zip(rgb, (.2126, .7152, .0722)))


def test_ramp_applies_a_second_uniform_seven_percent_luminance_cut():
    preceding = (
        192, 213, 223, 230, 236, 240, 242, 240, 238, 234, 230, 227,
        223, 219, 215, 209, 203, 198, 192, 186, 180, 174, 168, 163,
        157, 153, 165, 190,
    )
    reductions = [
        1 - linear_luminance((new,) * 3) / linear_luminance((old,) * 3)
        for old, new in zip(preceding, surface.BACKGROUND_SHADES)
    ]
    assert all(0.064 <= reduction <= 0.075 for reduction in reductions)
    assert len(set(surface.BACKGROUND_SHADES)) > 20, 'Keep the original 3D ramp detail'


def contrast_ratio(first, second):
    first_luminance = linear_luminance(first)
    second_luminance = linear_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + .05) / (darker + .05)


def test_representative_runtime_tints_are_more_restrained_with_measured_contrast():
    # The legacy client multiplies the neutral source by its category color at
    # runtime.  These measurements document the visual change without treating
    # the shared dynamic tint surface as an accessibility-conformance claim.
    cream = (231, 228, 222)
    preceding_peak = 242
    proposed_peak = max(surface.BACKGROUND_SHADES)
    measured = {
        (160, 26, 26): ((155, 25, 25), (150, 24, 24), 6.4983, 6.7810),
        (149, 161, 32): ((144, 156, 31), (139, 151, 30), 2.3775, 2.5293),
        (61, 50, 162): ((59, 48, 157), (57, 47, 152), 7.8974, 8.1367),
    }
    for source, (before, after, before_ratio, after_ratio) in measured.items():
        assert tuple(round(channel * preceding_peak / 250)
                     for channel in source) == before
        assert tuple(round(channel * proposed_peak / 250)
                     for channel in source) == after
        assert contrast_ratio(cream, before) == pytest.approx(before_ratio, abs=.00005)
        assert contrast_ratio(cream, after) == pytest.approx(after_ratio, abs=.00005)
        assert contrast_ratio(cream, after) > contrast_ratio(cream, before)


def test_original_cream_names_keep_native_bindings_without_new_drawables():
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
        assert tuple(int(label.findtext('TextColor/' + c)) for c in 'RGB') == (231, 228, 222)
        assert label.findtext('NoWrap') == 'false'
        assert label.findtext('AlignCenter') == 'true'
        assert label.findtext('Size/CX') == '104'
        assert label.findtext('Size/CY') == '26'
        assert label.findtext('Font') == '1'
        assert label.find('TextOffsetY') is None
        assert label.find('TextOffsetX') is None
        assert label.find('AlignVCenter') is None
        outline = root.find(f"StaticAnimation[@item='{name}_Outline']")
        assert outline.findtext('AutoDraw') == 'true'
        assert outline.findtext('Animation') == 'A_VantageSpellGemOutline'
        assert outline.find('Tint') is None
        assert pieces.index(name) < pieces.index(name + '_Outline') < pieces.index(name + '_Name')
        assert root.find(f"SpellGem[@item='{name}']/SpellGemDrawTemplate/Holder").text == 'V3_CastHolder'


def test_native_width_extension_preserves_endcaps_and_all_other_atlas_pixels():
    data = (SKIN / 'v3_controls.tga').read_bytes()
    assert surface.widen_spell_gem_controls(data) == data
    legacy = bytearray(data)
    allowed = set()
    for top, height in surface.CONTROL_CELLS:
        for y in range(top, top + height):
            start = 18 + y * surface.ATLAS_WIDTH * 4
            row = data[start:start + 136 * 4]
            legacy[start:start + 136 * 4] = row[:60 * 4] + row[76 * 4:] + bytes(16 * 4)
            allowed.update(range(start, start + 136 * 4))
    widened = surface.widen_spell_gem_controls(bytes(legacy))
    assert widened == data
    assert all(a == b for i, (a, b) in enumerate(zip(legacy, widened)) if i not in allowed)
    for top, height in surface.CONTROL_CELLS:
        for y in range(top, top + height):
            assert all(pixel(widened, x, y) == pixel(legacy, x, y) for x in range(60))
            assert all(pixel(widened, x + 16, y) == pixel(legacy, x, y) for x in range(60, 120))


def test_spell_atlas_frames_fit_exactly_without_overlapping_other_controls():
    roots = [ET.parse(SKIN / name).getroot()
             for name in ('EQUI_Animations.xml', 'EQUI_CastSpellWnd.xml')]
    expected = {
        'V3_CastHolder': (0, 0, 136, 28),
        'V3_CastBackground': (0, 28, 136, 28),
        'V3_CastHighlight': (0, 56, 136, 28),
        'V3_CastHeaderNormal': (0, 84, 136, 14),
        'V3_CastHeaderPressed': (0, 98, 136, 14),
        'V3_CastHeaderFlyby': (0, 112, 136, 14),
        'V3_CastHeaderPressedFlyby': (0, 126, 136, 14),
        'A_VantageSpellGemOutline': (0, 144, 136, 28),
        'A_CSPW_CastFooter': (0, 176, 136, 15),
        'A_CSPW_CastFill': (0, 196, 132, 9),
    }
    frames = {}
    for root in roots:
        for animation in root.findall('Ui2DAnimation'):
            name = animation.get('item')
            frame = animation.find('Frames')
            if frame.findtext('Texture') != 'v3_controls.tga' or name.startswith('CSPW_Cast_R'):
                continue
            frames[name] = tuple(int(frame.findtext(path))
                                 for path in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))
    assert frames == expected
    for x, y, w, h in frames.values():
        assert x >= 0 and y >= 0 and x + w <= 256 and y + h <= 256
    rectangles = list(frames.values())
    for i, (x, y, w, h) in enumerate(rectangles):
        for xx, yy, ww, hh in rectangles[i + 1:]:
            assert x + w <= xx or xx + ww <= x or y + h <= yy or yy + hh <= y
    data = (SKIN / 'v3_controls.tga').read_bytes()
    # Exact right caps, with no ghost cap at the old 120px boundary.
    for top, height in surface.CONTROL_CELLS:
        if top == 56:
            continue
        assert pixel(data, 119, top + height // 2)[3] == 255
        assert pixel(data, 134, top + height // 2)[3] == 255
        assert pixel(data, 135, top)[3] == 0
        assert all(pixel(data, x, y)[3] == 0
                   for x in range(136, 256) for y in range(top, top + height))
