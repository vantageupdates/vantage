"""Timer-only mute persistence and real offscreen window interaction."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers import config


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('saved, expected', (
    (None, False), (False, False), (True, True), ('false', False), (1, False)))
def test_timer_mute_setting_normalizes_without_changing_master(monkeypatch, saved, expected):
    monkeypatch.setattr(config, 'data', {
        'general': {'audio_muted': True},
        'timers': {'audio_muted': saved, 'volume': 37}})
    config.verify_settings()
    assert config.data['timers']['audio_muted'] is expected
    assert config.data['general']['audio_muted'] is True
    assert config.data['timers']['volume'] == 37


SCRIPT = r'''
import json
import os
from pathlib import Path
import sys
import time

from native_audit_fixture import isolate
profile = isolate()

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from vantage.helpers import audio, config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.parsers.timers import TimerEditDialog

restore = len(sys.argv) > 1
if restore:
    config.load(sys.argv[1])
    config.verify_settings()
else:
    config._filename = str(profile / 'timer-mute.json')
config.data['general']['startup_window_state'] = 'normal'
config.data['general']['audio_muted'] = False
config.data['general']['master_volume'] = 100
config.data['timers']['auto_hide_menu'] = False
app = VantageApp([])
primary = app._parsers_dict['timers']
primary._set_collapsed(False)
primary._refresh_zone_filter('')

if restore:
    result = {
        'muted': audio.timer_audio_muted(),
        'checked': [view.timer_audio_button.isChecked() for view in primary._views],
        'labels': [view.timer_audio_button.text() for view in primary._views],
        'gate': audio.playback_block_reason('timers', True),
        'master': audio.audio_muted(),
    }
else:
    timer = SpawnTimerState(
        'Port cooldown', 300, timer_mode='cooldown', delivery='tts',
        tts_text='{timer} ready', tts_voice='Saved voice', tts_pitch=-3,
        sound_path='builtin:portal-ping', volume=37)
    timer.start()
    primary._register_timer(timer)
    primary.state_changed()
    before = timer.to_dict()
    primary.resize(440, 185)
    primary.show()
    secondary = primary.create_secondary_window()
    secondary.show()
    QTest.qWait(50)

    # Activate the visible control using the keyboard, not a private callback.
    secondary._scale_scene.setFocusItem(secondary._scale_proxy)
    secondary.timer_audio_button.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(secondary.timer_audio_button, Qt.Key.Key_Space)
    app.processEvents()
    third = primary.create_secondary_window()
    states = [view.timer_audio_button.isChecked() for view in primary._views]
    after = timer.to_dict()
    interface = QAccessible.queryAccessibleInterface(secondary.timer_audio_button)
    result = {
        'muted_views': states,
        'unchanged_timer': before == after,
        'countdown_continues': timer.remaining(time.time() + 1) < timer.remaining(),
        'ticker_running': primary._ticker.isActive(),
        'master_unchanged': not audio.audio_muted(),
        'focus_policy': secondary.timer_audio_button.focusPolicy().name,
        'accessible_name': interface.text(QAccessible.Text.Name),
        'accessible_checked': bool(interface.state().checked),
        'shortcut': secondary._timer_audio_shortcut.key().toString(),
    }

    def snapshot(name, compact, width):
        primary.compact.setChecked(compact)
        primary._toggle_compact()
        primary.resize(width, 185)
        primary._sync_timer_canvas()
        QTest.qWait(40)
        button = primary.timer_audio_button
        logical = button.mapTo(primary._surface, button.rect().center())
        physical = primary._scale_view.mapFromScene(
            primary._scale_proxy.mapToScene(QPointF(logical)))
        state = {
            'width': primary.width(),
            'visible': button.isVisibleTo(primary._surface),
            'inside': primary._scale_view.viewport().rect().contains(physical),
            'text_fits': button.width() >= button.sizeHint().width(),
            'text': button.text(),
        }
        directory = os.environ.get('VANTAGE_TIMER_MUTE_CAPTURE_DIR')
        if directory:
            destination = Path(directory)
            destination.mkdir(parents=True, exist_ok=True)
            primary.grab().save(str(destination / (name + '.png')))
        return state

    result['normal'] = snapshot('timers-muted-normal', False, 440)
    result['compact'] = snapshot('timers-muted-compact', True, 300)

    # A muted completion still changes state and submits its visual event.
    visuals = []
    app.show_overlay_notification = lambda *a, **k: visuals.append((a, k))
    timer.deadline = time.time() - 1
    primary._tick()
    result['completed'] = timer.phase == 'available'
    result['visual_retained'] = any('Port cooldown' in str(item) for item in visuals)

    # Exercise actual global-route inheritance and editor previews, including
    # their explicit allow_hidden path. Native audio is disabled by isolate().
    route_results = []
    preview_results = []
    dialog = TimerEditDialog(timer, primary)
    for delivery in ('sound', 'voice'):
        config.data['sounds']['routes']['smart_timer']['delivery'] = delivery
        route = app.notify_event('smart_timer', 'Inherited timer', channel='timers')
        route_results.append([route.state, route.reason])
        dialog.delivery.setCurrentIndex(dialog.delivery.findData('legacy'))
        dialog.sound.setCurrentIndex(0)
        dialog._test_notification()
        preview_results.append(dialog.sound_test_status.text())
    dialog.delivery.setCurrentIndex(dialog.delivery.findData('tts'))
    dialog._test_notification()
    preview_results.append(dialog.sound_test_status.text())
    dialog.close()
    result['inherited_routes'] = route_results
    result['previews'] = preview_results

    # A reload and a second-window toggle both update the same shared switch.
    config.data['timers']['audio_muted'] = False
    app._signals['settings'].config_updated.emit()
    result['reload_synchronized'] = all(
        not view.timer_audio_button.isChecked() for view in primary._views)
    result['enabled'] = snapshot('timers-audio-enabled', False, 440)
    original_style = primary.timer_audio_button.styleSheet()
    # The application theme defines pixel fonts; override that same property
    # so the layout hint and painted text both use the enlarged test font.
    large_pixels = round(primary.timer_audio_button.fontMetrics().height() * 1.5)
    primary.timer_audio_button.setStyleSheet(f'font-size: {large_pixels}px;')
    result['large_text'] = snapshot('timers-audio-large-text', False, 440)
    primary.timer_audio_button.setStyleSheet(original_style)
    third.timer_audio_button.click()
    result['remuted_views'] = [view.timer_audio_button.isChecked() for view in primary._views]
    config.save()
    result['config_file'] = config._filename

print(json.dumps(result))
app.quit()
'''


def _run(*args):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src')))
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT, *args], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_timer_mute_visible_keyboard_synchronized_persistent_and_visual():
    result = _run()
    assert result['muted_views'] == [True, True, True]
    assert result['remuted_views'] == [True, True, True]
    for key in ('unchanged_timer', 'countdown_continues', 'ticker_running',
                'master_unchanged', 'accessible_checked', 'completed',
                'visual_retained', 'reload_synchronized'):
        assert result[key], key
    assert result['focus_policy'] == 'StrongFocus'
    assert result['accessible_name'] == 'Mute all timer audio'
    assert result['shortcut'] == 'Ctrl+Shift+M'
    for name, width in (('normal', 440), ('compact', 300)):
        state = result[name]
        assert state['width'] == width
        assert state['visible'] and state['inside'] and state['text_fits']
        assert state['text'] == 'Timers muted'
    assert result['inherited_routes'] == [['blocked', 'timer audio muted']] * 2
    assert result['previews'] == ['Test status · Timers muted'] * 3
    for name in ('enabled', 'large_text'):
        assert result[name]['text'] == 'Mute timers'
        assert result[name]['visible'] and result[name]['inside']
        assert result[name]['text_fits']

    restarted = _run(result['config_file'])
    assert restarted['muted'] is True
    assert restarted['checked'] == [True, True, True]
    assert restarted['labels'] == ['Timers muted'] * 3
    assert restarted['gate'] == 'timer audio muted'
    assert restarted['master'] is False
