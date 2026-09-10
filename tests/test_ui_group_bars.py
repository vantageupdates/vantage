"""Group controls align to the actual stats column, including native artwork."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui/skin'


def node(kind, name):
    n = ET.parse(SKIN / 'EQUI_GroupWindow.xml').getroot().find(f"{kind}[@item='{name}']")
    assert n is not None
    return n


def rect(n):
    return tuple(int(n.findtext(p)) for p in ('Location/X','Location/Y','Size/CX','Size/CY'))


@pytest.mark.parametrize('name,bounds,eq', [
    ('PlayerXPGauge_BG',(129,102,145,20),'4'),
    ('PlayerXPGauge',(131,102,141,20),'4'),
    ('P_Fatigue',(129,125,145,10),'3'),
    ('P_Breath',(129,138,145,10),'8'),
])
def test_gauge_hitbox_and_every_drawn_layer_have_identical_width(name,bounds,eq):
    gauge = node('Gauge',name)
    assert rect(gauge) == bounds
    assert gauge.findtext('EQType') == eq
    assert gauge.findtext('ScreenID') == name
    for layer in gauge.find('GaugeDrawTemplate'):
        frame = node('Ui2DAnimation',layer.text).find('Frames')
        assert frame.findtext('Texture') == 'VantageGroupBars.tga'
        assert rect(frame)[2:] == bounds[2:]
    assert bounds[0] + bounds[2] == (272 if name == 'PlayerXPGauge' else 274)


def test_all_three_bars_are_separated_and_percentage_is_not_under_a_fill():
    bars = [rect(node('Gauge',s)) for s in ('PlayerXPGauge_BG','P_Fatigue','P_Breath')]
    assert all(b[0] == 129 and b[2] == 145 for b in bars)
    assert bars[1][1] - sum(bars[0][1::2]) == 3
    assert bars[2][1] - sum(bars[1][1::2]) == 3
    assert rect(node('Label','PlayerXPPerc')) == (236,89,38,12)
    assert node('Label','PlayerXPPerc').findtext('EQType') == '26'
    assert rect(node('StaticAnimation','GW_StatEXPIcon')) == (129,90,10,10)
    assert rect(node('Label','STR'))[1] == 152
    assert 152 - (bars[-1][1] + bars[-1][3]) == 4
    for name in ('FR','CR','MR','PR','DR'):
        x,y,w,h = rect(node('Label',name))
        assert y == 220 and y+h <= 243-8
    assert rect(node('Screen','GroupWindow'))[2:] == (284,243)


@pytest.mark.parametrize('left,right',[('Invite','Disband'),('Follow','Decline')])
def test_button_pairs_are_centered_with_a_real_nine_pixel_gap(left,right):
    a,b = [rect(node('Button','GW_'+name+'Button')) for name in (left,right)]
    assert a == (133,0,64,16) and b == (206,0,64,16)
    assert b[0] - (a[0]+a[2]) == 9
    assert a[0]-129 == 274-(b[0]+b[2]) == 4
    for name in (left,right):
        button = node('Button','GW_'+name+'Button')
        assert button.findtext('Font') == '2'
        assert button.findtext('Text') == name


def test_new_bar_atlas_has_native_frames_and_transparent_gutters():
    data = (SKIN/'VantageGroupBars.tga').read_bytes()
    assert len(data) == 18+256*128*4
    assert data[2] == 2 and data[12:18] == bytes((0,1,128,0,32,40))
    cells = [(2,145,20),(26,141,20),(50,145,10),(64,145,10),(78,145,10)]
    for y in range(128):
        for x in range(256):
            used = any(2<=x<2+w and top<=y<top+h for top,w,h in cells)
            if not used:
                assert data[18+4*(y*256+x):22+4*(y*256+x)] == bytes(4)
    assert hashlib.sha256((SKIN/'dzbars.png').read_bytes()).hexdigest() == 'bef112ebdbf569836577422467c771d87dfd348dfb5f88d64753baa650439342'


def test_shared_legacy_gauges_and_inventory_exp_remain_independent():
    animations = ET.parse(SKIN/'EQUI_Animations.xml').getroot()
    assert animations.find("Ui2DAnimation[@item='A_dzFill']/Frames/Size/CX").text == '100'
    inventory = ET.parse(SKIN/'EQUI_Inventory.xml').getroot()
    assert inventory.find("Gauge[@item='IW_ExpGauge']/Size/CX").text == '118'
