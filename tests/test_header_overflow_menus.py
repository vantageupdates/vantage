"""Real scaled Combat menus retain native hierarchy and lazy source behavior."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import datetime
import json
import os
from pathlib import Path
import sys
import traceback

from native_audit_fixture import isolate
profile = isolate()
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from shiboken6 import isValid
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
config.data['combat'].update(live_overlay_enabled=False, live_overlay_rows=6,
                             live_overlay_id='alerts')
app = VantageApp([])
combat = app._parsers_dict['combat']
scale = float(os.environ['VANTAGE_MENU_SCALE'])
output = Path(os.environ['VANTAGE_MENU_OUTPUT'])
output.mkdir(parents=True, exist_ok=True)
result = {'errors': [], 'source_cold': not combat.live_overlay_menu.actions()}
source_export_actions = list(combat.export_menu.actions())
source_export_labels = [item.text() for item in source_export_actions]
source_format_menus = {
    item.text(): (item, item.menu(), list(item.menu().actions()))
    for item in source_export_actions if item.menu() is not None}
source_openings = []
combat.live_overlay_menu.aboutToShow.connect(lambda: source_openings.append(True))
sys.excepthook = lambda kind, value, trace: result['errors'].append(
    ''.join(traceback.format_exception(kind, value, trace)))

stamp = datetime.datetime.now()
combat.parse(stamp, 'AuditAlice slashes a synthetic goblin for 1000 points of damage.')
combat.parse(stamp + datetime.timedelta(seconds=5),
             'You kick a synthetic goblin for 500 points of damage.')
combat.parse(stamp + datetime.timedelta(seconds=10),
             'You have slain a synthetic goblin!')
combat.mode.setCurrentIndex(combat.mode.findData('last'))
combat.refresh()
combat._set_collapsed(False)
combat.resize(combat._design_size)
combat.show()
combat._set_replica_scale(scale)
combat._set_header_revealed(True)
QTest.qWait(30)
combat._pack_header_controls()
app.processEvents()
assert combat.live_overlay in combat._header_overflowed
assert combat.export in combat._header_overflowed
result['source_cold_after_pack'] = not combat.live_overlay_menu.actions()


def capture(menu, name):
    app.processEvents()
    assert menu.isVisible(), (name, 'menu did not open')
    assert menu.grab().save(str(output / (name + '.png')))


def action(menu, text):
    matches = [item for item in menu.actions() if item.text() == text]
    assert len(matches) == 1, (text, [item.text() for item in menu.actions()])
    return matches[0]


def select(menu, text):
    """Reach the action with genuine menu keyboard navigation."""
    target = action(menu, text)
    for _ in range(len(menu.actions()) + 1):
        if menu.activeAction() is target:
            return target
        QTest.keyClick(menu, Qt.Key.Key_Down)
    raise AssertionError(('unreachable action', text))


def descend(menu, text):
    item = select(menu, text)
    child = item.menu()
    assert child is not None, (text, 'lost its submenu')
    QTest.keyClick(menu, Qt.Key.Key_Right)
    QTest.qWait(25)
    assert child.isVisible(), (text, 'submenu did not open')
    return child


def choose(menu, text):
    select(menu, text)
    QTest.keyClick(menu, Qt.Key.Key_Return)
    app.processEvents()


def close_menus():
    # More may run a nested popup event loop during the pointer press.
    for widget in app.allWidgets():
        if isinstance(widget, QMenu) and widget.isVisible():
            widget.close()


def open_more(name, callback, keyboard=False):
    completed = []
    def visit():
        try:
            menu = combat._header_overflow_menu
            assert menu.isVisible(), 'More did not open through its input event'
            capture(menu, name + '-more')
            callback(menu)
        except BaseException:
            result['errors'].append(name + ': ' + traceback.format_exc())
        finally:
            close_menus()
            completed.append(True)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(visit)
    timer.start(100)
    button = combat._header_overflow_button
    assert button.isVisibleTo(combat._surface)
    if keyboard:
        combat._scale_view.setFocus(Qt.FocusReason.TabFocusReason)
        combat._scale_scene.setFocusItem(combat._scale_proxy)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        # Space activates the actual QToolButton, retaining its popup behavior.
        QTest.keyClick(combat._scale_view.viewport(), Qt.Key.Key_Space)
    else:
        point = button.mapTo(combat._surface, button.rect().center())
        scene_point = combat._scale_proxy.mapToScene(QPointF(point))
        viewport_point = combat._scale_view.mapFromScene(scene_point)
        QTest.mouseClick(combat._scale_view.viewport(),
                         Qt.MouseButton.LeftButton, pos=viewport_point)
    for _ in range(40):
        if completed:
            break
        QTest.qWait(10)
    assert completed, (name, 'popup callback did not complete')
    app.processEvents()


def export_formats(menu):
    export = descend(menu, combat.export.accessibleName())
    # Repacking More must borrow, not delete or reconstruct the source tree.
    assert list(combat.export_menu.actions()) == source_export_actions, (
        [item.text() for item in combat.export_menu.actions()],
        [(text, isValid(item)) for text, item in
         zip(source_export_labels, source_export_actions)])
    for text, (original, submenu, children) in source_format_menus.items():
        assert action(export, text) is original
        assert original.menu() is submenu
        assert list(submenu.actions()) == children
    copy = descend(export, 'Copy format')
    capture(copy, 'copy-formats')
    result['copy_formats'] = [item.text() for item in copy.actions()]
    QTest.keyClick(copy, Qt.Key.Key_Left)
    save = descend(export, 'Save format')
    capture(save, 'save-formats')
    result['save_formats'] = [item.text() for item in save.actions()]
    QTest.keyClick(save, Qt.Key.Key_Left)
    copy = descend(export, 'Copy format')
    app.clipboard().setText('Synthetic clipboard sentinel')
    choose(copy, 'Current table')
    result['clipboard'] = app.clipboard().text()


open_more('export-pointer', export_formats)
result['lazy_before_live'] = not source_openings
definitions = app._notification_overlay.definitions()
definitions['audit-destination'] = dict(definitions['alerts'],
                                       label='Synthetic destination', enabled=True)


def live_destination(menu):
    live = descend(menu, combat.live_overlay.accessibleName())
    capture(live, 'live-overlay-cold')
    result['live_initial'] = [item.text() for item in live.actions()]
    route = descend(live, 'Damage destination')
    capture(route, 'damage-destination')
    choose(route, 'Synthetic destination')


open_more('live-keyboard', live_destination, keyboard=True)


def visible_rows(menu):
    live = descend(menu, combat.live_overlay.accessibleName())
    rows = descend(descend(live, 'Visible rows'), 'Damage')
    capture(rows, 'visible-damage-rows')
    assert action(rows, '6').isChecked()
    choose(rows, '8')


open_more('rows-pointer', visible_rows)


def toggle_primary(menu):
    live = descend(menu, combat.live_overlay.accessibleName())
    primary = action(live, combat.live_overlay.accessibleName())
    assert primary.isCheckable() and not primary.isChecked()
    choose(live, primary.text())


open_more('primary-keyboard', toggle_primary, keyboard=True)
result['primary_toggled'] = combat.live_overlay.isChecked()
result['persisted'] = json.loads(Path(config._filename).read_text())['combat']

# Change definitions and return through normal size. A new opening must use
# current source actions, not an old snapshot retained by the More menu.
definitions['audit-destination']['label'] = 'Renamed synthetic destination'
definitions['audit-new'] = dict(definitions['alerts'],
                               label='New synthetic destination', enabled=True)
definitions['audit-hidden'] = dict(definitions['alerts'],
                                  label='Disabled synthetic destination', enabled=False)
combat._set_replica_scale(1.)
QTest.qWait(20)
combat._set_replica_scale(scale)
combat._set_header_revealed(True)
QTest.qWait(20)


def reopened(menu):
    live = descend(menu, combat.live_overlay.accessibleName())
    assert action(live, combat.live_overlay.accessibleName()).isChecked()
    assert action(live, 'Live damage / DPS').isChecked()
    route = descend(live, 'Damage destination')
    capture(route, 'destination-reopened')
    result['updated_destinations'] = [item.text() for item in route.actions()]
    assert action(route, 'Renamed synthetic destination').isChecked()
    QTest.keyClick(route, Qt.Key.Key_Left)
    rows = descend(descend(live, 'Visible rows'), 'Damage')
    assert action(rows, '8').isChecked()
    assert not action(rows, '6').isChecked()
    result['reopened_current'] = True


open_more('reopened-keyboard', reopened, keyboard=True)
open_more('export-reopened-keyboard', export_formats, keyboard=True)
result['source_openings'] = len(source_openings)
result['source_actions_preserved'] = (
    list(combat.export_menu.actions()) == source_export_actions)
print(json.dumps(result))
app.quit()
'''


@pytest.mark.parametrize("scale", (".35", ".25"))
def test_combat_more_preserves_nested_lazy_menus_and_actions(tmp_path, scale):
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1",
        QT_ACCESSIBILITY="0", PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src"))),
        VANTAGE_MENU_SCALE=scale,
        VANTAGE_MENU_OUTPUT=str(tmp_path / "native-popup-captures"))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, (
        f"Disposable native-menu app exited {completed.returncode}\n"
        f"STDERR:\n{completed.stderr[-6000:]}\nSTDOUT:\n{completed.stdout[-6000:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["errors"] == [], result["errors"]
    assert result["source_cold"] and result["source_cold_after_pack"]
    assert result["lazy_before_live"]
    assert result["source_openings"] == 4
    assert result["source_actions_preserved"]
    assert "Current table" in result["copy_formats"]
    assert "Current table as HTML" in result["copy_formats"]
    assert "Full encounter as XML…" in result["save_formats"]
    assert "Combat session as JSON…" in result["save_formats"]
    assert "AuditAlice" in result["clipboard"] and "\t" in result["clipboard"]
    assert "Visible rows" in result["live_initial"]
    assert result["primary_toggled"]
    assert result["persisted"]["live_overlay_enabled"] is True
    assert result["persisted"]["live_overlay_id"] == "audit-destination"
    assert result["persisted"]["live_overlay_rows"] == 8
    assert result["reopened_current"]
    assert "New synthetic destination" in result["updated_destinations"]
    assert "Synthetic destination" not in result["updated_destinations"]
    assert "Disabled synthetic destination" not in result["updated_destinations"]
