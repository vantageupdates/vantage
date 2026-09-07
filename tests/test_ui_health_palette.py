"""Native threshold geometry, texture origins and live fill regression checks."""
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
spec = importlib.util.spec_from_file_location('ui_health_palette', ROOT / 'scripts' / 'ui_health_palette.py')
palette = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palette)


def rect(node):
    return tuple(int(node.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def layer(prefix, hp):
    return f'{prefix}_HP_{hp // 20}' if hp % 20 == 0 else f'{prefix}_HP_S{hp:02}'


def test_palette_is_dense_in_the_former_green_yellow_jump_and_keeps_anchors():
    assert palette.THRESHOLDS == (*range(0, 61, 5), *range(62, 81, 2))
    assert len(palette.COLORS) == len(set(palette.COLORS.values())) == 23
    assert palette.PALETTE['interpolation'] == 'oklab'
    assert palette.PALETTE['gamut'] == 'srgb'
    assert all(palette.color_at(hp) == rgb for hp, rgb in palette.STOPS)
    assert palette.color_at(-1) == (239, 68, 68)
    assert palette.color_at(100) == (0, 240, 0)
    assert palette.color_at(70) == (169, 232, 0)  # Computed Oklab sample, not RGB midpoint.
    assert palette.color_at(78) == (76, 239, 0)
    colors = list(palette.COLORS.values())
    assert all(0 <= channel <= 255 for color in colors for channel in color)
    # Reject the old 240-channel jump without a color-library runtime dependency.
    jumps = [max(abs(a-b) for a,b in zip(left,right)) for left,right in zip(colors,colors[1:])]
    assert max(jumps) <= 76
    assert all(colors[i][1] <= colors[i+1][1] for i in range(len(colors)-1))


@pytest.mark.parametrize('filename', palette.CONFIGS)
def test_every_intermediate_layer_preserves_native_binding_origin_and_clipping(filename):
    text = (SKIN / filename).read_text(encoding='ascii')
    root = ET.fromstring(text)
    parent_name, prefixes = palette.CONFIGS[filename]
    parent = palette.item(root, 'Screen', parent_name)
    pieces = [p.text for p in parent.findall('Pieces')]
    order = {n.get('item'): i for i,n in enumerate(root)}
    for prefix in prefixes:
        base = palette.item(root, 'Gauge', prefix + '_HP_0')
        x,y,width,height = rect(base)
        template = palette.item(root, 'Gauge', prefix + '_HP_1A')
        base_anim = palette.item(root, 'Ui2DAnimation', template.findtext('GaugeDrawTemplate/Fill'))
        origin = int(base_anim.findtext('Frames/Location/X')) + 2000
        assert origin == (2 if filename in ('EQUI_GroupWindow.xml', 'EQUI_PetInfoWindow.xml') else 0)
        expected = [prefix + '_HP_0']
        for hp in palette.THRESHOLDS[1:]:
            name = layer(prefix, hp)
            expected.extend((name + 'A_X', name + 'B'))
            if hp % 20 == 0:
                continue
            a = palette.item(root, 'Gauge', name + 'A')
            b = palette.item(root, 'Gauge', name + 'B')
            clip = palette.item(root, 'Screen', name + 'A_X')
            anim = palette.item(root, 'Ui2DAnimation', name + 'Fill')
            cut = width * hp // 100
            assert rect(clip) == (x,y,cut,height)
            assert rect(a) == (0,0,10000-100*hp,height)
            assert rect(b) == (x+cut,y,width-cut,height)
            assert a.findtext('GaugeOffsetX') == str(-100*hp)
            assert b.findtext('GaugeOffsetX') == str(-cut)
            assert clip.findtext('Pieces') == name + 'A'
            assert clip.findtext('Style_Transparent') == 'true'
            assert anim.findtext('Frames/Location/X') == str(origin - 100*hp)
            assert anim.findtext('Frames/Location/Y') == base_anim.findtext('Frames/Location/Y')
            assert anim.findtext('Frames/Texture') == base_anim.findtext('Frames/Texture')
            assert anim.findtext('Cycle') == 'false' and len(anim.findall('Frames')) == 1
            assert order[name + 'Fill'] < order[name + 'A'] < order[name + 'A_X'] < order[parent_name]
            for gauge in (a,b):
                assert gauge.findtext('EQType') == base.findtext('EQType')
                assert gauge.findtext('DrawLinesFill') == 'false'
                assert [n.tag for n in gauge.find('GaugeDrawTemplate')] == ['Fill']
                assert tuple(int(gauge.findtext('FillTint/'+c)) for c in 'RGB') == palette.COLORS[hp]
        assert all(pieces.count(name) == 1 for name in expected)
        assert [p for p in pieces if p in expected] == expected
        assert pieces.index(expected[-1]) < pieces.index(prefix + '_HealthDetail')
        assert not any(p == prefix + '_HP_VantageTicks' for p in pieces)
    assert palette.refine(text, filename) == text.replace('\r\n', '\n')


@pytest.mark.parametrize('width', (100, 240))
def test_native_threshold_model_never_paints_beyond_live_hp_or_into_empty_groups(width):
    # Geometry model only: a native gauge's usable span is CX - GaugeOffsetX.
    # Test every integer HP, not just endpoints; this is not a game renderer.
    for hp in range(101):
        end = width * hp // 100
        pixels = [palette.COLORS[0]] * end + [None] * (width-end)
        for threshold in palette.THRESHOLDS[1:]:
            cut = width * threshold // 100
            left_end = max(0, min(cut, 100*hp - 100*threshold))
            for x in range(left_end):
                assert x < end
                pixels[x] = palette.COLORS[threshold]
            for x in range(cut, end):
                pixels[x] = palette.COLORS[threshold]
        assert all(color is None for color in pixels[end:])
        if hp == 0:
            assert all(color is None for color in pixels)
        if hp == 100:
            assert all(color == (0,240,0) for color in pixels)
