"""Map pointer, profile attribution and saved-view regressions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers.maps.mapcanvas import MapCanvas

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def canvas(monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved = copy.deepcopy(config.data)
    config.verify_settings()
    monkeypatch.setattr(config, 'save', lambda: None)
    config.data['maps'].update(show_mouse_location=True, last_zone='')
    view = MapCanvas()
    view.resize(640, 420)
    assert view.load_map('the nektulos forest', remember=False)
    view.show()
    app.processEvents()
    yield view
    view.close()
    view.deleteLater()
    app.processEvents()
    config.data.clear()
    config.data.update(saved)


def test_unpressed_pointer_movement_recovers_hidden_location(canvas):
    assert canvas.hasMouseTracking() and canvas.viewport().hasMouseTracking()
    canvas._mouse_location.hide()
    QTest.mouseMove(canvas.viewport(), QPoint(200, 180))
    QApplication.processEvents()
    assert canvas._mouse_location.isVisible()
    first = canvas._mouse_location.toPlainText()
    QTest.mouseMove(canvas.viewport(), QPoint(300, 240))
    assert canvas._mouse_location.toPlainText() != first
    assert canvas._mouse_location.toPlainText().startswith('LOC · ')


def test_hover_respects_off_and_reenables_without_enter_event(canvas):
    position = QPoint(240, 160)
    config.data['maps']['show_mouse_location'] = False
    canvas.refresh_mouse_location(position)
    assert not canvas._mouse_location.isVisible()
    config.data['maps']['show_mouse_location'] = True
    canvas.refresh_mouse_location(position)
    assert canvas._mouse_location.isVisible()
    assert canvas._mouse_location.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert not canvas._mouse_location.acceptHoverEvents()


@pytest.mark.parametrize('zoom', [.015, .2, 2.5])
def test_location_label_stays_inside_all_viewport_edges(canvas, zoom):
    canvas.update_(zoom)
    viewport = canvas.viewport().rect()
    for position in (QPoint(5, 5), QPoint(viewport.right()-5, 5),
                     QPoint(5, viewport.bottom()-5),
                     QPoint(viewport.right()-5, viewport.bottom()-5)):
        canvas.refresh_mouse_location(position)
        label = canvas._mouse_location
        pixels = label.deviceTransform(canvas.viewportTransform()).mapRect(
            label.boundingRect())
        assert viewport.contains(pixels.toAlignedRect())
        assert label.scale() == 1


def test_keyboard_can_read_center_without_changing_hover_preference(canvas):
    config.data['maps']['show_mouse_location'] = False
    QTest.keyClick(canvas, Qt.Key.Key_L)
    assert canvas._mouse_location.isVisible()
    assert canvas._mouse_location.toPlainText() in canvas.accessibleDescription()
    assert config.data['maps']['show_mouse_location'] is False


def test_first_saved_zone_preserves_zoom_after_queued_fit_and_resize(monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved = copy.deepcopy(config.data)
    config.verify_settings()
    monkeypatch.setattr(config, 'save', lambda: None)
    config.data['maps'].update(last_zone='the nektulos forest', scale=.23)
    view = MapCanvas()
    try:
        assert view.load_map('the nektulos forest')
        view.resize(700, 480)
        view.show()
        for _ in range(3):
            app.processEvents()
        assert view._scale == pytest.approx(.23)
        assert config.data['maps']['scale'] == pytest.approx(.23)
        view.fit_overview()
        assert view._scale != pytest.approx(.23)
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()
        config.data.clear()
        config.data.update(saved)


CONTEXT_SCRIPT = r'''
import datetime, json
from types import SimpleNamespace
from PySide6.QtCore import QPoint
from vantage.helpers.application import VantageApp
from vantage.helpers import config
app = VantageApp([])
maps = app._parsers_dict['maps']
maps.show()
now = datetime.datetime.now()
def line(character, zone, text, server='P1999Green'):
    maps._active_character = character
    maps._active_server = server
    maps._character_context = SimpleNamespace(zone=zone)
    maps.parse(now, text)
line('First', 'The Nektulos Forest', 'You have entered The Nektulos Forest.')
line('First', 'The Nektulos Forest', 'Your Location is 3069.61, 316.33, 5.02')
first = maps._map._data.players['__you__']
line('Second', 'East Commonlands', 'Your Location is 10, 20, 3')
second = maps._map._data.players['__you__']
assert maps._map._data.zone == 'east commonlands'
assert second is not first
assert (second.location.x, second.location.y) == (-20, -10)
assert not maps.clear_player_location('First', 'P1999Green')
assert maps._map._data.players['__you__'] is second
line('Third', '', 'Your Location is 9000, 8000, 0')
assert '__you__' not in maps._map._data.players
line('Third', '', 'There are 2 players in The Nektulos Forest.')
line('Third', '', 'Your Location is 20, 30, 4')
assert maps._map._data.zone == 'the nektulos forest'
assert '__you__' in maps._map._data.players
line('First', 'The Nektulos Forest', 'Your Location is 40, 50, 4')
assert maps._map_source_identity == ('first', 'p1999green')
assert not maps._map._data.players['__you__'].directional.isVisible()
assert maps.clear_player_location('First', 'P1999Green')
assert maps._preview_zone('skyshrine')
maps._toggle_show_mouse_location(False)
for view in (maps._map, maps._preview_map):
    view.refresh_mouse_location(QPoint(100, 100))
    assert not view._mouse_location.isVisible()
maps._toggle_show_mouse_location(True)
for view in (maps._map, maps._preview_map):
    view.refresh_mouse_location(QPoint(100, 100))
    assert view._mouse_location.isVisible() is view.isVisibleTo(maps._surface)
    assert view._mouse_location.scene() is view.scene()
assert maps._pointer_loc_button.isChecked()
assert maps._cursor_loc_timer.isActive()
line('First', 'The Nektulos Forest', 'Your Location is 60, 70, 4')
assert maps._preview_map is None
line('First', 'The Nektulos Forest', 'You have entered The Nektulos Forest.')
assert '__you__' not in maps._map._data.players
line('First', 'The Nektulos Forest', 'Your Location is 60, 70, 4')
line('First', 'The Nektulos Forest', 'You have entered Unsupported Testing Zone.')
line('First', 'The Nektulos Forest', 'Your Location is 9000, 8000, 4')
assert '__you__' not in maps._map._data.players
line('First', 'The Nektulos Forest', 'You have entered The Nektulos Forest.')
line('First', 'The Nektulos Forest', 'Your Location is 60, 70, 4')
line('First', 'The Nektulos Forest', 'LOADING, PLEASE WAIT...')
line('First', 'The Nektulos Forest', 'Your Location is 9000, 8000, 4')
assert '__you__' not in maps._map._data.players
print(json.dumps({'passed': True}))
maps.close()
app.quit()
'''


def test_character_zone_and_camp_are_isolated_and_toggle_updates_both_maps(tmp_path):
    env = dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path), QT_QPA_PLATFORM='offscreen')
    result = subprocess.run([sys.executable, '-B', '-c', CONTEXT_SCRIPT],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(next(line for line in result.stdout.splitlines()
                           if line.startswith('{')))['passed']


RECOVERY_SCRIPT = r'''
from datetime import datetime
import os
from pathlib import Path
from vantage.helpers.application import VantageApp
from vantage.helpers.logreader import LogReader
app = VantageApp([])
maps = app._parsers_dict['maps']
root = Path(os.environ['VANTAGE_DATA_DIR']) / 'Logs'
root.mkdir(parents=True, exist_ok=True)
path = root / 'eqlog_Example_P1999Green.txt'
def entry(text):
    return ('[' + datetime.now().strftime('%a %b %d %H:%M:%S %Y') + '] ' + text + '\r\n').encode()
path.write_bytes(entry('You have entered The Estate of Unrest.'))
reader = LogReader(str(root))
reader._bootstrap_context()
assert maps._map._data.zone == 'estate of unrest'
assert '__you__' not in maps._map._data.players
reader._watcher.removePath(str(path))
with path.open('ab') as stream:
    stream.write(entry('LOADING, PLEASE WAIT...'))
    stream.write(entry('You have entered East Commonlands.'))
    stream.write(entry('Your Location is 10, 20, 3'))
reader._poll()
assert maps._map._data.zone == 'east commonlands'
player = maps._map._data.players['__you__']
assert (player.location.x, player.location.y) == (-20, -10)
reader.stop()
maps.close()
app.quit()
'''


def test_recovered_log_and_live_zone_events_reach_map_without_native_watch(tmp_path):
    env = dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path), QT_QPA_PLATFORM='offscreen')
    result = subprocess.run([sys.executable, '-B', '-c', RECOVERY_SCRIPT],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
