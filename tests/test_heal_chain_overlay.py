"""Live CH overlay behavior uses synthetic calls and disposable Qt profiles."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers.heal_chain import HealChainTracker


ROOT = Path(__file__).resolve().parents[1]


def test_predicted_cleric_requires_an_observed_marker_on_same_tank():
    tracker = HealChainTracker()
    now = datetime(2026, 10, 17)
    tracker.ingest(now, "Brielle tells the guild, 'BBB - CH - Dain'")
    tracker.ingest(now + timedelta(seconds=3), "Althea tells the guild, 'AAA - CH - Dain'")
    assert tracker.next_cleric("Dain", "AAA") == "Brielle"
    assert tracker.next_cleric("Vulak", "AAA") == ""
    assert tracker.next_cleric("Dain", "BBB") == ""
    tracker.clear()
    assert tracker.next_cleric("Dain", "AAA") == ""


@pytest.mark.parametrize("scale", ("1", "1.25", "1.5"))
def test_overlay_lifecycle_timing_keyboard_and_position(scale):
    script = r'''
import json
from datetime import datetime, timedelta
from native_audit_fixture import isolate
profile = isolate()
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.heal_rail import HealChainOverlay
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
app = VantageApp([])
heals = app._parsers_dict['heals']
heals._refresh_timer.stop()
overlay = heals.overlay
assert not overlay.isVisible()
heals._set_collapsed(False)
heals.resize(heals._design_size)
heals.show()
heals.notify_turn.setChecked(False)
heals.overlay_button.click()
QTest.qWait(30)
assert overlay.isVisible() and heals.overlay_enabled.isChecked()
assert config.data['heals']['overlay_enabled']
assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
assert overlay.parentWidget() is None

now = datetime.now()
heals.parse(now - timedelta(seconds=6), "Brielle tells the guild, 'BBB - CH - Dain'")
heals.parse(now, "Althea tells the guild, 'AAA - CH - Dain'")
overlay.refresh(now + timedelta(seconds=1))
assert overlay.state.text() == 'CHAIN ACTIVE'
assert '9.0s cast remaining' in overlay.current.text()
assert overlay.next_call.text() == 'Expected next: BBB · Brielle · in 2.0s'
overlay.refresh(now + timedelta(seconds=4))
assert overlay.next_call.text().endswith('call due')
assert len(heals._tracker.casts) == 2  # No invented cast on countdown expiry.
heals.own_marker.setText('BBB')
heals._save_embedded_settings()
assert overlay.state.text() == 'YOUR MARKER NEXT'
assert 'BBB · You' in overlay.next_call.text()
assert overlay.rails.own_marker == 'BBB' and heals.rails.own_marker == 'BBB'

heals.hide()
QTest.qWait(20)
assert overlay.isVisible()
heals.parse(now + timedelta(seconds=1), "Celeste tells the guild, 'CCC - CH - Vulak'")
overlay.refresh(now + timedelta(seconds=2))
assert {cast.tank for cast in overlay.tracker.active(now + timedelta(seconds=2))} == {'Dain', 'Vulak'}
assert 'Vulak' in overlay.current.text()
assert 'Expected next: DDD' in overlay.next_call.text()
assert 'Brielle' not in overlay.next_call.text()
heals.parse(now + timedelta(seconds=2), "Celeste's casting is interrupted!")
overlay.refresh(now + timedelta(seconds=2))
assert overlay.state.text() == 'CAST INTERRUPTED'
assert 'interrupted' in overlay.current.text()
assert overlay.grab().save(str(profile / 'heal-chain-overlay-interrupted.png'))

heals.pause.setChecked(True)
assert overlay.state.text() == 'MONITORING PAUSED'
assert 'due' not in overlay.next_call.text()
count = len(heals._tracker.casts)
heals.parse(now, "Ignored tells the guild, 'DDD - CH - Vulak'")
assert len(heals._tracker.casts) == count
heals.pause.setChecked(False)
heals.monitor_enabled.setChecked(False)
assert overlay.state.text() == 'MONITOR OFF'
assert heals.header_countdown.text() == 'OFF'
heals.monitor_enabled.setChecked(True)
overlay.refresh(now + timedelta(seconds=60))
assert overlay.state.text() == 'WAITING FOR CALLS'
assert 'due' not in overlay.next_call.text()

overlay.settings_button.click()
assert heals.isVisible() and heals.tabs.currentWidget() is heals.settings_tab
heals.overlay_opacity.setValue(75)
assert abs(overlay.windowOpacity() - .75) < .01
assert config.data['heals']['overlay_opacity'] == 75
heals.overlay_reset.click()
QTest.qWait(20)
area = app.primaryScreen().availableGeometry()
assert area.contains(overlay.frameGeometry())
overlay.move(area.topLeft())
before = QPoint(overlay.pos())
overlay.activateWindow()
overlay.title.setFocus()
QTest.qWait(20)
assert overlay.title.hasFocus()
QTest.keyClick(overlay.title, Qt.Key.Key_Right)
assert overlay.x() == before.x() + 10
QTest.keyClick(overlay.title, Qt.Key.Key_Tab)
assert overlay.settings_button.hasFocus()
QTest.keyClick(overlay.settings_button, Qt.Key.Key_Tab)
assert overlay.hide_button.hasFocus()

# Deliver a real Qt drag sequence without interacting with the desktop.
origin = overlay.title.mapToGlobal(QPoint(12, 8))
target = origin + QPoint(20, 20)
for kind, global_pos, button, buttons in (
    (QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
    (QEvent.Type.MouseMove, target, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
    (QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
):
    local_pos = overlay.title.mapFromGlobal(global_pos)
    event = QMouseEvent(kind, QPointF(local_pos), QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay.title, event)
assert overlay.pos() == before + QPoint(30, 20)
assert config.data['heals']['overlay_position'] == [overlay.x(), overlay.y()]

overlay.move(90000, 90000)
overlay._recover_screen_geometry()
assert area.contains(overlay.frameGeometry())
overlay.reset_position()
position = [overlay.x(), overlay.y()]
overlay.activateWindow()
overlay.hide_button.setFocus()
QTest.qWait(20)
QTest.keyClick(overlay.hide_button, Qt.Key.Key_Escape)
assert not overlay.isVisible()
assert not heals.overlay_button.isChecked() and not heals.overlay_enabled.isChecked()
assert not config.data['heals']['overlay_enabled']
assert config.data['heals']['enabled'] and not heals.pause.isChecked()
heals.parse(datetime.now(), "Newcleric tells the guild, 'EEE - CH - Dain'")
assert heals._tracker.casts[-1].cleric == 'Newcleric'
heals.overlay_enabled.setChecked(True)
assert overlay.isVisible() and heals.overlay_button.isChecked()
assert [overlay.x(), overlay.y()] == position
overlay.hide_button.click()
assert not overlay.isVisible() and config.data['heals']['enabled']

# A freshly constructed overlay recovers the saved independent position.
restored = HealChainOverlay(heals._tracker)
assert [restored.x(), restored.y()] == position
restored.deleteLater()
heals.overlay_enabled.setChecked(True)
heals._tracker.clear()
now = datetime.now()
heals.parse(now - timedelta(seconds=6), "Brielle tells the guild, 'BBB - CH - Dain'")
heals.parse(now, "Althea tells the guild, 'AAA - CH - Dain'")
overlay.refresh(now + timedelta(seconds=1), own_marker='BBB')
heals.settings_tab.ensureWidgetVisible(heals.overlay_opacity)
QTest.qWait(30)
assert overlay.grab().save(str(profile / 'heal-chain-overlay.png'))
assert heals.grab().save(str(profile / 'heal-chain-overlay-settings.png'))
print(json.dumps({'passed': True, 'profile': str(profile), 'scale': overlay.devicePixelRatioF()}))
# Both normal exit and updater handoff use the APP_EXIT shutdown boundary.
# Closing the overlay during that sequence must preserve its saved-on state.
config.APP_EXIT = True
QTimer.singleShot(0, app.quit)
app.exec()
assert config.data['heals']['overlay_enabled'] is True
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_SCALE_FACTOR"] = scale
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["passed"]
    assert report["scale"] == float(scale)
    print(report)
