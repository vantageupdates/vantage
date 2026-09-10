"""Native bindings and final-size asset contracts, not an in-game render test."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
STATS = ('HP', 'MANA', 'AC', 'ATK', 'EXP', 'STR', 'STA', 'AGI', 'DEX', 'WIS', 'INT', 'CHA')
YS = (50, 64, 78, 92, 114, 144, 158, 172, 186, 200, 214, 228)
VALUES = ('IW_CurrentHP', 'IW_MANANumber', 'IW_ACNumber', 'IW_ATKNumber',
          'IW_EXP_Percentage', 'IW_STRNumber', 'IW_STANumber', 'IW_AGINumber',
          'IW_DEXNumber', 'IW_WISNumber', 'IW_INTNumber', 'IW_CHANumber')
EQTYPES = ('70', '128', '22', '23', '26', '5', '6', '8', '7', '9', '10', '11')


def node(kind, name, filename='EQUI_Inventory.xml'):
    value = ET.parse(SKIN / filename).getroot().find(f"{kind}[@item='{name}']")
    assert value is not None, (kind, name)
    return value


def rect(n):
    return tuple(int(n.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def rgba(filename, x, y):
    data = (SKIN / filename).read_bytes()
    width = int.from_bytes(data[12:14], 'little')
    start = 18 + 4 * (y * width + x)
    b, g, r, a = data[start:start + 4]
    return r, g, b, a


@pytest.mark.parametrize('i', range(12))
def test_stat_icons_keep_native_values_and_clear_label_value_gutters(i):
    stat = STATS[i]
    icon = node('StaticAnimation', f'IW_Stat{stat}Icon')
    label = node('Label', 'IW_NextLevel' if stat == 'EXP' else 'IW_' + stat)
    value = node('Label', VALUES[i])
    assert rect(icon) == (251, YS[i] + 1, 12, 12)
    assert rect(label) == (265, YS[i], 31 if i < 5 else 62, 14)
    assert rect(value) == ((300, YS[i], 72, 14) if i < 5 else (334, YS[i], 38, 14))
    if i < 5:
        assert label.findtext('Font') == value.findtext('Font') == '2'
    assert value.findtext('EQType') == EQTYPES[i]
    assert value.findtext('AlignRight') == 'true'
    assert label.findtext('Text') == stat
    assert label.findtext('NoWrap') == 'true'
    assert int(label.findtext('Location/X')) + int(label.findtext('Size/CX')) + 4 <= int(value.findtext('Location/X'))
    assert icon.findtext('Animation') == f'A_VantageStat{stat}'
    pieces = [p.text for p in node('Screen', 'InventoryWindow').findall('Pieces')]
    assert pieces.count(icon.get('item')) == 1
    assert pieces.index(icon.get('item')) < pieces.index(label.get('item'))
    animation = node('Ui2DAnimation', icon.findtext('Animation'))
    assert rect(animation.find('Frames')) == (2 + 16 * (i % 4), 2 + 16 * (i // 4), 12, 12)


def test_weight_is_a_real_icon_with_separate_label_current_and_maximum():
    assert rect(node('StaticAnimation', 'IW_StatWEIGHTIcon')) == (4, 306, 12, 12)
    names = ('IW_Weight', 'IW_CurrentWeight', 'IW_WeightNumber', 'IW_MaxWeight')
    expected = ((20, 305, 46, 14), (70, 305, 42, 14), (115, 305, 4, 14), (122, 305, 29, 14))
    assert tuple(rect(node('Label', n)) for n in names) == expected
    assert node('Label', names[1]).findtext('EQType') == '24'
    assert node('Label', names[3]).findtext('EQType') == '25'
    assert node('Label', names[0]).findtext('Text') == 'WEIGHT'
    assert node('Label', names[2]).findtext('Text') == '/'
    assert rect(node('Ui2DAnimation', 'A_VantageStatWEIGHT').find('Frames')) == (2, 50, 12, 12)


@pytest.mark.parametrize('i,coin', tuple(enumerate(('Platinum', 'Gold', 'Silver', 'Copper'))))
def test_money_uses_unchanged_coins_outside_native_amount_hit_boxes(i, coin):
    button = node('Button', f'IW_Money{i}')
    icon = node('StaticAnimation', f'IW_Coin{i}Icon')
    assert button.findtext('ScreenID') == f'IW_Money{i}'
    assert rect(button) == (105, 181 + i * 25, 46, 22)
    assert rect(icon) == (82, 184 + i * 25, 18, 18)
    assert icon.findtext('Animation') == f'A_{coin}Coin'
    assert button.findtext('Font') == '2'
    assert button.findtext('Style_Transparent') == 'true'
    assert button.findtext('Style_Checkbox') == 'false'
    assert button.find('DecalOffset') is None and button.find('DecalSize') is None
    assert button.find('ButtonDrawTemplate/NormalDecal') is None
    # No invented button TextOffset, duplicate native binding, or fake money label.
    assert button.find('TextOffsetX') is None and button.find('EQType') is None
    assert 'Click the amount' in button.findtext('TooltipReference')
    for state in ('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled'):
        assert button.findtext('ButtonDrawTemplate/' + state) == 'A_VantageMoney' + state
    coin_animation = node('Ui2DAnimation', f'A_{coin}Coin', 'EQUI_Animations.xml')
    assert coin_animation.findtext('Frames/Texture') == 'window_pieces01.tga'
    assert rect(coin_animation.find('Frames')) == (90 + i * 18, 140, 18, 18)


def test_sprite_atlas_has_thirteen_distinct_alpha_sprites_and_clear_gutters():
    filename = 'VantageStatIcons.tga'
    data = (SKIN / filename).read_bytes()
    assert data[12:18] == bytes((64, 0, 64, 0, 32, 40))
    assert len(data) == 18 + 64 * 64 * 4
    sprite_hashes = set()
    for i in range(13):
        x, y = 2 + (i % 4) * 16, 2 + (i // 4) * 16
        pixels = [rgba(filename, x + a, y + b) for b in range(12) for a in range(12)]
        assert sum(c[3] > 32 for c in pixels) >= 22
        assert any(0 < c[3] < 255 for c in pixels)
        assert len(set(pixels)) >= 25
        sprite_hashes.add(hashlib.sha256(bytes(v for c in pixels for v in c)).digest())
    assert len(sprite_hashes) == 13
    for y in range(64):
        for x in range(64):
            if x % 16 < 2 or x % 16 >= 14 or y % 16 < 2 or y % 16 >= 14:
                assert rgba(filename, x, y)[3] == 0
    assert not (SKIN / 'vantage-stat-icons.png').exists()
    assert not (SKIN / 'vantage-weight-icon.png').exists()


@pytest.mark.parametrize('i,state', tuple(enumerate(('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled'))))
def test_money_faces_have_clear_round_corners_and_separated_states(i, state):
    assert rect(node('Ui2DAnimation', 'A_VantageMoney' + state).find('Frames')) == (2, 2 + 25 * i, 46, 22)
    y = 2 + 25 * i
    for x, dy in ((0, 0), (45, 0), (0, 21), (45, 21)):
        assert rgba('VantageMoneyControls.tga', 2 + x, y + dy)[3] == 0
    r, g, b, a = rgba('VantageMoneyControls.tga', 25, y + 11)
    assert r == g == b and a == 255  # Neutral, never tinted panel faces.


def test_inventory_height_and_bag_positions_remain_fixed_without_fake_capacity_gauges():
    root = ET.parse(SKIN / 'EQUI_Inventory.xml').getroot()
    assert rect(node('Screen', 'InventoryWindow')) == (100, 50, 389, 355)
    for i in range(8):
        slot = node('InvSlot', f'InvSlot{i + 22}')
        assert rect(slot) == (156 + 39 * (i // 4), 165 + 39 * (i % 4), 40, 40)
        assert slot.findtext('EQType') == str(i + 22)
    assert node('Gauge', 'IW_ExpGauge').findtext('EQType') == '4'
    assert not any('bag' in (n.get('item') or '').lower() for n in root.findall('Gauge'))
    for kind in ('Label', 'StaticAnimation', 'Button', 'Ui2DAnimation'):
        names = [n.get('item') for n in root.findall(kind)]
        assert len(names) == len(set(names))


def test_inventory_footer_actions_share_the_full_width_without_changing_bindings_or_order():
    screen = node('Screen', 'InventoryWindow')
    assert rect(screen) == (100, 50, 389, 355)

    visual_order = ('IW_DoneButton', 'IW_FacePick', 'IW_Skills', 'IW_Destroy')
    expected_x = (2, 99, 196, 293)
    expected_screen_ids = ('DoneButton', 'IW_FacePick', 'IW_Skills', 'IW_Destroy')
    expected_labels = ('Done', 'Face', 'Skills', 'Destroy')
    states = ('Normal', 'Pressed', 'Flyby', 'Disabled', 'PressedFlyby')

    buttons = [node('Button', name) for name in visual_order]
    assert tuple(rect(button) for button in buttons) == tuple(
        (x, 325, 94, 20) for x in expected_x
    )
    assert tuple(button.findtext('ScreenID') for button in buttons) == expected_screen_ids
    assert tuple(button.findtext('Text') for button in buttons) == expected_labels
    for button in buttons:
        assert tuple(button.findtext(f'ButtonDrawTemplate/{state}') for state in states) == tuple(
            f'A_Btn{state}' for state in states
        )

    # Four equal actions span the 389px footer with symmetric 2px outer margins
    # and consistent 3px gutters, without changing the native Pieces/focus order.
    assert expected_x[0] == 2
    assert 389 - (expected_x[-1] + 94) == 2
    assert tuple(expected_x[i + 1] - (expected_x[i] + 94) for i in range(3)) == (3, 3, 3)
    footer_piece_order = [
        piece.text for piece in screen.findall('Pieces') if piece.text in visual_order
    ]
    assert footer_piece_order == ['IW_Skills', 'IW_Destroy', 'IW_DoneButton', 'IW_FacePick']


def test_existing_resist_and_coin_art_are_not_repainted_or_resized():
    expected = {'window_pieces01.tga': '39077fbb9da9c5a5101eb11212cbe4a440eca56aeacdc6be42eda931e8927a2e',
                'v3_resists.tga': '9b111fc19afbc6d4b11639f37dc6d2bd86e928aac50d48048690ba4376dafba4'}
    for filename, digest in expected.items():
        assert hashlib.sha256((SKIN / filename).read_bytes()).hexdigest() == digest
