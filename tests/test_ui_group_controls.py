"""Group buttons have independent native-size faces, spacing and alias bindings."""
from copy import deepcopy
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
STATES = ('Normal','Flyby','Pressed','PressedFlyby','Disabled')


def node(kind,name):
    n=ET.parse(SKIN/'EQUI_GroupWindow.xml').getroot().find(f"{kind}[@item='{name}']")
    assert n is not None
    return n


def rect(n):
    return tuple(int(n.findtext(p)) for p in ('Location/X','Location/Y','Size/CX','Size/CY'))


def pixel(state,x,y):
    data=(SKIN/'VantageGroupControls.tga').read_bytes()
    pos=18+4*((2+20*state+y)*128+2+x)
    return tuple(data[pos:pos+4])


@pytest.mark.parametrize('name,x,y', [
    ('Invite',5,0), ('Follow',5,0), ('Disband',5,17), ('Decline',5,17),
])
def test_group_alias_buttons_keep_native_ids_and_fit_text_without_touching(name,x,y):
    b=node('Button','GW_'+name+'Button')
    assert b.findtext('ScreenID') == name+'Button'
    assert b.findtext('Text') == name
    assert b.findtext('Font') == '2'
    assert rect(b) == (x,y,64,16)
    assert b.findtext('Style_Transparent') == 'true'
    assert b.findtext('Style_Border') == b.findtext('Style_Checkbox') == 'false'
    assert b.find('EQType') is None
    assert 64 >= len(name)*6+12
    assert b.find('TextOffsetX') is None and b.find('TextOffsetY') is None
    pieces=[p.text for p in node('Screen','GroupWindow').findall('Pieces')]
    assert pieces.count(b.get('item')) == 1
    for state in STATES:
        assert b.findtext('ButtonDrawTemplate/'+state) == 'A_VantageGroup'+state


def test_compact_button_column_leaves_a_native_titlebar_drag_strip_open():
    assert rect(node('Screen','GroupWindow')) == (516,78,284,281)
    upper = rect(node('Button','GW_InviteButton'))
    lower = rect(node('Button','GW_DisbandButton'))
    assert upper == (5,0,64,16)
    assert lower == (5,17,64,16)
    assert upper[1] + upper[3] < lower[1]
    # Pixels x=73..125 in the native 16px titlebar remain free for moving.
    assert upper[0] + upper[2] < 73
    assert lower[0] + lower[2] < 73
    assert rect(node('Gauge','Party1_HP_BG'))[1] == 35
    assert int(node('Label','PlayerHP').findtext('Location/X')) == 178
    assert rect(node('Button','GW_LFGButton')) == (-3,16,1,1)
    assert node('Button','GW_LFGButton').findtext('ButtonDrawTemplate/Normal') == 'A_SquareBtnNormal'


def test_alternate_button_states_share_positions_and_preserve_native_piece_order():
    assert rect(node('Button','GW_InviteButton')) == rect(node('Button','GW_FollowButton'))
    assert rect(node('Button','GW_DisbandButton')) == rect(node('Button','GW_DeclineButton'))
    for primary, alias in (('Invite','Follow'), ('Disband','Decline')):
        pair = [deepcopy(node('Button','GW_'+name+'Button')) for name in (primary,alias)]
        for button in pair:
            button.attrib.pop('item')
            button.remove(button.find('ScreenID'))
            button.remove(button.find('Text'))
            button.tail = None
        assert ET.tostring(pair[0]) == ET.tostring(pair[1])
    pieces = [p.text for p in node('Screen','GroupWindow').findall('Pieces')]
    assert pieces[:6] == ['GW_StatsResizeGrip','GWDummy','GW_InviteButton',
                          'GW_DisbandButton','GW_FollowButton','GW_DeclineButton']
    # Member indices are native target bindings; button placement must never
    # reorder the roster or change the order of the layered health pieces.
    member_indices = [int(p[5]) for p in pieces if p.startswith('Party')]
    assert member_indices == sorted(member_indices)
    assert set(member_indices) == {1,2,3,4,5}
    for i in range(1,6):
        assert pieces.index(f'Party{i}_HP_BG') < pieces.index(f'Party{i}_HP_0')
        assert pieces.index(f'Party{i}_HP_0') < pieces.index(f'Party{i}_HealthDetail')
        assert pieces.index(f'Party{i}_HealthDetail') < pieces.index(f'GW_PetGauge{i}')


@pytest.mark.parametrize('member,y', [(1,35),(2,76),(3,117),(4,159),(5,201)])
def test_party_rows_keep_their_geometry_target_bindings_and_function_key_labels(member,y):
    background = node('Gauge',f'Party{member}_HP_BG')
    assert rect(background) == (-2,y,124,30)
    assert background.findtext('EQType') == str(10+member)
    for suffix in ('HP_0','HealthDetail'):
        gauge = node('Gauge',f'Party{member}_{suffix}')
        assert rect(gauge) == (20,y+10,100,20)
        assert gauge.findtext('EQType') == str(10+member)
    pet = node('Gauge',f'GW_PetGauge{member}')
    assert rect(pet) == (18,y+27,104,10)
    assert pet.findtext('ScreenID') == f'PetGauge{member}'
    assert pet.findtext('EQType') == str(16+member)
    health = node('Label',f'GW_HPLabel{member}')
    assert rect(health) == (-2,y+11,20,12)
    assert health.findtext('ScreenID') == f'HPLabel{member}'
    assert health.findtext('EQType') == str(34+member)
    shortcut = node('Label',f'F{member+1}')
    assert shortcut.findtext('ScreenID') == shortcut.findtext('Text') == f'F{member+1}'
    assert rect(shortcut) == (5,y,20 if member == 1 else 14,14)
    hidden_percent = node('Label',f'GW_HPPercLabel{member}')
    assert rect(hidden_percent) == (-2,42,1,1)


def test_every_global_roster_layer_moves_by_exactly_34_without_moving_internal_layers():
    root = ET.parse(SKIN/'EQUI_GroupWindow.xml').getroot()
    bases = (1,42,83,125,167)
    for member, old_base in enumerate(bases, 1):
        global_y = old_base + 10 + 34
        party_nodes = [n for n in root if (n.get('item') or '').startswith(f'Party{member}_HP_')]
        for part in party_nodes:
            y = part.findtext('Location/Y')
            if y is None:
                continue
            if part.get('item') == f'Party{member}_HP_BG':
                assert int(y) == old_base + 34
            else:
                assert int(y) in (0, global_y)
        assert rect(node('Gauge',f'Party{member}_HealthDetail'))[1] == global_y


def test_compact_width_keeps_controls_roster_and_brand_but_clips_personal_stats():
    compact_width = 126
    for name in ('GW_InviteButton','GW_FollowButton','GW_DisbandButton','GW_DeclineButton'):
        x,_,w,_ = rect(node('Button',name))
        assert x >= 0 and x+w <= compact_width
    for member in range(1,6):
        for kind,name in (
            ('Gauge',f'Party{member}_HP_BG'),
            ('Gauge',f'GW_PetGauge{member}'),
        ):
            x,_,w,_ = rect(node(kind,name))
            assert x+w <= 122
    for kind,name in (
        ('StaticAnimation','GW_VantageBrandMark'),
        ('Label','GW_VantageVersionLabel'),
    ):
        x,_,w,_ = rect(node(kind,name))
        assert x+w <= 121
    for kind,name in (
        ('StaticAnimation','GW_StatHPIcon'), ('Label','PlayerHPLabel'),
        ('Gauge','PlayerXPGauge_BG'), ('StaticAnimation','FRIcon'), ('Label','FR'),
    ):
        x,_,w,_ = rect(node(kind,name))
        assert x >= compact_width
        assert x+w <= 284


@pytest.mark.parametrize('i,state', list(enumerate(STATES)))
def test_all_button_states_have_matching_native_frames_clear_corners_and_neutral_rims(i,state):
    a=node('Ui2DAnimation','A_VantageGroup'+state)
    assert a.findtext('Cycle') == 'false'
    assert a.findtext('Frames/Texture') == 'VantageGroupControls.tga'
    assert rect(a.find('Frames')) == (2,2+20*i,64,16)
    assert a.findtext('Frames/Duration') == '1000'
    for x,y in ((0,0),(63,0),(0,15),(63,15)):
        assert pixel(i,x,y) == (0,0,0,0)
    for y in range(16):
        for x in range(64):
            b,g,r,alpha=pixel(i,x,y)
            assert b==g==r
    assert pixel(i,35,8)[3] == 255
    assert pixel(i,35,0)[0] > pixel(i,35,2)[0]


def test_raised_pressed_hover_and_disabled_faces_are_distinct_with_identical_alpha():
    hashes=set()
    for i in range(5):
        values=b''.join(bytes(pixel(i,x,y)) for y in range(16) for x in range(64))
        hashes.add(hashlib.sha256(values).digest())
        assert all(pixel(i,x,y)[3]==pixel(0,x,y)[3] for y in range(16) for x in range(64))
    assert len(hashes)==5
    assert pixel(0,35,3)[0]>pixel(0,35,12)[0]  # Raised.
    assert pixel(2,35,3)[0]<pixel(2,35,12)[0]  # Depressed.
    assert pixel(1,35,8)[0]>pixel(0,35,8)[0]>pixel(4,35,8)[0]


def test_atlas_is_flat_power_of_two_and_has_clear_gutters():
    data=(SKIN/'VantageGroupControls.tga').read_bytes()
    assert len(data)==18+128*128*4
    assert data[:3]==bytes((0,0,2))
    assert data[12:18]==bytes((128,0,128,0,32,40))
    for y in range(128):
        for x in range(128):
            if not (2<=x<66 and any(2+20*i<=y<18+20*i for i in range(5))):
                assert data[18+4*(y*128+x)+3]==0


def test_group_faces_restore_exact_known_visible_ui80_art():
    # Baseline: commit 96b7b6b, before the footer move and 54px shrink.
    assert hashlib.sha256((SKIN/'VantageGroupControls.tga').read_bytes()).hexdigest() == \
        '02299d2a6fe961b13f8436863958f12cbe2a10e42af61f378ebe53c7b083f2ca'
