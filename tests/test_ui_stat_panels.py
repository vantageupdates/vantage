"""Compact stat rows: native bindings, real sprites and separate label/value rails."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
ATTRS = ('STR', 'STA', 'AGI', 'DEX', 'WIS', 'INT', 'CHA')
TYPES = ('5', '6', '8', '7', '9', '10', '11')
STATS = ('HP', 'MANA', 'AC', 'ATK', 'EXP', *ATTRS[:2], 'AGI', 'DEX', 'WIS', 'INT', 'CHA', 'WEIGHT')


def node(file, kind, name):
    n = ET.parse(SKIN / ('EQUI_' + file + '.xml')).getroot().find(f"{kind}[@item='{name}']")
    assert n is not None, (file, kind, name)
    return n


def rect(n):
    return tuple(int(n.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def row(file, owner_kind, owner, stat, label_id, value_id, x, y, eq, label_width, value_x, value_width):
    prefix = 'AW' if file == 'ActionsWindow' else 'GW'
    icon_id = f'{prefix}_Stat{stat}Icon'
    icon = node(file, 'StaticAnimation', icon_id)
    label = node(file, 'Label', label_id)
    value = node(file, 'Label', value_id)
    assert rect(icon) == (x, y + 2, 10, 10)
    assert rect(label) == (x + 12, y, label_width, 14)
    assert rect(value) == (value_x, y, value_width, 14)
    assert x + 12 + label_width + 2 <= value_x
    assert value.findtext('EQType') == eq
    assert value.findtext('Font') == label.findtext('Font') == '2'
    assert value.findtext('NoWrap') == label.findtext('NoWrap') == 'true'
    assert [e.text for e in value.findall('AlignRight')] == ['true']
    assert value.findtext('AlignLeft') != 'true'
    assert label.findtext('AlignRight') == 'false'
    assert value_width >= 4 * 5 + 6  # Four native Font-2 digits plus breathing room.
    assert icon.findtext('Animation') == f'A_VantageCompactStat{stat}'
    pieces = [e.text for e in node(file, owner_kind, owner).findall('Pieces')]
    assert all(pieces.count(n) == 1 for n in (icon_id, label_id, value_id))


@pytest.mark.parametrize('i,stat,eq', [(i, s, TYPES[i]) for i, s in enumerate(ATTRS)])
def test_actions_attribute_rows(i, stat, eq):
    row('ActionsWindow', 'Page', 'ActionsMainPage', stat, stat+'txt', stat+'num', 3, i*11, eq, 22, 40, 26)


@pytest.mark.parametrize('i,stat,eq', [(0, 'AC', '22'), (1, 'ATK', '23')])
def test_actions_combat_rows(i, stat, eq):
    row('ActionsWindow', 'Page', 'ActionsMainPage', stat, stat+'txt', stat+'num', 70, i*11, eq, 24, 108, 26)


@pytest.mark.parametrize('i,key,short,full,eq', [
    (0,'M','MR','Magic','16'), (1,'F','FR','Fire','14'), (2,'C','CR','Cold','15'),
    (3,'D','DR','Disease','13'), (4,'P','PR','Poison','12'),
])
def test_actions_resists_have_nonoverlapping_abbreviations_and_full_tooltips(i,key,short,full,eq):
    label = node('ActionsWindow', 'Label', f'Sv{key}txt')
    value = node('ActionsWindow', 'Label', f'Sv{key}num')
    icon = node('ActionsWindow', 'StaticAnimation', f'AW_Resist{full}Icon')
    assert rect(label) == (82,22+i*11,24,14)
    assert rect(value) == (108,22+i*11,26,14)
    assert rect(icon) == (70,24+i*11,10,10)
    assert label.findtext('Text') == short
    assert label.findtext('TooltipReference') == full + ' resistance'
    assert value.findtext('EQType') == eq
    assert [n.text for n in value.findall('AlignRight')] == ['true']
    assert icon.findtext('Animation') == 'V3_ActionResist' + full


@pytest.mark.parametrize('stat,label,value,x,y,eq', [
    ('ATK','ATKLabel','ATK',129,72,'23'), ('AC','ACLabel','AC',207,72,'22'),
    ('STR','STRLabel','STR',129,124,'5'), ('STA','STALabel','STA',129,135,'6'),
    ('AGI','AGILabel','AGI',129,146,'8'), ('DEX','DEXLabel','DEX',129,157,'7'),
    ('WIS','WISLabel','WIS',207,124,'9'), ('INT','INTLabel','INT',207,135,'10'),
    ('CHA','CHALabel','CHA',207,146,'11'), ('WEIGHT','WGTLabel','WGT',207,157,'24'),
    ('HP','PlayerHPLabel','PlayerHP',129,45,'70'), ('MANA','PlayerManaLabel','PlayerMana',129,57,'128'),
])
def test_group_personal_stat_rows(stat,label,value,x,y,eq):
    resource = stat in ('HP','MANA')
    row('GroupWindow','Screen','GroupWindow',stat,label,value,x,y,eq,
        31 if resource else 23,178 if resource else x+37,96 if resource else 30)
    if resource:
        assert rect(node('GroupWindow','Label',value))[2] >= len('1,000/1,000') * 6 + 6


def test_window_bounds_and_native_xp_fatigue_breath_remain_distinct():
    assert rect(node('ActionsWindow','Screen','ActionsWindow')) == (516,292,144,182)
    assert rect(node('GroupWindow','Screen','GroupWindow')) == (516,78,284,215)
    for name,eq in (('PlayerXPGauge','4'),('PlayerXPGauge_BG','4'),('P_Fatigue','3'),('P_Breath','8')):
        g=node('GroupWindow','Gauge',name)
        assert g.findtext('EQType') == eq
        x,y,w,h=rect(g)
        assert x+w == (274 if name=='PlayerXPGauge' else 276)
    assert rect(node('GroupWindow','StaticAnimation','GW_StatEXPIcon')) == (129,90,10,10)
    assert node('GroupWindow','Label','PlayerXPPerc').findtext('EQType') == '26'
    assert rect(node('ActionsWindow','Label','CHAnum'))[1]+14 == 80
    assert rect(node('ActionsWindow','Button','AMP_CampButton')) == (4,87,128,18)


def test_compact_sprites_are_complete_native_size_and_original_atlas_is_unchanged():
    assert hashlib.sha256((SKIN/'VantageStatIcons.tga').read_bytes()).hexdigest() == '2442711deedc4593c9bb740f1e276729ab7a4a7903df2228cfdbc99de3d23799'
    data=(SKIN/'VantageCompactStatIcons.tga').read_bytes()
    assert data[12:18] == bytes((64,0,64,0,32,40))
    assert len(data) == 18+64*64*4
    hashes=set()
    for i,stat in enumerate(STATS):
        frame=node('Animations','Ui2DAnimation',f'A_VantageCompactStat{stat}').find('Frames')
        x,y=3+16*(i%4),3+16*(i//4)
        assert rect(frame) == (x,y,10,10)
        pixels=b''.join(data[18+4*((y+b)*64+x):18+4*((y+b)*64+x+10)] for b in range(10))
        assert sum(a>32 for a in pixels[3::4]) >= 15
        hashes.add(hashlib.sha256(pixels).digest())
    assert len(hashes)==13
    for y in range(64):
        for x in range(64):
            if x%16<3 or x%16>=13 or y%16<3 or y%16>=13:
                assert data[18+4*(y*64+x)+3] == 0
