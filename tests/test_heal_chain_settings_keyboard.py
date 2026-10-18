"""Embedded Heal Chain settings follow the form order across the Qt proxy."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scale", ("1", "1.5"))
def test_settings_include_overlay_controls_and_preserve_keyboard_wrap(scale):
    script = r'''
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

app = VantageApp([])
heals = app._parsers_dict['heals']
heals._refresh_timer.stop()
heals._set_collapsed(False)
heals.resize(heals._design_size)
heals.show()
heals.activateWindow()
heals._show_inline_settings()
QTest.qWait(40)
controls = (
    heals.monitor_enabled, heals.settings_interval, heals.cast_seconds,
    heals.hotkey_format, heals.own_marker, heals.overlay_enabled,
    heals.overlay_opacity, heals.overlay_reset, heals.notify_turn)
assert heals.settings_tab.verticalScrollBar().maximum() > 0
heals.monitor_enabled.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
assert heals._surface.focusWidget() is controls[0]

def press(key, expected):
    QTest.keyClick(app.focusWidget(), key)
    app.processEvents()
    actual = heals._surface.focusWidget()
    assert actual is expected, (
        expected.accessibleName(), actual.accessibleName() if actual else None)

def in_view(control):
    viewport = heals.settings_tab.viewport()
    return viewport.rect().contains(control.mapTo(viewport, control.rect().center()))

for expected in controls[1:]:
    press(Qt.Key.Key_Tab, expected)
    assert in_view(expected), expected.accessibleName()
# The final settings field still wraps to the first window control.
press(Qt.Key.Key_Tab, heals._button)
press(Qt.Key.Key_Backtab, heals.notify_turn)
for expected in reversed(controls[:-1]):
    press(Qt.Key.Key_Backtab, expected)
    assert in_view(expected), expected.accessibleName()
# Leaving the first setting backwards returns to the tabs, as before.
QTest.keyClick(app.focusWidget(), Qt.Key.Key_Backtab)
app.processEvents()
assert heals._surface.focusWidget() in (heals.tabs, heals.tabs.tabBar())
app.quit()
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src")))
    env["QT_SCALE_FACTOR"] = scale
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
