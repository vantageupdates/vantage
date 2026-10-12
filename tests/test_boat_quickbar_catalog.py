"""The boat launcher is first-class without creating another boat controller."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from vantage.helpers import config
from vantage.helpers.icons import WINDOW_ICONS
from vantage.helpers.parser import DESIGN_SIZES
from vantage.helpers.quickbar_items import QUICKBAR_ITEMS


ROOT = Path(__file__).resolve().parents[1]
BOAT_PRESENTATION = {
    'geometry': [450, 80, 400, 560], 'toggled': False, 'opacity': 94,
    'clickthrough': False, 'auto_hide_menu': False,
    'always_on_top': True, 'frameless': True, 'collapsed': False,
}


@pytest.fixture
def empty_profile(monkeypatch):
    monkeypatch.setattr(config, 'data', {})
    config.verify_settings()
    return config.data


def test_boats_catalog_is_direct_visible_window_with_bundled_icon(empty_profile):
    keys = [item[0] for item in QUICKBAR_ITEMS]
    assert keys.index('boats') == keys.index('maps') + 1
    assert QUICKBAR_ITEMS[keys.index('boats')] == (
        'boats', 'Boat Schedules', 'ph-boat', 'windows')
    assert keys.count('boats') == 1
    assert empty_profile['quickbar']['show_boats'] is True
    assert WINDOW_ICONS['boats'] == 'ph-boat'
    assert [DESIGN_SIZES['boats'].width(), DESIGN_SIZES['boats'].height()] == [
        400, 560]
    asset = ROOT / 'data' / 'ui' / 'icons' / 'ph-boat.svg'
    assert ET.parse(asset).getroot().attrib['viewBox'] == '0 0 256 256'
    assert '#D0B675' in asset.read_text(encoding='utf-8')


def test_boats_normalized_defaults_and_reset_are_presentation_only(empty_profile):
    assert empty_profile['boats'] == BOAT_PRESENTATION
    empty_profile['boats'].update({
        'geometry': [32, 45, 280, 420], 'opacity': 70, 'toggled': True,
        'collapsed': True, 'auto_hide_menu': True})
    empty_profile['spells'].update({
        'boat_view_server': 'Blue', 'boat_reporter': 'Mindflux',
        'show_boat_schedules': True})
    preferences = copy.deepcopy(empty_profile['spells'])
    empty_profile['quickbar']['show_boats'] = False
    config.verify_settings()
    assert empty_profile['quickbar']['show_boats'] is False
    config.apply_ui_presentation()
    assert empty_profile['boats'] == BOAT_PRESENTATION
    assert empty_profile['quickbar']['show_boats'] is True
    assert empty_profile['spells']['boat_view_server'] == preferences['boat_view_server']
    assert empty_profile['spells']['boat_reporter'] == preferences['boat_reporter']
    assert empty_profile['spells']['show_boat_schedules'] == preferences['show_boat_schedules']
    assert {path[1] for path in config.UI_PRESENTATION_DEFAULTS
            if path[0] == 'boats'} == set(BOAT_PRESENTATION)


@pytest.mark.parametrize('geometry', [
    None, [], [1, 2, 3], [1, 2, 3, 4, 5], [1, 2, 0, 560],
    [1, 2, 400, -1], [1, 2, 400, '560'], [True, 2, 400, 560],
    [1, 2, 400.0, 560], '400x560',
])
def test_boats_rejects_malformed_saved_geometry(empty_profile, geometry):
    empty_profile['boats']['geometry'] = geometry
    config.verify_settings()
    assert empty_profile['boats']['geometry'] == BOAT_PRESENTATION['geometry']


def test_boats_config_repairs_wrong_section_and_forbids_clickthrough(empty_profile):
    empty_profile['boats'] = ['not a settings object']
    config.verify_settings()
    assert empty_profile['boats'] == BOAT_PRESENTATION
    empty_profile['boats'].update(clickthrough=True, opacity=1000)
    config.verify_settings()
    assert empty_profile['boats']['clickthrough'] is False
    assert empty_profile['boats']['opacity'] == 94


NATIVE_SCRIPT = r'''
import json
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.parsers.spells import BoatScheduleGroup

app = VantageApp([])
bar = app._parsers_dict['quickbar']
boats = app._parsers_dict['boats']
spells = app._parsers_dict['spells']
app.processEvents()
button = bar._buttons['boats']
initial = {
    'hidden': not boats.isVisible(),
    'buffs_hidden': not spells.isVisible(),
    'name': button.accessibleName(),
    'visible': button.isVisible(),
    'checkable': button.isCheckable(),
    'icon': not button.icon().isNull(),
    'title': boats.windowTitle(),
    'one_group': boats._surface.findChildren(BoatScheduleGroup) == [
        spells._boat_group],
    'interactive': not boats._allow_clickthrough,
}
bar._trigger('boats')
app.processEvents()
bar.refresh_state()
opened = {
    'visible': boats.isVisible(), 'checked': button.isChecked(),
    'dot': bar._enabled_dots['boats'].isVisible(),
    'buffs_hidden': not spells.isVisible(),
}
bar._trigger('boats')
app.processEvents()
bar.refresh_state()
closed = not boats.isVisible() and not button.isChecked()
presets = []
boats._set_collapsed(False)
for scale in (.25, .35, .5, .75, 1):
    boats._set_replica_scale(scale)
    QTest.qWait(20)
    presets.append([boats.width(), boats.height()] == [
        round(400 * scale), round(560 * scale)])
boats._set_collapsed(True)
app.processEvents()
rolled = boats.height() < 560
boats._set_collapsed(False)
app.processEvents()
config.data['quickbar']['show_boats'] = False
bar._apply_quickbar_settings()
app.processEvents()
hidden_pref = not button.isVisible()
print(json.dumps({
    'initial': initial, 'opened': opened, 'closed': closed,
    'presets': presets, 'rolled': rolled, 'hidden_pref': hidden_pref,
}))
app.quit()
'''


def test_boats_registered_window_opens_directly_and_keeps_normal_presets(tmp_path):
    env = os.environ.copy()
    env.update({
        'QT_QPA_PLATFORM': 'offscreen', 'QT_ACCESSIBILITY': '0',
        'PYTHONPATH': os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src'))),
        'VANTAGE_DATA_DIR': str(tmp_path / 'profile'),
    })
    completed = subprocess.run(
        [sys.executable, '-c', NATIVE_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['initial'] == {
        'hidden': True, 'buffs_hidden': True, 'name': 'Boat Schedules',
        'visible': True, 'checkable': True, 'icon': True,
        'title': 'Boat Schedules', 'one_group': True, 'interactive': True,
    }
    assert result['opened'] == {
        'visible': True, 'checked': True, 'dot': True, 'buffs_hidden': True}
    assert result['closed'] is True
    assert all(result['presets'])
    assert result['rolled'] is True
    assert result['hidden_pref'] is True
