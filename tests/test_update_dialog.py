import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
import semver

from vantage.helpers.updater import UpdateDialog


class Controller(QObject):
    check_finished = Signal(object, str)
    failed = Signal(str)
    download_progress = Signal(int, int)
    download_ready = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.current_version = semver.VersionInfo.parse('1.0.0')
        self.latest_info = None
        self.busy = False
        self.downloaded = None
        self.installed = None

    def check(self):
        return True

    def download(self, info):
        self.downloaded = info
        return True

    def launch_installer(self, info, path, **options):
        self.installed = [str(info.version), path, options]

class VantageUI(QObject):
    update_state_changed = Signal(object)
    _busy = False
    def __init__(self):
        super().__init__()
        self.checks = 0
    def update_snapshot(self):
        return {'installed': '1.44.51', 'available': '1.44.51', 'busy': False}
    def check_for_updates(self):
        self.checks += 1
        return True


app = QApplication([])
controller = Controller()
ui = VantageUI()
opened = []
dialog = UpdateDialog(
    controller, vantage_ui=ui,
    open_vantage_ui=lambda: opened.append(True))
info = SimpleNamespace(
    version=semver.VersionInfo.parse('1.0.1'),
    size=1000,
    notes='A verified update.',
)
dialog._checked(info, 'Vantage 1.0.1 is ready to download.')
before = {
    'text': dialog.download_button.text(),
    'enabled': dialog.download_button.isEnabled(),
    'accessible': dialog.download_button.accessibleName(),
    'tooltip': dialog.download_button.toolTip(),
    'opt_in': dialog.open_ui_after_restart.isChecked(),
    'opt_accessible': dialog.open_ui_after_restart.accessibleDescription(),
    'ui_versions': dialog.ui_version.text(),
    'tab_order': (
        dialog.open_ui_after_restart.nextInFocusChain() is dialog.check_button
        and dialog.check_button.nextInFocusChain() is dialog.open_ui_button
        and dialog.open_ui_button.nextInFocusChain() is dialog.download_button),
}
dialog.open_ui_button.click()
dialog.open_and_check()
ui.update_state_changed.emit({
    'installed': '1.44.51', 'available': '1.44.52', 'busy': False})
app.processEvents()
ui_updated = dialog.ui_version.text()
dialog.open_ui_after_restart.setChecked(True)
dialog.download_button.click()
controller.download_progress.emit(500, 1000)
app.processEvents()
during = {
    'downloaded': controller.downloaded is info,
    'text': dialog.download_button.text(),
    'enabled': dialog.download_button.isEnabled(),
    'later_enabled': dialog.close_button.isEnabled(),
    'progress': dialog.progress.value(),
    'accessible_status': dialog.status.accessibleName(),
}
controller.download_ready.emit(info, 'verified-Vantage.exe')
app.processEvents()
after = {
    'installed': controller.installed,
    'progress': dialog.progress.value(),
    'active': dialog._one_click_active,
}

class FailingController(Controller):
    def launch_installer(self, info, path, **options):
        raise RuntimeError(
            'The update was cancelled and Vantage remains open.')

failing_controller = FailingController()
failure_dialog = UpdateDialog(failing_controller)
failure_dialog.info = info
failure_dialog.staged_path = 'verified-Vantage.exe'
failure_dialog.show()
failure_dialog.install()
app.processEvents()
failure = {
    'visible': failure_dialog.isVisible(),
    'active': failure_dialog._one_click_active,
    'status': failure_dialog.status.text(),
    'try_again': failure_dialog.download_button.text(),
    'later_enabled': failure_dialog.close_button.isEnabled(),
}
print(json.dumps({
    'before': before, 'during': during, 'after': after, 'failure': failure,
    'opened': opened, 'ui_checks': ui.checks,
    'ui_updated': ui_updated}))
failure_dialog.close()
dialog.close()
"""


def test_update_dialog_has_one_download_verify_install_action(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['before']['text'] == 'Download and install update'
    assert result['before']['enabled'] is True
    assert result['before']['accessible'] == (
        'Download, verify, install, and restart Vantage')
    assert 'EverQuest and WinEQ remain open' in result['before']['tooltip']
    assert result['before']['opt_in'] is False
    assert 'does not install' in result['before']['opt_accessible']
    assert result['before']['ui_versions'] == (
        'Installed: 1.44.51 · Available: 1.44.51')
    assert result['before']['tab_order'] is True
    assert result['opened'] == [True]
    assert result['ui_checks'] == 1
    assert result['ui_updated'] == (
        'Installed: 1.44.51 · Available: 1.44.52')
    assert result['during'] == {
        'downloaded': True,
        'text': 'Downloading…',
        'enabled': False,
        'later_enabled': False,
        'progress': 50,
        'accessible_status': (
            'Update status: Downloading and verifying Vantage.exe · 50%'),
    }
    assert result['after'] == {
        'installed': ['1.0.1', 'verified-Vantage.exe',
                      {'open_vantage_ui': True}],
        'progress': 100,
        'active': False,
    }
    assert result['failure'] == {
        'visible': True,
        'active': False,
        'status': (
            'Update could not start: The update was cancelled and Vantage '
            'remains open.'),
        'try_again': 'Try again',
        'later_enabled': True,
    }
