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
from vantage.parsers.spells import SpellTrigger, create_spell_book

app = VantageApp([])
spells = app._parsers_dict['spells']
config.data['spells']['use_casting_window'] = False
config.data['spells']['fade_sound_enabled'] = False
spells._current_zone = "Velketor's Labyrinth"
now = datetime.datetime.now().replace(microsecond=0)

# Replacing Clarity can emit the old copy's fade line just after the new
# landing. The new generation must keep its one row and refreshed deadline.
spells.parse(now, 'You begin casting Clarity.')
spells.parse(
    now + datetime.timedelta(seconds=4),
    'A cool breeze slips through your mind.')
clarity_target = spells._spell_container.get_spell_target_by_name('__you__')
clarity = clarity_target.spell_widgets()[0]
clarity_first_end = clarity.end_time
spells.parse(now + datetime.timedelta(seconds=10),
             'You begin casting Clarity.')
spells.parse(
    now + datetime.timedelta(seconds=14),
    'A cool breeze slips through your mind.')
spells.parse(
    now + datetime.timedelta(seconds=15), 'The cool breeze fades.')
clarity_rows = clarity_target.spell_widgets()

# Exact live-log wording: a named recast must restart the existing row.
spells.parse(now, 'You begin casting Fetter.')
spells.parse(
    now + datetime.timedelta(seconds=2),
    "Crystal Fang's feet adhere to the ground.")
named = spells._spell_container.get_spell_target_by_name('Crystal Fang')
first = named.spell_widget('fetter')
first_end = first.end_time
spells.parse(now + datetime.timedelta(seconds=12), 'You begin casting Fetter.')
spells.parse(
    now + datetime.timedelta(seconds=14),
    "Crystal Fang's feet adhere to the ground.")
named_rows = spells._spell_container.get_spell_targets_by_name('Crystal Fang')

# Interrupted casts must clear the real current trigger, not an unused queue.
spells.parse(now + datetime.timedelta(seconds=20), 'You begin casting Fetter.')
spells.parse(
    now + datetime.timedelta(seconds=21), 'Your spell is interrupted.')
interrupted_cleared = spells._spell_trigger is None

spells.parse(now + datetime.timedelta(seconds=24), 'You begin casting Allure.')
spells.parse(now + datetime.timedelta(seconds=25), 'Your spell fizzles!')
fizzle_cleared = (
    spells._spell_trigger is None and spells._pending_charm is None)
fizzle_event = spells.recent_spell_events()[0]

spells.parse(now + datetime.timedelta(seconds=26), 'You begin casting Fetter.')
spells.parse(
    now + datetime.timedelta(seconds=27),
    'Your target resisted the Fetter spell.')
resist_event = spells.recent_spell_events()[0]

# P99 emits no normal target landing text for charm. After the bounded cast
# window, the player-owned pet command identifies the charmed mob exactly.
spells.parse(now + datetime.timedelta(seconds=30), 'You begin casting Allure.')
spells._spell_triggered()
pending_before_activity = spells._pending_charm is not None
spells.parse(
    now + datetime.timedelta(seconds=38),
    "a blizzard hunter tells you, 'Attacking Crystal Fang Master.'")
charmed = spells._spell_container.get_spell_target_by_name(
    'a blizzard hunter')

# A backlogged short cast must be active immediately instead of asking Qt to
# start a negative activation timer and then silently missing its landing.
book, _, _ = create_spell_book()
config.data['spells']['use_casting_window'] = True
backlogged = SpellTrigger(
    spell=book['Fetter'], timestamp=now - datetime.timedelta(seconds=10))

print(json.dumps({
    'clarity_count': len(clarity_rows),
    'clarity_refreshed': (
        clarity_rows[0] is clarity and clarity.end_time > clarity_first_end),
    'clarity_active_after_stale_fade': (
        not clarity._faded and not clarity._removed and
        clarity.progress._time_text != 'FADED'),
    'named_count': len(named_rows),
    'named_restarted': named_rows[0].spell_widget('fetter').end_time > first_end,
    'named_label': named_rows[0].target_label.text(),
    'interrupted_cleared': interrupted_cleared,
    'fizzle_cleared': fizzle_cleared,
    'fizzle_event': fizzle_event,
    'resist_event': resist_event,
    'pending_before_activity': pending_before_activity,
    'pending_after_activity': spells._pending_charm is None,
    'charm_spell': charmed.spell_widgets()[0].spell.name if charmed else '',
    'backlogged_active': backlogged.activated,
}))
backlogged.stop()
app.quit()
"""


def test_live_casts_recast_named_track_charm_and_clear_interruptions(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        'clarity_count': 1,
        'clarity_refreshed': True,
        'clarity_active_after_stale_fade': True,
        'named_count': 1,
        'named_restarted': True,
        'named_label': 'Crystal Fang',
        'interrupted_cleared': True,
        'fizzle_cleared': True,
        'fizzle_event': 'FIZZLE · Allure',
        'resist_event': 'RESIST · Fetter',
        'pending_before_activity': True,
        'pending_after_activity': True,
        'charm_spell': 'allure',
        'backlogged_active': True,
    }
