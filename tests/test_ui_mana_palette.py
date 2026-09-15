"""Native mana-threshold geometry, palette and accessibility contracts."""

import importlib.util
import math
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
spec = importlib.util.spec_from_file_location('ui_mana_palette', ROOT / 'scripts' / 'ui_mana_palette.py')
palette = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palette)


def item(root, tag, name):
    matches = root.findall(f"{tag}[@item='{name}']")
    assert len(matches) == 1
    return matches[0]


def rect(node):
    return tuple(int(node.findtext(path))
                 for path in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def rgb(node, path='FillTint'):
    return tuple(int(node.findtext(path + '/' + channel)) for channel in 'RGB')


def contrast(left, right):
    def luminance(color):
        values = [value / 255 for value in color]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in values]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    darker, lighter = sorted((luminance(left), luminance(right)))
    return (lighter + .05) / (darker + .05)


def test_palette_is_dense_oklab_blue_first_and_reserves_red_for_critical_mana():
    assert palette.THRESHOLDS == tuple(range(0, 100, 5))
    assert len(palette.COLORS) == len(set(palette.COLORS.values())) == 20
    assert palette.COLORS[0] == (239, 68, 68)
    assert palette.COLORS[95] == palette.CURRENT_BLUE == (57, 169, 255)
    assert palette.COLORS[20] == (140, 113, 240)
    assert palette.COLORS[30] == (65, 125, 245)
    assert all(blue > red and blue > green
               for threshold, (red, green, blue) in palette.COLORS.items()
               if threshold >= 20)
    assert all(red > blue for threshold, (red, _, blue) in palette.COLORS.items()
               if threshold <= 10)
    deltas = []
    colors = list(palette.COLORS.values())
    for before, after in zip(colors, colors[1:]):
        first, second = palette.to_oklab(before), palette.to_oklab(after)
        deltas.append(math.sqrt(sum((left - right) ** 2 for left, right in zip(first, second))))
    assert max(deltas) < 0.09, 'No abrupt critical-state jump'
    assert all(0 <= component <= 255 for color in colors for component in color)


def test_native_mana_binding_geometry_template_and_numeric_label_are_preserved():
    root = ET.parse(SKIN / 'EQUI_PlayerWindow.xml').getroot()
    base = item(root, 'Gauge', 'Player_Mana')
    label = item(root, 'Label', 'Player_ManaLabel')
    window = item(root, 'Screen', 'PlayerWindow')
    pieces = [piece.text for piece in window.findall('Pieces')]
    assert base.findtext('ScreenID') == 'PlayerMana'
    assert base.findtext('EQType') == '2'
    assert base.findtext('RelativePosition') == 'true'
    assert rect(base) == (20, 44, 240, 11)
    assert base.findtext('GaugeOffsetY') == '0'
    assert base.findtext('Style_VScroll') == 'false'
    assert base.findtext('Style_HScroll') == 'false'
    assert base.findtext('Style_Transparent') == 'false'
    assert base.findtext('DrawLinesFill') == 'false'
    draw = base.find('GaugeDrawTemplate')
    assert [(child.tag, child.text) for child in draw] == [
        ('Background', 'A_dzThinLongBackground'),
        ('Fill', 'A_dzThinLongFill'),
        ('Lines', 'A_dzThinLongLines'),
    ]
    assert label.findtext('ScreenID') == 'ManaLabel'
    assert label.findtext('EQType') == '20'
    assert label.findtext('Font') == '1'
    assert label.findtext('RelativePosition') == 'true'
    assert rect(label) == (1, 44, 18, 12)
    assert label.findtext('Text') == '100'
    assert rgb(label, 'TextColor') == (26, 159, 255)
    assert label.findtext('NoWrap') == 'true'
    assert label.findtext('AlignRight') == 'true'
    assert pieces.count('Player_Mana') == pieces.count('Player_ManaLabel') == 1
    assert pieces.index('Player_ManaLabel') > pieces.index('Player_Mana_S95B')


def test_every_threshold_layer_uses_native_binding_and_exact_clip_geometry():
    root = ET.parse(SKIN / 'EQUI_PlayerWindow.xml').getroot()
    window = item(root, 'Screen', 'PlayerWindow')
    pieces = [piece.text for piece in window.findall('Pieces')]
    order = {node.get('item'): index for index, node in enumerate(root)}
    expected = ['Player_Mana']
    for threshold in palette.THRESHOLDS[1:]:
        name = f'Player_Mana_S{threshold:02}'
        expected.extend((name + 'A_X', name + 'B'))
        animation = item(root, 'Ui2DAnimation', name + 'Fill')
        left = item(root, 'Gauge', name + 'A')
        right = item(root, 'Gauge', name + 'B')
        clip = item(root, 'Screen', name + 'A_X')
        cut = 240 * threshold // 100
        assert rect(left) == (0, 0, 10000 - 100 * threshold, 11)
        assert rect(right) == (20 + cut, 44, 240 - cut, 11)
        assert rect(clip) == (20, 44, cut, 11)
        assert left.findtext('GaugeOffsetX') == str(-100 * threshold)
        assert right.findtext('GaugeOffsetX') == str(-cut)
        assert clip.findtext('Pieces') == name + 'A'
        assert clip.findtext('Style_Transparent') == 'true'
        assert animation.findtext('Cycle') == 'false'
        assert animation.findtext('Frames/Texture') == 'dzbars.png'
        assert animation.findtext('Frames/Location/X') == str(-100 * threshold)
        assert animation.findtext('Frames/Location/Y') == '200'
        assert tuple(int(animation.findtext('Frames/Size/' + axis)) for axis in ('CX', 'CY')) == (10000, 11)
        assert order[name + 'Fill'] < order[name + 'A'] < order[name + 'A_X'] < order['PlayerWindow']
        for gauge, fill in ((left, name + 'Fill'), (right, 'A_dzThinLongFill')):
            assert gauge.find('ScreenID') is None
            assert gauge.findtext('EQType') == '2'
            assert gauge.findtext('TextOffsetX') == '8000'
            assert gauge.findtext('DrawLinesFill') == 'false'
            assert [(child.tag, child.text) for child in gauge.find('GaugeDrawTemplate')] == [('Fill', fill)]
            assert rgb(gauge) == palette.COLORS[threshold]
    start = pieces.index('Player_Mana')
    assert pieces[start:start + len(expected)] == expected
    assert len(pieces) == 92
    assert len(pieces) < 100, 'Stay below the denser native Inventory and Group screens'
    assert palette.refine((SKIN / 'EQUI_PlayerWindow.xml').read_text(encoding='ascii')) == (
        SKIN / 'EQUI_PlayerWindow.xml').read_text(encoding='ascii').replace('\r\n', '\n')


def test_render_model_never_paints_past_live_mana_or_creates_a_spatial_rainbow():
    width = 240
    for mana in range(101):
        end = width * mana // 100
        pixels = [palette.COLORS[0]] * end + [None] * (width - end)
        for threshold in palette.THRESHOLDS[1:]:
            cut = width * threshold // 100
            left_end = max(0, min(cut, 100 * mana - 100 * threshold))
            for x in range(left_end):
                assert x < end
                pixels[x] = palette.COLORS[threshold]
            for x in range(cut, end):
                pixels[x] = palette.COLORS[threshold]
        assert all(color is None for color in pixels[end:])
        if end:
            visible = set(pixels[:end])
            assert len(visible) <= 2, 'Never expose a multi-band spatial rainbow'
            if len(visible) == 2:
                indices = sorted(list(palette.COLORS.values()).index(color) for color in visible)
                assert indices[1] - indices[0] == 1, 'Only neighboring states may share the short wipe'
        else:
            assert all(color is None for color in pixels)
    assert all(color == palette.COLORS[95] for color in pixels)


def test_every_modeled_fill_state_has_structural_contrast_and_a_numeric_backup():
    # dzbars.png rows 202..208 are the visible grayscale fill; rows 213..219
    # are the adjacent empty-track pixels. Model the native multiplicative tint.
    fill_shades = (238, 245, 245, 239, 228, 215, 200)
    track = ((11, 16, 21), (14, 18, 22), (14, 19, 23), (15, 19, 24),
             (16, 20, 25), (19, 23, 28), (21, 25, 30))
    for color in palette.COLORS.values():
        for shade, background in zip(fill_shades, track):
            rendered = tuple(round(component * shade / 255) for component in color)
            assert contrast(rendered, background) >= 3
    root = ET.parse(SKIN / 'EQUI_PlayerWindow.xml').getroot()
    label = item(root, 'Label', 'Player_ManaLabel')
    assert label.findtext('EQType') == '20' and label.findtext('Text') == '100'
