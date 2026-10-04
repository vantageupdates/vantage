"""A saved narrow Quick Bar remains a viewport, not an expanded catalog."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import ctypes
import sys
from ctypes import wintypes
import json
import os
from pathlib import Path
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QContextMenuEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.parser import WM_SIZING, WMSZ_BOTTOM
from vantage.parsers.quickbar import QuickBar

# Test exact authored rectangles independent of the synthetic 800px monitor;
# screen recovery has separate coverage. Never access a live profile or game.
QuickBar._fit_to_available_screen = lambda self: None
config.data['general']['startup_window_state'] = 'normal'
config.data['quickbar'].update(orientation='vertical',
    geometry=[10, 0, 30, 767], show_header=True, notification_rail=True)
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar._auto_hide_menu = False
bar.show()
bar._set_header_revealed(True)
QTest.qWait(40)
scroll = bar._scale_view.verticalScrollBar()
footer = bar._column_scroll_button
result = {'saved': {
    'rect': [bar.x(), bar.y(), bar.width(), bar.height()],
    'pref': list(config.data['quickbar']['geometry']),
    'design': [bar._design_size.width(), bar._design_size.height()],
    'logical_height': bar._logical_surface_height,
    'targets': all((b.width(), b.height()) == (24, 24)
                   for b in bar._buttons.values()),
    'footer': [footer.isVisible(), footer.width(), footer.height()],
    'range': scroll.maximum(), 'scale': bar._scale_view.transform().m11(),
}}
capture_dir = os.environ.get('VANTAGE_COLUMN_CAPTURE_DIR')
scale_name = os.environ.get('QT_SCALE_FACTOR', '1').replace('.', '_')
def capture(name):
    if capture_dir:
        destination = Path(capture_dir)
        destination.mkdir(parents=True, exist_ok=True)
        assert bar.grab().save(str(destination / (scale_name + '--' + name + '.png')))

capture('saved-first')
viewport = bar._scale_view.viewport()
point = QPointF(viewport.rect().center())
wheel = QWheelEvent(point, QPointF(viewport.mapToGlobal(point.toPoint())),
    QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(viewport, wheel)
QTest.qWait(20)
offset = scroll.value()
result['wheel'] = offset > 0
bar.refresh_state()
bar._update_uniform_scale()
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(40)
result['refresh'] = scroll.value() == offset and \
    [bar.width(), bar.height()] == [30, 767]
bar._save_geometry()
result['persisted'] = config.data['quickbar']['geometry'] == [10, 0, 30, 767]
scroll.setValue(scroll.maximum())
capture('saved-last')

# Bottom-edge native resizing may shorten the viewport while keeping the
# width floor and full-size canvas. Other panels' native constraints are not
# changed; no actual user window is resized by this synthetic message.
if sys.platform == 'win32':
    from vantage.helpers.parser import _WindowsRect
    dpr = bar.devicePixelRatioF()
    width_pixels = round(30 * dpr)
    height_pixels = round(360 * dpr)
    rect = _WindowsRect(10, 0, 10 + width_pixels, height_pixels)
    message = wintypes.MSG()
    message.message = WM_SIZING
    message.wParam = WMSZ_BOTTOM
    message.lParam = ctypes.addressof(rect)
    native_result = bar.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
    result['native'] = native_result == (True, 1) and \
        (rect.left, rect.top, rect.right, rect.bottom) == \
            (10, 0, 10 + width_pixels, height_pixels) and \
        bar._effective_minimum_scale() == 1 and bar._minimum_readable_width == 0
    edges = []
    for edge in range(1, 9):
        rect = _WindowsRect(10, 0, 15, height_pixels)
        message.wParam = edge
        message.lParam = ctypes.addressof(rect)
        bar.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
        edges.append(rect.right - rect.left >= width_pixels and
                     rect.bottom - rect.top == height_pixels)
    result['native_width_all_edges'] = all(edges)
    bar._native_resize_session = False
else:
    result['native'] = True

bar.resize(30, 360)
QTest.qWait(30)
scroll.setValue(scroll.minimum())
capture('short-first')
def visible(widget):
    corner = widget.mapTo(bar._surface, QPoint(0, 0))
    rect = bar._scale_proxy.mapRectToScene(QRectF(
        corner.x(), corner.y(), widget.width(), widget.height()))
    mapped = bar._scale_view.mapFromScene(rect).boundingRect()
    return mapped.top() >= 0 and mapped.bottom() < viewport.height()

# Normal Tab navigation reveals the entire visual sequence, including the
# final support action, without shrinking targets or changing the rectangle.
app.setActiveWindow(bar)
bar.restore_action_focus('maps')
QTest.qWait(30)
bar.orientation_button.setFocus(Qt.FocusReason.TabFocusReason)
QTest.qWait(20)
actions = bar._column_focus_actions()
walk = []
for expected in actions:
    current = bar._surface.focusWidget()
    walk.append(current is expected and current.hasFocus() and visible(current))
    QTest.keyClick(current, Qt.Key.Key_Tab)
    QTest.qWait(15)
result['tab_walk'] = walk
result['footer_keyboard'] = footer.hasFocus()
QTest.keyClick(footer, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(20)
result['backtab'] = actions[-1].hasFocus() and visible(actions[-1])
capture('short-last')

QTest.keyClick(actions[-1], Qt.Key.Key_PageUp)
QTest.qWait(20)
result['page_up'] = scroll.value() < scroll.maximum()
QTest.keyClick(actions[-1], Qt.Key.Key_PageDown)
QTest.qWait(20)
result['page_down'] = scroll.value() == scroll.maximum()
footer.click()
result['footer_click'] = scroll.value() < scroll.maximum()

# Reopening/closing an editor from a currently clipped action restores and
# reveals the actual launcher instead of leaving keyboard focus offscreen.
scroll.setValue(scroll.maximum())
dialog = app.show_triggers(owner=bar)
QTest.qWait(30)
dialog.close()
QTest.qWait(60)
trigger = bar._buttons['triggers']
result['editor_focus'] = trigger.hasFocus() and visible(trigger)

calls = []
original_trigger = bar._trigger
bar._trigger = lambda key: calls.append(key)
bar._buttons['maps'].setEnabled(False)
bar._buttons['mute'].setChecked(True)
menu, menu_actions = bar._build_window_context_menu()
all_actions = menu_actions['quickbar_actions'].menu()
entries = {action.text(): action for action in all_actions.actions()}
result['menu_state'] = (
    menu.actions()[0] is menu_actions['quickbar_actions'] and
    len(entries) == sum(not button.isHidden() for button in bar._buttons.values()) and
    not entries['Maps'].isEnabled() and entries['Sounds'].isChecked())
entries[str(bar._buttons['support'].property('BaseLabel'))].trigger()
result['menu_dispatch'] = calls == ['support']
bar._buttons['maps'].setEnabled(True)
bar._trigger = original_trigger
menu.deleteLater()

# Native keyboard context events from a logical action and the native footer
# route to the same window menu, without shared router modifications.
context_calls = []
bar._show_window_context_menu = lambda position=None: context_calls.append(position)
for widget in (bar._buttons['support'], footer):
    event = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard,
        QPoint(1, 1), widget.mapToGlobal(QPoint(1, 1)))
    QApplication.sendEvent(widget, event)
result['keyboard_context'] = len(context_calls) == 2
QTest.keyClick(bar._buttons['support'], Qt.Key.Key_F10,
               Qt.KeyboardModifier.ShiftModifier)
QTest.keyClick(footer, Qt.Key.Key_Menu)
result['context_shortcuts'] = len(context_calls) == 4

# A catalog preference change may adjust the canvas, never the saved viewport.
prior = [bar.width(), bar.height()]
config.data['quickbar']['show_support'] = False
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(20)
result['catalog_rectangle'] = [bar.width(), bar.height()] == prior
config.data['quickbar']['show_server_tick'] = False
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(20)
result['hidden_tick_focus'] = bar.tick_countdown not in bar._column_focus_actions()
config.data['quickbar']['show_server_tick'] = True
config.data['quickbar']['show_support'] = True
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(20)

# Floating written notifications are outside this scrolling action viewport.
rail = bar.notification_rail
rail.present(991, 'Synthetic scroll-safe notice', reduce_motion=True)
QTest.qWait(20)
before_notice = (rail._current_text, list(rail._pending))
scroll.setValue(scroll.maximum())
bar._update_uniform_scale()
result['notice_unchanged'] = before_notice == (rail._current_text, list(rail._pending))
config.data['quickbar']['orientation'] = 'horizontal'
bar._apply_quickbar_settings(preserve_scale=True)
QTest.qWait(20)
result['horizontal'] = not footer.isVisible() and bar._column_footer_height == 0 and \
    bar._buttons['triggers'].text() == 'Triggers'
result['presets'] = []
for scale in (.5, .75, 1):
    bar._set_replica_scale(scale)
    QTest.qWait(15)
    result['presets'].append([bar.width(), bar.height()] == [
        round(bar._design_size.width() * scale),
        round(bar._design_size.height() * scale)])
print(json.dumps(result))
app.quit()
'''


@pytest.mark.parametrize('display_scale', ('1', '1.25', '1.5'))
def test_saved_column_scrolls_and_reveals_all_authored_actions(display_scale):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=display_scale,
               PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src'))))
    completed = subprocess.run([sys.executable, '-B', '-c', SCRIPT],
        cwd=ROOT, env=env, check=False, capture_output=True, text=True, timeout=50)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['saved'] == {
        'rect': [10, 0, 30, 767], 'pref': [10, 0, 30, 767],
        'design': [30, 791], 'logical_height': 791, 'targets': True,
        'footer': [True, 24, 24], 'range': 48, 'scale': 1.0}
    assert all(result['tab_walk']), result['tab_walk']
    assert all(result['presets'])
    for name, value in result.items():
        if name not in {'saved', 'tab_walk', 'presets'}:
            assert value is True, (name, result)
