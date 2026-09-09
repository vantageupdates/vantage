"""Geometry regressions from UI69 client captures; native font rendering is manual."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
STATS = ('HP', 'MANA', 'AC', 'ATK', 'EXP', 'STR', 'STA', 'AGI', 'DEX', 'WIS', 'INT', 'CHA')
RESISTS = ('Magic', 'Fire', 'Cold', 'Disease', 'Poison')
ICONS = tuple('IW_Stat' + s + 'Icon' for s in STATS) + tuple('IW_Resist' + s + 'Icon' for s in RESISTS)


def root():
    return ET.parse(SKIN / 'EQUI_Inventory.xml').getroot()


def item(xml, kind, name):
    n = xml.find(f"{kind}[@item='{name}']")
    assert n is not None
    return n


def rect(n):
    return tuple(int(n.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def rightmost_slot(xml):
    members = {p.text for p in item(xml, 'Screen', 'InventoryWindow').findall('Pieces')}
    return max(rect(n)[0] + rect(n)[2] for n in xml.findall('InvSlot')
               if n.get('item') in members and n.find('Location') is not None)


@pytest.mark.parametrize('name', ICONS)
def test_all_stat_and_resist_icons_have_ten_pixels_of_clear_space(name):
    xml = root()
    assert rightmost_slot(xml) == 241
    x, _, w, h = rect(item(xml, 'StaticAnimation', name))
    assert x - rightmost_slot(xml) == 10
    assert (w, h) == (12, 12)


def test_old_icon_rail_reproduces_the_reported_equipment_overlap():
    xml = root()
    icon = deepcopy(item(xml, 'StaticAnimation', 'IW_StatHPIcon'))
    icon.find('Location/X').text = '239'
    # Bags end at 235, but equipment ends at 241: UI69 overlapped by 2px.
    assert rect(icon)[0] - rightmost_slot(xml) == -2
    assert rect(icon)[0] - rightmost_slot(xml) < 10


@pytest.mark.parametrize('name,sample', (
    ('IW_CurrentHP', '1,000/1,000'), ('IW_MANANumber', '1,000/1,000'),
    ('IW_ACNumber', '1,000'), ('IW_ATKNumber', '1,000'), ('IW_EXP_Percentage', '100.0%'),
))
def test_resource_values_budget_four_digits_without_touching_the_outer_frame(name, sample):
    xml = root()
    value = item(xml, 'Label', name)
    x, _, width, height = rect(value)
    assert (x, width, height) == (300, 72, 14)
    assert value.findtext('Font') == '2'
    # Conservative Font-2 ink budget, not a claim about measured client glyphs.
    # Number formatting remains native: commas here stress width, not replace data.
    assert len(sample) * 6 <= width - 6
    assert value.findtext('AlignRight') == 'true'
    assert int(item(xml, 'Screen', 'InventoryWindow').findtext('Size/CX')) - x - width == 17


@pytest.mark.parametrize('stat', STATS[5:] + RESISTS)
def test_attribute_and_resist_values_allow_1000_at_the_same_right_edge(stat):
    xml = root()
    label = item(xml, 'Label', 'IW_' + stat)
    value = item(xml, 'Label', 'IW_' + stat + 'Number')
    lx, _, lw, _ = rect(label)
    vx, _, vw, _ = rect(value)
    assert (lx, lw, vx, vw) == (265, 62, 334, 38)
    assert vx - (lx + lw) == 7
    assert len('1,000') * 6 <= vw - 6
    assert vx + vw == 372


def test_heading_xp_and_window_match_the_expanded_right_hand_area():
    xml = root()
    assert rect(item(xml, 'Screen', 'InventoryWindow')) == (100, 50, 389, 355)
    assert rect(item(xml, 'Gauge', 'IW_ExpGauge')) == (254, 129, 118, 8)
    for name in ('IW_Name', 'IW_Deity', 'IW_Class'):
        x, _, w, _ = rect(item(xml, 'Label', name))
        assert x + w == 372
    assert item(xml, 'Gauge', 'IW_ExpGauge').findtext('EQType') == '4'
    assert item(xml, 'Gauge', 'IW_ExpGauge').findtext('DrawLinesFill') == 'true'
    assert item(xml, 'Gauge', 'IW_ExpGauge').findtext('GaugeDrawTemplate/Fill') == 'A_GaugeFill'
