"""The real rolled tick header keeps its live readout available in More."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
import sys
from types import SimpleNamespace

from native_audit_fixture import isolate
isolate()

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QProgressBar, QWidgetAction
from shiboken6 import isValid
from vantage.helpers.application import VantageApp
from vantage.parsers import tick as tick_module

now = [100.0]
tick_module.time = SimpleNamespace(monotonic=lambda: now[0])
app = VantageApp([])
errors = []
sys.excepthook = lambda kind, value, trace: errors.append(f'{kind.__name__}: {value}')
tick = app._parsers_dict['tick']
tick.show()
menu = tick._header_overflow_menu
parents = [widget.parentWidget() for widget in (
    tick.header_tick, tick.header_countdown, tick.header_progress)]
timers_before = len(tick.findChildren(QTimer))

def readout():
    for action in menu.actions():
        if isinstance(action, QWidgetAction):
            host = action.defaultWidget()
            if host.objectName() == 'ServerTickOverflowReadout':
                return (host, host.findChild(QLabel, 'ServerTickOverflowCountdown'),
                        host.findChild(QProgressBar))
    return None

def opened_state():
    # Use the real More popup and its aboutToShow signal. Do not manufacture
    # overflow membership or invoke the readout builder before first opening.
    if not menu.isVisible():
        menu.popup(tick._header_overflow_button.mapToGlobal(
            tick._header_overflow_button.rect().bottomLeft()))
        app.processEvents()
    widgets = readout()
    if widgets is None:
        return None
    host, label, progress = widgets
    return {
        'text': label.text(), 'progress': progress.value(),
        'description': label.accessibleDescription(),
        'progress_description': progress.accessibleDescription(),
        'source': host.accessibleDescription(),
        'name': label.accessibleName(),
        'native': host.graphicsProxyWidget() is None,
        'font_pixels': label.fontInfo().pixelSize(),
        'visible': all(widget.isVisibleTo(menu) for widget in widgets),
        'synced': progress.property('Synced'),
        'pulse': progress.property('Pulse'),
    }

cases = []
for scale in (.25, .35, .5, .75):
    tick._set_collapsed(False)
    tick._set_replica_scale(scale)
    tick._set_header_revealed(True)
    QTest.qWait(30)
    width = tick.width()
    tick._set_collapsed(True)
    QTest.qWait(30)
    tick.clear_sync()
    case = {
        'scale': scale, 'width': tick.width(), 'expanded_width': width,
        'overflowed': tick.header_tick in tick._header_overflowed,
        'more_visible': tick._header_overflow_button.isVisibleTo(tick._surface),
        'waiting': opened_state(),
    }
    widgets = readout()
    if widgets is not None:
        now[0] = 100.0
        tick.sync_now()
        case['pulse'] = opened_state()
        now[0] = 101.5
        # The normal 100 ms render timer must update a menu that stays open.
        QTest.qWait(125)
        case['remaining'] = opened_state()
        tick._pack_header_controls()
        tick._rebuild_header_overflow_menu()
        case['popup_retained'] = (
            menu.isVisible() and readout() == widgets and
            all(isValid(widget) for widget in widgets))
        tick.clear_sync()
        case['cleared'] = opened_state()
        case['parents_preserved'] = all(
            widget.parentWidget() is parent for widget, parent in zip((
                tick.header_tick, tick.header_countdown, tick.header_progress), parents))
    menu.close()
    cases.append(case)

# Reopening after a size change must replace the old native clones safely.
old_widgets = readout()
tick._set_collapsed(False)
tick._set_replica_scale(.35)
QTest.qWait(30)
tick._set_collapsed(True)
QTest.qWait(30)
now[0] = 100.0
tick.sync_now()
now[0] = 102.5
QTest.qWait(125)
reopened = opened_state()
new_widgets = readout()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
replaced = (old_widgets is not None and new_widgets is not None and
            new_widgets != old_widgets and
            all(not isValid(widget) for widget in old_widgets))
menu.close()
menu.clear()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
destroyed = (new_widgets is not None and
             all(not isValid(widget) for widget in new_widgets))
cleared_references = all(getattr(tick, name, None) is None for name in (
    '_overflow_tick_countdown', '_overflow_tick_progress'))
now[0] = 103.5
QTest.qWait(125)
after_clear = opened_state()
no_extra_timer = len(tick.findChildren(QTimer)) == timers_before
menu.close()
print(json.dumps({
    'cases': cases, 'reopened': reopened, 'replaced': replaced,
    'destroyed': destroyed, 'cleared_references': cleared_references,
    'after_clear': after_clear, 'no_extra_timer': no_extra_timer, 'errors': errors,
}))
app.quit()
'''


def test_rolled_tick_more_keeps_native_countdown_live_and_owned(tmp_path):
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen", QT_ACCESSIBILITY="0",
        PYTHONPATH=os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src"))),
        VANTAGE_DATA_DIR=str(tmp_path / "profile"))
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["errors"] == []
    for case in result["cases"]:
        assert case["width"] == case["expanded_width"], case
        assert case["overflowed"] and case["more_visible"], case
        assert case["waiting"] is not None, case
        waiting = case["waiting"]
        assert waiting["text"] == "—" and waiting["progress"] == 0
        assert waiting["description"] == "Not synchronized"
        assert waiting["synced"] is False and waiting["pulse"] is False
        assert waiting["native"] and waiting["visible"]
        assert waiting["font_pixels"] >= 12
        assert waiting["name"] == "Time until the next server tick"
        assert case["pulse"]["text"] == "TICK"
        assert case["pulse"]["progress"] == 1000
        assert case["pulse"]["description"] == "Tick now"
        remaining = case["remaining"]
        assert remaining["text"] == "4.5s" and remaining["progress"] == 250
        assert remaining["description"] == "4.5 seconds remaining"
        assert remaining["progress_description"] == remaining["description"]
        assert remaining["synced"] is True and remaining["pulse"] is False
        assert "Manual sync" in remaining["source"]
        assert case["popup_retained"] and case["parents_preserved"]
        assert case["cleared"]["description"] == "Not synchronized"
        assert case["cleared"]["text"] == "—"
        assert case["cleared"]["progress"] == 0
    assert result["reopened"]["text"] == "3.5s"
    assert result["replaced"] and result["destroyed"]
    assert result["cleared_references"] and result["no_extra_timer"]
    assert result["after_clear"]["text"] == "2.5s"
