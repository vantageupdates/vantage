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


@pytest.mark.parametrize('name,bounds,eq,source_width', [
    ('PlayerXPGauge_BG',(129,86,145,20),'4',145),
    ('PlayerXPGauge',(131,86,141,20),'4',141),
    ('P_Fatigue',(129,109,145,10),'3',145),
    ('P_Breath',(129,122,145,10),'8',145),
])
def test_gauge_hitbox_matches_native_art_without_clipping_endcaps(name,bounds,eq,source_width):
    gauge = node('Gauge',name)
    assert rect(gauge) == bounds
    assert gauge.findtext('EQType') == eq
    assert gauge.findtext('ScreenID') == name
    for layer in gauge.find('GaugeDrawTemplate'):
        frame = node('Ui2DAnimation',layer.text).find('Frames')
        assert frame.findtext('Texture') == 'VantageGroupBars.tga'
        # Titanium clips oversized frames: both endcaps and all dividers must
        # fit at 1:1 native size, without assuming renderer scaling.
        assert rect(frame)[2:] == (source_width,bounds[3])
        assert source_width == bounds[2]
    assert bounds[0] + bounds[2] == (272 if name == 'PlayerXPGauge' else 274)


def test_all_three_bars_are_separated_and_percentage_is_not_under_a_fill():
    bars = [rect(node('Gauge',s)) for s in ('PlayerXPGauge_BG','P_Fatigue','P_Breath')]
    assert all(b[0] == 129 and b[2] == 145 for b in bars)
    assert bars[1][1] - sum(bars[0][1::2]) == 3
    assert bars[2][1] - sum(bars[1][1::2]) == 3
    assert rect(node('Label','PlayerXPPerc')) == (236,72,38,14)
    assert node('Label','PlayerXPPerc').findtext('EQType') == '26'
    assert rect(node('StaticAnimation','GW_StatEXPIcon')) == (129,74,10,10)
    assert rect(node('Label','STR'))[1] == 136
    assert 136 - (bars[-1][1] + bars[-1][3]) == 4
    group_size = rect(node('Screen','GroupWindow'))[2:]
    assert group_size == (288,281)
    top_frame_inset = bottom_frame_inset = 4
    client_height = group_size[1] - top_frame_inset - bottom_frame_inset - 16
    assert client_height == 257
    for name in ('FR','CR','MR','PR','DR'):
        x,y,w,h = rect(node('Label',name))
        assert y == 214 and y+h <= client_height


@pytest.mark.parametrize('left,right',[('Invite','Disband'),('Follow','Decline')])
def test_button_alias_pairs_share_the_compact_row(left,right):
    a,b = [rect(node('Button','GW_'+name+'Button')) for name in (left,right)]
    assert a == (5,2,56,16) and b == (65,2,56,16)
    assert b[0] - (a[0]+a[2]) == 4
    assert b[0]+b[2] == 121 < 126
    for name in (left,right):
        button = node('Button','GW_'+name+'Button')
        assert button.findtext('Font') == '2'
        assert button.findtext('Text') == name


def test_new_bar_atlas_has_native_frames_and_transparent_gutters():
    data = (SKIN/'VantageGroupBars.tga').read_bytes()
    assert len(data) == 18+256*128*4
    assert data[2] == 2 and data[12:18] == bytes((0,1,128,0,32,40))
    cells = [(2,145,20),(26,141,20),(50,145,10),(64,145,10),
             (78,145,10),(92,145,10)]
    for y in range(128):
        for x in range(256):
            used = any(2<=x<2+w and top<=y<top+h for top,w,h in cells)
            if not used:
                assert data[18+4*(y*256+x):22+4*(y*256+x)] == bytes(4)
    assert hashlib.sha256((SKIN/'dzbars.png').read_bytes()).hexdigest() == 'bef112ebdbf569836577422467c771d87dfd348dfb5f88d64753baa650439342'


def test_experience_dividers_are_crisp_single_pixel_and_clearly_darker():
    data=(SKIN/'VantageGroupBars.tga').read_bytes()
    def luma(x,y):
        b,g,r,a=data[18+4*(y*256+x):22+4*(y*256+x)]
        assert a > 0
        return r+g+b
    top,width=26,141
    for section in range(1,5):
        x=2+round(width*section/5)
        core=luma(x,top+10)
        sides=(luma(x-1,top+10),luma(x+1,top+10))
        assert core < min(sides)
        assert core*100 <= max(sides)*82
        # Adjacent pixels remain the original gradient instead of forming a
        # three-pixel divider/falloff around the core.
        assert sides == (luma(x-2,top+10),luma(x+2,top+10))

    # The empty track uses the same one-pixel geometry, with its visible
    # darker-gold marker leaving both neighboring pixels untouched.
    top,width=2,145
    for section in range(1,5):
        x=2+round(width*section/5)
        assert luma(x-1,top+10) == luma(x-2,top+10)
        assert luma(x+1,top+10) == luma(x+2,top+10)


def test_each_bar_uses_darker_dividers_from_its_own_hue_family():
    data=(SKIN/'VantageGroupBars.tga').read_bytes()
    def rgba(x,y):
        b,g,r,a=data[18+4*(y*256+x):22+4*(y*256+x)]
        return r,g,b,a
    # Empty EXP track uses a deep raw gold; filled EXP remains grayscale so the
    # game's unchanged FillTint produces a darker version of the same gold.
    exp=rgba(2+29,2+10)
    assert exp[0] > exp[1] > exp[2] > 0 and exp[3] > 0
    fill=rgba(2+28,26+10)
    assert fill[0] == fill[1] == fill[2] and fill[3] > 0
    tint=node('Gauge','PlayerXPGauge').find('FillTint')
    tinted=tuple(fill[i]*int(tint.findtext(c))//255 for i,c in enumerate(('R','G','B')))
    assert tinted[0] > tinted[1] > tinted[2] > 0
    # Thin separator masks share geometry/alpha, but each owns its bar hue.
    fatigue=rgba(2+28,78+5)
    breath=rgba(2+28,92+5)
    assert fatigue[:3] == (127,76,8)
    assert breath[:3] == (20,104,126)
    assert fatigue[3] == breath[3] > 0
    assert node('Gauge','P_Fatigue').findtext('GaugeDrawTemplate/Lines') == 'A_VantageGroupFatigueLines'
    assert node('Gauge','P_Breath').findtext('GaugeDrawTemplate/Lines') == 'A_VantageGroupBreathLines'


def test_shared_legacy_gauges_and_inventory_exp_remain_independent():
    animations = ET.parse(SKIN/'EQUI_Animations.xml').getroot()
    assert animations.find("Ui2DAnimation[@item='A_dzFill']/Frames/Size/CX").text == '100'
    inventory = ET.parse(SKIN/'EQUI_Inventory.xml').getroot()
    assert inventory.find("Gauge[@item='IW_ExpGauge']/Size/CX").text == '118'


def test_experience_heading_matches_left_labels_and_right_resource_values():
    label = node('Label', 'GW_ExperienceLabel')
    percent = node('Label', 'PlayerXPPerc')
    assert label.findtext('Text') == 'Experience'
    assert rect(label) == (141,72,75,14)
    assert label.findtext('EQType') is None
    assert label.findtext('AlignRight') == label.findtext('AlignCenter') == 'false'
    assert label.findtext('NoWrap') == percent.findtext('NoWrap') == 'true'
    assert label.findtext('Font') == percent.findtext('Font') == '2'
    assert rect(label)[1::2] == rect(percent)[1::2]
    assert percent.findtext('AlignRight') == 'true'
    assert 141+75+20 == rect(percent)[0]
    assert 75 >= len('Experience')*6+8
    for name in ('PlayerHPLabel','PlayerManaLabel','ATKLabel','STRLabel'):
        assert rect(node('Label',name))[0] == rect(label)[0]
    for name in ('PlayerHP','PlayerMana'):
        value = node('Label',name)
        assert value.findtext('AlignRight') == 'true'
        assert rect(value)[0] + rect(value)[2] == 274
    pieces = [p.text for p in node('Screen','GroupWindow').findall('Pieces')]
    assert pieces.count('GW_ExperienceLabel') == 1


def test_compacted_right_panel_keeps_readable_identity_fields_and_frame_clearance():
    for name in ('Class','Deity'):
        value = node('Label',name)
        assert rect(value) == (153,2 if name == 'Class' else 14,121,14)
        assert rect(value)[2] >= len(value.findtext('Text'))*6+8
    essential = [
        ('Label','Class'), ('Label','Deity'), ('Label','PlayerHP'),
        ('Label','PlayerMana'), ('Label','PlayerXPPerc'), ('Label','AC'),
        ('Label','WIS'), ('Label','DR'), ('Gauge','PlayerXPGauge_BG'),
    ]
    right_edge = max(rect(node(kind,name))[0] + rect(node(kind,name))[2]
                     for kind,name in essential)
    assert right_edge == 276
    assert rect(node('Screen','GroupWindow'))[2] - right_edge == 12

def test_expanded_native_client_leaves_clearance_beyond_every_visible_control():
    window=node('Screen','GroupWindow')
    width,height=rect(window)[2:]
    client_width=width-4-4
    client_height=height-16-4-4
    assert client_width == 280 and client_height == 257
    for kind,names in (
        ('Gauge',('PlayerXPGauge_BG','PlayerXPGauge','P_Fatigue','P_Breath')),
        ('Label',('PlayerHP','PlayerMana','AC','WIS','INT','CHA','WGT','DR','GW_VantageVersionLabel')),
        ('StaticAnimation',('DRIcon','GW_VantageBrandMark')),
    ):
        for name in names:
            x,y,w,h=rect(node(kind,name))
            assert x+w+2 <= client_width
            assert y+h+2 <= client_height

def test_resist_cells_have_uniform_spacing_across_the_full_bar_width():
    names=('FR','CR','MR','PR','DR')
    icons=[rect(node('StaticAnimation',name+'Icon')) for name in names]
    values=[rect(node('Label',name)) for name in names]
    assert [r[0] for r in icons] == [129,160,191,222,253]
    assert [r[0] for r in values] == [126,157,188,219,250]
    for icon,value in zip(icons,values):
        assert icon[0]+icon[2]/2 == value[0]+value[2]/2
