from vantage.parsers.maps.mapdata import bundled_map_paths


def test_velketor_uses_only_exact_zone_files_without_glyph_sheet():
    names = {path.name.casefold() for path in bundled_map_paths('velketor')}

    assert 'velketor.txt' in names
    assert 'velketor_1.txt' in names
    assert 'velketor_2.txt' not in names
    assert not any(name.startswith('velketortwo') for name in names)
