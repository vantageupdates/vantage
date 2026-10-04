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

app = VantageApp([])
spells = app._parsers_dict['spells']
config.data['spells']['use_casting_window'] = False
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['fade_warning_seconds'] = 40
now = datetime.datetime.now().replace(microsecond=0)

# Sanitized Spiritflux multi-log sequence: this is explicit other-target
# evidence. It may create Vebekn's row, but never a Spiritflux self row.
app._parse((now, 'You begin casting Aura of Black Petals.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=3),
            'Vebekn is covered by an aura of black petals.',
            'Spiritflux', 'P1999Green'))
petals_target = spells._spell_container.get_spell_target_by_name('Vebekn')
self_target = spells._spell_container.get_spell_target_by_name('__you__')
petals_other = [w.spell.name for w in petals_target.spell_widgets()]
petals_self = [w.spell.name for w in self_target.spell_widgets()] \
    if self_target else []

# An unrelated owned item glow is not permission to consume another nearby
# player's Petals landing.
app._parse((now + datetime.timedelta(seconds=5),
            'Your Pegasus Feather Cloak begins to glow.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=6),
            'Natella is covered by an aura of black petals.',
            'Spiritflux', 'P1999Green'))
natella = spells._spell_container.get_spell_target_by_name('Natella')

# Wildflux supplies exact cast ownership. An unrelated Spiritflux cast then
# replaces the visible cast window before the recipient emote arrives. The
# retained owned-cast evidence must still resolve the exact rank.
app._parse((now + datetime.timedelta(seconds=10),
            'You begin casting Regrowth of the Grove.',
            'Wildflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=11),
            'You begin casting Focus of Spirit.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=16),
            'You begin to regenerate.', 'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=16),
            'Bellaca begins to regenerate.', 'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=16),
            'Wildflux begins to regenerate.', 'Spiritflux', 'P1999Green'))
self_target = spells._spell_container.get_spell_target_by_name('__you__')
spiritflux_rows = [
    w for w in self_target.spell_widgets()
    if w.runtime_character == 'Spiritflux']

# A different recipient has only the ambiguous self emote while an unrelated
# local cast is pending. That must not create the old rank-unknown sentinel.
app._parse((now + datetime.timedelta(seconds=20),
            'You begin casting Clarity.', 'Harmflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=24),
            'You begin to regenerate.', 'Harmflux', 'P1999Green'))
unknown_rows = [
    w for w in self_target.spell_widgets()
    if w.runtime_character == 'Harmflux' and
    ('rank unknown' in w.spell.name or 'regeneration' in w.spell.name)]

# One SoW generation owns at most one fading/worn alert. Its confirmed
# re-entry revives and rearms the same row; a stale duplicate worn line inside
# the replacement guard cannot fade or announce the refreshed generation.
notices = []
app.notify_event = lambda route, notice, **kwargs: (
    notices.append((route, notice)) or True)
app._parse((now + datetime.timedelta(seconds=30),
            'You begin casting Spirit of Wolf.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=34),
            'You feel the spirit of wolf enter you.',
            'Spiritflux', 'P1999Green'))
sow = next(w for w in self_target.spell_widgets()
           if w.spell.name == 'spirit of wolf' and
           w.runtime_character == 'Spiritflux')
app._parse((now + datetime.timedelta(seconds=40),
            'You begin casting Spirit of Wolf.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=45),
            'The spirit of wolf leaves you.',
            'Spiritflux', 'P1999Green'))
worn_notice_count = len(notices)
app._parse((now + datetime.timedelta(seconds=45),
            'You feel the spirit of wolf enter you.',
            'Spiritflux', 'P1999Green'))
app._parse((now + datetime.timedelta(seconds=46),
            'The spirit of wolf leaves you.',
            'Spiritflux', 'P1999Green'))
count_after_stale_worn = len(notices)
rearmed_before_warning = not sow._warning_played
sow.end_time = datetime.datetime.now() + datetime.timedelta(seconds=10)
sow._update()
sow._update()

print(json.dumps({
    'petals_other': petals_other,
    'petals_self': petals_self,
    'natella_created': natella is not None,
    'bellaca_created': spells._spell_container.get_spell_target_by_name(
        'Bellaca') is not None,
    'wildflux_created': spells._spell_container.get_spell_target_by_name(
        'Wildflux') is not None,
    'spiritflux_rows': [w.spell.name for w in spiritflux_rows],
    'unknown_count': len(unknown_rows),
    'worn_notice_count': worn_notice_count,
    'count_after_stale_worn': count_after_stale_worn,
    'sow_active_after_reentry': not sow._faded and not sow._removed,
    'rearmed_before_warning': rearmed_before_warning,
    'final_notices': notices,
}))
if spells._spell_trigger:
    spells._spell_trigger.stop()
app.quit()
"""


def test_sanitized_spiritflux_attribution_and_fade_rearm(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=60)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['petals_other'] == ['aura of black petals']
    assert 'aura of black petals' not in result['petals_self']
    assert result['natella_created'] is False
    assert result['bellaca_created'] is False
    assert result['wildflux_created'] is False
    assert result['spiritflux_rows'] == ['regrowth of the grove']
    assert result['unknown_count'] == 0
    assert result['worn_notice_count'] == 1
    assert result['count_after_stale_worn'] == 1
    assert result['sow_active_after_reentry'] is True
    assert result['rearmed_before_warning'] is True
    assert [route for route, _notice in result['final_notices']] == [
        'spell_worn_off', 'spell_fading']
