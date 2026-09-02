import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])

def audit(panel):
    controls = []
    for control_type in (QAbstractButton, QAbstractSpinBox, QComboBox):
        for control in panel._parser_menu_area.findChildren(control_type):
            if not control.isVisible():
                continue
            top_left = control.mapTo(panel._menu, control.rect().topLeft())
            controls.append((control.objectName() or control_type.__name__,
                             QRect(top_left, control.size())))
    overlaps = []
    for index, (first_name, first_rect) in enumerate(controls):
        for second_name, second_rect in controls[index + 1:]:
            if first_rect.intersects(second_rect):
                overlaps.append([first_name, second_name])
    chrome = []
    for name in ('_button', '_title_icon', '_title', '_parser_menu_area',
                 '_header_overflow_button', '_settings_button',
                 '_roll_button', '_minimize_button'):
        control = getattr(panel, name, None)
        if control is None or not control.isVisibleTo(panel._surface):
            continue
        top_left = control.mapTo(panel._menu, control.rect().topLeft())
        chrome.append((name, QRect(top_left, control.size())))
    chrome_overlaps = []
    for index, (first_name, first_rect) in enumerate(chrome):
        for second_name, second_rect in chrome[index + 1:]:
            if first_rect.intersects(second_rect):
                chrome_overlaps.append([first_name, second_name])
    inside = all(
        rect.left() >= 4 and rect.right() < panel._menu.width() - 4
        for _name, rect in chrome)
    return {
        'height': panel._menu.sizeHint().height(),
        'overlaps': overlaps,
        'chrome_overlaps': chrome_overlaps,
        'inside': inside,
        'title_width': panel._title.width(),
    }

result = {}
for name, panel in app._parsers_dict.items():
    panel._set_collapsed(False)
    panel.resize(panel._design_size)
    panel._set_header_revealed(True)
    panel.show()
    app.processEvents()
    normal = audit(panel)
    panel._set_collapsed(True)
    app.processEvents()
    result[name] = {'normal': normal, 'rolled': audit(panel)}

# Force the densest representative header below its authored width. The
# countdown and interval remain in place; lower-priority actions must move to
# an accessible overflow menu instead of covering the title or spin-box text.
heals = app._parsers_dict['heals']
heals._set_collapsed(False)
heals._set_design_size(QSize(300, heals._design_size.height()), False)
heals.resize(210, round(heals._design_size.height() * .7))
heals._set_header_revealed(True)
heals.show()
app.processEvents()
heals._pack_header_controls()
app.processEvents()
result['constrained_heals'] = {
    'normal': audit(heals),
    'overflow_visible': heals._header_overflow_button.isVisibleTo(
        heals._surface),
    'overflow_actions': [
        action.text() for action in heals._header_overflow_menu.actions()],
    'interval_width': heals.interval.width(),
    'countdown_visible': heals.header_countdown.isVisibleTo(heals._surface),
    'interval_visible': heals.interval.isVisibleTo(heals._surface),
}

print(json.dumps(result))
app.quit()
"""


def test_parser_headers_are_compact_and_controls_never_overlap(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result
    for panel_name, states in result.items():
        for state_name, state in states.items():
            if not isinstance(state, dict) or 'height' not in state:
                continue
            assert state['height'] <= 22
            assert state['overlaps'] == []
            assert state['chrome_overlaps'] == [], (panel_name, state_name)
            assert state['inside'] is True, (panel_name, state_name)
            assert state['title_width'] >= 36

    constrained = result['constrained_heals']
    assert constrained['overflow_visible'] is True
    assert constrained['overflow_actions']
    assert constrained['countdown_visible'] is True
    assert constrained['interval_visible'] is True
    assert constrained['interval_width'] >= 48
