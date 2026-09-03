import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
market = app._parsers_dict['market']
market._refresh_timer.stop()
market._model.set_items([{
    'n': 'Fungus Covered Scale Tunic',
    'a30': 900,
    't30': 4,
    't': 0,
}])
app.processEvents()

opened = []
market._show_wiki_card = lambda index=None: opened.append({
    'row': index.row(),
    'column': index.column(),
    'name': market._selected_item(index)['n'],
})
name_index = market._proxy.index(0, 0)
price_index = market._proxy.index(0, 1)
market.table.clicked.emit(price_index)
market.table.clicked.emit(name_index)
app.processEvents()

print(json.dumps({
    'opened': opened,
    'name_tooltip': name_index.data(3),
    'table_tooltip': market.table.toolTip(),
}))
app.quit()
"""


def test_pigparse_item_name_click_opens_only_the_item_link(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['opened'] == [{
        'row': 0,
        'column': 0,
        'name': 'Fungus Covered Scale Tunic',
    }]
    assert 'Open the compact item card' in result['name_tooltip']
    assert "Click an item's gold name" in result['table_tooltip']
