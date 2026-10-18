"""Isolated Qt regressions for the bounded 1.44.137 polish fixes."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(script, tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (
        f"Qt fixture failed:\n{completed.stdout}\n{completed.stderr}")


def test_diagnostics_minimum_keeps_readable_controls_and_scaled_input(tmp_path):
    _run(r'''
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from vantage.helpers.combat import CombatTracker
from vantage.helpers.combat_diagnostics import CombatDiagnosticsDialog
from vantage.helpers.scaled_dialog import UniformScaleDialog

app = QApplication([])
tracker = CombatTracker()
dialog = CombatDiagnosticsDialog(tracker)
dialog.show()
QTest.qWait(30)
normal = dialog.search.geometry()
dialog.resize(1, 1)
QTest.qWait(30)
assert isinstance(dialog, UniformScaleDialog)
assert (dialog.width(), dialog.height()) == (608, 312)
assert abs(dialog.uniform_scale - .8) < .001
assert dialog.search.geometry() == normal
assert (dialog._surface.width(), dialog._surface.height()) == (760, 390)

logical = dialog.search.mapTo(dialog._surface, dialog.search.rect().center())
point = dialog._view.mapFromScene(dialog._proxy.mapToScene(QPointF(logical)))
QTest.mouseClick(dialog._view.viewport(), Qt.MouseButton.LeftButton, pos=point)
QTest.keyClicks(dialog._view.viewport(), "bat")
assert dialog.search.text() == "bat"
event = QHelpEvent(
    QEvent.Type.ToolTip, point, dialog._view.viewport().mapToGlobal(point))
QApplication.sendEvent(dialog._view.viewport(), event)
assert QToolTip.text() == dialog.search.toolTip()
assert dialog._refresh_timer.isActive()
dialog.close()
assert not dialog._refresh_timer.isActive()
assert tracker.diagnostics_enabled is False
app.quit()
''', tmp_path)


FRIENDS_SETUP = r'''
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from vantage.helpers import config, friends_manager
from vantage.helpers.friends_manager import FriendsBackupStore, FriendsManagerDialog

# Every file read or written by this fixture lives beneath pytest's temp path.
profile = Path(os.environ["VANTAGE_DATA_DIR"])
eq_root = profile / "synthetic-everquest"
(eq_root / "Logs").mkdir(parents=True)
green = eq_root / "GreenCharacter_P1999Green.ini"
blue = eq_root / "BlueCharacter_P1999Blue.ini"
green.write_text("[Friends]\nFriend0=GreenFriend\n", encoding="utf-8")
blue.write_text("[Friends]\nFriend0=BlueFriend\n", encoding="utf-8")
config.data.setdefault("general", {})["eq_log_dir"] = str(eq_root / "Logs")
app = QApplication([])
dialog = FriendsManagerDialog(backup_store=FriendsBackupStore(profile / "backups"))
dialog.show()
QTest.qWait(30)
prompts = []
answer = QMessageBox.StandardButton.Cancel
def question(_parent, title, text, buttons, default):
    prompts.append((title, text, buttons, default))
    return answer
QMessageBox.question = question
QMessageBox.warning = lambda *_args: None
'''


def test_friends_cancel_preserves_server_draft_cursor_and_editor_focus(tmp_path):
    _run(FRIENDS_SETUP + r'''
dialog.server.setCurrentIndex(1)
assert dialog.editor.toPlainText() == "BlueFriend"
dialog.server.setCurrentIndex(0)
assert not prompts
original_scan = dialog._scan
dialog.editor.appendPlainText("UnpushedFriend")
draft = dialog.editor.toPlainText()
cursor = dialog.editor.textCursor().position()
dialog.server.setFocus()
dialog.server.setCurrentIndex(1)
assert dialog.server.currentData() == "P1999Green"
assert dialog._scan is original_scan
assert dialog.editor.toPlainText() == draft
assert dialog.editor.textCursor().position() == cursor
assert dialog.scaled_surface.focusWidget() is dialog.editor
assert prompts[-1][3] == QMessageBox.StandardButton.Cancel
assert prompts[-1][2] & QMessageBox.StandardButton.Discard

dialog.reload_button.click()
assert dialog.editor.toPlainText() == draft
assert dialog._scan is original_scan
assert dialog.scaled_surface.focusWidget() is dialog.editor
assert dialog.close() is False
assert dialog.isVisible()
assert dialog.editor.toPlainText() == draft
QTest.keyClick(dialog, Qt.Key.Key_Escape)
assert dialog.isVisible()
close_button = next(button for button in dialog.scaled_surface.findChildren(QPushButton)
                    if button.text() == "Close")
close_button.click()
assert dialog.isVisible()
assert dialog.editor.toPlainText() == draft
assert dialog.scaled_surface.focusWidget() is dialog.editor

answer = QMessageBox.StandardButton.Discard
dialog.server.setCurrentIndex(1)
assert dialog.server.currentData() == "P1999Blue"
assert dialog.editor.toPlainText() == "BlueFriend"
dialog.editor.appendPlainText("DiscardOnReload")
dialog.reload_button.click()
assert dialog.editor.toPlainText() == "BlueFriend"
prompt_count = len(prompts)
dialog.reload_button.click()
assert len(prompts) == prompt_count
dialog.editor.appendPlainText("DiscardOnClose")
assert dialog.close() is True
assert not dialog.isVisible()
assert dialog.editor.toPlainText() == "BlueFriend"
assert "UnpushedFriend" not in green.read_text(encoding="utf-8")
assert "Discard" not in blue.read_text(encoding="utf-8")
app.quit()
''', tmp_path)


def test_friends_push_keeps_failed_drafts_and_clears_successful_edits(tmp_path):
    _run(FRIENDS_SETUP + r'''
dialog.editor.appendPlainText("NewFriend")
draft = dialog.editor.toPlainText()
answer = QMessageBox.StandardButton.Yes
real_push = friends_manager.push_friends
friends_manager.push_friends = lambda *_args: friends_manager.FriendsWriteReport(
    errors=("Synthetic write failure",))
dialog.push()
assert dialog.editor.toPlainText() == draft
assert dialog.editor.toPlainText() != dialog._loaded_text
assert len(prompts) == 1
friends_manager.push_friends = real_push
dialog.push()
assert len(prompts) == 2
assert dialog.editor.toPlainText() == dialog._loaded_text
assert "Friend1=NewFriend" in green.read_text(encoding="utf-8")
dialog.editor.appendPlainText("AfterPushDraft")
draft = dialog.editor.toPlainText()
answer = QMessageBox.StandardButton.Cancel
dialog.restore_last_push()
assert "unpushed edits" in prompts[-1][1]
assert dialog.editor.toPlainText() == draft
answer = QMessageBox.StandardButton.Yes
dialog.restore_last_push()
assert dialog.editor.toPlainText() == "GreenFriend"
assert dialog.editor.toPlainText() == dialog._loaded_text
prompt_count = len(prompts)
assert dialog.close() is True
assert len(prompts) == prompt_count
app.quit()
''', tmp_path)


def test_log_search_label_matches_rolling_twenty_four_hour_filter(tmp_path):
    _run(r'''
from datetime import datetime
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers import log_searcher

class Settings(QObject):
    config_updated = Signal()

app = QApplication([])
app._signals = {"settings": Settings()}
config.data.setdefault("log_searcher", {})
config.save = lambda: None
log_searcher.LogSearcher.refresh_index = lambda self: False
panel = log_searcher.LogSearcher()
panel._logs_directory = lambda: "synthetic-log-root"
calls = []
def search(*args, **kwargs):
    calls.append(kwargs)
    return (), False
panel._cache_for = lambda _directory: SimpleNamespace(search=search)
class ImmediateThread:
    def __init__(self, *, target, **kwargs):
        self.target = target
    def start(self):
        self.target()
log_searcher.threading.Thread = ImmediateThread
panel.date_range.setCurrentIndex(panel.date_range.findData(24))
assert panel.date_range.currentText() == "Past 24 hours"
before = datetime.now().timestamp()
panel.search()
after = datetime.now().timestamp()
assert before - 86400 <= calls[-1]["since_epoch"] <= after - 86400
panel.shutdown_workers()
panel.close()
app.quit()
''', tmp_path)
