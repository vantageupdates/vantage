"""A bounded visible roll history must not change the round's result."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import datetime
import json
from PySide6.QtGui import QFontMetrics
from vantage.helpers.application import VantageApp

app = VantageApp([])
panel = app._parsers_dict['random_parser']
panel.resize(430, 300)
panel.show()
app.processEvents()
app.processEvents()
result_metrics = QFontMetrics(panel._winner_font(panel.table.font()))
column_layout = {
    'result_width': panel.table.columnWidth(2),
    'needed_result_width': max(result_metrics.horizontalAdvance(text)
                               for text in ('Winner', 'Tied winner', 'Participant')) + 16,
    'player_width': panel.table.columnWidth(0),
    'viewport_width': panel.table.viewport().width(),
}
at = datetime.datetime(2026, 1, 1)

def roll(player, value, high=1000):
    panel.parse(at, f'**A Magic Die is rolled by {player}.')
    panel.parse(at, f'**It could have been any number from 0 to {high}, but this time it turned up a {value}.')

def snapshot():
    return {
        'summary': panel.summary.text(),
        'accessible': panel.summary.accessibleDescription(),
        'tooltip': panel.table.toolTip(),
        'rows': panel.table.rowCount(),
        'history': len(panel._rolls),
        'accepted': len(panel._accepted_players),
        'range': panel._locked_high,
        'round': panel._round,
        'results': [panel.table.item(row, 2).text()
                    for row in range(panel.table.rowCount())],
    }

# Batch only repainting: every game pair still passes through the real parser.
render = panel._render
panel._render = lambda announce=False: None
roll('FirstWinner', 1000)
for index in range(499):
    roll(f'Participant{index}', 1)
panel._render = render
roll('LastParticipant', 1)
overflow = snapshot()

# An evicted participant is still ineligible for a second roll, and the round
# continues to reject a different range even after the history fills up.
roll('firstwinner', 999)
roll('WrongRange', 2000, high=2000)
rejected = snapshot()
roll('LaterTie', 1000)
tie = snapshot()

# Both tied leaders can age out of the visible history without losing either.
panel._render = lambda announce=False: None
for index in range(500):
    roll(f'AnotherParticipant{index}', 2)
panel._render = render
roll('ThirdTie', 1000)
evicted_tie = snapshot()

panel.new_round()
new_round_empty = snapshot()
roll('FirstWinner', 5, high=10)
new_round = snapshot()
panel.clear_rolls()
cleared_empty = snapshot()
roll('FirstWinner', 7, high=20)
cleared = snapshot()
panel.reset()
reset_empty = snapshot()
roll('LaterTie', 0, high=0)
reset = snapshot()

print(json.dumps({
    'column_layout': column_layout,
    'overflow': overflow, 'rejected': rejected, 'tie': tie,
    'evicted_tie': evicted_tie, 'new_round_empty': new_round_empty,
    'new_round': new_round, 'cleared_empty': cleared_empty,
    'cleared': cleared, 'reset_empty': reset_empty, 'reset': reset,
}))
panel.close()
app.quit()
'''


@pytest.fixture(scope="module")
def round_results(tmp_path_factory):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path_factory.mktemp('random-profile'))
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=35)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_first_winner_survives_501_valid_rolls(round_results):
    result = round_results['overflow']
    assert 'WINNER: FirstWinner · 1000' in result['summary']
    assert result['history'] == result['rows'] == 500
    assert result['accepted'] == 501
    assert set(result['results']) == {'Participant'}
    assert 'Showing latest 500 of 501 rolls' in result['summary']
    assert result['accessible'] == result['summary']


def test_history_eviction_does_not_reset_duplicate_or_range_rules(round_results):
    assert round_results['rejected'] == round_results['overflow']


def test_result_column_reserves_space_for_status_before_first_roll(round_results):
    layout = round_results['column_layout']
    assert layout['result_width'] >= layout['needed_result_width']
    assert layout['player_width'] >= layout['viewport_width'] / 2


def test_ties_include_all_winners_even_after_history_eviction(round_results):
    result = round_results['tie']
    assert 'TIE at 1000: FirstWinner, LaterTie' in result['summary']
    assert result['results'].count('Tied winner') == 1
    assert result['accepted'] == 502
    result = round_results['evicted_tie']
    assert 'TIE at 1000: FirstWinner, LaterTie, ThirdTie' in result['summary']
    assert result['results'].count('Tied winner') == 1
    assert result['accepted'] == 1003
    assert result['rows'] == result['history'] == 500


@pytest.mark.parametrize(
    'action, round_number, player, value, high',
    [('new_round', 2, 'FirstWinner', 5, 10),
     ('cleared', 2, 'FirstWinner', 7, 20),
     ('reset', 1, 'LaterTie', 0, 0)],
)
def test_round_controls_reset_cumulative_results(
        round_results, action, round_number, player, value, high):
    empty = round_results[action + '_empty']
    assert empty['summary'] == (
        f'ROUND {round_number} · Waiting for valid /random 0 N results')
    assert empty['history'] == empty['rows'] == empty['accepted'] == 0
    assert empty['range'] is None
    result = round_results[action]
    assert result['summary'] == (
        f'ROUND {round_number} · RANGE 0–{high} · WINNER: {player} · {value}')
    assert result['history'] == result['rows'] == result['accepted'] == 1
    assert result['results'] == ['Winner']
