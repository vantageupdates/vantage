import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config

app = VantageApp([])
combat = app._parsers_dict['combat']
settings = config.data['combat']
settings['live_overlay_enabled'] = True
settings['tanking_overlay_enabled'] = True
settings['secondary_overlay_enabled'] = True
settings['live_overlay_id'] = 'alerts'
settings['tanking_overlay_id'] = 'alerts'
settings['secondary_overlay_id'] = 'alerts'

stamp = datetime.datetime.now()
combat.parse(stamp, 'You begin casting Ignite.')
combat.parse(
    stamp + datetime.timedelta(seconds=1),
    'a goblin was hit by non-melee for 40 points of damage.')
combat.parse(
    stamp + datetime.timedelta(seconds=2),
    'a goblin has taken 8 damage from your Flame Lick.')
combat.parse(
    stamp + datetime.timedelta(seconds=3),
    'a goblin hits You for 12 points of damage.')
combat._refresh_live_combat_overlay()
combat.refresh()
app.processEvents()

entries = app._notification_overlay.overlays['alerts']._entries
damage = next(entry for entry in entries if entry.get('key') == 'combat-live')
tanking = next(
    entry for entry in entries if entry.get('key') == 'combat-tanking-live')
secondary = next(
    entry for entry in entries if entry.get('key') == 'combat-secondary-live')
combat._rebuild_live_overlay_menu()
actions = [action.text() for action in combat.live_overlay_menu.actions()]
result = {
    'damage_message': 'DPS' in damage['message'],
    'tanking_message': 'DTPS' in tanking['message'],
    'independent_keys': damage['key'] != tanking['key'],
    'secondary_message': 'DPS' in secondary['message'],
    'secondary_key': secondary['key'],
    'damage_rows': combat.tables['Direct Damage'].rowCount(),
    'dot_rows': combat.tables['Damage over Time'].rowCount(),
    'menu_damage': 'Live damage / DPS' in actions,
    'menu_tanking': 'Live tanking' in actions,
    'menu_secondary': 'Secondary DPS' in actions,
}
print(json.dumps(result))
app.quit()
"""


def test_damage_and_tanking_overlays_are_independent(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'damage_message': True,
        'tanking_message': True,
        'independent_keys': True,
        'secondary_message': True,
        'secondary_key': 'combat-secondary-live',
        'damage_rows': 1,
        'dot_rows': 1,
        'menu_damage': True,
        'menu_tanking': True,
        'menu_secondary': True,
    }
