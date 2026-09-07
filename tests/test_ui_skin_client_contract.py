"""Regression contracts from actual client errors and native inventory bounds."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
SCHOOLS = ('Magic', 'Fire', 'Cold', 'Disease', 'Poison')

def root(name):
    return ET.parse(SKIN / name).getroot()

def item(xml, kind, name):
    found = xml.find(f"{kind}[@item='{name}']")
    assert found is not None, (kind, name)
    return found

def rect(node):
    return tuple(int(node.findtext(path)) for path in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))

def forward_screen_references(xml):
    order = {node.get('item'): index for index, node in enumerate(xml) if node.tag == 'Screen'}
    errors = []
    for node in xml.findall('Screen'):
        for piece in node.findall('Pieces'):
            name = (piece.text or '').split(':')[-1].strip()
            if name in order and order[name] >= order[node.get('item')]:
                errors.append((node.get('item'), name))
    return errors

@pytest.mark.parametrize('filename', ['EQUI_PlayerWindow.xml', 'EQUI_GroupWindow.xml', 'EQUI_TargetWindow.xml'])
def test_nested_health_screens_are_declared_before_their_parent(filename):
    assert forward_screen_references(root(filename)) == []

def test_reproduces_four_actual_ui54_target_symbol_table_errors():
    xml = deepcopy(root('EQUI_TargetWindow.xml'))
    parent = item(xml, 'Screen', 'TargetWindow')
    xml.remove(parent)
    xml.insert(1, parent)
    assert forward_screen_references(xml) == [
        ('TargetWindow', f'VantageTarget_HP_{n}A_X') for n in range(1, 5)]

def bag_intrusions(xml, icon):
    x, y, width, height = rect(icon)
    pieces = {p.text.strip() for p in item(xml, 'Screen', 'InventoryWindow').findall('Pieces')}
    intrusions = []
    for slot in xml.findall('InvSlot'):
        if slot.get('item') not in pieces or slot.find('Location') is None:
            continue
        sx, sy, sw, sh = rect(slot)
        if y < sy + sh and sy < y + height and x < sx + sw and sx < x + width:
            intrusions.append(slot.get('item'))
    return intrusions

@pytest.mark.parametrize('school', SCHOOLS)
def test_inventory_resistance_icons_clear_slots_labels_and_window_edges(school):
    xml = root('EQUI_Inventory.xml')
    icon = item(xml, 'StaticAnimation', f'IW_Resist{school}Icon')
    label = item(xml, 'Label', f'IW_{school}')
    value = item(xml, 'Label', f'IW_{school}Number')
    x, y, w, h = rect(icon)
    lx, ly, lw, lh = rect(label)
    vx, vy, vw, vh = rect(value)
    assert (w, h) == (12, 12)
    assert bag_intrusions(xml, icon) == []
    # The rightmost bag column ends at 235; keep real space before the icon.
    for name in ('InvSlot28', 'InvSlot29'):
        sx, sy, sw, sh = rect(item(xml, 'InvSlot', name))
        assert x >= sx + sw + 4
    assert x + w + 2 <= lx and lx + lw + 4 <= vx
    assert ly == vy and ly + lh / 2 == y + h / 2
    window = item(xml, 'Screen', 'InventoryWindow')
    assert vx + vw <= int(window.findtext('Size/CX')) - 6
    assert y + h <= int(window.findtext('Size/CY')) - 6
    animation = item(root('EQUI_Animations.xml'), 'Ui2DAnimation', icon.findtext('Animation'))
    assert tuple(int(animation.findtext('Frames/Size/' + k)) for k in ('CX', 'CY')) == (w, h)

@pytest.mark.parametrize('school', SCHOOLS)
def test_reproduces_ui54_resistance_icon_overlap(school):
    xml = deepcopy(root('EQUI_Inventory.xml'))
    icon = item(xml, 'StaticAnimation', f'IW_Resist{school}Icon')
    icon.find('Location/X').text = '231'
    assert bag_intrusions(xml, icon), 'The previous four-pixel intrusion must be caught'
