"""Temporary map browsing must never masquerade as a character zone change."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]

MAP_BROWSE_SCRIPT = r"""
import datetime
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers import config, to_real_xy
from vantage.helpers.application import VantageApp
from vantage.parsers.maps.mapclasses import MapPoint, SpawnPoint
from vantage.parsers.maps.mapdata import MapData

app = VantageApp([])
maps = app._parsers_dict['maps']
maps.show()
maps.resize(640, 420)
maps._load_zone('east commonlands')
now = datetime.datetime.now().replace(microsecond=0)
maps.parse(now, 'Your Location is 12, 34, 5')
app.processEvents()
live_data = maps._map._data
live_player = live_data.players['__you__']
spawn = SpawnPoint(location=MapPoint(x=1, y=2, z=0), length=60)
live_data.spawns.append(spawn)
maps._map._scene.addItem(spawn)
spawn.start()
events = []
app._signals['maps'].new_zone.connect(events.append)
before = (config.data['maps']['last_zone'], config.data['maps']['scale'],
          config.data['maps']['auto_follow'])

assert maps._preview_zone('castle mistmoore')
app.processEvents()
preview = maps._preview_map
point = maps._all_pois()[0]
maps._activate_poi(point)
app.processEvents()
result = {
    'preview_zone': preview._data.zone,
    'live_zone': maps._map._data.zone,
    'same_live_data': maps._map._data is live_data,
    'same_player': maps._map._data.players['__you__'] is live_player,
    'same_spawn': maps._map._data.spawns[0] is spawn,
    'no_live_marker_on_preview': '__you__' not in preview._data.players,
    'live_hidden': maps._map.isHidden(),
    'preview_visible': not preview.isHidden(),
    'hud_preview': 'PREVIEW' in preview.location_overlay._zone_label.text(),
    'title_preview': 'Preview' in maps._title.text(),
    'browse_checked': maps._browse_button.isChecked(),
    'no_preview_zone_event': events == [],
    'preferences_unchanged': before == (
        config.data['maps']['last_zone'], config.data['maps']['scale'],
        config.data['maps']['auto_follow']),
    'preview_poi_focused': preview._focused_poi is point,
    'scene_owned': preview._scene.parent() is preview,
}
maps.parse(now, "Bob tells you, 'Your Location is 100, 200, 3'")
maps.parse(now, 'Your Location is unknown')
maps.parse(now, 'There are 3 players in East Commonlands.')
result['unrelated_logs_keep_preview'] = maps._preview_map is preview
maps.parse(now, 'Your Location is 45, 67, 5')
result.update({
    'loc_returns': maps._preview_map is None,
    'loc_keeps_live_data': maps._map._data is live_data,
    'loc_keeps_spawn': maps._map._data.spawns[0] is spawn,
    'new_coordinates': [live_player.location.x, live_player.location.y],
    'expected_coordinates': list(to_real_xy(45, 67)),
    'live_visible_after_loc': not maps._map.isHidden(),
    'loc_no_false_zone_event': events == [],
    'preview_title_cleared': 'Preview' not in maps._title.text(),
})
assert maps._preview_zone('lavastorm')
app.processEvents()
result['classic_preview'] = maps._preview_map._data.zone
maps._browse_button.click()
result['button_returns'] = maps._preview_map is None
result['button_keeps_spawn'] = maps._map._data.spawns[0] is spawn
assert maps._preview_zone('velketor')
old_preview = maps._preview_map
result['invalid_rejected'] = not maps._preview_zone('not a real map')
result['invalid_preserves_preview'] = maps._preview_map is old_preview
assert maps._preview_zone('castle mistmoore')
result['replace_preview_keeps_live'] = maps._map._data is live_data
maps.parse(now, 'You have entered The Nektulos Forest.')
result['zoning_returns'] = maps._preview_map is None
result['zoning_live_zone'] = maps._map._data.zone
result['zoning_events'] = list(events)

maps._open_map_browser()
app.processEvents()
dialog = maps._browse_dialog
result['search_count'] = dialog.selector.count()
result['catalog_count'] = len(MapData.get_zone_dict())
result['search_focus'] = dialog.selector.hasFocus() or dialog.selector.lineEdit().hasFocus()
dialog.selector.setEditText('not a real map')
result['invalid_search_disabled'] = not dialog.view_button.isEnabled()
dialog.selector.setEditText("Velketor's Labyrinth")
result['valid_search_enabled'] = dialog.view_button.isEnabled()
result['search_contains'] = dialog.selector.completer().filterMode() == Qt.MatchFlag.MatchContains
dialog.view_button.click()
app.processEvents()
result['search_opens_preview'] = maps._preview_map._data.zone == "velketor's labyrinth"
result['dialog_closed'] = maps._browse_dialog is None
maps._open_map_browser()
app.processEvents()
dialog = maps._browse_dialog
result['return_action_enabled'] = dialog.return_button.isEnabled()
dialog.return_button.click()
app.processEvents()
result['dialog_return_works'] = maps._preview_map is None
maps._open_map_browser()
app.processEvents()
QTest.keyClick(maps._browse_dialog, Qt.Key.Key_Escape)
app.processEvents()
result['escape_closes'] = maps._browse_dialog is None

# Browsing from Zones and the legacy Market zone view uses the same preview,
# never the live zone loader.
called = []
original_preview = maps._preview_zone
maps._preview_zone = lambda name: called.append(name) or True
for feature in ('zones', 'market'):
    panel = app._parsers_dict[feature]
    panel._zone_data = {'name': 'Castle Mistmoore'}
    panel._open_zone_map()
maps._preview_zone = original_preview
result['linked_browsers_use_preview'] = called == ['Castle Mistmoore', 'Castle Mistmoore']
print(json.dumps(result))
app.quit()
"""


@pytest.fixture(scope='module')
def browsing_result(tmp_path_factory):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path_factory.mktemp('map-browse') / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', MAP_BROWSE_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_preview_preserves_real_zone_markers_timers_and_preferences(browsing_result):
    result = browsing_result
    assert result['preview_zone'] == 'castle mistmoore'
    assert result['live_zone'] == 'east commonlands'
    for key in ('same_live_data', 'same_player', 'same_spawn',
                'no_live_marker_on_preview', 'no_preview_zone_event',
                'preferences_unchanged', 'scene_owned'):
        assert result[key], key


def test_preview_is_visible_labeled_and_pois_use_the_preview(browsing_result):
    for key in ('live_hidden', 'preview_visible', 'hud_preview',
                'title_preview', 'browse_checked', 'preview_poi_focused'):
        assert browsing_result[key], key


def test_only_valid_new_loc_returns_and_places_marker_on_live_zone(browsing_result):
    result = browsing_result
    for key in ('unrelated_logs_keep_preview', 'loc_returns',
                'loc_keeps_live_data', 'loc_keeps_spawn', 'live_visible_after_loc',
                'loc_no_false_zone_event', 'preview_title_cleared'):
        assert result[key], key
    assert result['new_coordinates'] == result['expected_coordinates']


def test_manual_return_and_multiple_previews_do_not_reset_live_map(browsing_result):
    result = browsing_result
    assert result['classic_preview'] == 'lavastorm mountains'
    for key in ('button_returns', 'button_keeps_spawn', 'invalid_rejected',
                'invalid_preserves_preview', 'replace_preview_keeps_live'):
        assert result[key], key


def test_actual_zone_change_exits_preview_and_emits_only_real_zone(browsing_result):
    result = browsing_result
    assert result['zoning_returns']
    assert result['zoning_live_zone'] == 'the nektulos forest'
    assert result['zoning_events'] == ['the nektulos forest']


def test_map_search_keyboard_and_manual_return(browsing_result):
    result = browsing_result
    assert result['search_count'] == result['catalog_count']
    for key in ('search_focus', 'invalid_search_disabled', 'valid_search_enabled',
                'search_contains', 'search_opens_preview', 'dialog_closed',
                'return_action_enabled', 'dialog_return_works', 'escape_closes'):
        assert result[key], key


def test_zones_and_market_map_links_use_temporary_preview(browsing_result):
    assert browsing_result['linked_browsers_use_preview']
