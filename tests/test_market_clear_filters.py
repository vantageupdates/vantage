import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from native_audit_fixture import isolate
isolate()

from PySide6.QtCore import Qt

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers import market as market_module

config.data['general']['startup_window_state'] = 'normal'
config.data['market']['server'] = 'Blue'
config.data['market']['live_watch_items'] = ['Manastone']
app = VantageApp([])
panel = app._parsers_dict['market']
panel._refresh_timer.stop()
panel.show()
app.processEvents()

announcements = []
market_module._announce_accessible = (
    lambda _widget, text, assertive=False: announcements.append(text))
panel.tabs.setCurrentIndex(panel._gear_tab_index)
panel.gear_search.setText('flowing thought')
panel.gear_class_filter.setCurrentIndex(14)
panel.gear_race_filter.setCurrentIndex(6)
panel.gear_slot_filter.setCurrentIndex(3)
panel.stat_sort.setCurrentIndex(8)
panel.effect_filter.setCurrentIndex(3)
panel.tradeability_filter.setCurrentIndex(2)
panel.era_filter.setCurrentIndex(3)
panel.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
panel.gear_clear_filters_button.click()
app.processEvents()

print(json.dumps({
    'search': panel.gear_search.text(),
    'indices': [
        panel.gear_class_filter.currentIndex(), panel.gear_race_filter.currentIndex(),
        panel.gear_slot_filter.currentIndex(), panel.stat_sort.currentIndex(),
        panel.effect_filter.currentIndex(),
        panel.tradeability_filter.currentIndex(), panel.era_filter.currentIndex(),
    ],
    'active_stat': panel._gear_model.active_stat,
    'price_sort': [panel.table.horizontalHeader().sortIndicatorSection(),
                   panel.table.horizontalHeader().sortIndicatorOrder().value],
    'gear_sort': [panel.gear_table.horizontalHeader().sortIndicatorSection(),
                  panel.gear_table.horizontalHeader().sortIndicatorOrder().value],
    'server': panel._server,
    'watchlist': config.data['market']['live_watch_items'],
    'tab': panel.tabs.currentIndex(),
    'button_visible': panel.gear_clear_filters_button.isVisibleTo(panel._surface),
    'button_name': panel.gear_clear_filters_button.accessibleName(),
    'button_description': panel.gear_clear_filters_button.accessibleDescription(),
    'button_tip': panel.gear_clear_filters_button.toolTip(),
    'status': panel.status.text(),
    'announcements': announcements,
}))
app.quit()
"""


def test_clear_gear_filters_preserves_price_sort_and_user_context(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['search'] == ''
    assert result['indices'] == [0, 0, 0, 0, 0, 0, 0]
    assert result['active_stat'] == 'ac'
    assert result['price_sort'][0] == 2
    assert result['gear_sort'][0] == 3
    assert result['server'] == 'Blue'
    assert result['watchlist'] == ['Manastone']
    assert result['tab'] == 1
    assert result['button_visible'] is True
    assert result['button_name'] == 'Clear Gear search and filters'
    assert 'without changing PigParse filters' in result['button_description']
    assert 'keeps PigParse filters, server, and watchlist' in result['button_tip']
    assert result['status'] == 'Gear filters cleared'
    assert result['announcements'] == ['Gear filters cleared']
