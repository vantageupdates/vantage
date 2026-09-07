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
import semver
import vantage.helpers.updater as updater_module
from vantage.helpers.updater import UpdateDialog

announcements = []
class AccessibleRecorder:
    @staticmethod
    def updateAccessibility(event):
        announcements.append(event.message())
updater_module.QAccessible = AccessibleRecorder

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
        self.checks = 0
    def check(self):
        self.checks += 1
        return True
    def download(self, info):
        self.downloaded = info
        return True
    def launch_installer(self, info, path, **options):
        self.installed = [str(info.version), path, options]

class VantageUI(QObject):
    update_state_changed = Signal(object)
    def __init__(self):
        super().__init__()
        self.state = {
            'installed': '1.44.51', 'available': '1.44.51',
            'busy': False, 'update_available': False}
    def update_snapshot(self):
        return dict(self.state)

app = QApplication([])
controller = Controller()
ui = VantageUI()
opened, updated, restored = [], [], []
dialog = UpdateDialog(
    controller, vantage_ui=ui,
    open_vantage_ui=lambda: opened.append(True),
    update_vantage_ui=lambda: updated.append(True),
    restore_focus=lambda: restored.append(True))
info = SimpleNamespace(
    version=semver.VersionInfo.parse('1.0.1'),
    size=1000, notes='A verified update.')
dialog._checked(info, 'Vantage 1.0.1 is ready to download.')
ui.state = {
    'installed': '1.44.51', 'available': '1.44.52', 'busy': False,
    'update_available': True}
ui.update_state_changed.emit(ui.state)
app.processEvents()
dialog.show()
dialog.activateWindow()
app.processEvents()
ready = {
    'title': dialog.windowTitle(),
    'companion_action': dialog.download_button.text(),
    'companion_enabled': dialog.download_button.isEnabled(),
    'ui_action': dialog.open_ui_button.text(),
    'ui_enabled': dialog.open_ui_button.isEnabled(),
    'companion_versions': dialog.version.text(),
    'ui_versions': dialog.ui_version.text(),
    'joint_visible': dialog.open_ui_after_restart.isVisible(),
}

control_names = {
    id(dialog.download_button): 'Update Vantage',
    id(dialog.open_ui_button): 'VantageUI action',
    id(dialog.notes): 'Release notes',
    id(dialog.open_ui_after_restart): 'Joint checkbox',
    id(dialog.check_button): 'Check again',
    id(dialog.close_button): 'Later',
}
dialog._focus_control(dialog.download_button)
app.processEvents()
tab_order = []
for _ in range(7):
    focused = dialog.scaled_surface.focusWidget()
    tab_order.append(control_names.get(id(focused), focused.__class__.__name__))
    QTest.keyClick(focused, Qt.Key.Key_Tab)
    app.processEvents()
dialog.open_ui_button.click()

# One manual shared check produces one combined completion announcement.
dialog.show()
dialog.check()
controller.check_finished.emit(info, 'Vantage 1.0.1 is ready.')
app.processEvents()
combined_status = dialog.status.text()

# Escape closes and restores keyboard focus to the Quick Bar launcher.
dialog.activateWindow()
QTest.keyClick(dialog, Qt.Key.Key_Escape)
app.processEvents()
escape = {'visible': dialog.isVisible(), 'restored': len(restored)}

# Companion progress stops at the three useful milestones, then gives one
# final verified/restart status. The checkbox carries the explicit opt-in.
app.quit = lambda: None
dialog.show()
dialog.open_ui_after_restart.setChecked(True)
dialog.download_button.click()
for received in (250, 510, 800, 1000):
    controller.download_progress.emit(received, 1000)
controller.download_ready.emit(info, 'verified-Vantage.exe')
app.processEvents()
download = {
    'downloaded': controller.downloaded is info,
    'installed': controller.installed,
    'progress': dialog.progress.value(),
}

# Manual check errors return focus to Check again, not a disabled download.
error_dialog = UpdateDialog(Controller())
error_dialog.show()
error_dialog.raise_()
error_dialog.activateWindow()
app.processEvents()
error_dialog.check()
error_dialog.controller.failed.emit('GitHub unavailable')
app.processEvents()
app.processEvents()
check_error = {
    'status': error_dialog.status.text(),
    'focused': QApplication.focusWidget() is error_dialog.check_button,
    'focus_class': (QApplication.focusWidget().__class__.__name__
                    if QApplication.focusWidget() else ''),
    'button_has_focus': error_dialog.check_button.hasFocus(),
    'surface_focus': (error_dialog.scaled_surface.focusWidget()
                      is error_dialog.check_button),
    'check_enabled': error_dialog.check_button.isEnabled(),
}

# When the joint option is absent, the same real Tab path skips it and wraps.
current_ui = VantageUI()
current_dialog = UpdateDialog(Controller(), vantage_ui=current_ui,
                              open_vantage_ui=lambda: None,
                              update_vantage_ui=lambda: None)
current_dialog._checked(info, 'Vantage ready')
current_dialog.show()
current_dialog.activateWindow()
app.processEvents()
current_names = {
    id(current_dialog.download_button): 'Update Vantage',
    id(current_dialog.open_ui_button): 'VantageUI action',
    id(current_dialog.notes): 'Release notes',
    id(current_dialog.check_button): 'Check again',
    id(current_dialog.close_button): 'Later',
}
current_dialog._focus_control(current_dialog.download_button)
app.processEvents()
hidden_tab_order = []
for _ in range(6):
    focused = current_dialog.scaled_surface.focusWidget()
    hidden_tab_order.append(
        current_names.get(id(focused), focused.__class__.__name__))
    QTest.keyClick(focused, Qt.Key.Key_Tab)
    app.processEvents()

print(json.dumps({
    'ready': ready, 'updated': updated, 'opened': opened,
    'combined_status': combined_status, 'escape': escape,
    'download': download, 'check_error': check_error,
    'tab_order': tab_order, 'hidden_tab_order': hidden_tab_order,
    'announcements': announcements,
}))
error_dialog.close()
current_dialog.close()
dialog.close()
"""


def test_update_dialog_separates_products_and_restores_focus(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['ready'] == {
        'title': 'Updates',
        'companion_action': 'Update Vantage',
        'companion_enabled': True,
        'ui_action': 'Update VantageUI',
        'ui_enabled': True,
        'companion_versions': '1.0.0 installed · 1.0.1 available',
        'ui_versions': '1.44.51 installed · 1.44.52 available',
        'joint_visible': True,
    }
    assert result['updated'] == [True]
    assert result['opened'] == []
    assert result['tab_order'] == [
        'Update Vantage', 'VantageUI action', 'Release notes',
        'Joint checkbox', 'Check again', 'Later', 'Update Vantage']
    assert result['hidden_tab_order'] == [
        'Update Vantage', 'VantageUI action', 'Release notes',
        'Check again', 'Later', 'Update Vantage']
    assert result['combined_status'] == (
        'Check complete. Vantage 1.0.1 ready. VantageUI 1.44.52 ready.')
    assert result['escape']['visible'] is False
    assert result['escape']['restored'] >= 1
    assert result['download'] == {
        'downloaded': True,
        'installed': [
            '1.0.1', 'verified-Vantage.exe', {'open_vantage_ui': True}],
        'progress': 100,
    }
    assert result['check_error'] == {
        'status': 'GitHub unavailable',
        'focused': False,
        'focus_class': 'QGraphicsView',
        'button_has_focus': True,
        'surface_focus': True,
        'check_enabled': True,
    }
    completion = [
        message for message in result['announcements']
        if message.startswith('Check complete.')]
    assert completion == [
        'Check complete. Vantage 1.0.1 ready. VantageUI 1.44.52 ready.']
    progress = [
        message for message in result['announcements']
        if 'Downloading and verifying Vantage.exe ·' in message]
    assert progress == [
        'Downloading and verifying Vantage.exe · 25%',
        'Downloading and verifying Vantage.exe · 50%',
        'Downloading and verifying Vantage.exe · 75%',
    ]
    assert result['announcements'].count(
        'Verified · installing update and restarting Vantage…') == 1
