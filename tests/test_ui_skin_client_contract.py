"""Regression contracts from actual client errors and native inventory bounds."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
SCHOOLS = ('Magic', 'Fire', 'Cold', 'Disease', 'Poison')

def root(name):
    return ET.parse(SKIN / name).getroot()

def item(xml, kind, name):
    found = xml.find(f"{kind}[@item='{name}']")
    assert found is not None, (kind, name)
    return found

def rect(node):
    return tuple(int(node.findtext(path)) for path in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))

def forward_screen_references(xml):
    order = {node.get('item'): index for index, node in enumerate(xml) if node.tag == 'Screen'}
    errors = []
    for node in xml.findall('Screen'):
        for piece in node.findall('Pieces'):
            name = (piece.text or '').split(':')[-1].strip()
            if name in order and order[name] >= order[node.get('item')]:
                errors.append((node.get('item'), name))
    return errors

@pytest.mark.parametrize('filename', ['EQUI_PlayerWindow.xml', 'EQUI_GroupWindow.xml', 'EQUI_TargetWindow.xml'])
def test_nested_health_screens_are_declared_before_their_parent(filename):
    assert forward_screen_references(root(filename)) == []

def test_reproduces_four_actual_ui54_target_symbol_table_errors():
    xml = deepcopy(root('EQUI_TargetWindow.xml'))
    parent = item(xml, 'Screen', 'TargetWindow')
    # Recreate 1.44.54 membership, excluding later intermediate-color layers.
    for piece in list(parent.findall('Pieces')):
        if (piece.text or '').startswith('VantageTarget_HP_S'):
            parent.remove(piece)
    xml.remove(parent)
    xml.insert(1, parent)
    assert forward_screen_references(xml) == [
        ('TargetWindow', f'VantageTarget_HP_{n}A_X') for n in range(1, 5)]

def bag_intrusions(xml, icon):
    x, y, width, height = rect(icon)
    pieces = {p.text.strip() for p in item(xml, 'Screen', 'InventoryWindow').findall('Pieces')}
    intrusions = []
    for slot in xml.findall('InvSlot'):
        if slot.get('item') not in pieces or slot.find('Location') is None:
            continue
        sx, sy, sw, sh = rect(slot)
        if y < sy + sh and sy < y + height and x < sx + sw and sx < x + width:
            intrusions.append(slot.get('item'))
    return intrusions

@pytest.mark.parametrize('school', SCHOOLS)
def test_inventory_resistance_icons_clear_slots_labels_and_window_edges(school):
    xml = root('EQUI_Inventory.xml')
    icon = item(xml, 'StaticAnimation', f'IW_Resist{school}Icon')
    label = item(xml, 'Label', f'IW_{school}')
    value = item(xml, 'Label', f'IW_{school}Number')
    x, y, w, h = rect(icon)
    lx, ly, lw, lh = rect(label)
    vx, vy, vw, vh = rect(value)
    assert (w, h) == (12, 12)
    assert bag_intrusions(xml, icon) == []
    # The rightmost bag column ends at 235; keep real space before the icon.
    for name in ('InvSlot28', 'InvSlot29'):
        sx, sy, sw, sh = rect(item(xml, 'InvSlot', name))
        assert x >= sx + sw + 4
    assert x + w + 2 <= lx and lx + lw + 4 <= vx
    assert ly == vy and ly + lh / 2 == y + h / 2
    window = item(xml, 'Screen', 'InventoryWindow')
    assert vx + vw <= int(window.findtext('Size/CX')) - 6
    assert y + h <= int(window.findtext('Size/CY')) - 6
    animation = item(root('EQUI_Animations.xml'), 'Ui2DAnimation', icon.findtext('Animation'))
    assert tuple(int(animation.findtext('Frames/Size/' + k)) for k in ('CX', 'CY')) == (w, h)

@pytest.mark.parametrize('school', SCHOOLS)
def test_reproduces_ui54_resistance_icon_overlap(school):
    xml = deepcopy(root('EQUI_Inventory.xml'))
    icon = item(xml, 'StaticAnimation', f'IW_Resist{school}Icon')
    icon.find('Location/X').text = '231'
    assert bag_intrusions(xml, icon), 'The previous four-pixel intrusion must be caught'


def assert_two_line_spell_name_room(gem, label):
    """Reserve two 12px line boxes plus descent slack, inside the gem.

    This is a conservative geometry budget, not a simulation of EQ's renderer.
    Checking only containment previously allowed a clipped 20px label to pass.
    """
    gx, gy, gw, gh = rect(gem)
    lx, ly, lw, lh = rect(label)
    assert lh >= 2 * 12 + 2, 'Two-line spell name needs descent slack'
    assert gy + 3 <= ly and ly + lh <= gy + gh - 3
    assert gx + 31 <= lx and lx + lw <= gx + gw - 4


@pytest.mark.parametrize('index', range(8))
def test_spell_gems_have_room_for_names_inset_icons_and_row_gaps(index):
    xml = root('EQUI_CastSpellWnd.xml')
    gem = item(xml, 'SpellGem', f'CSPW_Spell{index}')
    label = item(xml, 'Label', f'CSPW_Spell{index}_Name')
    window = item(xml, 'Screen', 'CastSpellWnd')
    assert rect(gem) == (1, 18 + 34 * index, 120, 32)
    assert rect(label) == (32, 21 + 34 * index, 85, 26)
    assert_two_line_spell_name_room(gem, label)
    assert label.findtext('Font') == '1'
    assert label.findtext('NoWrap') == 'false'
    assert label.findtext('EQType') == str(60 + index)
    assert label.findtext('AlignCenter') == 'true'
    assert gem.findtext('ScreenID') == f'CSPW_Spell{index}'
    assert gem.findtext('SpellIconOffsetX') == '4'
    assert gem.findtext('SpellIconOffsetY') == '4'
    gx, gy, gw, gh = rect(gem)
    lx, ly, lw, lh = rect(label)
    # Titanium icons are 24px. Never enlarge the art or use newer-client tags.
    assert gx + 4 + 24 + 3 <= lx
    assert 4 + 24 + 4 == gh
    assert lx + lw <= gx + gw - 4
    assert ly == gy + 3
    assert ly + lh <= gy + gh - 3
    assert gx + gw <= int(window.findtext('Size/CX')) - 8
    assert gy + gh <= int(window.findtext('Size/CY')) - 8
    assert gem.find('SpellIconSizeX') is None
    assert gem.find('SpellIconSizeY') is None
    if index < 7:
        following = item(xml, 'SpellGem', f'CSPW_Spell{index + 1}')
        assert rect(following)[1] - (gy + gh) == 2
    header = item(xml, 'Button', 'CSPW_SpellBook')
    assert rect(header) == (1, 1, 120, 14)
    assert window.findtext('Size/CX') == '130'
    assert window.findtext('Size/CY') == '298'


@pytest.mark.parametrize('index', range(8))
def test_rejects_ui59_clipped_two_line_spell_labels(index):
    xml = root('EQUI_CastSpellWnd.xml')
    gem = deepcopy(item(xml, 'SpellGem', f'CSPW_Spell{index}'))
    label = deepcopy(item(xml, 'Label', f'CSPW_Spell{index}_Name'))
    gem.find('Location/Y').text = str(18 + 30 * index)
    gem.find('Size/CY').text = '28'
    label.find('Location/Y').text = str(24 + 30 * index)
    label.find('Size/CY').text = '20'
    with pytest.raises(AssertionError, match='Two-line spell name'):
        assert_two_line_spell_name_room(gem, label)


def test_player_name_hp_and_mana_do_not_overlap():
    xml = root('EQUI_PlayerWindow.xml')
    name = rect(item(xml, 'Label', 'Player_Name'))
    hp = rect(item(xml, 'Gauge', 'Player_HP_0'))
    mana = rect(item(xml, 'Gauge', 'Player_Mana'))
    value = rect(item(xml, 'Label', 'Player_ManaLabel'))
    window = item(xml, 'Screen', 'PlayerWindow')
    assert name[1] + name[3] <= hp[1] - 1
    assert hp[1] + hp[3] + 3 == mana[1]
    assert (mana[0], mana[2]) == (hp[0], hp[2])
    assert value[1] == mana[1]
    assert mana[1] + mana[3] <= int(window.findtext('Size/CY')) - 8
    order = {node.get('item'): n for n, node in enumerate(xml)}
    assert not any((p.text or '').endswith('_HP_VantageTicks') for p in window.findall('Pieces'))


def test_attack_rim_is_client_drawn_not_a_permanent_decoration():
    xml = root('EQUI_PlayerWindow.xml')
    indicator = item(xml, 'StaticAnimation', 'A_AttackIndicatorAnim')
    assert indicator.findtext('AutoDraw') == 'false'
    assert indicator.findtext('ScreenID') == 'A_AttackIndicatorAnim'
    assert indicator.findtext('Animation') == 'A_AttackIndicator'
    animation = item(xml, 'Ui2DAnimation', 'A_AttackIndicator')
    assert animation.findtext('Cycle') == 'false'
    assert len(animation.findall('Frames')) == 1
    pieces = [p.text for p in item(xml, 'Screen', 'PlayerWindow').findall('Pieces')]
    assert pieces.count('A_AttackIndicatorAnim') == 1
    # Native attack control remains responsible for blink timing/red tint.
    schema = root('SIDL.xml')
    default = schema.find(".//{*}ElementType[@name='StaticScreenPiece']/{*}element[@name='AutoDraw']/{*}default")
    assert default is not None and default.text == 'true'


@pytest.mark.parametrize('filename,prefixes', [
    ('EQUI_PlayerWindow.xml', ['Player']),
    ('EQUI_GroupWindow.xml', [f'Party{i}' for i in range(1, 6)]),
    ('EQUI_PetInfoWindow.xml', ['Pet']),
    ('EQUI_TargetWindow.xml', ['VantageTarget']),
])
def test_health_reverts_extra_layers_and_removes_floating_ticks(filename, prefixes):
    xml = root(filename)
    assert forward_screen_references(xml) == []
    for prefix in prefixes:
        gauges = [n for n in xml.findall('Gauge') if (n.get('item') or '').startswith(prefix + '_HP_')]
        expected = {prefix + '_HP_' + suffix for suffix in ('0','1A','1B','2A','2B','3A','3B','4A','4B')}
        if prefix != 'VantageTarget':
            expected.add(prefix + '_HP_BG')
        assert {n.get('item') for n in gauges} == expected
        assert not any((p.text or '') == prefix + '_HP_VantageTicks' for p in xml.iter('Pieces'))


def test_attack_art_is_a_fine_rounded_outer_rim_with_transparent_interior():
    data = (SKIN / 'AttackIndicator.tga').read_bytes()
    assert data[2] == 2 and data[16:18] == bytes((32,40))
    assert int.from_bytes(data[12:14], 'little') == 512
    assert int.from_bytes(data[14:16], 'little') == 128
    assert len(data) == 18 + 512*128*4
    visible = [(i % 512, i // 512) for i, a in enumerate(data[21::4]) if a]
    assert visible
    assert all(0 <= x < 262 and 0 <= y < 57 for x,y in visible)
    assert not any(7 <= x <= 254 and 3 <= y <= 53 for x,y in visible)
    assert any(x == 130 and y <= 2 for x,y in visible)
    assert any(x == 130 and y >= 55 for x,y in visible)
    assert any(x <= 2 and y == 28 for x,y in visible)
    assert any(x >= 260 and y == 28 for x,y in visible)
    assert (0,0) not in visible and (261,56) not in visible


def test_native_edge_atlas_has_transparent_hp_relief_and_fine_gold():
    data = (SKIN / 'VantageControlEdges.tga').read_bytes()
    assert (data[2], data[16], data[17]) == (2, 32, 40)
    width = int.from_bytes(data[12:14], 'little')
    height = int.from_bytes(data[14:16], 'little')
    assert (width, height, len(data)) == (512, 128, 18 + 512 * 128 * 4)
    def pixel(x, y):
        offset = 18 + 4 * (y * width + x)
        return tuple(data[offset:offset + 4])
    for origin, bar_width in ((2, 240), (246, 100)):
        columns = {origin + i * bar_width // 5 - 1 for i in range(1, 5)}
        for x in range(origin, origin + bar_width):
            for y in range(12, 32):
                color = pixel(x, y)
                if x in columns and 15 <= y < 30:
                    assert color == (255, 255, 255, 26)
                assert color[3] <= 50
                if y < 15 or y >= 30:
                    assert color[3] == 0
        assert pixel(origin+10,15) == (255,255,255,50)
        assert pixel(origin+10,29) == (0,0,0,38)
        assert pixel(origin,15)[3] == 0
    alphas = [pixel(x, y)[3] for y in range(2, 4) for x in range(2, 44)]
    assert 0 < max(alphas) < 110


@pytest.mark.parametrize('filename,parent,prefixes', [
    ('EQUI_PlayerWindow.xml','PlayerWindow',['Player']),
    ('EQUI_GroupWindow.xml','GroupWindow',[f'Party{i}' for i in range(1,6)]),
    ('EQUI_PetInfoWindow.xml','PetInfoWindow',['Pet']),
    ('EQUI_TargetWindow.xml','TargetWindow',['VantageTarget']),
])
def test_health_detail_is_a_live_fill_not_static_empty_slot_markers(filename,parent,prefixes):
    xml=root(filename)
    pieces=[p.text for p in item(xml,'Screen',parent).findall('Pieces')]
    order={n.get('item'):i for i,n in enumerate(xml)}
    for prefix in prefixes:
        name=prefix+'_HealthDetail'
        detail=item(xml,'Gauge',name)
        base=item(xml,'Gauge',prefix+'_HP_0')
        assert rect(detail)==rect(base)
        assert detail.findtext('EQType')==base.findtext('EQType')
        assert detail.findtext('GaugeOffsetX')=='0'
        assert detail.findtext('GaugeOffsetY')=='0'
        assert detail.findtext('Style_Transparent')=='true'
        draw=detail.find('GaugeDrawTemplate')
        assert [n.tag for n in draw]==['Fill']
        assert draw.findtext('Fill')=='A_VantageHP'+base.findtext('Size/CX')+'Lines'
        assert all(detail.findtext('FillTint/'+c)=='255' for c in 'RGB')
        assert pieces.count(name)==1
        assert pieces.index(name)>pieces.index(prefix+'_HP_4B')
        assert order[name]<order[parent]
