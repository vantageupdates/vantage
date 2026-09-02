import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QApplication
from vantage.helpers.update_toast import QuickUpdateToast

class Controller(QObject):
    download_progress = Signal(int, int)
    download_ready = Signal(object, str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.downloaded = None

    def download(self, info):
        self.downloaded = info
        return True

class AppTarget:
    def __init__(self):
        self.installed = None

    def install_quick_update(self, info, path, toast):
        self.installed = [str(info.version), path, toast is not None]
        return True

app = QApplication([])
controller = Controller()
target = AppTarget()
toast = QuickUpdateToast(controller, target)
info = SimpleNamespace(version='9.8.7', size=1000)
toast.show_for(info)
app.processEvents()
screen = app.primaryScreen().availableGeometry()
shown = {
    'visible': toast.isVisible(),
    'tool': bool(toast.windowFlags() & Qt.WindowType.Tool),
    'top': bool(toast.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    'near_top_right': (
        toast.x() >= screen.right() - toast.width() - 20 and
        toast.y() <= screen.top() + 20),
    'button': toast.update_button.text(),
    'message': toast.message.text(),
    'button_tooltip': toast.update_button.toolTip(),
    'close_tooltip': toast.close_button.toolTip(),
}
toast.update_button.click()
controller.download_progress.emit(500, 1000)
app.processEvents()
downloading = {
    'started': controller.downloaded is info,
    'active': toast._one_click_active,
    'progress_visible': toast.progress.isVisible(),
    'progress': toast.progress.value(),
    'close_enabled': toast.close_button.isEnabled(),
}
controller.download_ready.emit(info, 'verified-Vantage.exe')
app.processEvents()
print(json.dumps({
    'shown': shown,
    'downloading': downloading,
    'installed': target.installed,
}))
toast.close()
app.quit()
"""


def test_update_toast_is_top_right_and_one_click_installs(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['shown'] == {
        'visible': True,
        'tool': True,
        'top': True,
        'near_top_right': True,
        'button': 'Update',
        'message': 'Vantage 9.8.7 is ready · verified GitHub Release',
        'button_tooltip': (
            'One click updates only Vantage; EverQuest and WinEQ remain open'),
        'close_tooltip': (
            'Dismiss this notification; update remains available in Vantage'),
    }
    assert result['downloading'] == {
        'started': True,
        'active': True,
        'progress_visible': True,
        'progress': 50,
        'close_enabled': False,
    }
    assert result['installed'] == [
        '9.8.7', 'verified-Vantage.exe', True]
