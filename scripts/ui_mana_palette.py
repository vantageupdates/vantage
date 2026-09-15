"""Generate a native threshold palette for PlayerWindow's real mana gauge.

The Titanium client supplies the live EQType 2 value.  Layered native Gauges
reuse that binding to recolor only the filled span; this is not a spatial
gradient and never paints the empty track.  By default the command prints an
apply_patch patch; ``--write`` applies the same deterministic refinement.
"""

from copy import deepcopy
import difflib
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


THRESHOLDS = tuple(range(0, 100, 5))
CURRENT_BLUE = (57, 169, 255)
ANCHORS = (
    (0, (239, 68, 68)),       # Final critical band only.
    (10, (216, 91, 165)),     # Short red-violet bridge.
    (20, (140, 113, 240)),    # Blue-violet near critical.
    (30, (65, 125, 245)),     # Deep saturated blue.
    (50, (48, 140, 248)),
    (70, (43, 151, 250)),
    (90, (52, 164, 253)),
    (95, CURRENT_BLUE),        # Preserve the existing calm high-mana blue.
)


def _linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _srgb(channel):
    channel = max(0.0, min(1.0, channel))
    encoded = 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return round(encoded * 255)


def _cuberoot(value):
    """Portable real cube root; math.cbrt is unavailable on Python 3.8-3.10."""
    return math.copysign(abs(value) ** (1 / 3), value)


def to_oklab(rgb):
    red, green, blue = map(_linear, rgb)
    light = _cuberoot(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue)
    medium = _cuberoot(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue)
    short = _cuberoot(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue)
    return (
        0.2104542553 * light + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * light - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * light + 0.7827717662 * medium - 0.8086757660 * short,
    )


def from_oklab(oklab):
    lightness, green_red, blue_yellow = oklab
    light = (lightness + 0.3963377774 * green_red + 0.2158037573 * blue_yellow) ** 3
    medium = (lightness - 0.1055613458 * green_red - 0.0638541728 * blue_yellow) ** 3
    short = (lightness - 0.0894841775 * green_red - 1.2914855480 * blue_yellow) ** 3
    return (
        _srgb(+4.0767416621 * light - 3.3077115913 * medium + 0.2309699292 * short),
        _srgb(-1.2684380046 * light + 2.6097574011 * medium - 0.3413193965 * short),
        _srgb(-0.0041960863 * light - 0.7034186147 * medium + 1.7076147010 * short),
    )


def color_at(percent):
    percent = max(0, min(95, percent))
    for index, (right_percent, right_rgb) in enumerate(ANCHORS):
        if percent == right_percent:
            return right_rgb
        if percent < right_percent:
            left_percent, left_rgb = ANCHORS[index - 1]
            amount = (percent - left_percent) / (right_percent - left_percent)
            left = to_oklab(left_rgb)
            right = to_oklab(right_rgb)
            return from_oklab(tuple(a + (b - a) * amount for a, b in zip(left, right)))
    return CURRENT_BLUE


COLORS = {threshold: color_at(threshold) for threshold in THRESHOLDS}


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


def set_rgb(node, path, color):
    for channel, component in zip('RGB', color):
        value(node, path + '/' + channel, component)


def ensure_before(node, before_tag, tag, text):
    target = node.find(tag)
    if target is None:
        before = node.find(before_tag)
        if before is None:
            raise ValueError(before_tag)
        target = ET.Element(tag)
        node.insert(list(node).index(before), target)
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


def animation(name, threshold, height):
    offset = threshold * 100
    return ET.fromstring(f'''<Ui2DAnimation item="{name}Fill">
  <Cycle>false</Cycle>
  <Frames>
    <Texture>dzbars.png</Texture>
    <Location><X>{-offset}</X><Y>200</Y></Location>
    <Size><CX>10000</CX><CY>{height}</CY></Size>
    <Hotspot><X>0</X><Y>0</Y></Hotspot>
    <Duration>1000</Duration>
  </Frames>
</Ui2DAnimation>''')


def clip_screen(name, x, y, width, height):
    return ET.fromstring(f'''<Screen item="{name}A_X">
  <RelativePosition>true</RelativePosition>
  <Location><X>{x}</X><Y>{y}</Y></Location>
  <Size><CX>{width}</CX><CY>{height}</CY></Size>
  <Style_Transparent>true</Style_Transparent>
  <Pieces>{name}A</Pieces>
</Screen>''')


def recolor_gauge(base, name, color, *, left, top, width, height, gauge_offset, fill):
    gauge = deepcopy(base)
    gauge.set('item', name)
    screen_id = gauge.find('ScreenID')
    if screen_id is not None:
        gauge.remove(screen_id)
    value(gauge, 'Location/X', left)
    value(gauge, 'Location/Y', top)
    value(gauge, 'Size/CX', width)
    value(gauge, 'Size/CY', height)
    ensure_before(gauge, 'GaugeOffsetY', 'GaugeOffsetX', gauge_offset)
    ensure_before(gauge, 'Style_VScroll', 'TextOffsetX', 8000)
    set_rgb(gauge, 'FillTint', color)
    set_rgb(gauge, 'LinesFillTint', (0, 0, 0))
    draw = gauge.find('GaugeDrawTemplate')
    if draw is None:
        raise ValueError('GaugeDrawTemplate')
    draw.clear()
    ET.SubElement(draw, 'Fill').text = fill
    return gauge


def _validate_existing(root):
    base = item(root, 'Gauge', 'Player_Mana')
    if tuple(int(base.findtext('FillTint/' + channel)) for channel in 'RGB') != COLORS[0]:
        raise ValueError('Existing Player_Mana base color differs; review before editing')
    parent = item(root, 'Screen', 'PlayerWindow')
    pieces = [piece.text for piece in parent.findall('Pieces')]
    expected = ['Player_Mana']
    for threshold in THRESHOLDS[1:]:
        name = f'Player_Mana_S{threshold:02}'
        expected.extend((name + 'A_X', name + 'B'))
        for suffix in ('A', 'B'):
            gauge = item(root, 'Gauge', name + suffix)
            if tuple(int(gauge.findtext('FillTint/' + channel)) for channel in 'RGB') != COLORS[threshold]:
                raise ValueError('Existing mana palette differs; review before editing')
    start = pieces.index('Player_Mana')
    if pieces[start:start + len(expected)] != expected:
        raise ValueError('Existing mana layer order differs; review before editing')


def refine(text):
    text = text.replace('\r\n', '\n')
    root = ET.fromstring(text)
    if root.find("Gauge[@item='Player_Mana_S05A']") is not None:
        _validate_existing(root)
        return text

    eqtype_two = [gauge for gauge in root.findall('Gauge') if gauge.findtext('EQType') == '2']
    if len(eqtype_two) != 1 or eqtype_two[0].get('item') != 'Player_Mana':
        raise ValueError('Expected exactly one original EQType 2 mana gauge')
    base = deepcopy(eqtype_two[0])
    original_fill = base.findtext('GaugeDrawTemplate/Fill')
    if original_fill != 'A_dzThinLongFill':
        raise ValueError('Unexpected native mana Fill animation')
    x = int(base.findtext('Location/X'))
    y = int(base.findtext('Location/Y'))
    width = int(base.findtext('Size/CX'))
    height = int(base.findtext('Size/CY'))
    set_rgb(base, 'FillTint', COLORS[0])

    parent = deepcopy(item(root, 'Screen', 'PlayerWindow'))
    pieces = [piece.text for piece in parent.findall('Pieces')]
    if pieces.count('Player_Mana') != 1:
        raise ValueError('Unexpected Player_Mana membership')
    insertion = next(i for i, child in enumerate(parent) if child.tag == 'Pieces' and child.text == 'Player_Mana') + 1
    definitions = []
    for threshold in THRESHOLDS[1:]:
        name = f'Player_Mana_S{threshold:02}'
        offset = threshold * 100
        cut = width * threshold // 100
        anim = animation(name, threshold, height)
        left = recolor_gauge(
            base, name + 'A', COLORS[threshold], left=0, top=0,
            width=10000 - offset, height=height, gauge_offset=-offset,
            fill=name + 'Fill',
        )
        right = recolor_gauge(
            base, name + 'B', COLORS[threshold], left=x + cut, top=y,
            width=width - cut, height=height, gauge_offset=-cut,
            fill=original_fill,
        )
        clip = clip_screen(name, x, y, cut, height)
        definitions.extend((anim, left, right, clip))
        for suffix in ('A_X', 'B'):
            piece = ET.Element('Pieces')
            piece.text = name + suffix
            parent.insert(insertion, piece)
            insertion += 1

    base_match = block(text, 'Gauge', 'Player_Mana')
    text = text[:base_match.start()] + serialize(base) + text[base_match.end():]
    parent_match = block(text, 'Screen', 'PlayerWindow')
    replacement = '\n'.join(map(serialize, definitions + [parent]))
    return text[:parent_match.start()] + replacement + text[parent_match.end():]


if __name__ == '__main__':
    write = sys.argv[1:2] == ['--write']
    path = Path(sys.argv[2] if write else sys.argv[1])
    original = path.read_text(encoding='ascii')
    revised = refine(original)
    if write:
        with path.open('w', encoding='ascii', newline='\n') as output:
            output.write(revised)
        raise SystemExit
    diff = list(difflib.unified_diff(original.splitlines(), revised.splitlines(), n=3, lineterm=''))
    print('*** Begin Patch')
    print('*** Update File: ' + str(path))
    for line in diff[2:]:
        print('@@' if line.startswith('@@') else line)
    print('*** End Patch')
