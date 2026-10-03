"""Native pixel/viewport contracts, not a certification of the game's renderer."""
from itertools import combinations
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
STATES = ('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled')
FAMILIES = (
    ('EQUI_Inventory.xml', 'A_VantageInventoryFooter', 2, 2, 123,
     ('IW_Skills', 'IW_Destroy', 'IW_DoneButton')),
    ('EQUI_BankWnd.xml', 'A_VantageBankFooter', 130, 2, 61,
     ('BW_ChangeButton', 'BW_DoneButton')),
    ('EQUI_Container.xml', 'A_VantageContainerCombine', 2, 128, 60,
     ('Container_Combine',)),
    ('EQUI_Container.xml', 'A_VantageContainerDone', 67, 128, 50,
     ('Container_CloseButton',)),
    ('EQUI_ActionsWindow.xml', 'A_VantageSocial', 67, 128, 50,
     tuple(f'ASP_SocialButton{i}' for i in range(1, 13))),
)


def root(filename):
    return ET.parse(SKIN / filename).getroot()


def item(xml, kind, name):
    matches = xml.findall(f"{kind}[@item='{name}']")
    assert len(matches) == 1, (kind, name)
    return matches[0]


def rect(node):
    return tuple(int(node.findtext(p)) for p in
                 ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def pixel(x, y):
    data = (SKIN / 'VantageCompactControls.tga').read_bytes()
    start = 18 + 4 * (y * 256 + x)
    return tuple(data[start:start + 4])


def client_size(xml, parent_name):
    parent = item(xml, 'Screen', parent_name)
    templates, animations = root('EQUI_Templates.xml'), root('EQUI_Animations.xml')
    template = item(templates, 'WindowDrawTemplate', parent.findtext('DrawTemplate'))
    border = template.find('Border')
    insets = {}
    for side, dimension in (('Left', 'CX'), ('Right', 'CX'),
                            ('Top', 'CY'), ('Bottom', 'CY')):
        frame = item(animations, 'Ui2DAnimation', border.findtext(side)).find('Frames')
        insets[side] = int(frame.findtext('Size/' + dimension)) - int(border.findtext('Overlap' + side))
    title = 0
    if parent.findtext('Style_Titlebar') == 'true':
        title_frame = item(animations, 'Ui2DAnimation',
                           template.findtext('Titlebar/Middle')).find('Frames')
        title = int(title_frame.findtext('Size/CY'))
    return (int(parent.findtext('Size/CX')) - insets['Left'] - insets['Right'],
            int(parent.findtext('Size/CY')) - insets['Top'] - insets['Bottom'] - title)


def assert_no_overlap(boxes):
    for (a_name, (ax, ay, aw, ah)), (b_name, (bx, by, bw, bh)) in combinations(boxes, 2):
        assert not (ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah), (a_name, b_name)


def test_dedicated_atlas_is_flat_top_origin_with_matching_texture_declaration():
    data = (SKIN / 'VantageCompactControls.tga').read_bytes()
    assert data[:3] == bytes((0, 0, 2))
    assert data[12:18] == bytes((0, 1, 0, 1, 32, 40))
    assert len(data) == 18 + 256 * 256 * 4
    declaration = item(root('EQUI_Animations.xml'), 'TextureInfo', 'VantageCompactControls.tga')
    assert (declaration.findtext('Size/CX'), declaration.findtext('Size/CY')) == ('256', '256')


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('state_index,state', tuple(enumerate(STATES)))
def test_every_button_state_matches_its_hit_box_and_has_clear_rounded_edges(family, state_index, state):
    filename, prefix, x, base_y, width, button_names = family
    xml = root(filename)
    animation = item(xml, 'Ui2DAnimation', prefix + state)
    frame = animation.find('Frames')
    y = base_y + 23 * state_index
    assert animation.findtext('Cycle') == 'false'
    assert frame.findtext('Texture') == 'VantageCompactControls.tga'
    assert rect(frame) == (x, y, width, 20)
    assert x + width <= 256 and y + 20 <= 256
    for name in button_names:
        button = item(xml, 'Button', name)
        assert rect(button)[2:] == (width, 20)
        assert button.findtext('ButtonDrawTemplate/' + state) == prefix + state
        assert list(xml).index(animation) < list(xml).index(button)
        assert button.findtext('Style_Checkbox', 'false') == 'false'
        assert button.find('TextOffsetX') is None
    for px, py in ((x, y), (x + width - 1, y),
                   (x, y + 19), (x + width - 1, y + 19)):
        assert pixel(px, py)[3] == 0
    assert pixel(x + width // 2, y + 10)[3] == 255
    alphas = {pixel(x + dx, y + dy)[3] for dx in range(6) for dy in range(6)}
    assert len(alphas - {0, 255}) >= 4
    for py in range(y - 1, y + 21):
        assert pixel(x - 1, py)[3] == pixel(x + width, py)[3] == 0
    for px in range(x - 1, x + width + 1):
        assert pixel(px, y - 1)[3] == pixel(px, y + 20)[3] == 0


def test_compact_faces_have_distinct_states_and_do_not_tint_native_text():
    for _, _, x, y, width, _ in FAMILIES:
        centers = [pixel(x + width // 2, y + 23 * i + 10) for i in range(5)]
        assert len(set(centers)) == 5
        assert all(b == g == r and a == 255 for b, g, r, a in centers)


def test_bag_slots_have_nonoverlapping_native_hit_boxes_and_footer_clearance():
    xml = root('EQUI_Inventory.xml')
    bags = [(f'InvSlot{i}', rect(item(xml, 'InvSlot', f'InvSlot{i}'))) for i in range(22, 30)]
    assert_no_overlap(bags)
    equipment = [(f'InvSlot{i}', rect(item(xml, 'InvSlot', f'InvSlot{i}'))) for i in range(1, 22)]
    assert_no_overlap(equipment + bags)
    client_width, client_height = client_size(xml, 'InventoryWindow')
    assert (client_width, client_height) == (381, 350)
    actions = [(name, rect(item(xml, 'Button', name))) for name in
               ('IW_DoneButton', 'IW_Skills', 'IW_Destroy')]
    assert_no_overlap(bags + actions)
    assert actions[0][1][1] - max(y + h for _, (_, y, _, h) in bags) == 3
    assert actions[0][1][0] == client_width - (actions[-1][1][0] + actions[-1][1][2]) == 3
    for _, (x, y, w, h) in bags + actions:
        assert x >= 0 and y >= 0 and x + w <= client_width and y + h <= client_height


def test_previous_39px_pitch_is_detected_as_hit_box_overlap():
    old_bags = [(f'InvSlot{i + 22}', (156 + 39 * (i // 4), 165 + 39 * (i % 4), 40, 40))
                for i in range(8)]
    with pytest.raises(AssertionError):
        assert_no_overlap(old_bags)
