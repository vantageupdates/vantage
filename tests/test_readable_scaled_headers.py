import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox

from vantage.helpers import config
from vantage.helpers.application import VantageApp


config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])


def physical_rect(panel, widget):
    logical = widget.mapTo(panel._surface, widget.rect().topLeft())
    scale = float(panel._scale_view.transform().m11())
    return QRect(
        round(logical.x() * scale), round(logical.y() * scale),
        max(1, round(widget.width() * scale)),
        max(1, round(widget.height() * scale)))


def no_overlaps(items):
    return all(
        not first.intersects(second)
        for index, first in enumerate(items)
        for second in items[index + 1:])


def snapshot(panel, width, height):
    panel._set_collapsed(False)
    panel.resize(width, height)
    panel._set_header_revealed(True)
    panel.show()
    QTest.qWait(40)
    panel._pack_header_controls()
    app.processEvents()
    scale = float(panel._scale_view.transform().m11())
    root = [
        panel._button, panel._title_icon, panel._title,
        panel._parser_menu_area, panel._header_overflow_button,
        panel._settings_button, panel._roll_button,
        panel._minimize_button]
    root_rects = [
        physical_rect(panel, widget) for widget in root
        if widget.isVisibleTo(panel._surface)]
    menu_controls = []
    for control_type in (QAbstractButton, QAbstractSpinBox, QComboBox):
        for control in panel._parser_menu_area.findChildren(control_type):
            if control.isVisibleTo(panel._surface):
                menu_controls.append(physical_rect(panel, control))
    return {
        'window': [panel.width(), panel.height()],
        'scale': scale,
        'menu_height': panel._menu.height() * scale,
        'title_font_height': panel._title.fontMetrics().height() * scale,
        'title_width': panel._title.width() * scale,
        'title_text_width': (
            panel._title.fontMetrics().horizontalAdvance(panel._title.text()) *
            scale),
        'root_inside': all(
            rect.left() >= 3 and rect.right() < panel.width() - 3
            for rect in root_rects),
        'root_separate': no_overlaps(root_rects),
        'menu_separate': no_overlaps(menu_controls),
        'smallest_control': min(
            (min(rect.width(), rect.height()) for rect in menu_controls),
            default=99),
        'overflow': panel._header_overflow_button.isVisibleTo(panel._surface),
    }


spells = app._parsers_dict['spells']
timers = app._parsers_dict['timers']
result = {
    'spells_short': snapshot(spells, 218, 180),
    'timers_short': snapshot(timers, 323, 180),
}
result['timers_tall'] = snapshot(timers, 323, 300)

# Rolling from either side of the former 215 px Spells breakpoint must produce
# one stable, fully measured header rather than swapping controls afterward.
rolled = []
for width in (214, 216):
    spells._set_collapsed(False)
    spells.resize(width, 180)
    spells.show()
    QTest.qWait(30)
    spells._set_collapsed(True)
    QTest.qWait(30)
    state = snapshot(spells, width, 180)
    spells._set_collapsed(True)
    QTest.qWait(30)
    state.update({
        'rolled_width': spells.width(),
        'surface_height': spells._surface.height(),
        'header_height': spells._menu.height(),
        'rolled_scale': float(spells._scale_view.transform().m11()),
    })
    rolled.append(state)
result['spells_rolled'] = rolled

# Startup can roll a window before its first show. Timers must stay a true
# header strip instead of re-expanding its protected 360 px timer canvas.
timers._set_collapsed(False)
timers.hide()
timers._set_collapsed(True)
timers.show()
QTest.qWait(30)
result['timers_rolled'] = {
    'window': [timers.width(), timers.height()],
    'surface': [timers._surface.width(), timers._surface.height()],
    'menu': [timers._menu.width(), timers._menu.height()],
    'scale': float(timers._scale_view.transform().m11()),
}

print(json.dumps(result))
app.quit()
"""


def test_scaled_spell_and_timer_headers_keep_readable_physical_metrics(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    for name in ('spells_short', 'timers_short', 'timers_tall'):
        state = result[name]
        assert state['menu_height'] >= 19
        assert state['title_font_height'] >= 12
        assert state['title_width'] >= state['title_text_width']
        assert state['root_inside'] is True
        assert state['root_separate'] is True
        assert state['menu_separate'] is True
        assert state['smallest_control'] >= 16
        assert state['overflow'] is True

    assert result['spells_short']['window'][0] >= 210
    assert result['timers_short']['window'][0] >= 300
    assert result['timers_short']['scale'] == result['timers_tall']['scale']
    assert result['timers_short']['menu_height'] == \
        result['timers_tall']['menu_height']

    rolled = result['spells_rolled']
    assert rolled[0]['rolled_width'] == rolled[1]['rolled_width']
    assert all(
        state['surface_height'] == state['header_height']
        and state['rolled_scale'] == 1.0
        for state in rolled)

    timers_rolled = result['timers_rolled']
    assert timers_rolled['window'][1] == timers_rolled['menu'][1]
    assert timers_rolled['surface'][1] == timers_rolled['menu'][1]
    assert timers_rolled['scale'] == 1.0
