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

    def launch_installer(self, info, path):
        self.installed = [str(info.version), path]


app = QApplication([])
controller = Controller()
dialog = UpdateDialog(controller)
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
}
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
print(json.dumps({'before': before, 'during': during, 'after': after}))
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
    assert result['during'] == {
        'downloaded': True,
        'text': 'Downloading…',
        'enabled': False,
        'later_enabled': False,
        'progress': 50,
        'accessible_status': (
            'Update status: Downloading and verifying Vantage.exe…'),
    }
    assert result['after'] == {
        'installed': ['1.0.1', 'verified-Vantage.exe'],
        'progress': 100,
        'active': False,
    }
