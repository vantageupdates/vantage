import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers.market import (
    _cache_file, _wiki_cache_paths, market_detail_api, market_endpoint,
    normalize_market_server, pigparse_server_url)


ROOT = Path(__file__).resolve().parents[1]


def test_market_server_helpers_and_caches_are_isolated():
    assert normalize_market_server("blue") == "Blue"
    assert normalize_market_server("not-a-server") == "Green"
    assert market_endpoint("Blue").endswith("/getall/Blue")
    assert market_detail_api("Blue").endswith(
        "/getdetails/Blue/{item_name}")
    assert pigparse_server_url("Blue").endswith("/ServerIndex/Blue")
    assert _cache_file("Green") != _cache_file("Blue")
    assert _wiki_cache_paths("Manastone", "Green")[0] != (
        _wiki_cache_paths("Manastone", "Blue")[0])
    # Icons and P99 item metadata are shared; only auction-price JSON differs.
    assert _wiki_cache_paths("Manastone", "Green")[1] == (
        _wiki_cache_paths("Manastone", "Blue")[1])


def test_market_server_config_normalizes_and_defaults():
    original = copy.deepcopy(config.data)
    try:
        config.data = {"market": {"server": "blue"}}
        config.verify_settings()
        assert config.data["market"]["server"] == "Blue"

        config.data = {"market": {"server": "Teal"}}
        config.verify_settings()
        assert config.data["market"]["server"] == "Green"
    finally:
        config.data = original


SCRIPT = r"""
import datetime
import json

from PySide6.QtNetwork import QNetworkReply

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.market import _cache_file


def cache(server, item, price):
    _cache_file(server).write_text(json.dumps({
        'server': server,
        'source': 'test',
        'updated_at': datetime.datetime.now().astimezone().isoformat(),
        'items': [{'n': item, 't': 0, 'a30': price, 't30': 4}],
    }), encoding='utf-8')


class Reply:
    def __init__(self, server, items):
        self.server = server
        self.items = items
        self.deleted = False
    def property(self, name):
        return self.server if name == 'market_server' else None
    def error(self):
        return QNetworkReply.NetworkError.NoError
    def errorString(self):
        return ''
    def readAll(self):
        return json.dumps(self.items).encode('utf-8')
    def deleteLater(self):
        self.deleted = True


config.data['market']['server'] = 'Green'
app = VantageApp([])
panel = app._parsers_dict['market']
panel._refresh_timer.stop()
cache('Green', 'Green Stone', 111)
cache('Blue', 'Blue Pearl', 222)
panel._load_cache('Green')
panel._local_model.add({
    'time': '12:00:00', 'seller': 'Localtrader',
    'message': 'WTS local item'})

refreshes = []
panel.refresh = lambda: refreshes.append(panel._server)
panel.server_selector.setCurrentText('Blue')
app.processEvents()

after_switch = [item['n'] for item in panel._model.items]
local_count = len(panel._local_model.items)
_cache_file('Blue').write_text(json.dumps({
    'server': 'Green',
    'updated_at': datetime.datetime.now().astimezone().isoformat(),
    'items': [{'n': 'Mislabeled Green Cache', 't': 0, 'a30': 777}],
}), encoding='utf-8')
mismatched_loaded = panel._load_cache('Blue')
after_mismatched_cache = [item['n'] for item in panel._model.items]
late = Reply('Green', [
    {'n': 'Late Green Reply', 't': 0, 'a30': 999, 't30': 9}])
panel._requests_in_flight.add('Green')
panel._finished(late)
green_cache = json.loads(_cache_file('Green').read_text(encoding='utf-8'))

result = {
    'server': panel._server,
    'configured': config.data['market']['server'],
    'selector': panel.server_selector.currentText(),
    'selector_name': panel.server_selector.accessibleName(),
    'selector_description': panel.server_selector.accessibleDescription(),
    'selector_tooltip': panel.server_selector.toolTip(),
    'window_title': panel.windowTitle(),
    'panel_title': panel._title.text(),
    'search_name': panel.search.accessibleName(),
    'refresh_tip': panel._refresh_button.toolTip(),
    'history_tip': panel._detail_button.toolTip(),
    'wiki_tip': panel._wiki_button.toolTip(),
    'tab_tip': panel.tabs.tabToolTip(0),
    'after_switch': after_switch,
    'mismatched_loaded': mismatched_loaded,
    'after_mismatched_cache': after_mismatched_cache,
    'after_late': [item['n'] for item in panel._model.items],
    'late_cached_green': green_cache['items'][0]['n'],
    'late_deleted': late.deleted,
    'refreshes': refreshes,
    'blue_price': panel._auction_price('Blue Pearl'),
    'local_count': local_count,
    'local_count_after': len(panel._local_model.items),
    'mobile': {key: value for key, value in panel.mobile_snapshot().items()
               if key != 'items'},
}
print(json.dumps(result))
app.quit()
"""


def test_market_ui_switches_to_blue_and_late_green_reply_cannot_overwrite(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['server'] == result['configured'] == result['selector'] == 'Blue'
    assert result['selector_name'] == 'PigParse market server'
    assert 'prices and Wiki Auction Tracker values stay separate' in (
        result['selector_description'])
    assert 'selection is remembered' in result['selector_tooltip']
    assert result['window_title'] == 'Blue Market · PigParse'
    assert result['panel_title'] == 'Market · Blue'
    assert result['search_name'] == 'Search the Blue market'
    assert all('Blue' in result[key] for key in (
        'refresh_tip', 'history_tip', 'wiki_tip', 'tab_tip'))
    assert result['after_switch'] == ['Blue Pearl']
    assert result['mismatched_loaded'] is False
    assert result['after_mismatched_cache'] == ['Blue Pearl']
    assert result['after_late'] == ['Blue Pearl']
    assert result['late_cached_green'] == 'Late Green Reply'
    assert result['late_deleted'] is True
    assert result['refreshes'] == ['Blue']
    assert result['blue_price'] == 222
    assert result['local_count'] == result['local_count_after'] == 1
    assert result['mobile']['server'] == 'Blue'
    assert result['mobile']['source'] == 'PigParse API · Blue'
