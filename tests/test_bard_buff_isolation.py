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
from vantage.parsers.spells import (
    Spell, _external_self_buff_effects, _is_short_bard_twist)
from PySide6.QtWidgets import QLineEdit

app = VantageApp([])
spells = app._parsers_dict['spells']
config.data['spells']['use_casting_window'] = False
config.data['spells']['use_custom_triggers'] = False
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['fade_warning_seconds'] = 40
config.data['spells']['level'] = 60
spells._character_context = None
spells._active_character = 'Mindflux'
spells._active_server = 'Green'
now = datetime.datetime.now().replace(microsecond=0)

notifications = []
notices = []
faded_signals = []
app.notify_event = lambda *args, **kwargs: notifications.append((args, kwargs))
app._queue_quickbar_notice = lambda *args, **kwargs: notices.append(args)
spells.spell_faded.connect(
    lambda target, spell: faded_signals.append((target, spell)))

# Automatic expiry/removal must never steal focus from an unrelated control.
outside_editor = QLineEdit()
outside_editor.show()
outside_editor.setFocus()
app.processEvents()

# A nearby Bard's group landing has no owned cast/item anchor. It must not
# become a self buff even though the sentence explicitly addresses "Your".
external_bard_line = 'You feel an aura of mystic protection surround you.'
spells.parse(now, external_bard_line)
self_target = spells._spell_container.get_spell_target_by_name('__you__')
external_names = [
    widget.spell.name for widget in self_target.spell_widgets()
] if self_target else []

# This player's own cast is authoritative and can be shown, but normal Bard
# twisting must never trigger fading notices/sounds or synced persistence.
spells.parse(now + datetime.timedelta(seconds=1),
             'You begin casting Chant of Battle.')
spells.parse(now + datetime.timedelta(seconds=4),
             'You feel your pulse quicken.')
self_target = spells._spell_container.get_spell_target_by_name('__you__')
chant = next(widget for widget in self_target.spell_widgets()
             if widget.spell.name == 'chant of battle')
silent_state = {
    'transient': chant.transient_silent,
    'warning': bool(chant.progress.property('Warning')),
    'critical': bool(chant.progress.property('Critical')),
    'pulse': bool(chant.progress.property('Pulse')),
    'runtime_snapshot': spells._spell_container.snapshot_runtime_state(),
    'camp_snapshot': spells.snapshot_you_spells('Mindflux', 'Green'),
    'mobile_timers': spells.mobile_snapshot()['timers'],
}
events_before_worn = list(spells.recent_spell_events())
outside_editor.setFocus()
app.processEvents()
spells.parse(now + datetime.timedelta(seconds=8),
             'Your battle fury fades.')
app.processEvents()

# External self-effect indexing is limited to grammatical self direction,
# independently of the Bard-specific suppression.
ordinary = Spell(
    name='Synthetic', type=1, duration_formula=11,
    class_levels=(1,) + (255,) * 15)
external_index = _external_self_buff_effects(
    {'Synthetic': ordinary}, {
        'Alice is surrounded by light.': ordinary,
        'You are surrounded by light.': ordinary,
    })

print(json.dumps({
    'external_names': external_names,
    'external_bard_indexed': (
        external_bard_line.casefold() in spells._external_self_effects),
    'is_short_bard': _is_short_bard_twist(chant.spell, 60),
    'silent_state': silent_state,
    'removed_on_worn': chant._removed,
    'events_unchanged': spells.recent_spell_events() == events_before_worn,
    'notifications': notifications,
    'notices': notices,
    'faded_signals': faded_signals,
    'outside_focus_preserved': outside_editor.hasFocus(),
    'external_index_keys': sorted(external_index),
}))
app.quit()
"""


def test_external_bard_ignored_and_owned_twist_is_silent(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result == {
        'external_names': [],
        'external_bard_indexed': True,
        'is_short_bard': True,
        'silent_state': {
            'transient': True,
            'warning': False,
            'critical': False,
            'pulse': False,
            'runtime_snapshot': [],
            'camp_snapshot': [],
            'mobile_timers': [],
        },
        'removed_on_worn': True,
        'events_unchanged': True,
        'notifications': [],
        'notices': [],
        'faded_signals': [],
        'outside_focus_preserved': True,
        'external_index_keys': ['you are surrounded by light.'],
    }
