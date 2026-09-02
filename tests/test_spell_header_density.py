import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QAbstractButton

from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
panel = app._parsers_dict['spells']
panel._set_collapsed(False)
panel._set_header_revealed(True)
panel.resize(184, 390)
panel.show()
app.processEvents()

visible_controls = []
for control in panel._menu.findChildren(QAbstractButton):
    if not control.isVisible():
        continue
    top_left = control.mapTo(panel._menu, control.rect().topLeft())
    visible_controls.append((
        control.accessibleName() or control.objectName(),
        QRect(top_left, control.size())))

overlaps = []
for index, (first_name, first_rect) in enumerate(visible_controls):
    for second_name, second_rect in visible_controls[index + 1:]:
        if first_rect.intersects(second_rect):
            overlaps.append([first_name, second_name])

result = {
    'title': panel._title.text(),
    'title_width': panel._title.width(),
    'boat_visible': panel._boat_toggle.isVisible(),
    'library_visible': panel._library_button.isVisible(),
    'overflow_visible': panel._header_tools_button.isVisible(),
    'overflow_name': panel._header_tools_button.accessibleName(),
    'overflow_tooltip': panel._header_tools_button.toolTip(),
    'overflow_actions': [
        {'text': action.text(), 'tooltip': action.toolTip()}
        for action in panel._header_tools_button.menu().actions()
        if not action.isSeparator()],
    'overlaps': overlaps,
}

panel.resize(260, 400)
app.processEvents()
result['wide_boat_visible'] = panel._boat_toggle.isVisible()
result['wide_library_visible'] = panel._library_button.isVisible()
result['wide_overflow_visible'] = panel._header_tools_button.isVisible()

print(json.dumps(result))
app.quit()
"""


def test_narrow_spell_header_collapses_low_priority_tools_without_overlap(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['title'] == 'Spells'
    assert result['title_width'] >= 34
    assert result['boat_visible'] is False
    assert result['library_visible'] is False
    assert result['overflow_visible'] is True
    assert result['overflow_name'] == 'More spell tools'
    assert result['overflow_tooltip']
    assert result['overlaps'] == []
    assert len(result['overflow_actions']) == 4
    assert all(action['text'] and action['tooltip']
               for action in result['overflow_actions'])
    assert result['wide_boat_visible'] is True
    assert result['wide_library_visible'] is True
    assert result['wide_overflow_visible'] is False
