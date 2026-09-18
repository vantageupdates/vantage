import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import datetime
import json
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
panel = app._parsers_dict['random_parser']
button = app._parsers_dict['quickbar']._buttons['random_parser']

at = datetime.datetime(2026, 9, 18, 12, 0, 0)
def line(offset, text):
    panel.parse(at + datetime.timedelta(seconds=offset), text)

# Exact game pair from local Project 1999 logs.
line(0, '**A Magic Die is rolled by Arganon.')
line(1, '**It could have been any number from 0 to 111, but this time it turned up a 109.')
line(2, '**A Magic Die is rolled by Mindflux.')
line(3, '**It could have been any number from 0 to 111, but this time it turned up 109.')
tie = {
    'summary': panel.summary.text(),
    'rows': [[panel.table.item(row, column).text() for column in range(3)]
             for row in range(panel.table.rowCount())],
    'accessible': panel.summary.accessibleDescription(),
    'tooltip': panel.table.toolTip(),
}

# Duplicate case variants, another 0-N range, non-zero lower bounds,
# malformed/out-of-bounds lines, and typed chat are ignored.
before = panel.table.rowCount()
line(4, '**A Magic Die is rolled by arganon.')
line(5, '**It could have been any number from 0 to 111, but this time it turned up a 110.')
line(6, '**A Magic Die is rolled by DifferentRange.')
line(7, '**It could have been any number from 0 to 100, but this time it turned up a 99.')
line(8, '**A Magic Die is rolled by Invalidrange.')
line(9, '**It could have been any number from 59 to 60, but this time it turned up a 60.')
line(10, 'Player says, "**A Magic Die is rolled by Fake."')
line(11, '**It could have been any number from 0 to 10, but this time it turned up a 99.')
ignored = panel.table.rowCount() == before

panel.new_round_button.click()
new_round = [panel._round, panel.table.rowCount(), panel.summary.text()]
line(12, '**A Magic Die is rolled by Winner.')
line(13, '**It could have been any number from 0 to 100, but this time it turned up a 88.')
winner = [panel.summary.text(), panel.table.item(0, 2).text()]
panel.clear_button.click()
line(14, '**A Magic Die is rolled by FreshAfterClear.')
line(15, '**It could have been any number from 0 to 250, but this time it turned up a 200.')
cleared = [panel._round, panel.table.rowCount(), panel._locked_high]
panel.reset_button.click()
reset = [panel._round, panel.table.rowCount(), panel._locked_high]

was_visible = panel.isVisible()
button.click()
app.processEvents()
toggled = [button.accessibleName(), button.toolTip(), was_visible, panel.isVisible()]

print(json.dumps({
    'tie': tie,
    'ignored': ignored,
    'new_round': new_round,
    'winner': winner,
    'cleared': cleared,
    'reset': reset,
    'toggled': toggled,
    'button_focus': button.focusPolicy().name,
    'control_names': [panel.new_round_button.accessibleName(),
                      panel.clear_button.accessibleName(),
                      panel.reset_button.accessibleName()],
}))
app.quit()
'''


def test_random_parser_quickbar_live_rolls_ties_controls_and_accessibility(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['tie']['summary'] == (
        'ROUND 1 · RANGE 0–111 · TIE at 109: Arganon, Mindflux')
    assert result['tie']['rows'] == [
        ['Arganon', '109', 'Tied winner'],
        ['Mindflux', '109', 'Tied winner'],
    ]
    assert result['tie']['accessible'] == result['tie']['summary']
    assert 'Active round range: 0–111' in result['tie']['tooltip']
    assert result['ignored'] is True
    assert result['new_round'] == [
        2, 0, 'ROUND 2 · Waiting for valid /random 0 N results']
    assert result['winner'] == [
        'ROUND 2 · RANGE 0–100 · WINNER: Winner · 88', 'Winner']
    assert result['cleared'] == [2, 1, 250]
    assert result['reset'] == [1, 0, None]
    assert result['toggled'] == [
        'Random Parser', 'Random Parser is open · click to toggle', False, True]
    assert result['button_focus'] != 'NoFocus'
    assert result['control_names'] == [
        'Start a new random round', 'Clear current random rolls',
        'Reset the random parser']


def test_random_parser_config_defaults_are_persistable(tmp_path, monkeypatch):
    previous = config.data
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'config.json'))
    try:
        config.data = {'random_parser': {
            'geometry': [7, 8, 444, 333], 'toggled': True,
            'opacity': 71, 'collapsed': True}}
        config.verify_settings()
        values = config.data['random_parser']
        assert values['geometry'] == [7, 8, 444, 333]
        assert values['toggled'] is True
        assert values['opacity'] == 71
        assert values['clickthrough'] is False
        assert config.UI_PRESENTATION_DEFAULTS[
            ('random_parser', 'collapsed')] is False
    finally:
        config.data = previous
