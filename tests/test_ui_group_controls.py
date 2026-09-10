"""Group buttons have independent native-size faces, spacing and alias bindings."""
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


@pytest.mark.parametrize('name,x', [('Invite',133),('Follow',133),('Disband',206),('Decline',206)])
def test_group_alias_buttons_keep_native_ids_and_fit_text_without_touching(name,x):
    b=node('Button','GW_'+name+'Button')
    assert b.findtext('ScreenID') == name+'Button'
    assert b.findtext('Text') == name
    assert b.findtext('Font') == '2'
    assert rect(b) == (x,0,64,16)
    assert b.findtext('Style_Transparent') == 'true'
    assert b.findtext('Style_Border') == b.findtext('Style_Checkbox') == 'false'
    assert b.find('EQType') is None
    assert 64 >= len(name)*6+12
    assert b.find('TextOffsetX') is None and b.find('TextOffsetY') is None
    pieces=[p.text for p in node('Screen','GroupWindow').findall('Pieces')]
    assert pieces.count(b.get('item')) == 1
    for state in STATES:
        assert b.findtext('ButtonDrawTemplate/'+state) == 'A_VantageGroup'+state


def test_button_row_has_nine_pixel_gap_and_clears_the_character_heading():
    assert rect(node('Screen','GroupWindow')) == (516,78,284,243)
    assert 206-(133+64) == 9
    assert int(node('Label','Level').findtext('Location/Y'))-16 == 2
    assert int(node('Label','Class').findtext('Location/Y'))-16 == 2
    assert int(node('Label','PlayerHP').findtext('Location/X')) == 178
    assert rect(node('Button','GW_LFGButton')) == (-3,16,1,1)
    assert node('Button','GW_LFGButton').findtext('ButtonDrawTemplate/Normal') == 'A_SquareBtnNormal'


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
