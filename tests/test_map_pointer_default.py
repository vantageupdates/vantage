"""Upgrade hidden pointer coordinates once, then respect the user's switch."""
import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers import config


@pytest.mark.parametrize('saved_maps, enabled', [
    ({}, True),
    ({'show_mouse_location': False}, True),
    ({'show_mouse_location': True}, True),
    ({'show_mouse_location': False, 'pointer_loc_visibility_version': 0}, True),
    ({'show_mouse_location': False, 'pointer_loc_visibility_version': 1}, False),
    ({'show_mouse_location': True, 'pointer_loc_visibility_version': 1}, True),
])
def test_pointer_default_migrates_once(monkeypatch, tmp_path, saved_maps, enabled):
    saved_maps = dict(saved_maps, show_location_hud=False,
                      geometry=[60, 70, 420, 320], scale=.23)
    monkeypatch.setattr(config, 'data', {'maps': copy.deepcopy(saved_maps)})
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'profile.json'))
    config.verify_settings()
    assert config.data['maps']['show_mouse_location'] is enabled
    assert config.data['maps']['pointer_loc_visibility_version'] == 1
    assert config.data['maps']['show_location_hud'] is False
    assert config.data['maps']['geometry'] == saved_maps['geometry']
    assert config.data['maps']['scale'] == saved_maps['scale']

    # A deliberate Off survives both a settings refresh and a disk restart.
    config.data['maps']['show_mouse_location'] = False
    config.verify_settings()
    config.save()
    config.load(config._filename)
    config.verify_settings()
    assert config.data['maps']['show_mouse_location'] is False
    assert config.data['maps']['pointer_loc_visibility_version'] == 1


UI_SCRIPT = r'''
import json
import os
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.parsers.maps import window as module

profile = Path(os.environ['VANTAGE_DATA_DIR']) / 'profile.json'
profile.write_text(json.dumps({'maps': {'show_mouse_location': False}}))
config.load(str(profile))
config.verify_settings()
config.save()
app = QApplication([])
class Settings(QObject):
    config_updated = Signal()
app._signals = {'settings': Settings(), 'maps': module.MapsSignals()}
class Cursor:
    point = QPoint(-10000, -10000)
    @classmethod
    def pos(cls):
        return QPoint(cls.point)
module.QCursor = Cursor
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))
window = module.Maps()
window.finish_startup(show_on_launch=False)
window.toggle()
QTest.qWait(70)
assert window._pointer_loc_button.isChecked()
assert 'Pointer LOC: On' in window._pointer_loc_button.toolTip()
assert window._cursor_loc_timer.isActive()
Cursor.point = window._scale_view.viewport().mapToGlobal(QPoint(180, 220))
QTest.qWait(90)
assert window._map._mouse_location.isVisible()
assert window._map._mouse_location.toPlainText().startswith('LOC ')

checked_states = []
choose_off = [True]
def inspect_menu():
    menu = next(menu for menu in window._map.findChildren(QMenu)
                if menu.isVisible() and any(
                    action.text() == 'Show pointer coordinates (/loc)'
                    for action in menu.actions()))
    action = next(action for action in menu.actions()
                  if action.text() == 'Show pointer coordinates (/loc)')
    checked_states.append(action.isChecked())
    if choose_off[0]:
        menu.setActiveAction(action)
        QTest.keyClick(menu, Qt.Key.Key_Return)
    else:
        QTest.keyClick(menu, Qt.Key.Key_Escape)
def open_menu():
    view = window._map
    QTimer.singleShot(0, inspect_menu)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                              QPoint(180, 220),
                              view.mapToGlobal(QPoint(180, 220)))
    view.contextMenuEvent(event)
open_menu()
assert checked_states == [True], checked_states
assert not window._pointer_loc_button.isChecked()
assert 'Pointer LOC: Off' in window._pointer_loc_button.toolTip()
assert not window._cursor_loc_timer.isActive()
assert not window._map._mouse_location.isVisible()
window.close()

config.load(str(profile))
config.verify_settings()
assert config.data['maps']['show_mouse_location'] is False
window = module.Maps()
window.finish_startup(show_on_launch=False)
window.toggle()
QTest.qWait(70)
assert not window._pointer_loc_button.isChecked()
assert not window._cursor_loc_timer.isActive()
choose_off[0] = False
open_menu()
assert checked_states == [True, False], checked_states
window.close()
app.quit()
print('POINTER DEFAULT UI PASSED')
'''


def test_migrated_map_has_checked_context_action_and_live_pointer(tmp_path):
    result = subprocess.run(
        [sys.executable, '-B', '-c', UI_SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path),
                 QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'POINTER DEFAULT UI PASSED' in result.stdout
