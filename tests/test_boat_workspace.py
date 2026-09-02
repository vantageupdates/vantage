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
from vantage.helpers.boats import schedules_from_activities

app = VantageApp([])
spells = app._parsers_dict['spells']
spells._boat_toggle.setChecked(True)
spells._boat_group.set_enabled(True)
now = datetime.datetime.now(datetime.timezone.utc)
payload = [
    {'startPoint': 'oasis', 'boat': 0, 'lastSeen': now.isoformat()},
    {'startPoint': 'overthere', 'boat': 1, 'lastSeen': now.isoformat()},
    {'startPoint': 'butcher', 'boat': 2, 'lastSeen': now.isoformat()},
    {'startPoint': 'nro', 'boat': 3,
     'lastSeen': (now - datetime.timedelta(days=2)).isoformat()},
]
spells._boat_group.update_schedules(
    schedules_from_activities(
        payload, now, source='PigParse API · Green'), 'Green')
rows = spells._boat_group.rows()
before_local = [row.toolTip() for row in rows]
status_before = spells._boat_group.status.text()
spells._active_character = 'Mindflux'
spells._active_server = 'Green'
spells.parse(
    datetime.datetime.now(),
    "Rack Stonebelly shouts, 'Da Barrel Barge will be here soon soon!'")
after_local = [row.toolTip() for row in spells._boat_group.rows()]

print(json.dumps({
    'rows': len(rows),
    'status': status_before,
    'stale_labels': sum('STALE' in row.source_label.text() for row in rows),
    'toggle_tooltip': bool(spells._boat_toggle.toolTip().strip()),
    'menu_tooltips': all(
        action.toolTip().strip()
        for action in spells._boat_toggle.menu().actions()),
    'group_tooltips': bool(
        spells._boat_group.header.toolTip().strip() and
        spells._boat_group.status.toolTip().strip() and
        all(row.toolTip().strip() and row.progress.toolTip().strip()
            for row in rows)),
    'pig_source_before': any(
        'PigParse API · Green' in value for value in before_local),
    'local_source_after': any(
        'EQ log · Mindflux' in value for value in after_local),
    'status_after_local': spells._boat_group.status.text(),
    'empty_hidden': spells._spell_container._empty_state.isHidden(),
}))
spells.close()
app.quit()
"""


def test_boat_rows_preserve_sources_freshness_and_tooltips(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'rows': 7,
        'status': 'BOATS · 7 arrivals · Green · 2 stale source',
        'stale_labels': 2,
        'toggle_tooltip': True,
        'menu_tooltips': True,
        'group_tooltips': True,
        'pig_source_before': True,
        'local_source_after': True,
        'status_after_local': 'BOATS · 7 arrivals · Green · 2 stale source',
        'empty_hidden': True,
    }
