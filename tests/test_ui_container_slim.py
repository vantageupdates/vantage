"""Compact native containers retain real item slots and functional controls."""
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

ROOT = ET.parse(Path(__file__).resolve().parents[1] / 'ui/skin/EQUI_Container.xml').getroot()

def node(name):
    return ROOT.find(f"*[@item='{name}']")

def rect(name):
    n = node(name)
    return tuple(int(n.findtext(p)) for p in ('Location/X','Location/Y','Size/CX','Size/CY'))

@pytest.mark.parametrize('name,bounds', [
    ('Container_Label',(2,2,84,28)), ('Container_Icon',(24,32,40,40)),
    ('Container_Combine',(14,280,60,20)), ('Container_CloseButton',(19,304,50,20)),
    ('ContainerWindow',(350,100,88,334)),
])
def test_compact_centered_header_and_footer(name,bounds):
    assert rect(name) == bounds
    if name != 'ContainerWindow':
        assert bounds[0]*2 + bounds[2] == 88

def test_labels_and_controls_remain_separate():
    assert node('Container_Label').findtext('NoWrap') == 'false'
    assert rect('Container_Label')[3] >= 2*14
    for a,b in [('Container_Label','Container_Icon'),('Container_Icon','ContainerSlot1'),
                ('ContainerSlot9','Container_Combine'),('Container_Combine','Container_CloseButton')]:
        ra,rb=rect(a),rect(b)
        assert rb[1] - (ra[1]+ra[3]) >= 2
    assert node('Container_CloseButton').findtext('ScreenID') == 'DoneButton'
    assert node('Container_Combine').findtext('ScreenID') == 'Container_Combine'
    for name in ('Container_Combine','Container_CloseButton'):
        assert {x.tag for x in node(name).find('ButtonDrawTemplate')} == {
            'Normal','Pressed','Flyby','Disabled','PressedFlyby'}

@pytest.mark.parametrize('count',[2,4,6,8,10])
def test_native_slot_prefixes_preserve_sizes_and_indices(count):
    for i in range(count):
        n=node(f'ContainerSlot{i+1}')
        assert rect(f'ContainerSlot{i+1}') == (4+40*(i%2),76+40*(i//2),40,40)
        assert n.findtext('EQType') == str(30+i)
    assert node('ContainerWindow').findtext('Style_Sizable') == 'false'
    assert node('ContainerWindow').findtext('Style_Closebox') == 'true'

def test_slot_grid_has_equal_margins_and_tight_footer():
    width=rect('ContainerWindow')[2]
    left=rect('ContainerSlot1')[0]
    right=width-(rect('ContainerSlot2')[0]+rect('ContainerSlot2')[2])
    assert left == right == 4
    assert rect('ContainerWindow')[3]-(rect('Container_CloseButton')[1]+20) == 10
