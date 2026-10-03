"""Keep window chrome reachable after a display changes or is disconnected."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QRect, Signal
from PySide6.QtWidgets import QApplication, QWidget

from vantage.helpers import config
from vantage.helpers.parser import ParserWindow, ScreenGeometryWatcher


class Screen(QObject):
    availableGeometryChanged = Signal(QRect)
    geometryChanged = Signal(QRect)

    def __init__(self, area):
        super().__init__()
        self.area = QRect(area)

    def availableGeometry(self):
        return QRect(self.area)


class RectanglePanel:
    _collapsed = False

    def __init__(self, geometry, chrome=(0, 0, 0, 0)):
        self.client = QRect(*geometry)
        self.chrome = chrome
        self.changes = 0

    def geometry(self):
        return QRect(self.client)

    def frameGeometry(self):
        left, top, right, bottom = self.chrome
        return self.client.adjusted(-left, -top, right, bottom)

    def minimumWidth(self):
        return 48

    def minimumHeight(self):
        return 24

    def setGeometry(self, left, top, width, height):
        self.client = QRect(left, top, width, height)
        self.changes += 1


@contextmanager
def screens(*items):
    def at(point):
        return next((screen for screen in items
                     if screen.availableGeometry().contains(point)), None)

    with patch.object(QApplication, 'screens', return_value=list(items)), \
            patch.object(QApplication, 'primaryScreen', return_value=items[0]), \
            patch.object(QApplication, 'screenAt', side_effect=at):
        yield


def values(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


app = QApplication([])
laptop = Screen(QRect(0, 0, 1920, 1040))
secondary = Screen(QRect(-1920, 0, 1920, 1040))
result = {}

with screens(laptop):
    oversized = RectanglePanel([3000, 1500, 3040, 1900])
    ParserWindow._fit_to_available_screen(oversized)
    result['laptop'] = values(oversized.geometry())

    inside = RectanglePanel([213, 147, 777, 489])
    ParserWindow._fit_to_available_screen(inside)
    result['inside'] = values(inside.geometry())
    result['inside_changes'] = inside.changes

    edge_frames = []
    for geometry in ([5, 5, 600, 400], [1350, 650, 600, 400],
                     [3000, 1500, 3040, 1900]):
        framed = RectanglePanel(geometry, (8, 30, 8, 8))
        ParserWindow._fit_to_available_screen(framed)
        edge_frames.append({
            'client': values(framed.geometry()),
            'contained': laptop.availableGeometry().contains(framed.frameGeometry()),
        })
    result['frame_edges'] = edge_frames

    framed_inside = RectanglePanel([213, 147, 777, 489], (8, 30, 8, 8))
    ParserWindow._fit_to_available_screen(framed_inside)
    result['framed_inside'] = values(framed_inside.geometry())
    result['framed_inside_changes'] = framed_inside.changes

with screens(laptop, secondary):
    inside = RectanglePanel([-1800, 90, 600, 400])
    ParserWindow._fit_to_available_screen(inside)
    result['negative_origin'] = values(inside.geometry())
    # The center is outside both screens, but part of the window remains on
    # the secondary display. Recover there rather than switching to primary.
    partial = RectanglePanel([-2200, 90, 500, 400])
    ParserWindow._fit_to_available_screen(partial)
    result['secondary_overlap'] = values(partial.geometry())


class SettingsSignals(QObject):
    config_updated = Signal()


app._signals = {'settings': SettingsSignals()}
profile = Path(os.environ['VANTAGE_DATA_DIR'])
profile.mkdir(parents=True, exist_ok=True)
config.load(str(profile / 'vantage.config.json'))
config.data['maps'] = {
    'geometry': [2600, 1100, 640, 460], 'toggled': True,
    'collapsed': False, 'frameless': True, 'auto_hide_menu': False,
}
with screens(laptop):
    panel = ParserWindow(name='maps')
    panel.apply_saved_presentation()
    app.processEvents()
    result['visible_reload'] = values(panel.geometry())
    result['visible_reload_visible'] = panel.isVisible()
    config.data['maps']['geometry'] = [140, 90, 640, 460]
    panel.apply_saved_presentation()
    app.processEvents()
    result['visible_reload_inside'] = values(panel.geometry())

    recovery_calls = []
    fit = panel._fit_to_available_screen
    panel._fit_to_available_screen = lambda: recovery_calls.append(True) or fit()
    panel._native_resize_session = True
    panel._screen_geometry_watcher.schedule()
    app.processEvents()
    result['drag_deferred'] = not recovery_calls
    panel._native_resize_session = False
    panel._screen_geometry_watcher.schedule()
    app.processEvents()
    result['drag_end_recovers_once'] = len(recovery_calls) == 1
    recovery_calls.clear()
    panel.move(2600, 1100)
    app.processEvents()
    result['ordinary_move_not_clamped'] = not recovery_calls
    panel._geometry_save_timer.stop()

    # A plain native window verifies that the watcher can also be reused by
    # non-parser overlays, with real queued signals rather than a fake timer.
    window = QWidget()
    callbacks = []
    watcher = ScreenGeometryWatcher(window, lambda: callbacks.append(True))
    laptop.geometryChanged.emit(laptop.availableGeometry())
    laptop.availableGeometryChanged.emit(laptop.availableGeometry())
    watcher.schedule()
    watcher.schedule()
    result['recovery_is_queued'] = callbacks == []
    app.processEvents()
    result['geometry_changes_coalesced'] = len(callbacks) == 1

    for kind in (QEvent.Type.ScreenChangeInternal,
                 QEvent.Type.DevicePixelRatioChange):
        before = len(callbacks)
        QApplication.sendEvent(window, QEvent(kind))
        app.processEvents()
        result[kind.name] = len(callbacks) == before + 1

    before = len(callbacks)
    app.screenRemoved.emit(secondary)
    app.screenAdded.emit(secondary)
    app.processEvents()
    result['screen_topology_coalesced'] = len(callbacks) == before + 1
    before = len(callbacks)
    secondary.availableGeometryChanged.emit(secondary.availableGeometry())
    app.processEvents()
    result['new_screen_watched'] = len(callbacks) == before + 1

print(json.dumps(result))
panel._geometry_save_timer.stop()
app.quit()
"""


@pytest.fixture(scope='module')
def recovery_result(tmp_path_factory):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(
        tmp_path_factory.mktemp('screen-recovery') / 'profile')
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_large_monitor_geometry_fits_laptop_work_area(recovery_result):
    assert recovery_result['laptop'] == [0, 0, 1920, 1040]


def test_in_bounds_geometry_remains_exact(recovery_result):
    assert recovery_result['inside'] == [213, 147, 777, 489]
    assert recovery_result['inside_changes'] == 0
    assert recovery_result['framed_inside'] == [213, 147, 777, 489]
    assert recovery_result['framed_inside_changes'] == 0


def test_secondary_negative_origin_and_overlap_are_preserved(recovery_result):
    assert recovery_result['negative_origin'] == [-1800, 90, 600, 400]
    assert recovery_result['secondary_overlap'] == [-1920, 90, 500, 400]


def test_native_frame_edges_fit_without_resizing_smaller_clients(recovery_result):
    cases = recovery_result['frame_edges']
    assert all(case['contained'] for case in cases)
    assert cases[0]['client'] == [8, 30, 600, 400]
    assert cases[1]['client'] == [1312, 632, 600, 400]
    assert cases[2]['client'] == [8, 30, 1904, 1002]


def test_visible_reload_keeps_fitted_and_in_bounds_geometry(recovery_result):
    assert recovery_result['visible_reload_visible']
    assert recovery_result['visible_reload'] == [1280, 580, 640, 460]
    assert recovery_result['visible_reload_inside'] == [140, 90, 640, 460]


def test_monitor_recovery_is_queued_and_coalesced(recovery_result):
    for key in ('recovery_is_queued', 'geometry_changes_coalesced',
                'ScreenChangeInternal', 'DevicePixelRatioChange',
                'screen_topology_coalesced', 'new_screen_watched'):
        assert recovery_result[key], key


def test_monitor_recovery_waits_for_drag_without_clamping_ordinary_moves(
        recovery_result):
    for key in ('drag_deferred', 'drag_end_recovers_once',
                'ordinary_move_not_clamped'):
        assert recovery_result[key], key
