"""Cursor-following LOC without MouseMove delivery, player data, or game logs."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMenu, QWidget, QGraphicsItem
from PySide6.QtTest import QTest
from vantage.helpers import config, to_eq_xy
sys.path.insert(0, str(Path('tests').resolve()))
from map_pointer_assertions import pointer_panel_rect, assert_pointer_pixels
from vantage.parsers.maps import window as module

app = QApplication([])
QFontDatabase.addApplicationFont('data/fonts/NotoSans-Regular.ttf')
QFontDatabase.addApplicationFont('data/fonts/NotoSans-Bold.ttf')
app.setFont(QFont('Noto Sans'))
class Settings(QObject):
    config_updated = Signal()
app._signals = {'settings': Settings(), 'maps': module.MapsSignals()}
config.verify_settings()
config.save = lambda: None
config.data['maps'].update(show_mouse_location=True, auto_hide_menu=False,
                           clickthrough=False)
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))

class Cursor:
    point = QPoint(-10000, -10000)
    @classmethod
    def pos(cls):
        return QPoint(cls.point)
# Do not move the user's actual cursor. No synthetic MouseMove is sent either.
module.QCursor = Cursor
window = module.Maps()
window.resize(640, 440)
window.show()
QTest.qWait(100)

def view():
    return window._preview_map or window._map

def point_at(x=.5, y=.6):
    outer = window._scale_view.viewport()
    return QPoint(round(outer.width()*x), round(outer.height()*y))

def move_cursor(position):
    Cursor.point = window._scale_view.viewport().mapToGlobal(position)
    QTest.qWait(100)

def expect(position):
    outer = window._scale_view
    logical = window._scale_proxy.mapFromScene(outer.mapToScene(position)).toPoint()
    local = view().viewport().mapFrom(window._surface, logical)
    assert view().viewport().rect().contains(local)
    x, y = to_eq_xy(*view().mapToScene(local).toTuple())
    overlay = view()._mouse_location
    assert overlay.isVisible(), (position, Cursor.pos(), overlay.toPlainText())
    assert overlay.toPlainText() == f'LOC · {int(x)}, {int(y)}'
    bounds = assert_pointer_pixels(window, view())
    assert outer.viewport().rect().contains(bounds), (outer.viewport().rect(), bounds)
    if outer.viewport().width() >= 200:
        assert bounds.height() < 40, 'Normal windows should use a compact single-line readout'
    assert not hasattr(window, '_pointer_loc_overlay'), 'Exactly one scene readout'
    return overlay.toPlainText(), pointer_panel_rect(window, view()).topLeft()

mode = sys.argv[1]
if mode in ('inner_move', 'inner_resize', 'inner_scale'):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    position = point_at(.3, .65)
    Cursor.point = window._scale_view.viewport().mapToGlobal(position)
    logical = window._scale_proxy.mapFromScene(window._scale_view.mapToScene(position)).toPoint()
    local = view().viewport().mapFrom(window._surface, logical)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(local),
                       Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view().viewport(), event)
    QTest.qWait(100)
    expect(position)
    assert window._canvas_pointer_event is not None
    stationary = QPoint(Cursor.pos())
    if mode == 'inner_move':
        window.move(window.pos() + QPoint(60, 0))
    elif mode == 'inner_resize':
        window.resize(740, 440)
    else:
        window.resize(300, 440)
    QTest.qWait(120)
    assert Cursor.pos() == stationary
    assert window._canvas_pointer_event is None
    expect(window._scale_view.viewport().mapFromGlobal(stationary))
elif mode == 'inner_event':
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    # Windows/proxy delivery may reach only the inner map. Global sampling is
    # deliberately outside: it must not erase a valid local move immediately.
    Cursor.point = QPoint(-10000, -10000)
    first_text = None
    for local in (QPoint(100, 120), QPoint(260, 180)):
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(local),
                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                           Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view().viewport(), event)
        QTest.qWait(120)
        position = window._canvas_to_panel(view(), local)
        text, _ = expect(position)
        if first_text is not None:
            assert text != first_text
        first_text = text
    assert not view()._data.players
elif mode == 'mouse_only':
    assert not view()._data.players
    # A lost/disabled Qt mouse stream must not affect sampled cursor tracking.
    window._scale_view.viewport().setMouseTracking(False)
    view().viewport().setMouseTracking(False)
    first = point_at(.25, .45)
    second = point_at(.75, .75)
    move_cursor(first)
    text1, pos1 = expect(first)
    move_cursor(second)
    text2, pos2 = expect(second)
    assert text1 != text2 and pos1 != pos2
    assert not view()._data.players, 'Hover must not create/move a player'
    assert view()._mouse_location.scene() is view().scene()
    assert view()._mouse_location.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert not view()._mouse_location.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
    assert 33 <= window._cursor_loc_timer.interval() <= 50
elif mode in ('preview_scale', 'high_dpi'):
    overlay = view()._mouse_location
    timer = window._cursor_loc_timer
    for width in (100, 200, 400, 900, 300):
        window.resize(width, 440)
        QTest.qWait(80)
        position = point_at(.7, .75)
        move_cursor(position)
        expect(position)
    assert window._preview_zone('skyshrine')
    QTest.qWait(100)
    position = point_at(.4, .6)
    move_cursor(position)
    expect(position)
    assert view()._mouse_location is not overlay and window._cursor_loc_timer is timer
    assert window._return_to_live_map()
    QTest.qWait(100)
    expect(position)
elif mode == 'inactive_window':
    other = QWidget()
    other.show()
    other.activateWindow()
    QTest.qWait(100)
    assert not window.isActiveWindow()
    for position in (point_at(.3, .5), point_at(.7, .8)):
        move_cursor(position)
        expect(position)
        assert not window.isActiveWindow(), 'Readout must not steal focus'
    other.close()
elif mode == 'stationary_transform':
    position = point_at(.6, .6)
    move_cursor(position)
    initial, _ = expect(position)
    center = view().mapToScene(view().viewport().rect().center())
    view().centerOn(center + QPointF(500, 400))
    QTest.qWait(100)
    moved, _ = expect(position)
    assert moved != initial
    view().update_(view()._scale * 1.5)
    QTest.qWait(100)
    expect(position)
elif mode == 'lifecycle':
    position = point_at()
    move_cursor(position)
    expect(position)
    window._toggle_show_mouse_location(False)
    QTest.qWait(80)
    assert not window._cursor_loc_timer.isActive()
    assert not view()._mouse_location.isVisible()
    window._toggle_show_mouse_location(True)
    QTest.qWait(100)
    expect(position)
    window._set_collapsed(True)
    QTest.qWait(80)
    assert not window._cursor_loc_timer.isActive()
    assert not view()._mouse_location.isVisible()
    window._set_collapsed(False)
    QTest.qWait(100)
    move_cursor(point_at())
    expect(point_at())
    window.hide()
    assert not window._cursor_loc_timer.isActive()
    window.show()
    QTest.qWait(100)
    move_cursor(point_at())
    expect(point_at())
    window.showMinimized()
    QTest.qWait(80)
    assert not window._cursor_loc_timer.isActive()
    assert not view()._mouse_location.isVisible()
    window.showNormal()
    QTest.qWait(100)
    move_cursor(point_at())
    expect(point_at())
    window._clickthrough = True
    window._sample_pointer_loc()
    assert not view()._mouse_location.isVisible()
elif mode == 'edges_and_idle':
    for fraction in ((.02, .12), (.98, .12), (.02, .98), (.98, .98)):
        position = point_at(*fraction)
        move_cursor(position)
        expect(position)
    calls = []
    overlay = view()._mouse_location
    original = overlay.setPlainText
    def record(text):
        calls.append(text)
        original(text)
    overlay.setPlainText = record
    QTest.qWait(250)
    assert not calls, 'Unchanged cursor must not relayout the readout every tick'
    move_cursor(QPoint(10, 5))
    assert not overlay.isVisible(), 'Header is not the map'
    Cursor.point = QPoint(-10000, -10000)
    QTest.qWait(100)
    assert not overlay.isVisible()
elif mode == 'keyboard':
    Cursor.point = QPoint(-10000, -10000)
    QTest.qWait(80)
    QTest.keyClick(view(), Qt.Key.Key_L)
    QTest.qWait(120)
    assert view()._mouse_location.isVisible()
    assert view()._mouse_location.toPlainText() in view().accessibleDescription()
    move_cursor(point_at())
    expect(point_at())
    window._toggle_show_mouse_location(False)
    QTest.keyClick(view(), Qt.Key.Key_L)
    QTest.qWait(100)
    assert view()._mouse_location.isVisible()
    assert not window._cursor_loc_timer.isActive()
    assert config.data['maps']['show_mouse_location'] is False
elif mode in ('popup', 'proxied_popup'):
    position = point_at()
    move_cursor(position)
    expect(position)
    menu = QMenu(view() if mode == 'proxied_popup' else window._scale_view.viewport())
    menu.addAction('Test map menu')
    menu.popup(Cursor.pos())
    QTest.qWait(100)
    assert not view()._mouse_location.isVisible()
    menu.close()
    QTest.qWait(100)
    expect(position)
window.close()
assert not window._cursor_loc_timer.isActive()
app.quit()
print('CURSOR TRACKING PASSED')
'''


@pytest.mark.parametrize('mode', [
    'mouse_only', 'preview_scale', 'stationary_transform', 'lifecycle',
    'edges_and_idle', 'keyboard', 'popup', 'proxied_popup', 'high_dpi', 'inactive_window',
    'inner_event', 'inner_move', 'inner_resize', 'inner_scale'])
def test_pointer_loc_without_mouse_events_or_game_logs(tmp_path, mode):
    env = dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path),
               QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
    if mode == 'high_dpi':
        env['QT_SCALE_FACTOR'] = '1.5'
    result = subprocess.run([sys.executable, '-B', '-c', SCRIPT, mode],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CURSOR TRACKING PASSED' in result.stdout
