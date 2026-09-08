import json
import os
from PySide6.QtTest import QTest
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import os
from PySide6.QtTest import QTest

import vantage.parsers.quickbar as quickbar_module

receipt_announcements = []
class AccessibleRecorder:
    @staticmethod
    def updateAccessibility(event):
        if event.message().startswith('Update complete.'):
            receipt_announcements.append([
                event.message(), str(event.politeness())])
quickbar_module.QAccessible = AccessibleRecorder

from vantage.helpers import config
from vantage.helpers.application import (
    UPDATE_BUSY_RETRY_MS, UPDATE_HEARTBEAT_MS, UPDATE_INITIAL_DELAY_MS,
    UPDATE_RETRY_MS, VantageApp)

config.data['general']['startup_window_state'] = 'normal'
config.data['general']['update_check'] = True
os.environ['VANTAGE_UPDATED_FROM'] = '1.44.44'
os.environ['VANTAGE_OPEN_UI_AFTER_UPDATE'] = '1'
app = VantageApp([])
app.processEvents()
app.processEvents()
bar = app._parsers_dict['quickbar']
button = bar._buttons['updates']
bar.refresh_state()
app.processEvents()

initial = {
    'active': app._update_heartbeat.isActive(),
    'interval': app._update_heartbeat.interval(),
    'tooltip': button.toolTip(),
    'button_text': button.text(),
    'badge_text': bar._update_badge.text(),
    'update_toast_visible': app._update_toast.isVisible(),
    'rail_text': bar.notification_rail._label.text(),
    'rail_pending': list(bar.notification_rail._pending),
    'vantage_ui_visible': app._parsers_dict['vantage_ui'].isVisible(),
    'vantage_ui_shared': (
        app._parsers_dict['vantage_ui']._shared_update_controller
        is app._update_controller),
    'vantage_ui_timer_active': (
        app._parsers_dict['vantage_ui']._automatic_timer.isActive()),
    'receipt_announcements': list(receipt_announcements),
}
app.clear_update_receipt()
app.processEvents()

app._update_heartbeat.stop()
checks = []
app._update_controller.check = lambda: checks.append('Vantage') or False
ui = app._parsers_dict['vantage_ui']
ui.check_for_updates = lambda **options: checks.append(
    ['VantageUI', options]) or False
app._update_heartbeat_tick()
busy = app._update_heartbeat.interval()

ui_notices = []
app._update_toast.show_updates = lambda **values: ui_notices.append([
    str(values['info'].version) if values.get('info') else '',
    values.get('vantage_ui_version', '')])
ui_ready = {
    'installed': '1.44.51',
    'available': '1.44.52',
    'busy': False,
    'checking': False,
    'update_available': True,
    'check_error': '',
}
app._vantage_ui_update_state_changed(ui_ready)
app._vantage_ui_update_state_changed(ui_ready)
QTest.qWait(180)
app.processEvents()
ui_alert = {
    'notices': ui_notices,
    'badge': bar._update_badge.isVisible(),
    'products': button.property('UpdateProducts'),
    'name': button.accessibleName(),
    'tooltip': button.toolTip(),
    'button_text': button.text(),
    'badge_text': bar._update_badge.text(),
    'ui_badge': bar._vantage_ui_badge.text(),
    'ui_badge_visible': bar._vantage_ui_badge.isVisible(),
}
app._vantage_ui_update_state_changed({
    **ui_ready, 'installed': '', 'update_available': False})
ui_not_installed = {
    'ready': app.vantage_ui_update_available(),
    'badge': bar._update_badge.isVisible(),
}

app._update_check_started()
checking = {
    'state': button.property('UpdateState'),
    'name': button.accessibleName(),
    'tooltip': button.toolTip(),
}

app._update_check_failed('temporary GitHub failure')
retrying = {
    'state': button.property('UpdateState'),
    'name': button.accessibleName(),
    'interval': app._update_heartbeat.interval(),
}

app._update_check_finished(None, 'Up to date')
healthy = {
    'state': button.property('UpdateState'),
    'interval': app._update_heartbeat.interval(),
}

print(json.dumps({
    'initial': initial,
    'checks': checks,
    'busy': busy,
    'ui_alert': ui_alert,
    'ui_not_installed': ui_not_installed,
    'checking': checking,
    'retrying': retrying,
    'healthy': healthy,
    'constants': [
        UPDATE_INITIAL_DELAY_MS, UPDATE_BUSY_RETRY_MS,
        UPDATE_RETRY_MS, UPDATE_HEARTBEAT_MS],
}))
app._update_heartbeat.stop()
app.quit()
"""


def test_update_heartbeat_starts_fast_retries_and_updates_quickbar(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['constants'] == [3000, 15000, 60000, 60000]
    assert result['initial']['active'] is True
    assert result['initial']['interval'] == 3000
    assert 'Vantage 1.44.62 installed' in result['initial']['tooltip']
    assert result['initial']['button_text'] == 'Updated'
    assert result['initial']['badge_text'] == '✓'
    assert result['initial']['receipt_announcements'] == [[
        'Update complete. Vantage 1.44.62 installed · was 1.44.44.',
        'AnnouncementPoliteness.Polite']]
    assert result['initial']['update_toast_visible'] is False
    update_message = 'Vantage updated · 1.44.44 → 1.44.62'
    assert update_message in (
        [result['initial']['rail_text']] + result['initial']['rail_pending'])
    assert result['initial']['vantage_ui_visible'] is True
    assert result['initial']['vantage_ui_shared'] is True
    assert result['initial']['vantage_ui_timer_active'] is False
    assert result['checks'] == ['Vantage']
    assert result['busy'] == 15000
    assert result['ui_alert'] == {
        'notices': [['', '1.44.52']],
        'badge': True,
        'products': 'VantageUI',
        'name': (
            'Update ready for VantageUI 1.44.52; open Updates'),
        'tooltip': (
            'VantageUI 1.44.52 ready · open verified updates'),
        'button_text': 'VantageUI',
        'badge_text': '1',
        'ui_badge': 'UP',
        'ui_badge_visible': True,
    }
    assert result['ui_not_installed'] == {
        'ready': False,
        'badge': False,
    }
    assert result['checking'] == {
        'state': 'checking',
        'name': 'Checking Vantage and VantageUI updates',
        'tooltip': (
            'Checking GitHub for verified Vantage and VantageUI updates…'),
    }
    assert result['retrying'] == {
        'state': 'retrying',
        'name': 'Vantage update check will retry automatically',
        'interval': 60000,
    }
    assert result['healthy'] == {
        'state': 'idle',
        'interval': 60000,
    }
