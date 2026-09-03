import os
import json
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsView)

from vantage.helpers import config
from vantage.parsers.maps.mapcanvas import MapCanvas
from vantage.parsers.maps.mapclasses import MapPoint, Player, SpawnPoint
from vantage.parsers.maps.mapdata import MapData
from vantage.parsers.maps.window import (
    detect_log_location, detect_log_zone, detect_who_player_count)


ROOT = Path(__file__).resolve().parents[1]


MAP_LOG_SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
maps = app._parsers_dict['maps']
now = datetime.datetime.now().replace(microsecond=0)
maps.parse(now, "There are 12 players in Velketor's Labyrinth.")
maps.parse(now, 'Your Location is -123.50, 456.25, 7.00')
hud = maps._map.location_overlay
button = maps._location_hud_button
before = not hud.isHidden()
button.setChecked(False)
maps._toggle_location_hud(False)
print(json.dumps({
    'zone': maps._map._data.zone,
    'zone_text': hud._zone_label.text(),
    'loc_text': hud._location_label.text(),
    'marker': '__you__' in maps._map._data.players,
    'tooltip': button.toolTip(),
    'accessible': button.accessibleName(),
    'visible_before': before,
    'hidden_after': hud.isHidden(),
}))
app.quit()
"""


def _app():
    return QApplication.instance() or QApplication([])


def test_zone_detection_accepts_zoning_who_and_status_lines():
    assert detect_log_zone("You have entered East Commonlands.") == (
        "east commonlands", "zoning")
    assert detect_log_zone("There are 12 players in Eastern Wastes.") == (
        "eastern wastelands", "who")
    assert detect_log_zone("There is 1 player in Kael Drakkal.") == (
        "kael drakkel", "who")
    assert detect_log_zone("Players in The Wakening Land:") == (
        "the wakening lands", "who")
    assert detect_log_zone("Current Zone: ecommons") == (
        "east commonlands", "status")


def test_zone_detection_rejects_generic_or_unknown_text():
    assert detect_log_zone("There are 250 players in EverQuest.") == (None, None)
    assert detect_log_zone("Bob tells you, 'meet me in East Commonlands'") == (
        None, None)
    assert MapData.resolve_zone_name("not a real p99 zone") is None


def test_location_and_who_lines_are_parsed_safely():
    assert detect_log_location(
        'Your Location is -123.50, 456.25, 7.00') == (
            -123.5, 456.25, 7.0)
    assert detect_log_location('Your Location is unknown') is None
    assert detect_who_player_count(
        'There are 12 players in Eastern Wastes.') == 12
    assert detect_who_player_count(
        'There are no players in Eastern Wastes.') == 0
    assert detect_who_player_count(
        'Players in The Wakening Land:') is None


def test_map_uses_direct_pointer_drag_and_explains_controls():
    _app()
    config.data.setdefault("maps", {})["scale"] = 0.07
    canvas = MapCanvas()

    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    assert "Drag" in canvas.toolTip()
    assert "wheel" in canvas.toolTip()


def test_location_hud_is_compact_click_through_and_updates():
    app = _app()
    config.data.setdefault("maps", {})["scale"] = 0.07
    config.data["maps"]["show_location_hud"] = True
    config.data["maps"].setdefault("show_mouse_location", True)
    canvas = MapCanvas()
    canvas.resize(640, 420)
    canvas.show()
    app.processEvents()

    hud = canvas.location_overlay
    canvas.update_location_hud_zone(
        "Eastern Wastelands", "who", 12)
    canvas.update_location_hud_position((-123.5, 456.25, 7))
    app.processEvents()

    assert hud.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert hud.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert hud.width() <= 270
    assert hud.x() + hud.width() <= canvas.width()
    assert "Eastern Wastelands" in hud._zone_label.text()
    assert "WHO · 12" in hud._zone_label.text()
    assert "LOC · -123.5, 456.25, 7" == hud._location_label.text()
    assert "slash loc" in hud.accessibleName()

    canvas.set_location_hud_visible(False)
    assert hud.isHidden()
    canvas.close()


def test_map_log_commands_update_the_location_hud_and_toolbar(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', MAP_LOG_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        'zone': "velketor's labyrinth",
        'zone_text': "Velketor's Labyrinth · WHO · 12",
        'loc_text': 'LOC · -123.5, 456.25, 7',
        'marker': True,
        'tooltip': 'Show location HUD from EverQuest /loc and /who',
        'accessible': 'Show map location HUD',
        'visible_before': True,
        'hidden_after': True,
    }


def test_player_heading_uses_crisp_vantage_direction_arrow():
    _app()
    player = Player(
        name='__you__', previous_location=MapPoint(x=0, y=0),
        location=MapPoint(x=10, y=0))
    player.update_(1.0)

    assert isinstance(player.directional, QGraphicsPathItem)
    assert not player.directional.path().isEmpty()
    assert player.directional.isVisible()
    assert player.directional.brush().color().name() == '#e0c66e'
    assert player.directional.toolTip() == 'Your direction of travel'


def test_map_timers_are_draggable_restartable_and_expire_cleanly():
    _app()
    removed = []
    timer = SpawnPoint(
        location=MapPoint(x=1, y=2, z=0), length=60,
        name='camp timer', on_remove=removed.append)

    assert timer.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    assert timer.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
    assert 'drag' in timer.toolTip()
    timer.setPos(15, 25)
    assert (timer.location.x, timer.location.y) == (15, 25)
    timer.start()
    timer.stop()
    generation = timer._generation
    timer._remove_if_expired(generation)
    assert removed == [timer]
