import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.market import GearItem, gear_comparison_rows


ROOT = Path(__file__).resolve().parents[1]


def test_comparison_rows_report_values_deltas_and_tied_leaders():
    rows = gear_comparison_rows((
        GearItem(name='Base', ac=10, hp=100, awis=5),
        GearItem(name='Armor', ac=15, hp=50, awis=5),
        GearItem(name='Health', ac=8, hp=120, awis=2),
    ))
    ac = next(row for row in rows if row['key'] == 'ac')
    hp = next(row for row in rows if row['key'] == 'hp')
    wis = next(row for row in rows if row['key'] == 'awis')

    assert ac['values'] == (10, 15, 8)
    assert ac['deltas'] == (0, 5, -2)
    assert ac['leaders'] == (1,)
    assert hp['leaders'] == (2,)
    assert wis['leaders'] == (0, 1)


SCRIPT = r"""
import json

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QAbstractItemView, QPushButton, QTableWidget)

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.market import GearItem, WikiItemCard

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
panel = app._parsers_dict['market']
panel._refresh_timer.stop()
items = [
    GearItem(
        name='Base Robe', classes=8192, races=1, slots=131072,
        ac=10, hp=100, awis=5, wornName='Flowing Thought I'),
    GearItem(
        name='Armor Robe', classes=8192, races=1, slots=131072,
        ac=15, hp=50, awis=5, clickName='Shielding'),
    GearItem(
        name='Health Robe', classes=8192, races=1, slots=131072,
        ac=8, hp=120, awis=2, procName='Stun'),
]
panel._gear_model.set_items(items)
panel._gear_model.set_prices([
    {'n': 'Base Robe', 't': 0, 'a30': 1000, 't30': 3},
    {'n': 'Armor Robe', 't': 0, 'a30': 1400, 't30': 4},
    {'n': 'Health Robe', 't': 0, 'a30': 900, 't30': 2},
])
panel._begin_comparison({'n': 'Base Robe', '_gear': items[0]})
selection = panel.gear_table.selectionModel()
for row in (1, 2):
    index = panel._gear_proxy.mapFromSource(panel._gear_model.index(row, 0))
    selection.select(
        index,
        QItemSelectionModel.SelectionFlag.Select |
        QItemSelectionModel.SelectionFlag.Rows)
app.processEvents()
dialog = panel._open_comparison()
app.processEvents()
table = dialog.table
rows = {
    table.verticalHeaderItem(row).text(): row
    for row in range(table.rowCount())
}

card = WikiItemCard({'n': 'Base Robe', '_gear': items[0]}, panel)
requested = []
card.compare_requested.connect(
    lambda payload: requested.append(payload['_gear'].name))
card_button = card.compare_button
card_button.click()

result = {
    'mode': panel._compare_mode,
    'selection_mode': panel.gear_table.selectionMode().value,
    'multi_mode': QAbstractItemView.SelectionMode.MultiSelection.value,
    'base': panel._compare_base.name,
    'selected': [item.name for item in panel._selected_comparison_items()],
    'view_text': panel.compare_selected_button.text(),
    'view_enabled': panel.compare_selected_button.isEnabled(),
    'mode_name': panel.compare_mode_button.accessibleName(),
    'mode_description': panel.compare_mode_button.accessibleDescription(),
    'view_tip': panel.compare_selected_button.toolTip(),
    'dialog_title': dialog.windowTitle(),
    'table_name': table.accessibleName(),
    'table_description': table.accessibleDescription(),
    'headers': [
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())],
    'ac': [table.item(rows['AC'], column).text() for column in range(3)],
    'hp': [table.item(rows['HP'], column).text() for column in range(3)],
    'price': [
        table.item(rows['30d price'], column).text() for column in range(3)],
    'worn': [table.item(rows['Worn'], column).text() for column in range(3)],
    'summary': dialog.summary.text(),
    'card_enabled': card_button.isEnabled(),
    'card_tip': card_button.toolTip(),
    'card_requested': requested,
}
print(json.dumps(result))
dialog.close()
app.quit()
"""


def test_market_compare_mode_and_dialog_are_clear_and_keyboard_ready(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['mode'] is True
    assert result['selection_mode'] == result['multi_mode']
    assert result['base'] == 'Base Robe'
    assert result['selected'] == [
        'Base Robe', 'Armor Robe', 'Health Robe']
    assert result['view_text'] == 'View comparison · 3'
    assert result['view_enabled'] is True
    assert result['mode_name'] == 'Select Market items to compare'
    assert 'each click add or remove' in result['mode_description']
    assert 'stats, effects, and differences' in result['view_tip']
    assert result['dialog_title'] == 'Vantage · Compare Items'
    assert result['table_name'] == 'Item stat comparison'
    assert 'differences from the base item' in result['table_description']
    assert result['headers'] == [
        'BASE · Base Robe', 'Armor Robe', 'Health Robe']
    assert result['ac'] == [
        '+10 · BASE', 'BEST · +15 · vs BASE +5', '+8 · vs BASE -2']
    assert result['hp'] == [
        '+100 · BASE', '+50 · vs BASE -50',
        'BEST · +120 · vs BASE +20']
    assert result['price'] == [
        '1,000 pp · BASE', '1,400 pp · vs BASE +400 pp',
        '900 pp · vs BASE -100 pp']
    assert result['worn'] == ['Flowing Thought I', '—', '—']
    assert 'Build, class, slot, and effects' in result['summary']
    assert result['card_enabled'] is True
    assert 'Use this item as BASE' in result['card_tip']
    assert result['card_requested'] == ['Base Robe']
