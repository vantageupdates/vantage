"""Pure XML refinement of the skin's existing native threshold-gauge technique.

No timers, memory reads or new client bindings. Uses 23 precomputed perceptual
colors: 5% steps up to yellow, then finer 2% steps to high-health green.
This is not a continuously time-animated color interpolator.
The command prints an apply_patch patch and never writes a skin itself.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

STOPS = ((0, (239, 68, 68)), (20, (249, 115, 22)),
         (40, (245, 158, 11)), (60, (240, 220, 0)), (80, (0, 240, 0)))
PALETTE = json.loads(Path(__file__).with_name('ui_health_colors.json').read_text(encoding='utf-8'))
COLORS = {sample['hp']: tuple(sample['rgb']) for sample in PALETTE['samples']}
THRESHOLDS = tuple(COLORS)
CONFIGS = {
    'EQUI_PlayerWindow.xml': ('PlayerWindow', ('Player',)),
    'EQUI_GroupWindow.xml': ('GroupWindow', tuple(f'Party{i}' for i in range(1, 6))),
    'EQUI_PetInfoWindow.xml': ('PetInfoWindow', ('Pet',)),
    'EQUI_TargetWindow.xml': ('TargetWindow', ('VantageTarget',)),
}

def color_at(percent):
    """Color selected by the palette; native reveal can span a sub-percent."""
    threshold = max(hp for hp in THRESHOLDS if hp <= max(0, min(100, percent)))
    return COLORS[threshold]

def item(root, tag, name):
    matches = root.findall(f"{tag}[@item='{name}']")
    if len(matches) != 1:
        raise ValueError((tag, name, len(matches)))
    return matches[0]

def value(node, path, text):
    target = node.find(path)
    if target is None:
        raise ValueError(path)
    target.text = str(text)

def serialize(node):
    node = deepcopy(node)
    node.tail = None
    ET.indent(node, space='  ', level=1)
    return '  ' + ET.tostring(node, encoding='unicode')

def block(text, tag, name):
    match = re.search(rf'(?ms)^  <{tag} item="{re.escape(name)}">.*?^  </{tag}>', text)
    if match is None:
        raise ValueError(name)
    return match

def refine(text, filename):
    text = text.replace('\r\n', '\n')
    root = ET.fromstring(text)
    window_name, prefixes = CONFIGS[filename]
    if any(n.get('item', '').endswith('_HP_S05A') for n in root):
        for prefix in prefixes:
            for threshold in THRESHOLDS[1:]:
                if threshold % 20:
                    gauge = item(root, 'Gauge', f'{prefix}_HP_S{threshold:02}A')
                    if tuple(int(gauge.findtext('FillTint/' + c)) for c in 'RGB') != COLORS[threshold]:
                        raise ValueError('Existing intermediate palette differs; review before editing')
        return text
    parent = deepcopy(item(root, 'Screen', window_name))
    definitions = []
    for prefix in prefixes:
        base = item(root, 'Gauge', prefix + '_HP_0')
        a0 = item(root, 'Gauge', prefix + '_HP_1A')
        b0 = item(root, 'Gauge', prefix + '_HP_1B')
        clip0 = item(root, 'Screen', prefix + '_HP_1A_X')
        anim0 = item(root, 'Ui2DAnimation', a0.findtext('GaugeDrawTemplate/Fill'))
        width = int(base.findtext('Size/CX'))
        x = int(base.findtext('Location/X'))
        sequence = [prefix + '_HP_0']
        for threshold in THRESHOLDS[1:]:
            if threshold % 20 == 0:
                stage = threshold // 20
                sequence.extend((f'{prefix}_HP_{stage}A_X', f'{prefix}_HP_{stage}B'))
                continue
            name = f'{prefix}_HP_S{threshold:02}'
            animation = deepcopy(anim0)
            animation.set('item', name + 'Fill')
            offset = threshold * 100
            # Group/pet textures begin at X=2, unlike the player/target's X=0.
            # Preserve that origin; the old 5% experiment incorrectly erased it.
            texture_origin = int(anim0.findtext('Frames/Location/X')) + 2000
            value(animation, 'Frames/Location/X', texture_origin - offset)
            value(animation, 'Cycle', 'false')
            a, b, clip = deepcopy(a0), deepcopy(b0), deepcopy(clip0)
            a.set('item', name + 'A')
            b.set('item', name + 'B')
            clip.set('item', name + 'A_X')
            value(a, 'Size/CX', 10000 - offset)
            value(a, 'GaugeOffsetX', -offset)
            value(a, 'GaugeDrawTemplate/Fill', animation.get('item'))
            cut = width * threshold // 100
            value(b, 'Location/X', x + cut)
            value(b, 'Size/CX', width - cut)
            value(b, 'GaugeOffsetX', -cut)
            value(clip, 'Size/CX', cut)
            value(clip, 'Pieces', a.get('item'))
            for gauge in (a, b):
                for channel, color in zip('RGB', color_at(threshold)):
                    value(gauge, 'FillTint/' + channel, color)
            definitions.extend((animation, a, b, clip))
            sequence.extend((clip.get('item'), b.get('item')))
        old_pieces = [p for p in parent.findall('Pieces')
                      if p.text == prefix + '_HP_0' or re.fullmatch(
                          re.escape(prefix) + r'_HP_[1-4](A_X|B)', p.text or '')]
        if len(old_pieces) != 9:
            raise ValueError('Unexpected native layer membership: ' + prefix)
        insertion = list(parent).index(old_pieces[0])
        for piece in old_pieces:
            parent.remove(piece)
        for index, name in enumerate(sequence):
            piece = ET.Element('Pieces')
            piece.text = name
            parent.insert(insertion + index, piece)
    match = block(text, 'Screen', window_name)
    replacement = '\n'.join(map(serialize, definitions + [parent]))
    return text[:match.start()] + replacement + text[match.end():]

if __name__ == '__main__':
    import difflib
    folder = Path(sys.argv[1])
    filename = sys.argv[2]
    original = (folder / filename).read_text(encoding='ascii')
    revised = refine(original, filename)
    diff = list(difflib.unified_diff(original.splitlines(), revised.splitlines(), n=3, lineterm=''))
    print('*** Begin Patch')
    print('*** Update File: ' + str(folder / filename))
    for line in diff[2:]:
        print('@@' if line.startswith('@@') else line)
    print('*** End Patch')
