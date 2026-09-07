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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import vantage.helpers.update_toast as toast_module
from vantage.helpers.update_toast import QuickUpdateToast

announcements = []
class AccessibleRecorder:
    @staticmethod
    def updateAccessibility(event):
        announcements.append(event.message())
toast_module.QAccessible = AccessibleRecorder

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
toast.show_updates(info=info, vantage_ui_version='2.3.4')
app.processEvents()
screen = app.primaryScreen().availableGeometry()
combined = {
    'visible': toast.isVisible(),
    'tool': bool(toast.windowFlags() & Qt.WindowType.Tool),
    'top': bool(toast.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    'near_top_right': (
        toast.x() >= screen.right() - toast.width() - 20 and
        toast.y() <= screen.top() + 20),
    'title': toast.title.text(),
    'message': toast.message.text(),
    'transparent': toast.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents),
    'companion_action_hidden': toast.update_button.isHidden(),
    'ui_action_hidden': toast.ui_button.isHidden(),
    'no_focus': toast.focusPolicy() == Qt.FocusPolicy.NoFocus,
    'accessible_name': toast.message.accessibleName(),
}

# The status-only toast still reports progress correctly if an already-started
# update owns it; milestones are 25/50/75 and verification is announced once.
toast.start_one_click_update()
for received in (249, 250, 510, 800, 1000):
    controller.download_progress.emit(received, 1000)
controller.download_ready.emit(info, 'verified-Vantage.exe')
app.processEvents()
progress = {
    'started': controller.downloaded is info,
    'value': toast.progress.value(),
    'installed': target.installed,
}

toast.show_success('9.8.6', '9.8.7')
app.processEvents()
success_hidden = not toast.isVisible()

# Compatibility entry points also coalesce within one short discovery batch.
announcements.clear()
legacy = QuickUpdateToast(Controller(), target)
legacy.show_for(info)
legacy.show_for_vantage_ui('4.5.6')
QTest.qWait(180)
app.processEvents()
legacy_state = {
    'visible': legacy.isVisible(),
    'message': legacy.message.text(),
    'announcements': list(announcements),
}

print(json.dumps({
    'combined': combined,
    'progress': progress,
    'success_hidden': success_hidden,
    'legacy': legacy_state,
}))
legacy.close()
toast.close()
app.quit()
"""


def test_update_toast_is_atomic_status_only_and_accessible(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['combined'] == {
        'visible': True,
        'tool': True,
        'top': True,
        'near_top_right': True,
        'title': 'UPDATES READY',
        'message': (
            'Vantage 9.8.7 and VantageUI 2.3.4 are ready · open Updates '
            'in the Quick Bar'),
        'transparent': True,
        'companion_action_hidden': True,
        'ui_action_hidden': True,
        'no_focus': True,
        'accessible_name': (
            'Update status: Vantage 9.8.7 and VantageUI 2.3.4 are ready · '
            'open Updates in the Quick Bar'),
    }
    assert result['progress'] == {
        'started': True,
        'value': 100,
        'installed': ['9.8.7', 'verified-Vantage.exe', True],
    }
    assert result['success_hidden'] is True
    assert result['legacy']['visible'] is True
    assert result['legacy']['message'] == (
        'Vantage 9.8.7 and VantageUI 4.5.6 are ready · open Updates '
        'in the Quick Bar')
    assert len(result['legacy']['announcements']) == 1
