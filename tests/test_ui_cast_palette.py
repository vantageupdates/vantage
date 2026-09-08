"""Cast countdown colors, native clipping and preservation of surrounding UI."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
spec = importlib.util.spec_from_file_location('ui_cast_palette', ROOT / 'scripts' / 'ui_cast_palette.py')
cast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cast)


def rect(node):
    return tuple(int(node.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def rgb(node):
    return tuple(int(node.findtext('FillTint/' + c)) for c in 'RGB')


def test_cast_reuses_all_23_health_samples_in_countdown_order():
    assert len(cast.LAYERS) == 22
    assert tuple(t for t, _ in cast.LAYERS) == (*range(20, 41, 2), *range(45, 96, 5))
    assert (cast.SAMPLES[-1][1], *(c for _, c in cast.LAYERS)) == tuple(c for _, c in reversed(cast.SAMPLES))
    assert cast.SAMPLES[-1][1] == (0, 240, 0)
    assert cast.LAYERS[-1][1] == (239, 68, 68)


def test_all_cast_layers_preserve_binding_texture_origin_size_and_draw_order():
    root = ET.parse(SKIN / 'EQUI_TargetWindow.xml').getroot()
    parent = cast.item(root, 'Screen', 'TargetWindow')
    base = cast.item(root, 'Gauge', 'Target_Casting_Gauge')
    label = cast.item(root, 'Label', 'Target_Casting_SpellName')
    assert rect(base) == (20, 43, 240, 11)
    assert rect(label) == (21, 41, 238, 15)
    assert label.findtext('EQType') == '134'
    assert base.findtext('ScreenID') == 'Gauge'
    assert base.findtext('GaugeDrawTemplate/Fill') == 'A_dzThinLongFill'
    assert rgb(base) == cast.SAMPLES[-1][1]
    order = {n.get('item'): i for i, n in enumerate(root)}
    pieces = [p.text for p in parent.findall('Pieces')]
    sequence = [base.get('item')]
    for threshold, color in cast.LAYERS:
        name, cut = f'{cast.PREFIX}{threshold:02}', 240 * threshold // 100
        a = cast.item(root, 'Gauge', name + 'A')
        b = cast.item(root, 'Gauge', name + 'B')
        clip = cast.item(root, 'Screen', name + 'A_X')
        animation = cast.item(root, 'Ui2DAnimation', name + 'Fill')
        assert rect(a) == (0, 0, 10000 - threshold * 100, 11)
        assert rect(b) == (20 + cut, 43, 240 - cut, 11)
        assert rect(clip) == (20, 43, cut, 11)
        assert clip.findtext('Style_Transparent') == 'true'
        assert clip.findtext('Pieces') == name + 'A'
        assert animation.findtext('Frames/Location/X') == str(-threshold * 100)
        assert animation.findtext('Frames/Location/Y') == '200'
        assert animation.findtext('Frames/Texture') == 'dzbars.png'
        assert animation.findtext('Frames/Size/CX') == '10000'
        assert animation.findtext('Frames/Size/CY') == '11'
        assert animation.findtext('Cycle') == 'false'
        assert len(animation.findall('Frames')) == 1
        assert a.findtext('GaugeOffsetX') == str(-threshold * 100)
        assert b.findtext('GaugeOffsetX') == str(-cut)
        for gauge in (a, b):
            assert gauge.findtext('EQType') == '7'
            assert gauge.find('ScreenID') is None
            assert gauge.findtext('DrawLinesFill') == 'false'
            assert [n.tag for n in gauge.find('GaugeDrawTemplate')] == ['Fill']
            assert rgb(gauge) == color
        assert order[name + 'Fill'] < order[name + 'A'] < order[name + 'A_X'] < order['TargetWindow']
        sequence.extend((name + 'A_X', name + 'B'))
    start = pieces.index(base.get('item'))
    assert pieces[start:start + len(sequence)] == sequence
    assert pieces[start + len(sequence)] == 'Target_Casting_SpellName'
    assert all(pieces.count(p) == 1 for p in sequence)
    # No floating countdown window and no timers: keep the native hidden stub.
    hidden = cast.item(ET.parse(SKIN / 'EQUI_CastingWindow.xml').getroot(), 'Screen', 'CastingWindow')
    assert hidden.findtext('Size/CX') == hidden.findtext('Size/CY') == '0'


def model_pixels(remaining):
    """Existing paired-gauge geometry model, not the native game renderer."""
    width = 240
    end = width * remaining // 100
    pixels = [cast.SAMPLES[-1][1]] * end + [None] * (width - end)
    for threshold, color in cast.LAYERS:
        cut = width * threshold // 100
        left_end = max(0, min(cut, 100 * remaining - 100 * threshold))
        for x in range(left_end):
            assert x < end
            pixels[x] = color
        for x in range(cut, end):
            pixels[x] = color
    return pixels


@pytest.mark.parametrize('remaining', range(101))
def test_countdown_never_paints_past_live_fill_or_leaves_idle_color(remaining):
    pixels = model_pixels(remaining)
    end = 240 * remaining // 100
    assert all(c is None for c in pixels[end:])
    assert all(c is not None for c in pixels[:end])
    if remaining == 0:
        assert all(c is None for c in pixels)
    elif remaining == 100:
        assert set(pixels) == {(239, 68, 68)}
    elif remaining <= 20:
        assert set(pixels[:end]) == {(0, 240, 0)}


def test_countdown_reveals_every_intermediate_color_in_the_requested_direction():
    visible = []
    for remaining in range(100, 0, -1):
        color = model_pixels(remaining)[0]
        if not visible or color != visible[-1]:
            visible.append(color)
    assert visible == [color for _, color in cast.SAMPLES]


def test_generator_changes_only_cast_binding_color_and_its_added_pieces():
    text = (SKIN / 'EQUI_TargetWindow.xml').read_text(encoding='ascii')
    root = ET.fromstring(text)
    # Reconstruct the pre-change target; every unrelated subtree must survive.
    for node in list(root):
        if node.get('item', '').startswith(cast.PREFIX):
            root.remove(node)
    parent = cast.item(root, 'Screen', 'TargetWindow')
    for piece in list(parent.findall('Pieces')):
        if piece.text.startswith(cast.PREFIX):
            parent.remove(piece)
    cast.tint(cast.item(root, 'Gauge', 'Target_Casting_Gauge'), (241, 184, 75))
    ET.indent(root, space='  ')
    source = ET.tostring(root, encoding='unicode')
    regenerated = cast.refine(source, (SKIN / 'EQUI_Animations.xml').read_text(encoding='ascii'))
    rebuilt = ET.fromstring(regenerated)
    for node in root:
        name = node.get('item')
        if not name or name in ('Target_Casting_Gauge', 'TargetWindow'):
            continue
        left, right = deepcopy(node), deepcopy(cast.item(rebuilt, node.tag, name))
        left.tail = right.tail = None
        ET.indent(left)
        ET.indent(right)
        assert ET.tostring(left) == ET.tostring(right), name
    with pytest.raises(ValueError, match='already exist'):
        cast.refine(text, (SKIN / 'EQUI_Animations.xml').read_text(encoding='ascii'))
