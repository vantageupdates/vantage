from PySide6.QtWidgets import QApplication

from vantage.helpers import config, to_eq_xy, to_real_xy
from vantage.parsers.maps.mapdata import MapData, bundled_map_paths


def test_velketor_uses_only_exact_zone_files_without_glyph_sheet():
    names = {path.name.casefold() for path in bundled_map_paths('velketor')}

    assert 'velketor.txt' in names
    assert 'velketor_1.txt' in names
    assert 'velketor_2.txt' not in names
    assert not any(name.startswith('velketortwo') for name in names)


def test_revamped_live_zones_use_complete_classic_p99_overrides():
    lavastorm = bundled_map_paths('lavastorm')
    nektulos = bundled_map_paths('nektulos')

    assert [path.name.casefold() for path in lavastorm] == [
        'lavastorm_1.txt']
    assert [path.name.casefold() for path in nektulos] == [
        'nektulos.txt', 'nektulos_1.txt']
    assert all(path.parent.name == 'classic_maps' for path in (
        lavastorm + nektulos))


def test_classic_zone_geometry_contains_p99_location_ranges():
    app = QApplication.instance() or QApplication([])
    original = config.data.get('maps')
    config.data['maps'] = {'grid_line_width': 1, 'line_width': 1}
    try:
        lavastorm = MapData('lavastorm mountains')
        nektulos = MapData('the nektulos forest')
    finally:
        if original is None:
            config.data.pop('maps', None)
        else:
            config.data['maps'] = original

    # The modern Lavastorm map stops near Y=-90. P99's classic zone extends
    # north past Y=2000, where /loc markers were previously drawn off-map.
    assert lavastorm.geometry.lowest_y <= -1400
    assert lavastorm.geometry.highest_y >= 2100
    assert lavastorm.geometry.width >= 2400

    # Classic Nektulos spans the Neriak, EC, and Lavastorm zone lines. Its
    # geometry is materially taller than the unrelated Live revision.
    assert nektulos.geometry.lowest_y <= -3100
    assert nektulos.geometry.highest_y >= 2700
    assert nektulos.geometry.height >= 5800

    # Exercise the same EQ /loc -> scene conversion used by the live marker at
    # known classic zone lines. Both points must land inside their loaded map.
    for map_data, scene_point in (
            (lavastorm, (174.0, 2061.0)),
            (nektulos, (1108.0546, -2271.7407))):
        eq_y, eq_x = to_eq_xy(*scene_point)
        marker_x, marker_y = to_real_xy(eq_y, eq_x)
        assert (marker_x, marker_y) == scene_point
        assert (map_data.geometry.lowest_x <= marker_x <=
                map_data.geometry.highest_x)
        assert (map_data.geometry.lowest_y <= marker_y <=
                map_data.geometry.highest_y)
    assert app is not None
