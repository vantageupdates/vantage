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

app = VantageApp([])
spells = app._parsers_dict['spells']
now = datetime.datetime.now().replace(microsecond=0)
spells.parse(
    now,
    'You can use the ability Puretone Discipline again in '
    '48 minute(s) 45 seconds.')
spells.parse(now, 'You mend your wounds and heal some damage.')
target = spells._spell_container.get_spell_target_by_name('__utility__')
before = {
    widget.spell.name: {
        'seconds': widget._seconds,
        'maximum': widget.progress.maximum(),
        'tooltip': bool(widget.toolTip() and widget.progress.toolTip()),
    }
    for widget in target.spell_widgets()}

# A new authoritative cooldown line restarts the same row without duplicating it.
spells.parse(
    now + datetime.timedelta(seconds=1),
    'You can use the ability Puretone Discipline again in 1 minute 5 seconds.')
after = target.spell_widgets()
print(json.dumps({
    'title': target.target_label.text(),
    'before': before,
    'after_count': len(after),
    'puretone_seconds': next(
        widget._seconds for widget in after
        if widget.spell.name == 'Puretone Discipline'),
}))
app.quit()
"""


def test_log_authoritative_discipline_and_mend_cooldowns(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'title': 'Cooldowns',
        'before': {
            'Puretone Discipline': {
                'seconds': 2925, 'maximum': 2925, 'tooltip': True},
            'Mend': {
                'seconds': 360, 'maximum': 360, 'tooltip': True},
        },
        'after_count': 2,
        'puretone_seconds': 65,
    }
