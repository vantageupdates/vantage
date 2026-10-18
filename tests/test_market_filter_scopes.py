"""Market's price and equipment pages retain independent browsing state."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
import os
from pathlib import Path

from native_audit_fixture import isolate
isolate()

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers import market as module

config.data['general']['startup_window_state'] = 'normal'
config.data['market']['server'] = 'Blue'
config.data['market']['live_watch_items'] = ['Jade Mace']
module.GreenMarket._start_deferred_refresh = lambda self: None
app = VantageApp([])
panel = app._parsers_dict['market']
panel._refresh_timer.stop()
panel.show()
panel.resize(980, 620)
QTest.qWait(30)
items = [
    module.GearItem('Crown of Insight', classes=8192, races=32, slots=4,
                    ac=12, aint=9, wornName='Flowing Thought I',
                    era='velious', nodrop=1),
    module.GearItem('Jade Mace', classes=1, races=1, slots=8192,
                    astr=3, procName='Shock', era='kunark'),
    module.GearItem('Iron Helm', classes=1, races=1, slots=4,
                    ac=8, era='classic'),
]
prices = [{'n': item.name, 't': 0, 'a30': (index + 1) * 100, 't30': 5}
          for index, item in enumerate(items)]
panel._model.set_items(prices)
panel._proxy.set_gear({module._item_key(item.name): item for item in items})
panel._gear_model.set_items(items)
panel._gear_model.set_prices(prices)
panel._set_gear_status('Synthetic P99 item index · 3 items')
panel._update_gear_summary()
panel._local_model.add({'time': '12:00', 'seller': 'Synthetic trader',
                        'message': 'WTS Jade Mace'})
panel.live_search.setText('jade')
panel.live_table.selectRow(0)
panel.status.setText('Synthetic PigParse Blue prices · 3 items')

def choose(combo, data):
    index = combo.findData(data)
    assert index >= 0, data
    combo.setCurrentIndex(index)

def state(proxy, table):
    header = table.horizontalHeader()
    return {
        'query': proxy.query,
        'bits': [proxy.class_bit, proxy.race_bit, proxy.slot_bit],
        'sort': [header.sortIndicatorSection(), header.sortIndicatorOrder().value],
        'rows': [proxy.index(row, 0).data() for row in range(proxy.rowCount())],
        'selected': [index.data() for index in table.selectionModel().selectedRows()],
        'current': table.currentIndex().data(),
    }

def set_price_filters():
    panel.search.setText('jade')
    choose(panel.class_filter, 1)
    choose(panel.race_filter, 1)
    choose(panel.slot_filter, 8192)
    panel.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
    panel.table.selectRow(0)

def set_gear_filters():
    panel.gear_search.setText('flowing thought')
    choose(panel.gear_class_filter, 8192)
    choose(panel.gear_race_filter, 32)
    choose(panel.gear_slot_filter, 4)
    choose(panel.stat_sort, 'aint')
    choose(panel.effect_filter, 'worn')
    choose(panel.tradeability_filter, 'nodrop')
    choose(panel.era_filter, 'velious')
    panel.gear_table.selectRow(0)

set_price_filters()
price_state = state(panel._proxy, panel.table)
set_gear_filters()
assert state(panel._proxy, panel.table) == price_state
gear_state = state(panel._gear_proxy, panel.gear_table)
assert price_state['rows'] == ['Jade Mace']
assert gear_state['rows'] == ['Crown of Insight']
for index in (panel._gear_tab_index, panel._live_tab_index,
              panel._auction_tab_index, 0, panel._gear_tab_index):
    panel.tabs.setCurrentIndex(index)
    app.processEvents()
    assert state(panel._proxy, panel.table) == price_state
    assert state(panel._gear_proxy, panel.gear_table) == gear_state

capture_dir = os.environ.get('VANTAGE_MARKET_CAPTURE_DIR')
if capture_dir:
    output = Path(capture_dir)
    output.mkdir(parents=True, exist_ok=True)
    for index, name in ((0, 'prices-filtered'), (panel._gear_tab_index, 'gear-filtered')):
        panel.tabs.setCurrentIndex(index)
        QTest.qWait(30)
        panel.grab().save(str(output / (name + '.png')))

panel.tabs.setCurrentIndex(panel._gear_tab_index)
panel.gear_clear_filters_button.click()
app.processEvents()
assert state(panel._proxy, panel.table) == price_state
assert panel.gear_search.text() == ''
assert [control.currentIndex() for control in (
    panel.gear_class_filter, panel.gear_race_filter, panel.gear_slot_filter,
    panel.stat_sort, panel.effect_filter, panel.tradeability_filter,
    panel.era_filter)] == [0] * 7
assert panel._gear_model.active_stat == 'ac'
assert panel._gear_proxy.rowCount() == 3
assert not panel.gear_table.selectionModel().hasSelection()
assert not panel.gear_table.currentIndex().isValid()
set_gear_filters()
gear_state = state(panel._gear_proxy, panel.gear_table)
panel.tabs.setCurrentIndex(0)
panel.clear_filters_button.click()
app.processEvents()
assert state(panel._gear_proxy, panel.gear_table) == gear_state
assert panel.search.text() == ''
assert [control.currentIndex() for control in (
    panel.class_filter, panel.race_filter, panel.slot_filter)] == [0] * 3
assert panel._proxy.rowCount() == 3
assert panel.table.horizontalHeader().sortIndicatorSection() == 0
assert not panel.table.selectionModel().hasSelection()
assert not panel.table.currentIndex().isValid()
assert panel._server == 'Blue'
assert config.data['market']['live_watch_items'] == ['Jade Mace']
assert panel.live_search.text() == 'jade'
assert panel.live_table.selectionModel().hasSelection()

price_controls = (panel.search, panel.class_filter, panel.race_filter,
                  panel.slot_filter, panel.clear_filters_button)
gear_controls = (panel.gear_search, panel.gear_clear_filters_button,
                 panel.gear_class_filter, panel.gear_race_filter,
                 panel.gear_slot_filter, panel.stat_sort, panel.effect_filter,
                 panel.tradeability_filter, panel.era_filter,
                 panel.recharge_guide_button)
assert all(panel.tabs.widget(0).isAncestorOf(control) for control in price_controls)
assert all(panel.tabs.widget(panel._gear_tab_index).isAncestorOf(control)
           for control in gear_controls)

def rect(control):
    return [control.x(), control.y(), control.width(), control.height()]

layouts = {}
for tab, controls, table in ((0, price_controls, panel.table),
                            (panel._gear_tab_index, gear_controls, panel.gear_table)):
    panel.tabs.setCurrentIndex(tab)
    panel.resize(980, 620)
    QTest.qWait(30)
    layouts[tab] = [rect(control) for control in controls]
    panel.resize(245, 155)
    QTest.qWait(30)
    assert [rect(control) for control in controls] == layouts[tab]
    assert all(control.isVisibleTo(panel._surface) for control in controls)
    assert all(control.toolTip() and control.accessibleName() for control in controls)
    controls[0].clear()
    controls[0].setFocus(Qt.FocusReason.OtherFocusReason)
    for expected in (*controls[1:], table):
        QTest.keyClick(panel._scale_view.viewport(), Qt.Key.Key_Tab)
        assert panel._surface.focusWidget() is expected, (
            expected.accessibleName(), panel._surface.focusWidget())
    for expected in reversed(controls):
        QTest.keyClick(panel._scale_view.viewport(), Qt.Key.Key_Backtab)
        assert panel._surface.focusWidget() is expected, (
            expected.accessibleName(), panel._surface.focusWidget())

print(json.dumps({'independent': True, 'clear_scoped': True,
                  'keyboard': True, 'compact': True}))
panel.close()
app.quit()
'''


@pytest.fixture(scope='module')
def market_filter_scopes(tmp_path_factory):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))
    env['VANTAGE_DATA_DIR'] = str(tmp_path_factory.mktemp('market-scopes') / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout + '\n' + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_price_and_gear_filters_keep_independent_results_across_tabs(market_filter_scopes):
    assert market_filter_scopes['independent']


def test_each_clear_preserves_other_page_selection_sort_and_watchlist(market_filter_scopes):
    assert market_filter_scopes['clear_scoped']


def test_page_filters_keep_keyboard_order_and_compact_layout(market_filter_scopes):
    assert market_filter_scopes['keyboard'] and market_filter_scopes['compact']
