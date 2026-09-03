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
from vantage.parsers import spells as spells_module
from vantage.parsers.spells import CustomTrigger, compile_trigger_pattern

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
spells = app._parsers_dict['spells']
spells.show()
app.processEvents()
config.data['general']['audio_muted'] = False
config.data['spells']['fade_sound_enabled'] = True
config.data['spells']['sounds_when_hidden'] = False
config.data['spells']['level'] = 60

trigger = CustomTrigger(
    name='Fetter worn', text='Your feet come free.',
    sound_path='builtin:rune-pulse', enabled=True)
spells._custom_timers = [(
    compile_trigger_pattern(trigger.text), [], trigger)]
played = []
spells_module.play_alert = lambda *args, **kwargs: (
    played.append({'source': kwargs.get('source', ''),
                   'channel': kwargs.get('channel', '')}) or True)

now = datetime.datetime.now().replace(microsecond=0)
spell = spells.spell_book['Fetter']
spells._spell_container.add_spell(
    spell, now, 'a blizzard hunter', 'Mindflux', 'Green')
played.clear()
spells.parse(now + datetime.timedelta(seconds=3), 'Your feet come free.')

print(json.dumps({
    'events': spells.recent_spell_events(),
    'played': played,
    'tray_visible': spells._event_tray.isVisible(),
    'pill_count': len(spells._event_pills),
    'quickbar_notice': app._quickbar_notice,
}))
app.quit()
"""


def test_worn_off_uses_visible_pill_and_only_one_audio_owner(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['events'] == [
        'WORN OFF · Fetter · A Blizzard Hunter']
    assert result['played'] == [
        {'source': 'Trigger · Fetter worn', 'channel': 'spells'}]
    assert result['tray_visible'] is True
    assert result['pill_count'] == 1
    assert result['quickbar_notice'] == (
        'Fetter worn off · A Blizzard Hunter')
