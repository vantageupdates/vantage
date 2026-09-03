import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.application import VantageApp


config.data['general']['startup_window_state'] = 'normal'
config.data['timers']['auto_hide_menu'] = False
app = VantageApp([])
panel = app._parsers_dict['timers']


def physical_rect(widget):
    logical = widget.mapTo(panel._surface, widget.rect().topLeft())
    scale = float(panel._scale_view.transform().m11())
    return QRect(
        round(logical.x() * scale), round(logical.y() * scale),
        max(1, round(widget.width() * scale)),
        max(1, round(widget.height() * scale)))


def separate(rects):
    return all(
        not first.intersects(second)
        for index, first in enumerate(rects)
        for second in rects[index + 1:])


def snapshot(width, rolled=False):
    panel._set_collapsed(False)
    panel.resize(width, 220)
    panel._set_header_revealed(True)
    panel.show()
    QTest.qWait(40)
    panel._pack_header_controls()
    app.processEvents()
    if rolled:
        panel._set_collapsed(True)
        QTest.qWait(40)
        panel._pack_header_controls()
        app.processEvents()

    root = [
        panel._button, panel._title_icon, panel._title,
        panel._parser_menu_area, panel._header_overflow_button,
        panel._settings_button, panel._roll_button,
        panel._minimize_button]
    root_rects = [
        physical_rect(widget) for widget in root
        if widget.isVisibleTo(panel._surface)]
    controls = [
        widget for widget in panel._header_menu_widgets()
        if widget.isVisibleTo(panel._surface)]
    control_rects = [physical_rect(widget) for widget in controls]
    return {
        'window': [panel.width(), panel.height()],
        'share_visible': panel.share_button.isVisibleTo(panel._surface),
        'zone_visible': panel.zone_filter.isVisibleTo(panel._surface),
        'mobile_visible': panel.mobile_button.isVisibleTo(panel._surface),
        'root_separate': separate(root_rects),
        'controls_separate': separate(control_rects),
        'root_inside': all(
            rect.left() >= 3 and rect.right() < panel.width() - 3
            for rect in root_rects),
        'overflow_visible': panel._header_overflow_button.isVisibleTo(
            panel._surface),
        'overflow_actions': [
            action.text() for action in
            panel._header_overflow_menu.actions()],
        'share_physical_size': [
            physical_rect(panel.share_button).width(),
            physical_rect(panel.share_button).height()],
        'zone_physical_size': [
            physical_rect(panel.zone_filter).width(),
            physical_rect(panel.zone_filter).height()],
    }


result = {
    'wide': snapshot(520),
    'narrow': snapshot(300),
    'rolled': snapshot(300, rolled=True),
    'share_always_visible': bool(
        panel.share_button.property('HeaderAlwaysVisible')),
    'zone_always_visible': bool(
        panel.zone_filter.property('HeaderAlwaysVisible')),
    'share_accessible_name': panel.share_button.accessibleName(),
    'zone_accessible_name': panel.zone_filter.accessibleName(),
    'share_tooltip': panel.share_button.toolTip(),
    'zone_tooltip': panel.zone_filter.toolTip(),
    'share_strong_focus': (
        panel.share_button.focusPolicy().name == 'StrongFocus'),
    'zone_strong_focus': (
        panel.zone_filter.focusPolicy().name == 'StrongFocus'),
}

# Auto-hidden headers must still be reachable without a pointer. The shared
# application router reveals the header before Qt resolves the next Tab stop.
panel._set_collapsed(False)
panel.resize(520, 220)
panel._auto_hide_menu = True
panel._set_header_revealed(False)
panel._scale_view.setFocus()
QTest.keyClick(panel._scale_view.viewport(), Qt.Key.Key_Tab)
app.processEvents()
result['keyboard_reveals_auto_hidden_header'] = panel._menu.isEnabled()

# If responsive packing hides the focused secondary action, focus moves to the
# overflow button and returns to that action when enough width is restored.
panel._auto_hide_menu = False
panel._set_header_revealed(True)
panel.resize(520, 220)
QTest.qWait(40)
panel._pack_header_controls()
panel._scale_scene.setFocusItem(panel._scale_proxy)
panel.mobile_button.setFocus(Qt.FocusReason.TabFocusReason)
app.processEvents()
result['mobile_focused_wide'] = \
    panel._surface.focusWidget() is panel.mobile_button
panel.resize(300, 220)
QTest.qWait(40)
panel._pack_header_controls()
app.processEvents()
result['focus_moved_to_overflow'] = \
    panel._surface.focusWidget() is panel._header_overflow_button
panel.resize(520, 220)
QTest.qWait(40)
panel._pack_header_controls()
app.processEvents()
result['focus_restored_to_mobile'] = \
    panel._surface.focusWidget() is panel.mobile_button

print(json.dumps(result))
app.quit()
"""


def test_share_and_zone_stay_directly_visible_in_timer_header(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['share_always_visible'] is True
    assert result['zone_always_visible'] is True
    assert result['share_accessible_name'] == \
        'Share visible zone timers by code'
    assert result['zone_accessible_name'] == 'Timer zone view'
    assert result['share_tooltip']
    assert result['zone_tooltip']
    assert result['share_strong_focus'] is True
    assert result['zone_strong_focus'] is True
    assert result['keyboard_reveals_auto_hidden_header'] is True
    assert result['mobile_focused_wide'] is True
    assert result['focus_moved_to_overflow'] is True
    assert result['focus_restored_to_mobile'] is True

    for name in ('wide', 'narrow', 'rolled'):
        state = result[name]
        assert state['share_visible'] is True, name
        assert state['zone_visible'] is True, name
        assert state['root_separate'] is True, name
        assert state['controls_separate'] is True, name
        assert state['root_inside'] is True, name
        assert min(state['share_physical_size']) >= 16, name
        assert state['zone_physical_size'][0] >= 72, name
        assert state['zone_physical_size'][1] >= 16, name

    narrow = result['narrow']
    assert narrow['window'][0] >= 300
    assert narrow['overflow_visible'] is True
    assert narrow['mobile_visible'] is False
    assert 'View Vantage on your phone' in narrow['overflow_actions']
    assert 'Share visible zone timers by code' not in \
        narrow['overflow_actions']

    assert result['wide']['mobile_visible'] is True
    assert result['rolled']['window'][1] <= 24
