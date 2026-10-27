from copy import deepcopy
from types import SimpleNamespace
import time

import pytest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
import vantage.helpers.log_monitor as monitor


@pytest.fixture
def health_panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, 'data', deepcopy(config.data))
    config.verify_settings()
    monkeypatch.setattr(monitor, 'speech_voice_names', lambda: [])
    reader_state = {
        'folder': 'C:/Example/EverQuest/Logs', 'stopped': False,
        'events_delivered': 10, 'last_delivered_at': time.time(),
        'pending_bytes': 0, 'known_files': 2, 'watched_files': 2,
        'active_errors': [], 'repair_count': 0,
    }
    dispatch = {'events_completed': 10, 'events_with_errors': 0,
                'active_errors': []}
    host = SimpleNamespace(
        _log_reader=SimpleNamespace(
            health_snapshot=lambda: reader_state, profiles=lambda: []),
        log_dispatch_health=lambda: dispatch)
    panel = monitor.LogMonitorDialog(host)
    panel._refresh_timer.stop()
    yield panel, host, reader_state, dispatch
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_live_and_quiet_states_do_not_claim_disconnection(health_panel):
    panel, _, reader, _ = health_panel
    assert 'events are reaching' in panel.health_status.text()
    assert 'Events processed: 10' in panel.health_detail.text()
    reader['last_delivered_at'] = time.time() - 300
    panel.refresh()
    assert 'has not written' in panel.health_status.text()
    assert 'stopped' not in panel.health_status.text()


def test_failure_and_recovery_are_visible_and_copy_has_no_event_content(health_panel):
    panel, _, reader, dispatch = health_panel
    dispatch.update(events_with_errors=1, active_errors=[{
        'component': 'parser:spells', 'error_type': 'RuntimeError', 'count': 1,
        'message': 'PRIVATE CONVERSATION', 'token': 'PRIVATE TOKEN'}])
    panel.refresh()
    assert 'other features keep receiving' in panel.health_status.text()
    assert 'parser:spells' in panel.health_detail.text()
    panel.copy_diagnostics.click()
    copied = QApplication.clipboard().text()
    assert 'parser:spells' in copied and 'RuntimeError' in copied
    assert 'PRIVATE' not in copied
    assert reader['folder'] in copied
    dispatch['active_errors'] = []
    panel.refresh()
    assert 'events are reaching' in panel.health_status.text()


def test_missing_file_and_pending_data_have_distinct_status(health_panel):
    panel, _, reader, _ = health_panel
    reader['active_errors'] = [{'file': 'eqlog_Example_Green.txt',
                                'error': 'PermissionError'}]
    panel.refresh()
    assert 'retrying automatically' in panel.health_status.text()
    reader['active_errors'] = []
    reader['pending_bytes'] = 250
    panel.refresh()
    assert 'Reading pending' in panel.health_status.text()
    assert '250 bytes' in panel.health_detail.text()


def test_monitor_does_not_restart_an_intentionally_stopped_reader(health_panel):
    panel, host, reader, _ = health_panel
    reader['stopped'] = True
    panel.refresh()
    assert 'Monitoring stopped' in panel.health_status.text()
    host._log_reader = None
    panel.refresh()
    assert 'Connect Logs' in panel.health_status.text()
