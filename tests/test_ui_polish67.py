"""Native geometry and alpha regressions for UI67 (not an in-game renderer)."""
from itertools import combinations
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'

def root(name):
    return ET.parse(SKIN / name).getroot()

def rect(node):
    return tuple(int(node.findtext(path)) for path in ('Location/X','Location/Y','Size/CX','Size/CY'))

def pixel_reader(name):
    data = (SKIN / name).read_bytes()
    assert data[2] == 2 and data[16:18] == bytes((32,40))
    width = int.from_bytes(data[12:14], 'little')
    def pixel(x,y):
        pos=18+4*(y*width+x)
        return tuple(data[pos:pos+4])
    return pixel

@pytest.mark.parametrize('name,left,top', [
    ('classic_pieces01.tga',0,117),
    *[('VantageSlotHints.tga',2+42*(i%6),2+42*(i//6)) for i in range(18)],
])
def test_slot_backgrounds_clear_the_pointed_corners(name,left,top):
    pixel=pixel_reader(name)
    assert all(pixel(left+x,top+y)==(0,0,0,0) for x in (0,1,38,39) for y in (0,1,38,39))
    assert pixel(left+20,top+20)[3] == 255
    assert len({pixel(left+x,top+y)[3] for x in range(8) for y in range(8)} - {0,255}) >= 4

@pytest.mark.parametrize('left,top', [(start+14*i,y) for start,y in ((148,2),(364,42)) for i in range(5)])
def test_title_button_corners_have_no_square_backing(left,top):
    pixel=pixel_reader('quickbar_frames.tga')
    assert all(pixel(left+x,top+y)==(0,0,0,0) for x in (0,1,10,11) for y in (0,1,10,11))
    assert pixel(left+6,top+6)[3] > 0
    assert len({pixel(left+x,top+y)[3] for x in range(6) for y in range(6)} - {0,255}) >= 3

@pytest.mark.parametrize('width,height', [(144,120),(250,150),(421,200),(900,600)])
def test_chat_input_keeps_height_and_clearance_when_resized(width,height):
    xml=root('EQUI_ChatWindow.xml')
    entry=xml.find("Editbox[@item='CW_ChatInput']")
    output=xml.find("STMLbox[@item='CW_ChatOutput']")
    assert entry.findtext('ScreenID') == 'CWChatInput'
    assert output.findtext('ScreenID') == 'CWChatOutput'
    assert entry.findtext('DrawTemplate') == 'WDT_VantageSlotGold'
    assert entry.findtext('Style_Transparent') == entry.findtext('Style_Border') == 'true'
    assert entry.findtext('AutoStretch') == output.findtext('AutoStretch') == 'true'
    assert entry.findtext('TopAnchorToTop') == entry.findtext('BottomAnchorToTop') == 'false'
    assert entry.findtext('RightAnchorToLeft') == 'false'
    left=int(entry.findtext('LeftAnchorOffset')); right=width-int(entry.findtext('RightAnchorOffset'))
    top=height-int(entry.findtext('TopAnchorOffset')); bottom=height-int(entry.findtext('BottomAnchorOffset'))
    assert left == width-right == 6 and right > left
    assert bottom-top == 21 and height-bottom == 6
    assert top-(height-int(output.findtext('BottomAnchorOffset'))) == 3
    parent=xml.find("Screen[@item='ChatWindow']")
    assert rect(parent) == (95,280,421,200)
    assert parent.findtext('Style_Sizable') == 'true'

def test_pet_commands_have_four_pixel_gutters_without_resizing_window():
    xml=root('EQUI_PetInfoWindow.xml')
    expected={'Attack':(4,42,128,18),'Follow':(4,64,62,18),'Taunt':(70,64,62,18),
              'Guard':(4,86,62,18),'Sit':(70,86,62,18),'Stand':(70,86,62,18),
              'Back':(4,108,62,18),'Lost':(70,108,62,18)}
    parent=xml.find("Screen[@item='PetInfoWindow']")
    assert rect(parent)==(50,160,144,135)
    pieces=[n.text for n in parent.findall('Pieces')]
    for name,box in expected.items():
        button=xml.find(f"Button[@item='PIW_{name}Button']")
        assert rect(button)==box
        assert button.findtext('ScreenID') == name+'Button'
        assert button.findtext('Style_Transparent')=='true' and button.findtext('Style_Border')=='false'
        assert pieces.count('PIW_'+name+'Button')==1
        assert box[0]>=4 and box[0]+box[2]<=132 and box[1]+box[3]<=126
        for state in ('Normal','Pressed','Flyby','Disabled','PressedFlyby'):
            prefix='A_VantageActions' if name=='Attack' else 'A_VantagePet'
            assert button.findtext('ButtonDrawTemplate/'+state) == prefix+state
    # Sit/Stand are existing mutually exclusive native aliases, not two active buttons.
    for a,b in combinations([v for k,v in expected.items() if k!='Stand'],2):
        ax,ay,aw,ah=a; bx,by,bw,bh=b
        assert max(bx-(ax+aw),ax-(bx+bw),by-(ay+ah),ay-(by+bh)) >= 4

@pytest.mark.parametrize('state,left,top', [('Normal',128,34),('Flyby',256,34),('Pressed',256,54),('PressedFlyby',256,74),('Disabled',256,94)])
def test_pet_half_width_art_is_native_size_and_isolated(state,left,top):
    frame=root('EQUI_PetInfoWindow.xml').find(f"Ui2DAnimation[@item='A_VantagePet{state}']/Frames")
    assert frame.findtext('Texture')=='VantageControlEdges.tga' and rect(frame)==(left,top,62,18)
    pixel=pixel_reader('VantageControlEdges.tga')
    for y in range(18):
        for x in range(62):
            assert pixel(left+x,top+y)[3]==pixel(left+61-x,top+y)[3]==pixel(left+x,top+17-y)[3]
    assert all(pixel(left+x,top+y)[3]==0 for x in (-1,62) for y in range(-1,19))
    assert all(pixel(left+x,top+y)[3]==0 for x in range(-1,63) for y in (-1,18))
    assert all(pixel(left+x,top)[3]==0 for x in range(5))
