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
heals = app._parsers_dict['heals']
heals._set_collapsed(False)
heals.parse(
    datetime.datetime.now(),
    "Althea tells the guild, 'AAA - CH - Dain'")
app.processEvents()
live_text = heals.header_countdown.text()
heals._set_collapsed(True)
app.processEvents()
rolled_visible = heals.header_countdown.isVisibleTo(heals._surface)

headers = {}
for name, panel in app._parsers_dict.items():
    if not hasattr(panel, '_settings_button'):
        continue
    menu, actions = panel._build_window_context_menu()
    headers[name] = {
        'settings_tooltip': bool(panel._settings_button.toolTip()),
        'settings_icon': not panel._settings_button.icon().isNull(),
        'settings_section': panel._settings_section(),
        'context_settings': bool(actions['window_settings'].text()),
    }
    menu.deleteLater()

print(json.dumps({
    'live_text': live_text,
    'rolled_visible': rolled_visible,
    'header_countdown_tooltip': bool(heals.header_countdown.toolTip()),
    'headers': headers,
}))
app.quit()
"""


def test_each_window_has_local_settings_and_heal_timer_stays_in_header(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['live_text'].startswith('AAA ')
    assert result['live_text'].endswith('s')
    assert result['rolled_visible'] is True
    assert result['header_countdown_tooltip'] is True
    assert set(result['headers']) >= {
        'maps', 'spells', 'timers', 'combat', 'heals', 'market', 'tick'}
    assert all(item['settings_tooltip'] for item in result['headers'].values())
    assert all(item['settings_icon'] for item in result['headers'].values())
    assert all(item['context_settings'] for item in result['headers'].values())
    assert result['headers']['spells']['settings_section'] == 'Buffs & Triggers'
    assert result['headers']['heals']['settings_section'] == 'Heal Chain'
