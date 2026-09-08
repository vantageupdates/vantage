"""Apply the existing HP ramp to native EQType 7's remaining-cast gauge.

The client counts DOWN. Reverse the existing health threshold stack, not the
fill direction: full starts red, the final fifth is green, idle draws no fill.
All colors come from the same precomputed Oklab palette used by health.
This module prints patches; it never writes a skin or reads the game process.
"""
from copy import deepcopy
import difflib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

PALETTE = json.loads(Path(__file__).with_name('ui_health_colors.json').read_text(encoding='utf-8'))
SAMPLES = tuple((s['hp'], tuple(s['rgb'])) for s in PALETTE['samples'])
# Each layer appears just ABOVE its remaining-time threshold. Reversing the
# order alone would start green; associate each reversed boundary with the
# lower completed-progress color instead. The boundary itself retains the
# preceding layer until the native A gauge begins its sub-percent reveal.
LAYERS = tuple((100 - SAMPLES[i][0], SAMPLES[i-1][1])
               for i in range(len(SAMPLES)-1, 0, -1))
PREFIX = 'VantageCast_R'


def item(root, kind, name):
    nodes = root.findall(f"{kind}[@item='{name}']")
    if len(nodes) != 1:
        raise ValueError((kind, name, len(nodes)))
    return nodes[0]


def set_value(node, path, value):
    leaf = node.find(path)
    if leaf is None:
        if '/' in path:
            raise ValueError(path)
        leaf = ET.SubElement(node, path)
    leaf.text = str(value)


def tint(node, color):
    for channel, value in zip('RGB', color):
        set_value(node, 'FillTint/' + channel, value)


def serialize(node):
    node = deepcopy(node)
    node.tail = None
    ET.indent(node, space='  ', level=1)
    return '  ' + ET.tostring(node, encoding='unicode')


def replace_block(text, kind, name, replacement):
    pattern = rf'(?ms)^  <{kind} item="{re.escape(name)}">.*?^  </{kind}>'
    result, count = re.subn(pattern, lambda _: replacement, text)
    if count != 1:
        raise ValueError((kind, name, count))
    return result


def refine(text, animation_text):
    text = text.replace('\r\n', '\n')
    root = ET.fromstring(text)
    if any(n.get('item', '').startswith(PREFIX) for n in root):
        raise ValueError('Cast layers already exist; inspect instead of stacking them again')
    base = deepcopy(item(root, 'Gauge', 'Target_Casting_Gauge'))
    if base.findtext('EQType') != '7':
        raise ValueError('Expected native remaining-cast binding 7')
    parent = deepcopy(item(root, 'Screen', 'TargetWindow'))
    fill = item(ET.fromstring(animation_text), 'Ui2DAnimation',
                base.findtext('GaugeDrawTemplate/Fill'))
    width, height = (int(base.findtext('Size/' + p)) for p in ('CX', 'CY'))
    x, y = (int(base.findtext('Location/' + p)) for p in ('X', 'Y'))
    origin = int(fill.findtext('Frames/Location/X'))
    tint(base, SAMPLES[-1][1])
    definitions, pieces = [], []
    for threshold, color in LAYERS:
        name = f'{PREFIX}{threshold:02}'
        offset, cut = 100 * threshold, width * threshold // 100
        animation = deepcopy(fill)
        animation.set('item', name + 'Fill')
        set_value(animation, 'Cycle', 'false')
        set_value(animation, 'Frames/Location/X', origin - offset)
        set_value(animation, 'Frames/Size/CX', 10000)
        a, b = deepcopy(base), deepcopy(base)
        for suffix, gauge in (('A', a), ('B', b)):
            gauge.set('item', name + suffix)
            screen_id = gauge.find('ScreenID')
            if screen_id is not None:
                gauge.remove(screen_id)
            set_value(gauge, 'Text', '')
            set_value(gauge, 'TextOffsetX', 8000)
            tint(gauge, color)
        set_value(a, 'Location/X', 0)
        set_value(a, 'Location/Y', 0)
        set_value(a, 'Size/CX', 10000 - offset)
        set_value(a, 'GaugeOffsetX', -offset)
        set_value(a, 'GaugeDrawTemplate/Fill', name + 'Fill')
        set_value(b, 'Location/X', x + cut)
        set_value(b, 'Size/CX', width - cut)
        set_value(b, 'GaugeOffsetX', -cut)
        clip = ET.Element('Screen', item=name + 'A_X')
        for tag, value in (('RelativePosition', 'true'), ('Style_Transparent', 'true')):
            ET.SubElement(clip, tag).text = value
        for tag, values in (('Location', {'X': x, 'Y': y}), ('Size', {'CX': cut, 'CY': height})):
            pair = ET.SubElement(clip, tag)
            for key, value in values.items():
                ET.SubElement(pair, key).text = str(value)
        ET.SubElement(clip, 'Pieces').text = name + 'A'
        definitions.extend((animation, a, b, clip))
        pieces.extend((name + 'A_X', name + 'B'))
    original_piece = next(p for p in parent.findall('Pieces') if p.text == base.get('item'))
    insertion = list(parent).index(original_piece) + 1
    for index, name in enumerate(pieces):
        piece = ET.Element('Pieces')
        piece.text = name
        parent.insert(insertion + index, piece)
    text = replace_block(text, 'Gauge', base.get('item'), serialize(base))
    return replace_block(text, 'Screen', parent.get('item'),
                         '\n'.join(map(serialize, definitions + [parent])))


if __name__ == '__main__':
    folder = Path(sys.argv[1])
    path = folder / 'EQUI_TargetWindow.xml'
    original = path.read_text(encoding='ascii')
    revised = refine(original, (folder / 'EQUI_Animations.xml').read_text(encoding='ascii'))
    lines = list(difflib.unified_diff(original.splitlines(), revised.splitlines(), n=3, lineterm=''))
    print('*** Begin Patch')
    print('*** Update File: ' + str(path))
    for line in lines[2:]:
        print('@@' if line.startswith('@@') else line)
    print('*** End Patch')
