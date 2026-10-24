"""Real bundled-map regressions, isolated from every user/game profile."""

import datetime
import math

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem

from vantage.helpers import config, resource_path, to_real_xy
from vantage.parsers.maps.mapclasses import MapLine, MapPoint, Player
from vantage.parsers.maps.mapdata import MapData


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def bundled_maps(app, tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(config.data, 'maps', {
            'grid_line_width': 1, 'line_width': 1})
        patch.setattr('vantage.parsers.maps.mapdata.MAP_RECORDINGS_PATHLIB',
                      tmp_path_factory.mktemp('empty-map-recordings'))
        yield {
            'skyshrine': MapData('skyshrine'),
            'nektulos': MapData('the nektulos forest'),
        }


def test_first_fix_has_exact_position_but_no_invented_heading(app):
    location = MapPoint(x=-316.33, y=-3069.61, z=5.02)
    for player in (Player(name='__you__', location=location),
                   Player(name='__you__')):
        if not player._has_location:
            player.update_location(location)
        player.update_(10)
        assert player.previous_location is None
        assert not player.directional.isVisible()
        assert player.icon.isVisible()
        assert player.icon.mapToScene(QPointF(0, 0)) == QPointF(-316.33, -3069.61)


@pytest.mark.parametrize('x,y,heading', [
    (0, -10, 0), (10, 0, 90), (0, 10, -180), (-10, 0, -90)])
def test_valid_travel_heading_survives_stationary_and_z_only_samples(
        app, x, y, heading):
    start = datetime.datetime(2026, 10, 24, 12)
    player = Player(name='__you__', location=MapPoint(), timestamp=start)
    player.update_location(MapPoint(x=x, y=y), start + datetime.timedelta(seconds=1))
    player.update_(1)
    assert player.directional.isVisible()
    assert player.directional.rotation() == pytest.approx(heading)
    for seconds, z in ((2, 0), (3, 10), (120, 10)):
        player.update_location(MapPoint(x=x, y=y, z=z),
                               start + datetime.timedelta(seconds=seconds))
        player.update_(1)
        assert player.directional.isVisible()
        assert player.directional.rotation() == pytest.approx(heading)


def test_z_only_and_small_jitter_cannot_create_a_heading(app):
    player = Player(name='__you__', location=MapPoint(x=100, y=200))
    for location in (MapPoint(x=100, y=200, z=20),
                     MapPoint(x=100.1, y=200.1, z=20)):
        player.update_location(location)
        player.update_(1)
        assert not player.directional.isVisible()


def test_large_jump_clears_heading_until_new_plausible_travel(app):
    player = Player(name='__you__', location=MapPoint(x=0, y=0))
    player.update_location(MapPoint(x=10, y=0))
    player.update_(1)
    assert player.directional.isVisible()
    # The reported Skyshrine jump was approximately 3,959 units.
    player.update_location(MapPoint(x=3969, y=0))
    player.update_(1)
    assert not player.directional.isVisible()
    player.update_location(MapPoint(x=3969, y=0, z=5))
    player.update_(1)
    assert not player.directional.isVisible()
    player.update_location(MapPoint(x=3969, y=-10, z=5))
    player.update_(1)
    assert player.directional.isVisible()
    assert player.directional.rotation() == pytest.approx(0)


@pytest.mark.parametrize('distance,seconds', [(100, 1), (10, 31), (10, -1)])
def test_discontinuous_timed_samples_do_not_imply_facing(app, distance, seconds):
    start = datetime.datetime(2026, 10, 24, 12)
    player = Player(name='__you__', location=MapPoint(), timestamp=start)
    player.update_location(MapPoint(x=distance),
                           start + datetime.timedelta(seconds=seconds))
    player.update_(1)
    assert not player.directional.isVisible()


def test_same_second_log_samples_can_still_establish_travel(app):
    start = datetime.datetime(2026, 10, 24, 12)
    player = Player(name='__you__', location=MapPoint(), timestamp=start)
    player.update_location(MapPoint(x=10), start)
    player.update_(1)
    assert player.directional.isVisible()
    assert player.directional.rotation() == pytest.approx(90)


def test_nektulos_exact_position_and_original_marker_at_every_zoom(bundled_maps):
    data = bundled_maps['nektulos']
    previous_xy = to_real_xy(3045.39, 326.71)
    current_xy = to_real_xy(3069.61, 316.33)
    player = Player(name='__you__', location=MapPoint(
        x=previous_xy[0], y=previous_xy[1], z=5.02))
    player.update_location(MapPoint(x=current_xy[0], y=current_xy[1], z=5.02))

    for zoom in (0.05, 0.1, 0.5, 1.0, 4.0):
        player.update_(1 / zoom)
        assert (player.pos().x(), player.pos().y()) == (-316.33, -3069.61)
        assert player.directional.rotation() == pytest.approx(
            math.degrees(math.atan2(10.38, 24.22)))
        assert (data.geometry.lowest_y <= player.pos().y()
                <= data.geometry.highest_y)
        # The user's original arrow remains the same screen size at overview.
        # Its footprint can overlap narrow walls; never shift the true /loc.
        assert player.directional.scale() == 1
        transform = player.directional.deviceTransform(QTransform().scale(zoom, zoom))
        center = transform.map(QPointF(0, 0))
        tip = transform.map(QPointF(0, -16))
        assert math.hypot(tip.x() - center.x(), tip.y() - center.y()) == pytest.approx(16)
        icon = player.icon.deviceTransform(QTransform().scale(zoom, zoom)).mapRect(
            player.icon.boundingRect())
        assert icon.width() == 20
        assert icon.height() == 20


def test_self_marker_restores_original_asset_and_label(app):
    player = Player(name='__you__', location=MapPoint(x=10, y=20))
    player.update_(1)
    assert isinstance(player.icon, QGraphicsPixmapItem)
    expected = QPixmap(resource_path('data/maps/user.png')).toImage()
    assert not expected.isNull()
    assert player.icon.pixmap().toImage() == expected
    assert player.icon.offset() == QPointF(-10, -10)
    assert player.nametag.pos() == QPointF(10, -15)
    assert player.nametag.toPlainText() == 'You'
    label = player.nametag.document().firstBlock().begin().fragment().charFormat()
    assert label.foreground().color().name() == '#800080'
    assert label.fontPointSize() == 0
    assert label.property(label.Property.FontSizeAdjustment) == 2


def test_skyshrine_maze_labels_share_their_actual_wall_layers(bundled_maps):
    data = bundled_maps['skyshrine']
    maze_lines = [line for line in data.raw['lines']
                  if min(line.z1, line.z2) == 374.8999]
    assert len(maze_lines) == 381
    for label, expected_layer in [('Skyshrine_Maze', 374.8999), ('Maze_Level', 255.0)]:
        point = next(point for point in data.raw['poi'] if point.text == label)
        assert data.get_closest_z_group(point.z) == expected_layer
        assert data.get_closest_z_group(point.z, point.x, point.y) == expected_layer
        assert any(poi.location is point for poi in data[expected_layer]['poi'])
    assert all(data.get_closest_z_group(min(line.z1, line.z2)) == 374.8999
               for line in maze_lines)


def test_skyshrine_player_above_ground_uses_nearby_wall_layer(bundled_maps):
    data = bundled_maps['skyshrine']
    x, y = to_real_xy(-25.95, -663.62)
    assert (x, y) == (663.62, 25.95)
    assert data.get_closest_z_group(4.2) == 2.0999
    assert data.get_closest_z_group(4.2, x, y) == -19.8999
    nearby_wall = next(line for line in data.raw['lines']
                       if (line.x1, line.y1, line.z1) == (655.3999, 14.1999, 0.0999))
    assert data.get_closest_z_group(min(nearby_wall.z1, nearby_wall.z2)) == -19.8999


def test_layer_tolerance_does_not_merge_distinct_floors_or_snap_distant_geometry():
    data = MapData()
    data._z_groups = [-20, 2, 25, 45]
    data.raw['lines'] = [MapLine(x1=0, y1=0, z1=0, x2=20, y2=0, z2=0)]
    assert data.get_closest_z_group(24.9) == 25
    assert data.get_closest_z_group(24) == 2
    assert data.get_closest_z_group(4, 10, 5) == -20
    assert data.get_closest_z_group(4, 100, 100) == 2
    assert data.get_closest_z_group(25, 10, 5) == 25
    assert data.get_closest_z_group(-100) == -20
    assert data.get_closest_z_group(100) == 45


def test_layer_association_rejects_steep_segments_and_respects_stacked_floors():
    data = MapData()
    data._z_groups = [0, 20, 40]
    data.raw['lines'] = [
        MapLine(x1=0, y1=0, z1=0, x2=20, y2=0, z2=0),
        MapLine(x1=0, y1=0, z1=20, x2=20, y2=0, z2=20),
        MapLine(x1=0, y1=0, z1=0, x2=20, y2=0, z2=40),
    ]
    assert data.get_closest_z_group(4, 10, 5) == 0
    assert data.get_closest_z_group(24, 10, 5) == 20
    assert data.get_closest_z_group(40, 10, 5) == 40
