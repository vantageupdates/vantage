"""Inventory EXP must DRAW to the value column edge, not merely reserve width."""
from pathlib import Path
import hashlib
import importlib.util
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
spec = importlib.util.spec_from_file_location('inventory_exp', ROOT / 'scripts/ui_inventory_exp.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def node(kind, name):
    result = ET.parse(SKIN / 'EQUI_Inventory.xml').getroot().find(f"{kind}[@item='{name}']")
    assert result is not None
    return result


@pytest.mark.parametrize('part', renderer.PARTS)
def test_every_native_layer_reaches_the_same_right_edge_as_resource_values(part):
    gauge = node('Gauge', 'IW_ExpGauge')
    name = gauge.findtext('GaugeDrawTemplate/' + part)
    assert name == 'A_VantageInventoryExp' + part
    animation = node('Ui2DAnimation', name)
    frame = animation.find('Frames')
    assert animation.findtext('Cycle') == 'false'
    assert frame.findtext('Texture') == 'VantageInventoryExp.tga'
    assert (int(frame.findtext('Size/CX')), int(frame.findtext('Size/CY'))) == (118, 8)
    assert (int(frame.findtext('Location/X')), int(frame.findtext('Location/Y'))) == (2, 2 + 12 * renderer.PARTS.index(part))
    assert int(gauge.findtext('Location/X')) + int(frame.findtext('Size/CX')) == 372
    assert int(gauge.findtext('Size/CX')) == int(frame.findtext('Size/CX'))
    for value in ('IW_CurrentHP', 'IW_MANANumber', 'IW_EXP_Percentage'):
        label = node('Label', value)
        assert int(label.findtext('Location/X')) + int(label.findtext('Size/CX')) == 372


def test_atlas_is_deterministic_and_shared_art_is_unchanged():
    source = SKIN / 'window_pieces01.tga'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '39077fbb9da9c5a5101eb11212cbe4a440eca56aeacdc6be42eda931e8927a2e'
    data = (SKIN / 'VantageInventoryExp.tga').read_bytes()
    assert data == renderer.render(source)
    assert len(data) == 18 + 128 * 64 * 4
    assert data[2] == 2 and data[12:18] == bytes((128, 0, 64, 0, 32, 40))
    for y in range(64):
        for x in range(128):
            used = 2 <= x < 120 and any(2 + 12 * i <= y < 10 + 12 * i for i in range(4))
            if not used:
                assert data[18 + (y * 128 + x) * 4:22 + (y * 128 + x) * 4] == bytes(4)


@pytest.mark.parametrize('part', range(4))
def test_original_height_shading_alpha_and_end_caps_are_preserved(part):
    original = renderer.read_tga(SKIN / 'window_pieces01.tga')
    expanded = renderer.read_tga(SKIN / 'VantageInventoryExp.tga')
    for y in range(8):
        for x in range(118):
            source_x = (x * 99 + 58) // 117
            assert expanded[2 + part * 12 + y][2 + x] == original[10 + part * 10 + y][110 + source_x]


def test_native_experience_binding_and_colors_are_unchanged():
    gauge = node('Gauge', 'IW_ExpGauge')
    assert gauge.findtext('EQType') == '4'
    assert gauge.findtext('ScreenID') == 'ExpGauge'
    assert gauge.findtext('DrawLinesFill') == 'true'
    assert tuple(int(gauge.findtext('FillTint/' + c)) for c in 'RGB') == (241, 184, 75)
    assert tuple(int(gauge.findtext('LinesFillTint/' + c)) for c in 'RGB') == (0, 80, 220)


def test_old_shared_frames_reproduce_the_eighteen_pixel_shortfall():
    animations = ET.parse(SKIN / 'EQUI_Animations.xml').getroot()
    for part in renderer.PARTS:
        old = animations.find(f"Ui2DAnimation[@item='A_Gauge{part}']")
        assert 372 - (254 + int(old.findtext('Frames/Size/CX'))) == 18
