import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtTest import QTest

from vantage.helpers import config
from vantage.helpers.application import VantageApp


config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
result = {}

for name, panel in app._parsers_dict.items():
    if name == 'quickbar':
        continue
    panel._set_collapsed(False)
    cases = []
    for scale in (0.25, 0.35, 0.50, 0.75):
        panel._set_replica_scale(scale)
        QTest.qWait(20)
        cases.append({
            'scale': scale,
            'size': [panel.width(), panel.height()],
            'expected': [
                round(panel._design_size.width() * scale),
                round(panel._design_size.height() * scale)],
        })

    panel._set_replica_scale(0.35)
    QTest.qWait(20)
    mini = [panel.width(), panel.height()]
    menu, actions = panel._build_window_context_menu()
    labels = [action.text() for action in actions['sizes']]
    checked = [
        action.text() for action in actions['sizes'] if action.isChecked()]
    menu.deleteLater()

    panel._set_collapsed(True)
    QTest.qWait(20)
    rolled = [panel.width(), panel.height()]
    panel._set_collapsed(False)
    QTest.qWait(20)
    expanded = [panel.width(), panel.height()]

    panel.show()
    panel._minimize_to_tray()
    minimized = not panel.isVisible() and not panel._toggled
    saved_while_hidden = config.data[name]['geometry'][2:]
    panel.toggle()
    QTest.qWait(20)
    tray_restore = [panel.width(), panel.height()]

    result[name] = {
        'design': [panel._design_size.width(), panel._design_size.height()],
        'cases': cases,
        'mini': mini,
        'labels': labels,
        'checked': checked,
        'rolled': rolled,
        'expanded': expanded,
        'minimized': minimized,
        'saved_while_hidden': saved_while_hidden,
        'tray_restore': tray_restore,
    }

print(json.dumps(result))
app.quit()
"""


def test_every_window_size_preset_rollup_and_tray_restore_are_effective(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    expected_labels = [
        'Tiny replica · 25%', 'Mini replica · 35%',
        'Compact replica · 50%', 'Comfortable · 75%',
        'Original · 100%']
    assert set(result) == {
        'maps', 'spells', 'tick', 'timers', 'combat', 'heals', 'market',
        'opendkp', 'zones', 'quests', 'vantage_ui'}
    for state in result.values():
        assert all(case['size'] == case['expected'] for case in state['cases'])
        assert len({tuple(case['size']) for case in state['cases']}) == 4
        assert state['labels'] == expected_labels
        assert state['checked'] == ['Mini replica · 35%']
        assert state['expanded'] == state['mini']
        assert state['minimized'] is True
        assert state['saved_while_hidden'] == state['mini']
        assert state['tray_restore'] == state['mini']
        assert state['rolled'][1] <= 24
