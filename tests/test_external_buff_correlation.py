import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.spells import _shared_self_buff_family

app = VantageApp([])
spells = app._parsers_dict['spells']
config.data['spells']['use_casting_window'] = False
config.data['spells']['fade_sound_enabled'] = False
config.data['spells']['level'] = 1
now = datetime.datetime.now().replace(microsecond=0)

# With only the recipient log, EQ hides both rank and caster. This is not
# authoritative enough to create or sync an active self timer.
app._parse((
    now, 'You begin to regenerate.', 'Harmflux', 'P1999Green'))
target = spells._spell_container.get_spell_target_by_name('__you__')
fallback_count = len(target.spell_widgets()) if target else 0

# A replaced older rank can report the same worn-off text just after landing.
# The fresh unresolved family must survive that stale line.
app._parse((
    now + datetime.timedelta(seconds=1),
    'You have stopped regenerating.', 'Harmflux', 'P1999Green'))
fallback_count_after_worn = len(target.spell_widgets()) if target else 0

# When both character logs are tailed, preserve the spell and caster level
# from the Druid's named cast while assigning the self landing to the SK.
app._parse((
    now + datetime.timedelta(seconds=10),
    'You begin casting Regrowth of the Grove.',
    'Wildflux', 'P1999Green'))
app._parse((
    now + datetime.timedelta(seconds=16),
    'You begin to regenerate.', 'Harmflux', 'P1999Green'))
target = spells._spell_container.get_spell_target_by_name('__you__')
rows = [
    widget for widget in target.spell_widgets()
    if widget.runtime_character == 'Harmflux' and
    _shared_self_buff_family(widget.spell) == 'regeneration'
]
exact = rows[0]
exact_remaining = int(
    (exact.end_time - (now + datetime.timedelta(seconds=16))).total_seconds())
app._parse((
    now + datetime.timedelta(seconds=17),
    'You have stopped regenerating.', 'Harmflux', 'P1999Green'))
exact_survived_stale_worn = not exact._faded and not exact._removed

print(json.dumps({
    'fallback_count': fallback_count,
    'fallback_count_after_worn': fallback_count_after_worn,
    'exact_count': len(rows),
    'exact_name': exact.spell.name,
    'exact_runtime_level': exact.spell.runtime_level,
    'exact_remaining': exact_remaining,
    'exact_survived_stale_worn': exact_survived_stale_worn,
    'exact_painted_name': exact.progress._spell_name,
    'exact_accessible_name': exact.accessibleName(),
    'exact_character': exact.runtime_character,
    'exact_server': exact.runtime_server,
}))
if spells._spell_trigger:
    spells._spell_trigger.stop()
app.quit()
"""


def test_external_regen_is_honest_and_cross_log_cast_is_exact(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['fallback_count'] == 0
    assert result['fallback_count_after_worn'] == 0
    assert result['exact_count'] == 1
    assert result['exact_name'] == 'regrowth of the grove'
    assert result['exact_runtime_level'] >= 58
    assert result['exact_remaining'] >= 1100
    assert result['exact_survived_stale_worn'] is True
    assert result['exact_painted_name'] == 'Regrowth Of The Grove'
    assert result['exact_accessible_name'] == (
        'Regrowth Of The Grove spell timer')
    assert result['exact_character'] == 'Harmflux'
    assert result['exact_server'] == 'P1999Green'
