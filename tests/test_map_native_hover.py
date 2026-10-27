"""Exercise hover through the real panel, not directly through MapCanvas."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QPoint, QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from vantage.helpers import config, to_eq_xy
sys.path.insert(0, str(Path('tests').resolve()))
from map_pointer_assertions import pointer_panel_rect, assert_pointer_pixels
from vantage.parsers.maps.window import Maps, MapsSignals
from vantage.parsers.maps import window as maps_module

app = QApplication([])
QFontDatabase.addApplicationFont('data/fonts/NotoSans-Regular.ttf')
QFontDatabase.addApplicationFont('data/fonts/NotoSans-Bold.ttf')
app.setFont(QFont('Noto Sans'))
class Cursor:
    point = QPoint(-10000, -10000)
    @classmethod
    def pos(cls):
        return QPoint(cls.point)
maps_module.QCursor = Cursor
class Settings(QObject):
    config_updated = Signal()
app._signals = {'settings': Settings(), 'maps': MapsSignals()}
config.verify_settings()
config.save = lambda: None
config.data['maps'].update(show_mouse_location=True, auto_hide_menu=False,
                           clickthrough=False)
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))
window = Maps()
window.resize(400, 440)
window.show()

def settle():
    for _ in range(8):
        app.processEvents()

def move(position):
    viewport = window._scale_view.viewport()
    Cursor.point = viewport.mapToGlobal(position)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position),
                       QPointF(viewport.mapToGlobal(position)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)
    settle()

def canvas():
    return window._preview_map or window._map

def check_hover(fraction=.8):
    outer = window._scale_view
    position = QPoint(int(outer.viewport().width() * fraction),
                      int(outer.viewport().height() * .72))
    view = canvas()
    logical = window._scale_proxy.mapFromScene(outer.mapToScene(position))
    local = view.viewport().mapFrom(window._surface, logical.toPoint())
    assert view.viewport().rect().contains(local), (
        window.size(), view.viewport().size(), local)
    canvas()._mouse_location.hide()
    move(position)
    label = canvas()._mouse_location
    assert label.isVisible(), (window.size(), local, label.toPlainText())
    x, y = to_eq_xy(*view.mapToScene(local).toTuple())
    assert label.toPlainText() == f'LOC · {int(x)}, {int(y)}'
    bounds = assert_pointer_pixels(window, view)
    assert outer.viewport().rect().contains(bounds), bounds
    assert label.scene() is view.scene()

settle()
mode = sys.argv[1]
if mode == 'resize':
    # Native-width changes keep logical height constant. This must resize the
    # inner surface too; otherwise the right half is an input dead region.
    for width in (400, 640, 1000, 640, 400, 300, 200, 640):
        window.resize(width, 440)
        settle()
        expected = max(400, window._scale_view.viewport().width())
        assert window._surface.width() == expected, (
            width, window._surface.width(), expected)
        check_hover(.2)
        check_hover(.8)
elif mode == 'preview':
    assert window._preview_zone('skyshrine')
    settle()
    for width in (400, 750, 400):
        window.resize(width, 440)
        settle()
        check_hover()
    window._return_to_live_map()
    settle()
    check_hover()
elif mode == 'toggle':
    window.resize(640, 440)
    settle()
    button = next(button for button in window._surface.findChildren(QObject)
                  if hasattr(button, 'accessibleName') and
                  button.accessibleName() == 'Show map coordinates under the pointer')
    point = button.mapTo(window._surface, button.rect().center())
    point = window._scale_view.mapFromScene(window._scale_proxy.mapToScene(QPointF(point)))
    QTest.mouseClick(window._scale_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    move(QPoint(250, 250))
    assert not canvas()._mouse_location.isVisible()
    assert config.data['maps']['show_mouse_location'] is False
    QTest.mouseClick(window._scale_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    check_hover()
    assert config.data['maps']['show_mouse_location'] is True
    assert 'Pointer LOC: On' in button.toolTip()
elif mode == 'delivery':
    class LostInnerMove(QObject):
        def eventFilter(self, watched, event):
            return event.type() == QEvent.Type.MouseMove
    lost = LostInnerMove()
    # Simulate a nested proxy dropping unpressed moves. The physical panel
    # receives the event; LOC must provide immediate feedback as well as the
    # independent sampled-cursor recovery tested in test_map_cursor_tracking.
    canvas().viewport().installEventFilter(lost)
    check_hover(.3)
    check_hover(.7)
    assert window._cursor_loc_timer.isActive()
    move(QPoint(20, 10))
    assert not canvas()._mouse_location.isVisible()
    check_hover()
    Cursor.point = QPoint(-10000, -10000)
    QApplication.sendEvent(window._scale_view.viewport(), QEvent(QEvent.Type.Leave))
    settle()
    assert not canvas()._mouse_location.isVisible()
elif mode == 'menu':
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMenu
    from PySide6.QtGui import QContextMenuEvent
    # Use the native menu and keyboard activation inside its event loop.
    # Replacing QMenu.exec on the Python type does not override Qt's native
    # instance binding reliably.
    chosen = []
    def choose_pointer_loc():
        # The panel embeds popups in its graphics scene, so they are not
        # necessarily QApplication.activePopupWidget().
        menu = next(menu for menu in canvas().findChildren(QMenu)
                    if menu.isVisible() and any(
                        a.text() == 'Show pointer coordinates (/loc)'
                        for a in menu.actions()))
        action = next(a for a in menu.actions()
                      if a.text() == 'Show pointer coordinates (/loc)')
        assert action.isCheckable()
        QTest.qWait(100)
        assert not canvas()._mouse_location.isVisible(), 'Native LOC must not cover the proxied map menu'
        chosen.append(action.isChecked())
        menu.setActiveAction(action)
        QTest.keyClick(menu, Qt.Key.Key_Return)
    for preview in (False, True):
        if preview:
            assert window._preview_zone('skyshrine')
            settle()
        for enabled in (False, True):
            move(QPoint(250, 250))
            QTimer.singleShot(0, choose_pointer_loc)
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                      QPoint(150, 150),
                                      canvas().mapToGlobal(QPoint(150, 150)))
            canvas().contextMenuEvent(event)
            assert config.data['maps']['show_mouse_location'] is enabled, (
                preview, enabled, config.data['maps']['show_mouse_location'], chosen)
            assert window._pointer_loc_button.isChecked() is enabled, ('button', preview, enabled)
            move(QPoint(250, 250))
            assert canvas()._mouse_location.isVisible() is enabled, ('visible', preview, enabled)
    assert chosen == [True, False, True, False]
window.close()
app.quit()
print('PANEL HOVER PASSED')
'''


@pytest.mark.parametrize('mode', ['resize', 'preview', 'toggle', 'delivery', 'menu'])
def test_hover_from_physical_panel_viewport(tmp_path, mode):
    env = dict(os.environ, VANTAGE_DATA_DIR=str(tmp_path),
               QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-B', '-c', SCRIPT, mode],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PANEL HOVER PASSED' in result.stdout
