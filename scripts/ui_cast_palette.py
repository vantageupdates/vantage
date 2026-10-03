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
FOOTER_PREFIX = 'CSPW_Cast_R'
FOOTER_BASE = 'CSPW_CastingProgress'
SPELL_WIDTH = 136
SPELL_FILL_WIDTH = SPELL_WIDTH - 4
SPELL_TEXTURE = 'v3_controls.tga'
SPELL_OUTLINE_ORIGIN = (0, 144)
SPELL_FOOTER_ORIGIN = (0, 176)
SPELL_FILL_ORIGIN = (0, 196)


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


def refine(text, animation_text, *, base_name='Target_Casting_Gauge',
           parent_name='TargetWindow', prefix=PREFIX):
    text = text.replace('\r\n', '\n')
    root = ET.fromstring(text)
    if any(n.get('item', '').startswith(prefix) for n in root):
        raise ValueError('Cast layers already exist; inspect instead of stacking them again')
    base = deepcopy(item(root, 'Gauge', base_name))
    if base.findtext('EQType') != '7':
        raise ValueError('Expected native remaining-cast binding 7')
    parent = deepcopy(item(root, 'Screen', parent_name))
    fill_name = base.findtext('GaugeDrawTemplate/Fill')
    fill_root = root if root.findall(f"Ui2DAnimation[@item='{fill_name}']") else ET.fromstring(animation_text)
    fill = item(fill_root, 'Ui2DAnimation', fill_name)
    width, height = (int(base.findtext('Size/' + p)) for p in ('CX', 'CY'))
    x, y = (int(base.findtext('Location/' + p)) for p in ('X', 'Y'))
    origin = int(fill.findtext('Frames/Location/X'))
    tint(base, SAMPLES[-1][1])
    definitions, pieces = [], []
    for threshold, color in LAYERS:
        name = f'{prefix}{threshold:02}'
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


def add_spell_footer(text):
    """Append one real native countdown, never a timer or per-gem imitation."""
    root = ET.fromstring(text)
    if any(n.get('item', '').startswith(('CSPW_Cast', 'A_CSPW_Cast')) for n in root):
        raise ValueError('Spell footer already exists; inspect instead of stacking it')
    parent = deepcopy(item(root, 'Screen', 'CastSpellWnd'))
    if (parent.findtext('Size/CX'), parent.findtext('Size/CY')) != (str(SPELL_WIDTH + 10), '280'):
        raise ValueError('Unexpected spell window layout')
    definitions = ET.fromstring("""<XML>
  <Ui2DAnimation item="A_CSPW_CastFooter">
    <Cycle>false</Cycle>
    <Frames>
      <Texture>VantageControlEdges.tga</Texture>
      <Location><X>2</X><Y>96</Y></Location>
      <Size><CX>120</CX><CY>15</CY></Size>
      <Hotspot><X>0</X><Y>0</Y></Hotspot>
      <Duration>1000</Duration>
    </Frames>
  </Ui2DAnimation>
  <Ui2DAnimation item="A_CSPW_CastFill">
    <Cycle>false</Cycle>
    <Frames>
      <Texture>VantageControlEdges.tga</Texture>
      <Location><X>128</X><Y>96</Y></Location>
      <Size><CX>116</CX><CY>9</CY></Size>
      <Hotspot><X>0</X><Y>0</Y></Hotspot>
      <Duration>1000</Duration>
    </Frames>
  </Ui2DAnimation>
  <StaticAnimation item="CSPW_CastFooter">
    <ScreenID>CSPW_CastFooter</ScreenID>
    <RelativePosition>true</RelativePosition>
    <Location><X>1</X><Y>274</Y></Location>
    <Size><CX>120</CX><CY>15</CY></Size>
    <Animation>A_CSPW_CastFooter</Animation>
    <AutoDraw>true</AutoDraw>
  </StaticAnimation>
  <Gauge item="CSPW_CastingProgress">
    <RelativePosition>true</RelativePosition>
    <Location><X>3</X><Y>277</Y></Location>
    <Size><CX>116</CX><CY>9</CY></Size>
    <GaugeOffsetX>0</GaugeOffsetX>
    <GaugeOffsetY>0</GaugeOffsetY>
    <Text></Text>
    <TextOffsetX>8000</TextOffsetX>
    <Style_VScroll>false</Style_VScroll>
    <Style_HScroll>false</Style_HScroll>
    <Style_Transparent>true</Style_Transparent>
    <TooltipReference>Spell casting progress</TooltipReference>
    <FillTint><R>0</R><G>240</G><B>0</B><Alpha>255</Alpha></FillTint>
    <DrawLinesFill>false</DrawLinesFill>
    <EQType>7</EQType>
    <GaugeDrawTemplate><Fill>A_CSPW_CastFill</Fill></GaugeDrawTemplate>
  </Gauge>
</XML>""")
    last = item(root, 'SpellGem', 'CSPW_Spell7')
    for name, origin, width in (
        ('A_CSPW_CastFooter', SPELL_FOOTER_ORIGIN, SPELL_WIDTH),
        ('A_CSPW_CastFill', SPELL_FILL_ORIGIN, SPELL_FILL_WIDTH),
    ):
        frame = item(definitions, 'Ui2DAnimation', name).find('Frames')
        set_value(frame, 'Texture', SPELL_TEXTURE)
        set_value(frame, 'Location/X', origin[0])
        set_value(frame, 'Location/Y', origin[1])
        set_value(frame, 'Size/CX', width)
    set_value(item(definitions, 'StaticAnimation', 'CSPW_CastFooter'), 'Size/CX', SPELL_WIDTH)
    set_value(item(definitions, 'Gauge', FOOTER_BASE), 'Size/CX', SPELL_FILL_WIDTH)
    footer_y = int(last.findtext('Location/Y')) + int(last.findtext('Size/CY')) + 4
    set_value(item(definitions, 'StaticAnimation', 'CSPW_CastFooter'), 'Location/Y', footer_y)
    set_value(item(definitions, 'Gauge', FOOTER_BASE), 'Location/Y', footer_y + 3)
    set_value(parent, 'Size/CY', footer_y + 26)
    for name in ('CSPW_CastFooter', FOOTER_BASE):
        ET.SubElement(parent, 'Pieces').text = name
    text = replace_block(text, 'Screen', 'CastSpellWnd',
                         '\n'.join(map(serialize, [*definitions, parent])))
    return refine(text, '', base_name=FOOTER_BASE, parent_name='CastSpellWnd',
                  prefix=FOOTER_PREFIX)


def widen_spell_window(text, animation_text):
    """Rebuild only spell widths and source rectangles; preserve native bindings.

    The wider cells use free space in the existing spell-only atlas. Shared
    control art has no room for these widths beside the native Pet buttons.
    The paired remaining-time gauges retain their established 10000px model.
    """
    text = text.replace('\r\n', '\n')
    animation_text = animation_text.replace('\r\n', '\n')
    root, animations = ET.fromstring(text), ET.fromstring(animation_text)
    for node in root:
        name = node.get('item', '')
        if name == 'CastSpellWnd':
            set_value(node, 'Size/CX', SPELL_WIDTH + 10)
        elif name == 'CSPW_SpellBook' or re.fullmatch(r'CSPW_Spell[0-7](?:_Outline)?', name):
            set_value(node, 'Size/CX', SPELL_WIDTH)
        elif re.fullmatch(r'CSPW_Spell[0-7]_Name', name):
            set_value(node, 'Size/CX', SPELL_WIDTH - 32)
        elif name == 'CSPW_CastFooter':
            set_value(node, 'Size/CX', SPELL_WIDTH)
        elif name == FOOTER_BASE:
            set_value(node, 'Size/CX', SPELL_FILL_WIDTH)
        elif name in ('A_CSPW_CastFooter', 'A_CSPW_CastFill'):
            origin = SPELL_FOOTER_ORIGIN if name.endswith('Footer') else SPELL_FILL_ORIGIN
            set_value(node, 'Frames/Texture', SPELL_TEXTURE)
            set_value(node, 'Frames/Location/X', origin[0])
            set_value(node, 'Frames/Location/Y', origin[1])
            set_value(node, 'Frames/Size/CX', SPELL_WIDTH if name.endswith('Footer') else SPELL_FILL_WIDTH)
        elif name.startswith(FOOTER_PREFIX):
            threshold = int(name[len(FOOTER_PREFIX):len(FOOTER_PREFIX) + 2])
            cut = SPELL_FILL_WIDTH * threshold // 100
            if name.endswith('Fill'):
                set_value(node, 'Frames/Texture', SPELL_TEXTURE)
                set_value(node, 'Frames/Location/X', SPELL_FILL_ORIGIN[0] - 100 * threshold)
                set_value(node, 'Frames/Location/Y', SPELL_FILL_ORIGIN[1])
            elif name.endswith('B'):
                set_value(node, 'Location/X', 3 + cut)
                set_value(node, 'Size/CX', SPELL_FILL_WIDTH - cut)
                set_value(node, 'GaugeOffsetX', -cut)
            elif name.endswith('A_X'):
                set_value(node, 'Size/CX', cut)
            else:
                continue
        else:
            continue
        text = replace_block(text, node.tag, name, serialize(node))
    for node in animations:
        name = node.get('item', '')
        if name == 'A_VantageSpellGemOutline':
            set_value(node, 'Frames/Texture', SPELL_TEXTURE)
            set_value(node, 'Frames/Location/X', SPELL_OUTLINE_ORIGIN[0])
            set_value(node, 'Frames/Location/Y', SPELL_OUTLINE_ORIGIN[1])
            set_value(node, 'Frames/Size/CX', SPELL_WIDTH)
        elif name.startswith('V3_Cast'):
            set_value(node, 'Frames/Size/CX', SPELL_WIDTH)
        else:
            continue
        animation_text = replace_block(animation_text, node.tag, name, serialize(node))
    return text, animation_text


if __name__ == '__main__':
    folder = Path(sys.argv[1])
    if '--widen-spells' in sys.argv[2:]:
        paths = [folder / name for name in ('EQUI_CastSpellWnd.xml', 'EQUI_Animations.xml')]
        originals = [path.read_text(encoding='ascii') for path in paths]
        revisions = widen_spell_window(*originals)
        print('*** Begin Patch')
        for path, original, revised in zip(paths, originals, revisions):
            lines = list(difflib.unified_diff(original.splitlines(), revised.splitlines(), n=3, lineterm=''))
            if not lines:
                continue
            print('*** Update File: ' + str(path))
            for line in lines[2:]:
                print('@@' if line.startswith('@@') else line)
        print('*** End Patch')
        sys.exit(0)
    footer = '--spell-footer' in sys.argv[2:]
    path = folder / ('EQUI_CastSpellWnd.xml' if footer else 'EQUI_TargetWindow.xml')
    original = path.read_text(encoding='ascii')
    revised = (add_spell_footer(original) if footer else
               refine(original, (folder / 'EQUI_Animations.xml').read_text(encoding='ascii')))
    lines = list(difflib.unified_diff(original.splitlines(), revised.splitlines(), n=3, lineterm=''))
    print('*** Begin Patch')
    print('*** Update File: ' + str(path))
    for line in lines[2:]:
        print('@@' if line.startswith('@@') else line)
    print('*** End Patch')
