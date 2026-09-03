import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState


config.data['general']['startup_window_state'] = 'normal'
config.data['timers']['compact'] = True
app = VantageApp([])
panel = app._parsers_dict['timers']
panel._set_collapsed(False)
panel.compact.setChecked(True)

for index in range(4):
    timer = SpawnTimerState(f'Timer {index + 1}', 1800)
    panel._states[timer.timer_id] = timer
    panel._add_row(timer)

panel._sync_timer_canvas()
panel.resize(520, 1)
panel.show()
QTest.qWait(100)
four_row_minimum = panel.minimumHeight()
four_row_state = {
    'height': panel.height(),
    'minimum': four_row_minimum,
    'all_visible': all(not row.isHidden() for row in panel._rows.values()),
    'count': len(panel._rows),
    'status_visible': panel.status.isVisibleTo(panel._surface),
}

removed_id = next(iter(panel._states))
removed_row = panel._rows.pop(removed_id)
panel._states.pop(removed_id)
removed_row.setParent(None)
removed_row.deleteLater()
panel._sync_timer_canvas()
QTest.qWait(100)
three_row_state = {
    'minimum': panel.minimumHeight(),
    'all_visible': all(not row.isHidden() for row in panel._rows.values()),
    'count': len(panel._rows),
}

# A very large saved zone cannot make a top-level window taller than the
# available screen. Keep every row in the logical canvas and expose the
# exceptional overflow through the graphics view instead.
panel.compact.setChecked(False)
config.data['timers']['compact'] = False
for index in range(3, 15):
    timer = SpawnTimerState(f'Timer {index + 1}', 1800)
    panel._states[timer.timer_id] = timer
    panel._add_row(timer)
for row in panel._rows.values():
    row.refresh()
panel._sync_timer_canvas()
panel.resize(520, 1)
QTest.qWait(100)
scroll = panel._scale_view.verticalScrollBar()
last_row = list(panel._rows.values())[-1]
last_row.play_button.setFocus(Qt.FocusReason.TabFocusReason)
QTest.qWait(100)
logical_point = last_row.play_button.mapTo(
    panel._surface, last_row.play_button.rect().center())
scene_point = panel._scale_proxy.mapToScene(QPointF(logical_point))
viewport_point = panel._scale_view.mapFromScene(scene_point)
screen = panel.screen() or app.primaryScreen()
many_row_state = {
    'all_visible': all(not row.isHidden() for row in panel._rows.values()),
    'minimum': panel.minimumHeight(),
    'screen_height': screen.availableGeometry().height(),
    'scroll_policy': int(panel._scale_view.verticalScrollBarPolicy().value),
    'expected_policy': int(Qt.ScrollBarPolicy.ScrollBarAsNeeded.value),
    'scroll_maximum': scroll.maximum(),
    'scroll_value': scroll.value(),
    'focus_visible': panel._scale_view.viewport().rect().contains(
        viewport_point),
    'scroll_name': scroll.accessibleName(),
    'scroll_tooltip': scroll.toolTip(),
}

print(json.dumps({
    'four': four_row_state,
    'three': three_row_state,
    'many': many_row_state,
}))
app.quit()
"""


def test_timer_resize_floor_keeps_all_four_rows_visible(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['four']['count'] == 4
    assert result['four']['all_visible'] is True
    assert result['four']['status_visible'] is True
    assert result['four']['height'] == result['four']['minimum']
    assert result['three']['count'] == 3
    assert result['three']['all_visible'] is True
    assert result['three']['minimum'] < result['four']['minimum']
    assert result['many']['all_visible'] is True
    assert result['many']['minimum'] <= result['many']['screen_height']
    assert result['many']['scroll_policy'] == result['many']['expected_policy']
    assert result['many']['scroll_maximum'] > 0
    assert result['many']['scroll_value'] > 0
    assert result['many']['focus_visible'] is True
    assert result['many']['scroll_name'] == 'Scroll Smart Timer rows'
    assert 'complete zone list' in result['many']['scroll_tooltip']
