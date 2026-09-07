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
from PySide6.QtWidgets import QApplication, QLineEdit
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
        self.ui_opened = 0

    def install_quick_update(self, info, path, toast):
        self.installed = [str(info.version), path, toast is not None]
        return True

    def open_vantage_ui(self):
        self.ui_opened += 1
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
    'accessible_name': toast.message.accessibleName(),
    'accessible_description': toast.message.accessibleDescription(),
}
toast.show_for_vantage_ui('2.3.4')
app.processEvents()
combined = {
    'title': toast.title.text(),
    'message': toast.message.text(),
    'companion_action': toast.update_button.text(),
    'companion_visible': toast.update_button.isVisible(),
    'ui_action': toast.ui_button.text(),
    'ui_visible': toast.ui_button.isVisible(),
    'ui_accessible_name': toast.ui_button.accessibleName(),
}
toast.ui_button.click()
app.processEvents()
after_ui_action = {
    'opened': target.ui_opened,
    'visible': toast.isVisible(),
    'title': toast.title.text(),
    'companion_visible': toast.update_button.isVisible(),
    'ui_visible': toast.ui_button.isVisible(),
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
toast.show_success('9.8.6', '9.8.7')
app.processEvents()
success = {
    'visible': toast.isVisible(),
    'title': toast.title.text(),
    'message': toast.message.text(),
    'button': toast.update_button.text(),
    'progress': toast.progress.value(),
}

ui_only = QuickUpdateToast(Controller(), target)
ui_only.show_for_vantage_ui('4.5.6')
app.processEvents()
ui_only_state = {
    'visible': ui_only.isVisible(),
    'title': ui_only.title.text(),
    'message': ui_only.message.text(),
    'companion_visible': ui_only.update_button.isVisible(),
    'ui_visible': ui_only.ui_button.isVisible(),
    'tooltip': ui_only.ui_button.toolTip(),
}

overlap_controller = Controller()
overlap = QuickUpdateToast(overlap_controller, target)
overlap.show_for(info)
overlap.update_button.click()
overlap_controller.download_progress.emit(375, 1000)
app.processEvents()
overlap.show_for_vantage_ui('7.8.9')
app.processEvents()
overlap_state = {
    'active': overlap._one_click_active,
    'downloaded': overlap_controller.downloaded is info,
    'progress_visible': overlap.progress.isVisible(),
    'progress': overlap.progress.value(),
    'close_enabled': overlap.close_button.isEnabled(),
    'companion_enabled': overlap.update_button.isEnabled(),
    'companion_text': overlap.update_button.text(),
    'ui_visible': overlap.ui_button.isVisible(),
    'ui_enabled': overlap.ui_button.isEnabled(),
    'message': overlap.message.text(),
}

class FailedAppTarget:
    def install_quick_update(self, info, path, owner):
        owner._failed(
            'Update cancelled: live buffs could not be saved. Vantage '
            'remains open.')
        return False

failed_controller = Controller()
external_focus = QLineEdit()
external_focus.show()
external_focus.activateWindow()
external_focus.setFocus()
app.processEvents()
failed_toast = QuickUpdateToast(failed_controller, FailedAppTarget())
failed_toast.show_for(info)
failed_toast.update_button.click()
external_focus.activateWindow()
external_focus.setFocus()
app.processEvents()
failed_controller.download_ready.emit(info, 'verified-Vantage.exe')
app.processEvents()
failure = {
    'visible': failed_toast.isVisible(),
    'active': failed_toast._one_click_active,
    'message': failed_toast.message.text(),
    'button': failed_toast.update_button.text(),
    'close_enabled': failed_toast.close_button.isEnabled(),
    'accessible_name': failed_toast.message.accessibleName(),
    'accessible_description': failed_toast.message.accessibleDescription(),
    'external_focus_kept': app.focusWidget() is external_focus,
}
print(json.dumps({
    'shown': shown,
    'combined': combined,
    'after_ui_action': after_ui_action,
    'downloading': downloading,
    'installed': target.installed,
    'success': success,
    'ui_only': ui_only_state,
    'overlap': overlap_state,
    'failure': failure,
    'announcements': announcements,
}))
failed_toast.close()
ui_only.close()
overlap.close()
external_focus.close()
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
        'accessible_name': (
            'Update status: Vantage 9.8.7 is ready · verified GitHub Release'),
        'accessible_description': (
            'Vantage 9.8.7 is ready · verified GitHub Release'),
    }
    assert result['downloading'] == {
        'started': True,
        'active': True,
        'progress_visible': True,
        'progress': 50,
        'close_enabled': False,
    }
    assert result['combined'] == {
        'title': 'UPDATES READY',
        'message': (
            'Vantage 9.8.7 and VantageUI 2.3.4 are ready · verified releases'),
        'companion_action': 'Update',
        'companion_visible': True,
        'ui_action': 'Open VantageUI',
        'ui_visible': True,
        'ui_accessible_name': (
            'Open VantageUI to review and install its verified update'),
    }
    assert result['after_ui_action'] == {
        'opened': 1,
        'visible': True,
        'title': 'VANTAGE UPDATE',
        'companion_visible': True,
        'ui_visible': False,
    }
    assert result['installed'] == [
        '9.8.7', 'verified-Vantage.exe', True]
    assert result['success'] == {
        'visible': True,
        'title': 'UPDATE COMPLETE',
        'message': 'Vantage 9.8.7 is installed · was 9.8.6',
        'button': 'Done',
        'progress': 100,
    }
    assert result['ui_only'] == {
        'visible': True,
        'title': 'VANTAGEUI UPDATE',
        'message': (
            'VantageUI 4.5.6 is ready · verified GitHub Release'),
        'companion_visible': False,
        'ui_visible': True,
        'tooltip': (
            'Open VantageUI to review the verified release before installing'),
    }
    assert result['overlap'] == {
        'active': True,
        'downloaded': True,
        'progress_visible': True,
        'progress': 38,
        'close_enabled': False,
        'companion_enabled': False,
        'companion_text': 'Updating…',
        'ui_visible': True,
        'ui_enabled': False,
        'message': 'Updating Vantage · VantageUI 7.8.9 is also ready',
    }
    assert result['failure'] == {
        'visible': True,
        'active': False,
        'message': (
            'Update cancelled: live buffs could not be saved. Vantage '
            'remains open.'),
        'button': 'Try again',
        'close_enabled': True,
        'accessible_name': (
            'Update status: Update cancelled: live buffs could not be saved. '
            'Vantage remains open.'),
        'accessible_description': (
            'Update cancelled: live buffs could not be saved. Vantage '
            'remains open.'),
        'external_focus_kept': True,
    }
    assert any('ready' in message for message in result['announcements'])
    assert any('Downloading and verifying' in message
               for message in result['announcements'])
    assert any('remains open' in message
               for message in result['announcements'])
