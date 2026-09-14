import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


CREATE_SCRIPT = r"""
import json

from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.parsers.timers import SpawnTimers


config.data['general']['startup_window_state'] = 'normal'
config.data['timers']['compact'] = False
config.data['timers']['view_zone'] = ''
app = VantageApp([])
primary = app._parsers_dict['timers']
primary._refresh_zone_filter('')
secondary = primary.create_secondary_window()

kael = SpawnTimerState('Arena respawn', 1800, zone='Kael Drakkel')
global_timer = SpawnTimerState(
    'Potion cooldown', 300, timer_mode='cooldown')
primary._register_timer(kael)
primary._register_timer(global_timer)
primary.state_changed()

secondary._refresh_zone_filter('Kael Drakkel')
secondary.compact.setChecked(True)
secondary._toggle_compact()
secondary.setGeometry(91, 107, 520, secondary.minimumHeight())
secondary._save_geometry()
secondary._view_settings()['toggled'] = True
config.save()

print(json.dumps({
    'id': secondary.instance_id,
    'name': secondary.name,
    'parser_count': sum(isinstance(item, SpawnTimers) for item in app._parsers),
    'shared_dict': secondary._states is primary._states,
    'secondary_rows': len(secondary._rows),
    'secondary_ticker': secondary._ticker.isActive(),
    'primary_compact': primary.is_compact,
    'secondary_compact': secondary.is_compact,
    'primary_zone': primary._selected_zone,
    'secondary_zone': secondary._selected_zone,
    'geometry': secondary._view_settings()['geometry'],
    'new_window_name': primary.new_window_button.accessibleName(),
    'new_window_tooltip': primary.new_window_button.toolTip(),
    'remove_name': secondary.remove_window_button.accessibleName(),
}))
app.quit()
"""


RESTORE_SCRIPT = r"""
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import PHASE_RESPAWN
from vantage.parsers.timers import SpawnTimers


config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
primary = app._parsers_dict['timers']
secondary = primary.secondary_windows[0]
visible_on_restore = secondary.isVisible()
restored_geometry = list(secondary._view_settings()['geometry'])
restored_zone = secondary._selected_zone
restored_compact = secondary.is_compact
timer = next(
    timer for timer in primary._states.values()
    if timer.name == 'Potion cooldown')
secondary._rows[timer.timer_id]._restart()
app.processEvents()
shared_action = (
    primary._states[timer.timer_id].phase == PHASE_RESPAWN and
    primary._states[timer.timer_id].running and
    secondary._states[timer.timer_id] is primary._states[timer.timer_id])
instance_id = secondary.instance_id
section_name = secondary.name
before_remove = len(primary._states)
removed = primary.remove_secondary_window(instance_id)
app.processEvents()

print(json.dumps({
    'restored_count': len(primary.secondary_windows) + int(removed),
    'parser_count': sum(isinstance(item, SpawnTimers) for item in app._parsers),
    'ticker_active': secondary._ticker.isActive(),
    'visible_on_restore': visible_on_restore,
    'zone': restored_zone,
    'compact': restored_compact,
    'geometry': restored_geometry,
    'shared_action': shared_action,
    'removed': removed,
    'remaining_views': len(primary.secondary_windows),
    'settings_removed': section_name not in config.data,
    'timers_preserved': len(primary._states) == before_remove,
}))
app.quit()
"""


def _run(script, profile):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(profile)
    completed = subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_multiple_timer_windows_restore_and_share_one_controller(tmp_path):
    profile = tmp_path / 'profile'
    created = _run(CREATE_SCRIPT, profile)

    assert created['parser_count'] == 1
    assert created['shared_dict'] is True
    assert created['secondary_rows'] == 2
    assert created['secondary_ticker'] is False
    assert created['primary_compact'] is False
    assert created['secondary_compact'] is True
    assert created['primary_zone'] == ''
    assert created['secondary_zone'] == 'Kael Drakkel'
    assert created['geometry'][:2] == [91, 107]
    assert created['new_window_name'] == 'Open another timer window'
    assert 'same timer state' in created['new_window_tooltip']
    assert created['remove_name'] == \
        'Close and remove this extra timer window'

    restored = _run(RESTORE_SCRIPT, profile)
    assert restored['restored_count'] == 1
    assert restored['parser_count'] == 1
    assert restored['ticker_active'] is False
    assert restored['visible_on_restore'] is True
    assert restored['zone'] == 'Kael Drakkel'
    assert restored['compact'] is True
    assert restored['geometry'][:2] == [91, 107]
    assert restored['shared_action'] is True
    assert restored['removed'] is True
    assert restored['remaining_views'] == 0
    assert restored['settings_removed'] is True
    assert restored['timers_preserved'] is True
