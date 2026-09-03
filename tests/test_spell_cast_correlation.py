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

# Backlogged casts are correlated by log timestamps, not wall-clock age. This
# is the path used when Vantage catches up after startup or a busy UI frame.
book, _, _ = create_spell_book()
config.data['spells']['use_casting_window'] = True
config.data['spells']['casting_window_buffer'] = 250
backlogged = SpellTrigger(
    spell=book['Fetter'], timestamp=now - datetime.timedelta(seconds=10))
backlogged.parse(
    now - datetime.timedelta(seconds=8),
    "Crystal Fang's feet adhere to the ground.")

# A late signal from an already-replaced cast cannot finish the newer cast.
old_trigger = SpellTrigger(
    spell=book['Clarity II'], timestamp=now - datetime.timedelta(seconds=2))
current_trigger = SpellTrigger(
    spell=book['Illusion: Werewolf'], timestamp=now)
old_trigger.spell_triggered.connect(spells._spell_triggered)
spells._spell_trigger = current_trigger
old_trigger._times_up()
stale_signal_kept_current = spells._spell_trigger is current_trigger

# P99 reuses generic landing text for many unrelated effects. Without a cast
# or item-glow anchor it must not invent an item-only Airplane illusion.
spells._remove_spell_trigger(current_trigger)
before_unanchored = len(clarity_target.spell_widgets())
spells.parse(now + datetime.timedelta(seconds=45), 'You feel different.')
after_unanchored = len(clarity_target.spell_widgets())

# See Invisible is represented as a multi-target spell in the P99 spell file.
# Its one self landing must survive until the next cast closes the window.
clarity_before_werewolf = clarity.end_time
spells.parse(now + datetime.timedelta(seconds=50),
             'You begin casting See Invisible.')
spells.parse(now + datetime.timedelta(seconds=52), 'Your eyes tingle.')
see_invisible_immediate = any(
    widget.spell.name == 'see invisible'
    for widget in clarity_target.spell_widgets())
see_trigger_still_collecting = (
    spells._spell_trigger is not None and
    spells._spell_trigger.spell.name == 'see invisible')
spells.parse(now + datetime.timedelta(seconds=60),
             'You begin casting Illusion: Werewolf.')
spells.parse(now + datetime.timedelta(seconds=63), 'You feel different.')
spells.parse(now + datetime.timedelta(seconds=64),
             'You begin casting Clarity II.')
spells.parse(
    now + datetime.timedelta(seconds=68),
    'A soft breeze slips through your mind.')
timestamp_rows = {
    widget.spell.name: widget for widget in clarity_target.spell_widgets()}

# A delayed resist names the old spell. It remains visible but cannot cancel
# the different cast currently waiting for its landing line.
spells.parse(now + datetime.timedelta(seconds=70),
             'You begin casting Illusion: Werewolf.')
spells.parse(
    now + datetime.timedelta(seconds=71),
    'Your target resisted the Fetter spell.')
mismatched_resist_kept_cast = (
    spells._spell_trigger is not None and
    spells._spell_trigger.spell.name == 'illusion: werewolf')
mismatched_resist_event = spells.recent_spell_events()[0]
spells.parse(now + datetime.timedelta(seconds=73), 'You feel different.')

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
    'backlogged_target': backlogged.targets[0][1],
    'stale_signal_kept_current': stale_signal_kept_current,
    'unanchored_ignored': before_unanchored == after_unanchored,
    'see_invisible_immediate': see_invisible_immediate,
    'see_trigger_still_collecting': see_trigger_still_collecting,
    'timestamp_correlated_names': sorted(timestamp_rows),
    'werewolf_did_not_refresh_clarity': (
        clarity.end_time == clarity_before_werewolf),
    'mismatched_resist_kept_cast': mismatched_resist_kept_cast,
    'mismatched_resist_event': mismatched_resist_event,
    'quickbar_notice': app._quickbar_notice,
}))
backlogged.stop()
old_trigger.stop()
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
        'backlogged_target': 'Crystal Fang',
        'stale_signal_kept_current': True,
        'unanchored_ignored': True,
        'see_invisible_immediate': True,
        'see_trigger_still_collecting': True,
        'timestamp_correlated_names': [
            'clarity', 'clarity ii', 'illusion: werewolf', 'see invisible'],
        'werewolf_did_not_refresh_clarity': True,
        'mismatched_resist_kept_cast': True,
        'mismatched_resist_event': 'RESIST · Fetter',
        'quickbar_notice': 'Spells · Fetter resisted',
    }
