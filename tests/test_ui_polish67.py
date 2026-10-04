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

def test_pet_health_and_commands_are_centered_in_compact_window():
    xml=root('EQUI_PetInfoWindow.xml')
    expected={'Attack':(0,42,128,18),'Follow':(0,64,62,18),'Taunt':(66,64,62,18),
              'Guard':(0,86,62,18),'Sit':(66,86,62,18),'Stand':(66,86,62,18),
              'Back':(0,108,62,18),'Lost':(66,108,62,18)}
    tooltips={'Attack':'Pet Attack','Follow':'Pet Follow Me','Taunt':'Pet Taunt',
              'Guard':'Pet Guard Here','Sit':'Pet Sit Down','Stand':'Pet Stand Up',
              'Back':'Pet Back Off','Lost':'Dismiss your pet.'}
    parent=xml.find("Screen[@item='PetInfoWindow']")
    assert rect(parent)==(50,160,136,135)
    assert parent.findtext('DrawTemplate') == 'WDT_RoundedNoTitle'
    assert parent.findtext('Style_Titlebar') == 'false'
    templates=root('EQUI_Templates.xml')
    rounded=templates.find("WindowDrawTemplate[@item='WDT_RoundedNoTitle']")
    animations=root('EQUI_Animations.xml')
    insets={}
    for side,dimension in (('Left',2),('Right',2),('Top',3),('Bottom',3)):
        name=rounded.findtext('Border/'+side)
        insets[side]=rect(animations.find(f"Ui2DAnimation[@item='{name}']/Frames"))[dimension]
    assert insets == {'Left':4,'Right':4,'Top':4,'Bottom':4}
    client_width=rect(parent)[2]-insets['Left']-insets['Right']
    client_height=rect(parent)[3]-insets['Top']-insets['Bottom']
    assert (client_width,client_height) == (128,127)
    pieces=[n.text for n in parent.findall('Pieces')]
    assert pieces[:9] == ['PIW_BuffWindow','PIW_AttackButton','PIW_LostButton',
                          'PIW_BackButton','PIW_GuardButton','PIW_FollowButton',
                          'PIW_TauntButton','PIW_SitButton','PIW_StandButton']
    for name,box in expected.items():
        button=xml.find(f"Button[@item='PIW_{name}Button']")
        assert rect(button)==box
        assert button.findtext('ScreenID') == name+'Button'
        assert button.findtext('TooltipReference') == tooltips[name]
        assert button.find('Font') is None
        assert button.findtext('Style_Transparent')=='true' and button.findtext('Style_Border')=='false'
        assert pieces.count('PIW_'+name+'Button')==1
        assert box[0]>=0 and box[1]>=0
        assert box[0]+box[2]<=client_width and box[1]+box[3]<=client_height
        for state in ('Normal','Pressed','Flyby','Disabled','PressedFlyby'):
            prefix='A_VantageActions' if name=='Attack' else 'A_VantagePet'
            assert button.findtext('ButtonDrawTemplate/'+state) == prefix+state
    health=xml.find("Gauge[@item='Pet_HP_BG']")
    assert rect(health)==(12,5,104,34)
    assert health.findtext('Font')=='2'
    assert health.findtext('EQType')=='16'
    assert health.findtext('Text')=='No Pet'
    assert (health.findtext('TextOffsetX'),health.findtext('TextOffsetY'))==('37','0')
    assert health.find('AlignCenter') is None  # Unsupported on Titanium Gauge text.
    assert (health.findtext('GaugeOffsetX'),health.findtext('GaugeOffsetY'))==('0','14')
    assert health.findtext('GaugeDrawTemplate/Background')=='A_dzBackground'
    assert rect(health)[0] == client_width-(rect(health)[0]+rect(health)[2]) == 12
    # TextOffset is necessarily fixed; it centers the six-character fallback
    # and common-case pet name at native Font-2's five-pixel glyph width.
    text_left=rect(health)[0]+int(health.findtext('TextOffsetX'))
    assert text_left == 49
    assert text_left + len(health.findtext('Text'))*5/2 == client_width/2 == 64
    gauge_offset=int(health.findtext('GaugeOffsetX'))
    background= root('EQUI_Animations.xml').find("Ui2DAnimation[@item='A_dzBackground']/Frames")
    background_left=rect(health)[0]+gauge_offset
    background_width=rect(background)[2]
    assert (background_left,background_width)==(12,104)
    assert background_left == client_width-(background_left+background_width) == 12
    bar_left,_,bar_width,_=rect(xml.find("Gauge[@item='Pet_HP_0']"))
    assert (bar_left,bar_width)==(14,100)
    assert bar_left == client_width-(bar_left+bar_width) == 14
    assert bar_left+bar_width/2 == client_width/2 == 64
    assert bar_left-background_left == (background_left+background_width)-(bar_left+bar_width) == 2
    hp_label=xml.find("Label[@item='PIW_Pet_HPLabel']")
    assert rect(hp_label)==(0,5,18,12)
    assert hp_label.findtext('Font')=='1'
    assert hp_label.findtext('EQType')=='69'
    assert hp_label.findtext('AlignCenter')=='false'
    assert hp_label.findtext('AlignRight')=='true'
    percent_left,percent_top,percent_width,percent_height=rect(hp_label)
    assert percent_left>=0 and percent_top>=0
    assert percent_left+percent_width <= text_left
    assert percent_top+percent_height <= 19
    hidden_percent=xml.find("Label[@item='PIW_Pet_HPPercLabel']")
    assert rect(hidden_percent)==(109,3,1,1)
    for item in ('Pet_HP_0','Pet_HealthDetail','Pet_HP_VantageTicks'):
        assert rect(xml.find(f"*[@item='{item}']")) == (bar_left,19,bar_width,20)
    # Every threshold clip and complementary fill shares the same centered
    # 100px rail, while the large internal A gauges remain local at (0,0).
    clips=[n for n in xml.findall('Screen')
           if (n.get('item') or '').startswith('Pet_HP_')
           and n.get('item').endswith('A_X')]
    assert len(clips) == 22
    for clip in clips:
        clip_box=rect(clip)
        internal_name=clip.get('item')[:-2]
        complement_name=internal_name[:-1]+'B'
        internal=xml.find(f"Gauge[@item='{internal_name}']")
        complement=xml.find(f"Gauge[@item='{complement_name}']")
        assert clip_box[0] == bar_left and clip_box[1] == 19 and clip_box[3] == 20
        assert rect(internal)[:2] == (0,0)
        assert rect(complement)[1] == 19
        assert rect(complement)[0] == bar_left+clip_box[2]
        assert rect(complement)[0]+rect(complement)[2] == bar_left+bar_width
    attack=rect(xml.find("Button[@item='PIW_AttackButton']"))
    assert attack[0]==0 and client_width-(attack[0]+attack[2])==0
    assert attack[0]+attack[2]/2 == client_width/2 == 64
    follow=rect(xml.find("Button[@item='PIW_FollowButton']"))
    taunt=rect(xml.find("Button[@item='PIW_TauntButton']"))
    assert follow[0]==attack[0]==0
    assert taunt[0]-(follow[0]+follow[2])==4
    assert client_width-(taunt[0]+taunt[2])==0
    assert rect(xml.find("Button[@item='PIW_SitButton']")) == \
           rect(xml.find("Button[@item='PIW_StandButton']"))
    hidden=xml.find("Screen[@item='PIW_BuffWindow']")
    assert rect(hidden)==(-5000,0,0,0)
    hidden_pieces=[node.text for node in hidden.findall('Pieces')]
    assert hidden_pieces == [f'PIW_PetBuff{index}_Button' for index in range(30)]
    for index in range(30):
        buff=xml.find(f"Button[@item='PIW_PetBuff{index}_Button']")
        assert buff.findtext('ScreenID')==f'PetBuff{index}'
        assert tuple(int(buff.findtext(path)) for path in ('Size/CX','Size/CY'))==(1,1)
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
