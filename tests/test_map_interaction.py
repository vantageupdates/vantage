import os
import json
from pathlib import Path
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsView)

from vantage.helpers import config
from vantage.parsers.maps.mapcanvas import MapCanvas
from vantage.parsers.maps.mapclasses import (
    MapPoint, Player, PointOfInterest, SpawnPoint)
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


def test_poi_labels_remain_readable_in_overview_and_respect_toggle():
    _app()
    original = dict(config.data.setdefault("maps", {}))
    canvas = MapCanvas()

    class MapFixture(dict):
        pass

    point = PointOfInterest(location=MapPoint(
        x=100, y=200, z=0, size=2, text="Bank",
        color=QColor("#f0c765")))
    upper_point = PointOfInterest(location=MapPoint(
        x=120, y=220, z=100, size=2, text="Upper_floor",
        color=QColor("#9bd7ff")))
    paths = QGraphicsPathItem()
    upper_paths = QGraphicsPathItem()
    grid = QGraphicsPathItem()
    data = MapFixture({
        0: {"paths": paths, "poi": [point]},
        100: {"paths": upper_paths, "poi": [upper_point]},
    })
    data.geometry = type("Geometry", (), {"z_groups": [0, 100]})()
    data.players = {}
    data.way_point = None
    data.waypoints = {}
    data.spawns = []
    data.grid = grid
    canvas._data = data
    canvas._z_index = 0
    canvas._scene.addItem(paths)
    canvas._scene.addItem(upper_paths)
    canvas._scene.addItem(point.text)
    canvas._scene.addItem(upper_point.text)
    canvas._scene.addItem(grid)

    try:
        config.data["maps"].update({
            "show_poi": True, "use_z_layers": False,
            "current_z_alpha": 85, "other_z_alpha": 25,
            "closest_z_alpha": 55, "line_width": 1,
            "show_grid": False, "grid_line_width": 1,
        })
        canvas._manual_view = False
        canvas.update_(0.05)

        assert point.text.opacity() == pytest.approx(1.0)
        assert point.text.isVisible()
        assert point.text.flags() & (
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        assert point.text.scale() == pytest.approx(1.0)
        assert point.text.deviceTransform(
            canvas.viewportTransform()).m11() == pytest.approx(1.0)
        assert point._point_size <= 8.0
        assert 'font-weight:500' in point.text.toHtml().replace(' ', '')
        assert '#f4ead4' in point.text.toHtml().lower()
        assert '#071014' in point.text.toHtml().lower()
        point_rect = point.text.deviceTransform(
            canvas.viewportTransform()).mapRect(point.text.boundingRect())
        upper_rect = upper_point.text.deviceTransform(
            canvas.viewportTransform()).mapRect(
                upper_point.text.boundingRect())
        assert not point_rect.intersects(upper_rect)
        assert 'visible points of interest' in (
            canvas.accessibleDescription().lower())
        assert 'bank' in canvas.accessibleDescription().lower()

        config.data["maps"]["use_z_layers"] = True
        canvas.update_(2.0)
        assert point.text.opacity() == pytest.approx(1.0)
        assert upper_point.text.opacity() == pytest.approx(1.0)
        assert point.text.deviceTransform(
            canvas.viewportTransform()).m11() == pytest.approx(1.0)
        assert '● bank' in point.text.toPlainText().lower()
        assert '○ upper floor' in upper_point.text.toPlainText().lower()
        assert 'current z layer points of interest: bank' in (
            canvas.accessibleDescription().lower())
        assert 'other z layer points of interest: upper floor' in (
            canvas.accessibleDescription().lower())

        config.data["maps"]["show_poi"] = False
        canvas.update_(0.05)
        assert point.text.opacity() == 0
        assert upper_point.text.opacity() == 0
        assert not point.text.isVisible()
        assert not upper_point.text.isVisible()
        assert not point.leader.isVisible()
        assert not upper_point.leader.isVisible()
        assert 'points of interest are hidden' in (
            canvas.accessibleDescription().lower())
    finally:
        config.data["maps"].clear()
        config.data["maps"].update(original)
        canvas.close()


def test_west_commonlands_overview_packs_all_poi_labels_without_overlap():
    app = _app()
    original = dict(config.data.setdefault("maps", {}))
    canvas = MapCanvas()
    canvas.resize(415, 347)
    canvas.show()

    try:
        config.data["maps"].update({
            "show_poi": True, "use_z_layers": False,
            "current_z_alpha": 85, "other_z_alpha": 25,
            "closest_z_alpha": 55, "line_width": 1,
            "show_grid": True, "grid_line_width": 1,
            "show_mouse_location": True,
        })
        canvas._data = MapData("west commonlands")
        canvas._z_index = 0
        canvas._draw()
        geometry = canvas._data.geometry
        scene_rect = canvas._scene.sceneRect()
        scene_rect.adjust(
            -geometry.width * 2, -geometry.height * 2,
            geometry.width * 2, geometry.height * 2)
        canvas.setSceneRect(scene_rect)
        canvas.fit_overview()
        app.processEvents()

        label_rects = []
        for z in canvas._data.keys():
            for point in canvas._data[z]["poi"]:
                label_rects.append(
                    point.text.deviceTransform(
                        canvas.viewportTransform()).mapRect(
                            point.text.boundingRect()))

        assert len(label_rects) == 19
        viewport = canvas.viewport().rect().adjusted(4, 4, -4, -4)
        assert all(viewport.contains(rect.toRect()) for rect in label_rects)
        for index, rect in enumerate(label_rects):
            padded = rect.adjusted(-1, -1, 1, 1)
            assert all(
                not padded.intersects(other.adjusted(-1, -1, 1, 1))
                for other in label_rects[index + 1:])
    finally:
        config.data["maps"].clear()
        config.data["maps"].update(original)
        canvas.close()


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
