"""Preserve dynamic class selection and keep the enlarged ornament clear of money."""
from pathlib import Path
import xml.etree.ElementTree as ET

SKIN=Path(__file__).resolve().parents[1]/'ui/skin'
ROOT=ET.parse(SKIN/'EQUI_Inventory.xml').getroot()

def node(name):
    return ROOT.find(f"*[@item='{name}']")

def rect(name):
    n=node(name)
    return tuple(int(n.findtext(p)) for p in ('Location/X','Location/Y','Size/CX','Size/CY'))

def test_native_class_binding_and_autoequip_are_preserved():
    assert node('ClassAnim').findtext('ScreenID') == 'ClassAnim'
    assert node('ClassAnim').find('Animation') is None
    assert node('IW_CharacterView').findtext('TooltipReference') == 'Drop Item Here to Auto Equip'
    assert [p.text for p in node('IW_CharacterView').findall('Pieces')] == ['IW_ClassFrame','ClassAnim']
    assert rect('ClassAnim') == (5,3,68,136)
    assert 68/64 == 136/128

def test_centered_between_left_edge_and_coins_and_clear_of_weight():
    assert rect('IW_CharacterView') == (2,162,78,142)
    x,y,w,h=rect('IW_CharacterView')
    assert x+5+68/2 == 82/2
    assert x+w < 82  # Coin icon rail.
    assert y+h < 305  # Weight text rail.
    assert y > 161  # Equipment row above.
    assert rect('IW_ClassFrame') == (0,0,78,142)

def test_frame_is_neutral_translucent_and_transparent_inside():
    data=(SKIN/'VantageClassFrame.tga').read_bytes()
    assert data[12:18] == bytes((128,0,0,1,32,40))
    assert len(data) == 18+128*256*4
    alphas=[]
    for y in range(256):
        for x in range(128):
            b,g,r,a=data[18+4*(y*128+x):22+4*(y*128+x)]
            assert r==g==b
            alphas.append(a)
            if not (2<=x<80 and 2<=y<144) or (15<x<64 and 15<y<130):
                assert a==0
    assert 20 < max(alphas) <= 48
    frame=node('A_VantageClassFrame').find('Frames')
    assert frame.findtext('Texture') == 'VantageClassFrame.tga'
    assert (frame.findtext('Size/CX'),frame.findtext('Size/CY')) == ('78','142')
