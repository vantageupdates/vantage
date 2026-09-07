"""Pure XML refinement of the skin's existing native threshold-gauge technique.

No timers, memory reads or new client bindings. Colors are sampled every 5%
instead of every 20%; this is not a continuously animated color interpolator.
The command prints an apply_patch patch and never writes a skin itself.
"""
from copy import deepcopy
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

STOPS = ((0, (239, 68, 68)), (20, (249, 115, 22)),
         (40, (245, 158, 11)), (60, (240, 220, 0)), (80, (0, 240, 0)))
CONFIGS = {
    'EQUI_PlayerWindow.xml': ('PlayerWindow', ('Player',)),
    'EQUI_GroupWindow.xml': ('GroupWindow', tuple(f'Party{i}' for i in range(1, 6))),
    'EQUI_PetInfoWindow.xml': ('PetInfoWindow', ('Pet',)),
    'EQUI_TargetWindow.xml': ('TargetWindow', ('VantageTarget',)),
}

def color_at(percent):
    percent = max(0, min(80, percent))
    for (left, a), (right, b) in zip(STOPS, STOPS[1:]):
        if percent <= right:
            t = (percent - left) / (right - left)
            return tuple(round(x + (y-x)*t) for x, y in zip(a, b))
    return STOPS[-1][1]

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
        for threshold in range(5, 81, 5):
            if threshold % 20 == 0:
                stage = threshold // 20
                sequence.extend((f'{prefix}_HP_{stage}A_X', f'{prefix}_HP_{stage}B'))
                continue
            name = f'{prefix}_HP_S{threshold:02}'
            animation = deepcopy(anim0)
            animation.set('item', name + 'Fill')
            offset = threshold * 100
            value(animation, 'Frames/Location/X', -offset)
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
        # Declare separators before their consuming window as well.
        tick = block(text, 'StaticAnimation', prefix + '_HP_VantageTicks')
        window = block(text, 'Screen', window_name)
        if tick.start() > window.start():
            definitions.append(item(root, 'StaticAnimation', prefix + '_HP_VantageTicks'))
            text = text[:tick.start()] + text[tick.end():]
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
