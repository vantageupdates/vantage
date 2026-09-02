import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
import os
from pathlib import Path
from vantage.helpers.application import VantageApp
from vantage.helpers import config
import vantage.parsers.combat as combat_module

output = Path(os.environ['VANTAGE_TEST_OUTPUT'])
output.mkdir(parents=True, exist_ok=True)
app = VantageApp([])
combat = app._parsers_dict['combat']

combat.log_query.setText('Claws of Veeshan')
combat.log_regex.setChecked(False)
combat.log_reverse.setChecked(True)
combat.log_range.setCurrentIndex(combat.log_range.findData(24 * 7))
combat.log_limit.setCurrentIndex(combat.log_limit.findData(5000))
combat_module.QInputDialog.getText = staticmethod(
    lambda *args, **kwargs: ('Faction gains', True))
combat._save_log_search()
saved = dict(config.data['combat']['saved_searches'][0])
combat.log_query.clear()
combat.log_saved.setCurrentIndex(0)
combat.log_saved.setCurrentIndex(1)

stamp = datetime.datetime.now()
combat.parse(stamp, 'You slash a goblin for 20 points of damage.')
combat.parse(
    stamp + datetime.timedelta(milliseconds=250),
    'a goblin slashes You for 7 points of damage.')
combat.parse(
    stamp + datetime.timedelta(milliseconds=500),
    'a goblin tries to slash You, but You dodge!')
combat.refresh()
csv_path = output / 'overview.csv'
json_path = output / 'session.json'
combat_module.QFileDialog.getSaveFileName = staticmethod(
    lambda *args, **kwargs: (str(csv_path), 'CSV'))
combat._export_current_view_csv()
combat_module.QFileDialog.getSaveFileName = staticmethod(
    lambda *args, **kwargs: (str(json_path), 'JSON'))
combat._export_session_json()

payload = json.loads(json_path.read_text(encoding='utf-8'))

combat.parse(stamp + datetime.timedelta(seconds=1), 'You have slain a goblin!')
combat.parse(stamp + datetime.timedelta(seconds=2), 'You slash a bat for 5 points of damage.')
combat.parse(stamp + datetime.timedelta(seconds=3), 'You have slain a bat!')
combat._history_signature = None
combat._refresh_fights()
for row in range(combat.tables['Fights'].rowCount()):
    for column in range(combat.tables['Fights'].columnCount()):
        combat.tables['Fights'].item(row, column).setSelected(True)
combat_module.QInputDialog.getText = staticmethod(
    lambda *args, **kwargs: ('Merged fights', True))
combat._combine_selected_fights()
combined_count = len(combat._tracker.completed)
combined_target = combat._tracker.last().target
undo_enabled = combat.fight_undo.isEnabled()
combat._undo_fight_change()
restored_count = len(combat._tracker.completed)

print(json.dumps({
    'saved_name': saved['name'],
    'saved_hours': saved['hours'],
    'saved_limit': saved['limit'],
    'loaded_query': combat.log_query.text(),
    'csv_has_damage': '20' in csv_path.read_text(encoding='utf-8-sig'),
    'json_target': payload['encounters'][0]['target'],
    'json_damage': payload['encounters'][0]['total_damage'],
    'json_tank_type': payload['encounters'][0]['tanks'][0]['by_type']['Slashing']['name'],
    'json_tank_defended': payload['encounters'][0]['tanks'][0]['by_type']['Slashing']['dodges'],
    'percent_delegate': (
        combat.tables['Overview'].itemDelegateForColumn(2) is not None),
    'export_tooltip': bool(combat.export.toolTip()),
    'combined_count': combined_count,
    'combined_target': combined_target,
    'undo_enabled': undo_enabled,
    'restored_count': restored_count,
}))
app.quit()
"""


def test_saved_search_export_and_compact_percent_visual(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['VANTAGE_TEST_OUTPUT'] = str(tmp_path / 'exports')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'saved_name': 'Faction gains',
        'saved_hours': 24 * 7,
        'saved_limit': 5000,
        'loaded_query': 'Claws of Veeshan',
        'csv_has_damage': True,
        'json_target': 'a goblin',
        'json_damage': 20,
        'json_tank_type': 'Slashing',
        'json_tank_defended': 1,
        'percent_delegate': True,
        'export_tooltip': True,
        'combined_count': 1,
        'combined_target': 'Merged fights',
        'undo_enabled': True,
        'restored_count': 2,
    }
